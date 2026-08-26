import re
import io
import csv
from datetime import timedelta

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import not_, or_, and_, String, Text
from sqlalchemy.orm import aliased

from openpyxl import Workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from io import BytesIO
import qrcode

from pydantic import ValidationError

import app.model.models as models
import app.schema as schema
import app.service.report as report
from app.service.utils import (
    NON_MACHINE_CODES,
    NON_MACHINE_CATEGORY,
    SETUP_CODES,
)


def _category_code(category: str) -> str:
    """Extract 2-letter category code from full category string"""
    if not category:
        return ""
    return str(category).split(":")[0].strip().upper()


def is_non_machine_category(category: str) -> bool:
    return _category_code(category) in NON_MACHINE_CODES


def is_setup_category(category: str) -> bool:
    return _category_code(category) in SETUP_CODES


def _category_code_condition(column, categories):
    """Build a SQL condition matching category codes, independent of labels."""
    codes = {_category_code(category) for category in categories}
    codes.discard("")
    return or_(
        *(
            or_(
                column == code,
                column.startswith(f"{code}:"),
                column.startswith(f"{code} :"),
            )
            for code in codes
        )
    )


def normalize_optional_identifier(value):
    """Normalize empty values and frontend sentinel strings to ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value.lower() in {"", "null", "none"}:
            return None
    return value

def get_operator_active_machines(operator_id: str, exclude: list[str], session):
    """
    Retrieve all active machines that an operator is currently working on,
    excluding activities where category starts with prefixes in `exclude`.
    """
    activities = (
        session.query(models.ActivityMesin)
        .filter(models.ActivityMesin.operator_id == operator_id)
        .filter(models.ActivityMesin.stop_time_id.is_(None))  # Only active activities
        .filter(~_category_code_condition(models.ActivityMesin.category, exclude))
        .filter(
            models.ActivityMesin.mesin_id.isnot(None),
            models.ActivityMesin.mesin_id != "",
            models.ActivityMesin.tooling_id.isnot(None),
            models.ActivityMesin.tooling_id != "",
        )
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
        .filter(models.ActivityMesin.stop_time_id.is_(None))  # Only active activities
        .filter(~_category_code_condition(models.ActivityMesin.category, exclude))
        .all()
    )


def process_activity(activity, session):
    """
    Handles activity transitions and keeps atomic report facts in sync.

    Flow:
    1) Create MesinLog event (timestamp marker for stop/start).
    2) Stop any active NP activity for this operator.
    3) Stop relevant active activities:
       - Any active NON_MACHINE_CATEGORY for this operator, plus
       - The selected current activity (optionally scoped by mesin/tooling if machine-related).
       For stopped machine activities, also persist qty/reject/rework + details.
    4) Upsert report facts for all stopped activities (atomic; no merging).
    5) Start next ActivityMesin.
    """

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

    # 1) Insert new MesinLog entry (event marker)
    new_log = models.MesinLog(
        mesin_id=mesin_id,
        operator_id=operator_id,
        tooling_id=tooling_id,
        curr_category=curr_category,
        next_category=next_category,
    )

    # Use event_timestamp if provided for seed data
    if hasattr(activity, 'event_timestamp') and activity.event_timestamp:
        new_log.timestamp = activity.event_timestamp
    session.add(new_log)
    session.flush()  # get new_log.id without committing yet

    # 2) Stop any active NP activities for this operator
    np_activities = (
        session.query(models.ActivityMesin)
        .filter(
            models.ActivityMesin.operator_id == operator_id,
            models.ActivityMesin.stop_time_id.is_(None),
            models.ActivityMesin.category.startswith("NP"),
        )
        .all()
    )
    for a in np_activities:
        a.stop_time_id = new_log.id

    # 3) Stop selected ongoing activities (chosen + non-machine)
    base_active = and_(
        models.ActivityMesin.operator_id == operator_id,
        models.ActivityMesin.stop_time_id.is_(None),
    )

    non_machine_branch = and_(
        base_active,
        _category_code_condition(models.ActivityMesin.category, NON_MACHINE_CODES),
    )

    chosen_filters = [
        base_active,
        models.ActivityMesin.category == curr_category,
    ]

    # only restrict mesin/tooling for machine categories
    if curr_category and not is_non_machine_category(curr_category):
        chosen_filters.append(models.ActivityMesin.mesin_id == mesin_id)
        if tooling_id:
            chosen_filters.append(models.ActivityMesin.tooling_id == tooling_id)

    chosen_branch = and_(*chosen_filters)

    activities_to_stop = (
        session.query(models.ActivityMesin)
        .filter(or_(chosen_branch, non_machine_branch))
        .all()
    )

    for a in activities_to_stop:
        a.stop_time_id = new_log.id

        # non-machine: stop only (don’t overwrite details)
        if is_non_machine_category(a.category):
            continue

        # machine / chosen-category: persist production details
        a.output = output
        a.reject = reject
        a.rework = rework
        a.coil_no = coil_no
        a.lot_no = lot_no
        a.pack_no = pack_no
        a.keterangan = keterangan

    # Flush so upsert sees stop_time_id + stop_time relationship resolvable
    session.flush()

    # 4) Upsert report facts for stopped activities (atomic facts; includes NP/BT/BR)
    if activities_to_stop:
        report.upsert_report_facts_for_stopped_activities(activities_to_stop, session)

    # 5) Start the next activity
    next_is_non_machine = is_non_machine_category(next_category)

    target_mesin_id = None if next_is_non_machine else mesin_id
    target_tooling_id = None if next_is_non_machine else tooling_id

    # Check for existing identical active activity to prevent duplicates
    existing_active = (
        session.query(models.ActivityMesin)
        .filter(
            models.ActivityMesin.operator_id == operator_id,
            models.ActivityMesin.category == next_category,
            models.ActivityMesin.stop_time_id.is_(None),
            models.ActivityMesin.mesin_id.is_(target_mesin_id) if target_mesin_id is None else models.ActivityMesin.mesin_id == target_mesin_id,
            models.ActivityMesin.tooling_id.is_(target_tooling_id) if target_tooling_id is None else models.ActivityMesin.tooling_id == target_tooling_id,
        )
        .first()
    )

    if existing_active:
        session.commit()
        return

    new_activity = models.ActivityMesin(
        mesin_id=target_mesin_id,
        operator_id=operator_id,
        tooling_id=target_tooling_id,
        category=next_category,
        start_time_id=new_log.id,
        stop_time_id=None,
    )
    session.add(new_activity)

    # Single commit at the end keeps this whole transition consistent
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
    code = _category_code(downtime_category)
    return models.Status.SETUP if code in SETUP_CODES else models.Status.IDLE


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
    code = _category_code(downtime_category)
    return (
        models.DisplayedStatus.IDLE
        if code in NON_MACHINE_CODES
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


def generate_single_barcode(model_type, record_id, session):
    """
    Generate a single QR code barcode for a specific record ID.
    Returns a PNG image of the QR code.
    """
    # Validate model and check if record exists
    model_mapping = {
        "tooling": models.Tooling,
        "mesin": models.Mesin,
        "operator": models.Operator
    }

    if model_type.lower() not in model_mapping:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model '{model_type}'. Must be one of: {', '.join(model_mapping.keys())}"
        )

    model_class = model_mapping[model_type.lower()]

    # Check if record exists
    record = session.query(model_class).filter(model_class.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Record with ID '{record_id}' not found in {model_type} table"
        )

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,  # Larger box size for better visibility
        border=4,
    )
    qr.add_data(record_id)
    qr.make(fit=True)

    # Create QR code image
    img_pil = qr.make_image(fill_color="black", back_color="white")

    # Convert to bytes
    img_byte_arr = BytesIO()
    img_pil.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)

    return img_byte_arr


def generate_report_response(df, filename, report_format):
    if "dashboard" in report_format.value:
        rows = df.to_dict(orient="records")
        return JSONResponse(content={
            "rows": rows,
            "total": len(rows)
        })
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


def export_model_csv(model, model_name, session):
    """
    Export all records from a model table as CSV file.
    Similar to backup functionality but returns a streaming response.
    Excludes time_created and time_updated columns.
    """
    # Query all records from the model
    records = session.query(model).all()

    # Define columns to exclude from export
    excluded_columns = ["time_created", "time_updated"]

    # Create CSV content
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")

    if records:
        # Write column headers (excluding time_created and time_updated)
        column_names = [
            column.name for column in records[0].__table__.columns
            if column.name not in excluded_columns
        ]
        writer.writerow(column_names)

        # Write data rows
        for record in records:
            row = []
            for column in record.__table__.columns:
                # Skip excluded columns
                if column.name in excluded_columns:
                    continue

                value = getattr(record, column.name)
                # Add Excel-compatible formatting for strings (same as backup.py)
                if isinstance(value, str) and value:
                    value = f'="{value}"'
                row.append(value)
            writer.writerow(row)
    else:
        # If no records, just write headers from the model (excluding time columns)
        column_names = [
            column.name for column in model.__table__.columns
            if column.name not in excluded_columns
        ]
        writer.writerow(column_names)

    stream.seek(0)
    response_content = stream.getvalue()
    filename = f"{model_name}_export.csv"

    return StreamingResponse(
        iter([response_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _get_downtime_category(downtime_category):
    return _category_code(downtime_category)


def _update_downtime_mesin_status(downtime_category):
    return (
        models.Status.SETUP
        if _category_code(downtime_category) in SETUP_CODES
        else models.Status.IDLE
    )


def _dashboard_status_code_from_category(category: str) -> str:
    """Convert category to dashboard status code"""
    code = _category_code(category)
    return "OK" if code == "U" else code


def _status_bucket(category: str) -> int:
    """
    Lower number = higher priority.
    Priority:
    0 = Utility / running
    1 = machine downtime
    2 = non-machine statuses
    3 = fallback
    """
    code = _category_code(category)

    if code == "U":
        return 0
    if code in NON_MACHINE_CODES:
        return 2
    if code:
        return 1
    return 3


def resolve_current_machine_status(machine_id: str, session):
    """
    Single source of truth for current machine status.
    Returns one chosen active activity for the machine.
    """
    start_log = aliased(models.MesinLog)

    activities = (
        session.query(
            models.ActivityMesin.id.label("activity_id"),
            models.ActivityMesin.mesin_id.label("mesin_id"),
            models.ActivityMesin.tooling_id.label("tooling_id"),
            models.ActivityMesin.operator_id.label("operator_id"),
            models.ActivityMesin.category.label("category"),
            start_log.timestamp.label("start_ts"),
            models.Mesin.name.label("machine_name"),
            models.Operator.name.label("operator_name"),
        )
        .join(start_log, models.ActivityMesin.start_time_id == start_log.id)
        .outerjoin(models.Mesin, models.ActivityMesin.mesin_id == models.Mesin.id)
        .outerjoin(models.Operator, models.ActivityMesin.operator_id == models.Operator.id)
        .filter(models.ActivityMesin.stop_time_id.is_(None))
        .filter(models.ActivityMesin.mesin_id == machine_id)
        .all()
    )

    if not activities:
        return {
            "machine_id": machine_id,
            "machine_name": None,
            "status_code": "IDLE",
            "status_label": "IDLE",
            "category": None,
            "operator_id": None,
            "operator_name": None,
            "tooling_id": None,
            "start_ts": None,
        }

    def sort_key(a):
        return (
            _status_bucket(a.category),   # Utility first, then DT, then NP/BT/BR
            -a.start_ts.timestamp(),      # latest started wins inside same bucket
        )

    chosen = sorted(activities, key=sort_key)[0]
    status_code = _dashboard_status_code_from_category(chosen.category)

    return {
        "machine_id": chosen.mesin_id,
        "machine_name": chosen.machine_name,
        "status_code": status_code,
        "status_label": "OK" if status_code == "OK" else chosen.category,
        "category": chosen.category,
        "operator_id": chosen.operator_id,
        "operator_name": chosen.operator_name,
        "tooling_id": chosen.tooling_id,
        "start_ts": chosen.start_ts.isoformat() if chosen.start_ts else None,
    }


def get_current_machine_status_map(session, machine_ids: list[str]):
    """Get current status for multiple machines"""
    result = {}
    for machine_id in machine_ids:
        result[machine_id] = resolve_current_machine_status(machine_id, session)
    return result
