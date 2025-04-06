import re
import io
import csv
from datetime import timedelta

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import not_, or_

from openpyxl import Workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from io import BytesIO
import qrcode

from pydantic import ValidationError

import app.model.models as models
import app.schema as schema

# Kategori yang tidak melibatkan mesin
# Dipakai di /operator/status supaya tidak usah menampilkan pilihan STOP untuk kategori ini
# Dan di /activity/status supaya tidak usah menampilkan active activity mesin/operator
NON_MACHINE_CATEGORY = ["NP : No Plan", "BT : Breaktime", "BR : Briefing"]

# Setup Category produces reject and rework
SETUP_CATEGORY = ["TL : Trial", "TS : Tooling Setting", "TP : Tooling Problem"]

# Dipakai di /activity/status supaya tidak usah menampilkan kegiatan operator yang NP
NO_PLAN_CATEGORY = ["NP : No Plan"]

def is_non_machine_category(category: str) -> bool:
    return category in NON_MACHINE_CATEGORY

def is_setup_category(category: str) -> bool:
    return category in SETUP_CATEGORY

def get_operator_active_machines(operator_id: str, exclude: list[str], session):
    """
    Retrieve all active machines that an operator is currently working on,
    excluding activities where category starts with prefixes in `exclude`.
    """
    activities = (
        session.query(models.ActivityMesin)
        .filter(models.ActivityMesin.operator_id == operator_id)
        .filter(models.ActivityMesin.stop_time_id == None)  # Only active activities
        .filter(~models.ActivityMesin.category.in_(exclude))  # Exclude exact matches
        .all()
    )

    return activities


def get_machine_active_operators(mesin_id, exclude: list[str], session):
    """
    Retrieve all active operators working on the given machine,
    excluding activities where category starts with prefixes in exclude.
    """
    return (
        session.query(models.ActivityMesin)
        .filter(models.ActivityMesin.mesin_id == mesin_id)
        .filter(models.ActivityMesin.stop_time_id == None)  # Only active activities
        .filter(~models.ActivityMesin.category.in_(exclude))  # Exclude exact matches
        .all()
    )


def process_activity(activity, session):
    """
    Handles machine activity transitions based on operator input.

    - Saves the current activity and next planned activity into `MesinLog`.
    - Updates the previous `ActivityMesin` (if exists) by setting the stop time and saving results.
    - Creates a new `ActivityMesin` for the next activity.

    Ensures strict chronological tracking of machine operations and avoids overlapping activities.
    """

    # Empty tooling and mesin means user choose: Mulai Aktivitas Baru and then pick NP / BR / BT (non machine activity)
    tooling_id = activity.tooling_id
    mesin_id = activity.mesin_id
    operator_id = activity.operator_id
    output = activity.output
    reject = activity.reject
    rework = activity.rework
    coil_no = activity.coil_no
    lot_no = activity.lot_no
    pack_no = activity.pack_no
    keterangan = activity.keterangan
    curr_category = activity.curr_category
    next_category = activity.next_category

    print(mesin_id)
    print(tooling_id)
    print(curr_category)

    # Step 1: Insert new MesinLog entry
    new_log = models.MesinLog(
        mesin_id=mesin_id,
        operator_id=operator_id,
        tooling_id=tooling_id,
        curr_category=curr_category,
        next_category=next_category,
    )
    session.add(new_log)
    session.commit()

    # Step 2: Stop any NP activity
    np_activities = (
    session.query(models.ActivityMesin)
        .filter(
            models.ActivityMesin.operator_id == operator_id,
            models.ActivityMesin.stop_time_id.is_(None),  # Only active activities
            models.ActivityMesin.category.startswith("NP")  # Only NP activities
        )
        .all()
    )

    # Stop NP activities by setting their stop_time_id
    if np_activities:
        for np_activity in np_activities:
            np_activity.stop_time_id = new_log.id  # Use new log entry to mark the stop
        session.commit()

    # Step 3: Find the previous ongoing ActivityMesin entry
    # There might be multiple non-machine related activities (BR, BT, and RP) that needs to be stopped all at once
    # So for those, no need to filter by mesin
    activities_to_stop_query = (
        session.query(models.ActivityMesin)
        .filter(
            models.ActivityMesin.operator_id == operator_id,
            models.ActivityMesin.category == curr_category,
            models.ActivityMesin.stop_time_id.is_(None)  # Only active activities
        )
    )

    # If it's NOT a non-machine category, further filter by mesin_id
    if curr_category and curr_category not in NON_MACHINE_CATEGORY:
        activities_to_stop_query = activities_to_stop_query.filter(models.ActivityMesin.mesin_id == mesin_id)

        if tooling_id:
            activities_to_stop_query = activities_to_stop_query.filter(models.ActivityMesin.tooling_id == tooling_id)

    activities_to_stop = activities_to_stop_query.all()

    # Stop all selected activities
    if activities_to_stop:
        for activity in activities_to_stop:
            activity.stop_time_id = new_log.id
            activity.output = output
            activity.reject = reject
            activity.rework = rework
            activity.coil_no = coil_no
            activity.lot_no = lot_no
            activity.pack_no = pack_no
            activity.keterangan = keterangan

        session.commit()

    # Step 4: Create a new ActivityMesin entry for the next activity
    new_activity = models.ActivityMesin(
        mesin_id=mesin_id,
        operator_id=operator_id,
        tooling_id=tooling_id,
        category=next_category,
        start_time_id=new_log.id,  # Set this new log as the start time
        stop_time_id=None,  # It has just started, so stop time remains NULL
    )
    session.add(new_activity)
    session.commit()


def _determine_new_mesin_status(downtime_category):
    """
    Determines the machine's next operational state after a stop event.

    Business Justification:
    - **SETUP**: If the downtime is related to tooling (`TL` - Trial, `TS` - Tooling Setting, `TP` - Tooling Problem),
      the machine transitions to `SETUP`. This allows operators to log reject/rework before resuming production.
    - **IDLE**: For all other downtime reasons, the machine transitions to `IDLE`, indicating that it is
      available but not actively running.

    Why is this necessary?
    - Prevents machines that are being prepared for production from appearing as fully stopped.
    - Ensures that only **tooling-related downtime** moves to `SETUP`, keeping production downtime separate.

    :param downtime_category: The category of downtime that caused the machine to stop.
    :return: The new `MesinStatus` (`SETUP` or `IDLE`).
    """
    downtime_category_initial = _get_downtime_category(downtime_category)

    return models.Status.SETUP if downtime_category_initial in ["TL", "TS", "TP"] else models.Status.IDLE


def _get_displayed_status(downtime_category):
    """
    Determines the correct displayed status for the operator based on the downtime category.

    Business Justification:
    - **IDLE**: If the downtime category is `NP` (No Plan), `BT` (Breaktime), or `BR` (Briefing),
      the operator is not actively working and should be marked as idle.
    - **DOWNTIME**: For all other downtime reasons, the operator is actively handling an issue,
      so they should be displayed as in **downtime**.

    Why is this necessary?
    - Ensures that **planned non-working periods (breaks, briefings, no plan)** are not mistakenly marked as downtime.
    - Prevents confusion between **actual production downtime** (e.g., Machine Problem, Change Material)
      and scheduled non-working time.

    :param downtime_category: The category of downtime affecting the machine.
    :return: The new `DisplayedStatus` (`IDLE` or `DOWNTIME`).
    """
    downtime_category_initial = _get_downtime_category(downtime_category)

    return (
        models.DisplayedStatus.IDLE
        if downtime_category_initial in ["NP", "BT", "BR"]
        else models.DisplayedStatus.DOWNTIME
    )



def insert_or_update_tooling(
    tooling_data: schema.ToolingCreate,
    session,
) -> models.Tooling:
    tooling_id = (
        f"TL-{tooling_data.common_tooling_name}-{tooling_data.kode_tooling}".replace(
            " ", "-"
        ).replace("/", "-OF-")
    )
    existing_tooling = (
        session.query(models.Tooling).filter(models.Tooling.id == tooling_id).first()
    )

    if existing_tooling:
        for attr, value in tooling_data.dict().items():
            if attr not in [
                "id",
                "time_created",
                "time_updated",
            ]:  # Exclude fields that shouldn't be updated
                setattr(existing_tooling, attr, value.upper())
        return existing_tooling
    else:
        # Create new tooling record
        new_tooling = models.Tooling(**tooling_data.dict(), id=tooling_id)
        session.add(new_tooling)
        return new_tooling


def insert_or_update_mesin(mc: schema.MesinCreate, session) -> models.Mesin:
    name = mc.name
    tonase = mc.tonase
    if not validate_mesin_name(name) or not validate_tonase(tonase):
        raise HTTPException(status_code=400, detail=f"Invalid name: {name}, tonase: {tonase}")

    mesin_id = f"MC-{name}".replace(" ", "-")
    existing_mesin = (
        session.query(models.Mesin).filter(models.Mesin.id == mesin_id).first()
    )

    if existing_mesin:
        existing_mesin.name = name.upper()
        existing_mesin.tonase = tonase
        return existing_mesin
    else:
        new_mesin = models.Mesin(
            id=mesin_id,
            name=name.upper(),
            tonase=tonase,
        )
        session.add(new_mesin)
        return new_mesin


def insert_or_update_operator(op: schema.OperatorCreate, session) -> models.Operator:
    name = op.name
    nik = op.nik
    if not validate_nik(nik) or not validate_name(name):
        raise HTTPException(status_code=400, detail=f"Invalid name: {name}, nik: {nik}")

    operator_id = f"OP-{name.title()}".replace(" ", "-")
    existing_operator = (
        session.query(models.Operator).filter(models.Operator.id == operator_id).first()
    )

    if existing_operator:
        existing_operator.nik = nik
        existing_operator.name = name.title()
        return existing_operator
    else:
        new_operator = models.Operator(
            id=operator_id,
            nik=nik,
            name=name.title(),
        )
        session.add(new_operator)
        return new_operator


def validate_nik(nik: str) -> bool:
    # Alphanumeric characters and hyphens
    return re.match(schema.ALPHANUMERIC_HYPHENS, nik) is not None


def validate_name(name: str) -> bool:
    # Alphabetic characters, periods, and spaces
    return re.match(schema.ALPHANUMERIC_SPACE_PERIOD, name) is not None


def validate_mesin_name(name: str) -> bool:
    # Alphanumeric characters and hyphens
    return re.match(schema.ALPHANUMERIC_HYPHENS, name) is not None


def validate_tonase(tonase: str) -> bool:
    # Digits only
    return re.match(schema.DIGIT, tonase) is not None


def process_operator_row(row, row_index, session):
    try:
        operator_data = schema.OperatorCreate(
            name=row[0].strip(),
            nik=row[1].strip(),
        )
        insert_or_update_operator(operator_data, session)
    except ValidationError as e:
        error_messages = ', '.join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
        raise HTTPException(status_code=400, detail=f"Row {row_index}: {error_messages}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Row {row_index}: {str(e)}")


def process_mesin_row(row, row_index, session):
    try:
        mesin_data = schema.MesinCreate(
            name=row[0].strip(),
            tonase=row[1].strip(),
        )
        insert_or_update_mesin(mesin_data, session)
    except ValidationError as e:
        error_messages = ', '.join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
        raise HTTPException(status_code=400, detail=f"Row {row_index}: {error_messages}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Row {row_index}: {str(e)}")



def process_tooling_row(row, row_index, session):
    try:
        tooling_data = schema.ToolingCreate(
            customer=row[0].strip(),
            part_no=row[1].strip(),
            part_name=row[2].strip(),
            child_part_name=row[3].strip(),
            kode_tooling=row[4].strip(),
            common_tooling_name=row[5].strip(),
            proses=row[6].strip(),
            std_jam=int(row[7].strip()),
        )
        insert_or_update_tooling(tooling_data, session)
    except ValidationError as e:
        error_messages = ', '.join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
        raise HTTPException(status_code=400, detail=f"Row {row_index}: {error_messages}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Row {row_index}: {str(e)}")


def process_csv(file_content, row_processor, session):
    try:
        csvfile = io.StringIO(file_content.decode("utf-8"))
        try:
            dialect = csv.Sniffer().sniff(csvfile.readline(), delimiters=";,")
            csvfile.seek(0)
            csvreader = list(csv.reader(csvfile, dialect))
        except:
            csvfile.seek(0)  # Reset to start of file in case the sniffing fails
            csvreader = list(csv.reader(csvfile, delimiter=","))

        for index, row in enumerate(csvreader, start=1):
            row_processor(row, index, session)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e


def delete_item(model, item_id: str, session):
    item = session.query(model).filter(model.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")

    try:
        session.delete(item)
        session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=500, detail=f"Error deleting {model.__name__}: {e}"
        )


def generate_barcode(model, session):
    # Query the database to get the list of items based on the model
    if model == "operator":
        items = (
            session.query(models.Operator)
            .with_entities(models.Operator.id)
            .order_by(models.Operator.id.asc())
            .all()
        )
        filename = "barcode_operator.xlsx"
    elif model == "mesin":
        items = (
            session.query(models.Mesin)
            .with_entities(models.Mesin.id)
            .order_by(models.Mesin.id.asc())
            .all()
        )
        filename = "barcode_mesin.xlsx"
    elif model == "tooling":
        items = (
            session.query(models.Tooling)
            .with_entities(models.Tooling.id)
            .order_by(models.Tooling.id.asc())
            .all()
        )
        filename = "barcode_tooling.xlsx"
    else:
        raise HTTPException(status_code=404, detail="Model not found")

    # Create a new Excel workbook and select the active worksheet
    wb = Workbook()
    ws = wb.active

    # Set the desired cell width for text and QR codes
    col_width = 15
    for col in ["A", "B", "C", "D", "E"]:  # Set width for columns A to E
        ws.column_dimensions[col].width = col_width

    # Assuming each box of the QR code is 3 pixels
    box_size = 3
    qr_code_size = 100  # The size of the QR code image in pixels

    # Calculate row height for QR codes
    qr_row_height = (
        qr_code_size * 0.75
    )  # Excel row height is measured in points, and there are 0.75 points per pixel

    # Loop through items in chunks of 5
    for i in range(0, len(items), 5):
        row = ((i // 5) * 2) + 1  # Calculate the starting row for each group of 5 items
        ws.row_dimensions[row].height = 15  # Set row height for names
        ws.row_dimensions[row + 1].height = qr_row_height  # Set row height for QR codes

        # Place operator names and QR codes
        for j in range(5):
            if i + j < len(items):  # Check if there are enough items left
                item_id = items[i + j][0]
                col = chr(65 + j)  # Calculate the column letter (A to E)

                # Set operator id in the first row of the group
                ws.cell(row=row, column=j + 1, value=item_id)

                # Create and insert the QR code in the second row of the group
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=box_size,  # Adjust the box_size if necessary
                    border=1,
                )
                qr.add_data(item_id)
                qr.make(fit=True)
                img_pil = qr.make_image(fill_color="black", back_color="white")

                img_byte_arr = BytesIO()
                img_pil.save(img_byte_arr, format="PNG")
                img_byte_arr.seek(0)

                img_openpyxl = OpenpyxlImage(img_byte_arr)
                ws.add_image(
                    img_openpyxl, f"{col}{row + 1}"
                )  # Place QR code in the cell below the name

    # Save the workbook to a BytesIO object
    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    return excel_file, filename


def generate_report_response(df, filename, report_format):
    if "dashboard" in report_format.value:
        return JSONResponse(content=df.to_dict(orient="records"))
    else:
        if report_format == schema.FormatType.LIMAX:
            # Prepare CSV
            stream = io.StringIO()
            df.to_csv(stream, index=False, sep=";", lineterminator="\r\n")
            stream.seek(0)
            response_content = stream.getvalue()
            media_type = "text/csv"
            filename += ".csv"
        elif report_format == schema.FormatType.IMN:
            # Prepare Excel
            stream = io.BytesIO()
            df.to_excel(stream, index=False)
            stream.seek(0)
            response_content = stream.getvalue()
            media_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            filename += ".xlsx"

        return StreamingResponse(
            iter([response_content]),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


def _get_downtime_category(downtime_category):
    return downtime_category[:2].upper()


def _update_downtime_mesin_status(downtime_category):
    return (
        models.Status.SETUP
        if _get_downtime_category(downtime_category) in ["TP", "TS", "TL"]
        else models.Status.IDLE
    )
