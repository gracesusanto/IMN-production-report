import re
import io
import csv
from datetime import timedelta

from fastapi import HTTPException

from openpyxl import Workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from io import BytesIO
import qrcode

import app.model.models as models
import app.schema as schema


def is_operator_running(operator_id, session):
    operator_status = (
        session.query(models.OperatorStatus)
        .filter(models.OperatorStatus.id == operator_id)
        .one_or_none()
    )

    if operator_status is None:
        return False, models.DisplayedStatus.IDLE, "", ""

    if operator_status.status == models.DisplayedStatus.IDLE:
        return False, operator_status.status, "", ""
    else:
        return (
            True,
            operator_status.status,
            operator_status.last_tooling_id,
            operator_status.last_mesin_id,
        )


def check_operator(tooling_id, mesin_id, operator_id, session):
    operator_status = (
        session.query(models.OperatorStatus)
        .filter(models.OperatorStatus.id == operator_id)
        .one_or_none()
    )

    if operator_status is None:
        operator_status = models.OperatorStatus(
            id=operator_id,
            status=models.DisplayedStatus.RUNNING,
            last_tooling_id=tooling_id,
            last_mesin_id=mesin_id,
        )
        session.add(operator_status)
        session.commit()
        return True, ""

    if operator_status.status != models.DisplayedStatus.RUNNING:
        return True, ""
    else:
        if (
            operator_status.last_tooling_id == tooling_id
            and operator_status.last_mesin_id == mesin_id
        ):
            return True, ""

    message = (
        f"ERROR \nOperator {operator_id} sedang running di \n"
        + f"Mesin:\t {operator_status.last_mesin_id} \n"
        + f"Tooling:\t {operator_status.last_tooling_id}\n\n"
        + f"Silahkan stop operasi di Mesin {operator_status.last_mesin_id} dan Tooling {operator_status.last_tooling_id} dengan kategori NP : No Planning, \n"
        + "atau ganti operator di mesin tersebut.\n\n"
    )

    return False, message


def check_mesin(mesin_id, operator_id, session):
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )

    if mesin_status is None:
        return True, ""

    if mesin_status.displayed_status != models.DisplayedStatus.RUNNING:
        return True, ""

    if mesin_status.last_operator_id == operator_id:
        return True, ""

    message = (
        f"ERROR \nMesin {mesin_id} sedang running dengan detail \n"
        + f"Operator:\t {mesin_status.last_operator_id} \n"
        + f"Tooling:\t {mesin_status.last_tooling_id}.\n\n"
        + "Silahkan stop mesin terlebih dahulu."
    )

    return False, message


def start_activity(tooling_id, mesin_id, operator_id, reject, rework, session):
    # Insert to Start Table
    start_entity = models.MesinLog(
        tooling_id=tooling_id,
        mesin_id=mesin_id,
        operator_id=operator_id,
        category=models.MesinLogEnum.START,
    )
    session.add(start_entity)
    session.commit()

    # Get current mesin status
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is None:
        # Create mesin status, insert last stop 5 seconds before starting
        first_stop_mesin = models.MesinLog(
            mesin_id=mesin_id,
            timestamp=start_entity.timestamp - timedelta(seconds=5),
            downtime_category="Object Creation",
            category=models.MesinLogEnum.STOP,
        )
        session.add(first_stop_mesin)
        session.commit()

        mesin_status = models.MesinStatus(
            id=mesin_id,
            status=models.Status.IDLE,
            last_stop=first_stop_mesin,
            last_start=start_entity,
            last_tooling_id=tooling_id,
            last_operator_id=operator_id,
        )
        session.add(mesin_status)

    if mesin_status.status == models.Status.RUNNING:
        raise HTTPException(status_code=403, detail="Machine is already running")

    prev_downtime_category = mesin_status.last_stop.downtime_category

    # Insert mesin's last downtime
    last_downtime = models.ActivityMesin(
        mesin_id=mesin_id,
        operator_id=mesin_status.last_operator_id,
        start_time=mesin_status.last_stop,
        stop_time=start_entity,
        reject=reject,
        rework=rework,
        downtime_category=prev_downtime_category,
    )
    session.add(last_downtime)
    session.commit()

    if mesin_status.last_operator_id != operator_id:
        operator_status_old = (
            session.query(models.OperatorStatus)
            .filter(models.OperatorStatus.id == mesin_status.last_operator_id)
            .one_or_none()
        )
        operator_status_old.status = models.DisplayedStatus.IDLE

    operator_status_new = (
        session.query(models.OperatorStatus)
        .filter(models.OperatorStatus.id == operator_id)
        .one_or_none()
    )
    operator_status_new.last_tooling_id = tooling_id
    operator_status_new.last_mesin_id = mesin_id
    operator_status_new.status = models.DisplayedStatus.RUNNING

    # Update mesin's status and last start
    mesin_status.status = models.Status.RUNNING
    mesin_status.last_start = start_entity
    mesin_status.last_tooling_id = tooling_id
    mesin_status.last_operator_id = operator_id
    mesin_status.category_downtime = "U : Utility"
    mesin_status.displayed_status = models.DisplayedStatus.RUNNING
    session.commit()


def first_stop_activity(
    tooling_id,
    mesin_id,
    operator_id,
    output,
    downtime_category,
    reject,
    rework,
    session,
    coil_no="",
    lot_no="",
    pack_no="",
):
    # Insert to Stop Table
    stop_entity = models.MesinLog(
        tooling_id=tooling_id,
        mesin_id=mesin_id,
        operator_id=operator_id,
        output=output,
        downtime_category=downtime_category,
        category=models.MesinLogEnum.STOP,
    )
    session.add(stop_entity)
    session.commit()

    # Get current mesin status
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is None:
        # Create mesin status, insert last start 5 seconds before stopping
        first_start_mesin = models.MesinLog(
            mesin_id=mesin_id,
            timestamp=stop_entity.timestamp - timedelta(seconds=5),
            category=models.MesinLogEnum.START,
        )
        session.add(first_start_mesin)
        session.commit()

        mesin_status = models.MesinStatus(
            id=mesin_id,
            status=models.Status.RUNNING,
            last_stop=stop_entity,
            last_start=first_start_mesin,
            last_tooling_id=tooling_id,
            last_operator_id=operator_id,
        )
        session.add(mesin_status)

    if mesin_status.status != models.Status.RUNNING:
        raise HTTPException(status_code=403, detail="Machine is already idle")

    # Insert mesin's utility table
    utility = models.ActivityMesin(
        mesin_id=mesin_id,
        operator_id=mesin_status.last_operator_id,
        start_time=mesin_status.last_start,
        stop_time=stop_entity,
        output=output,
        reject=reject,
        rework=rework,
        coil_no=coil_no,
        lot_no=lot_no,
        pack_no=pack_no,
    )
    session.add(utility)
    session.commit()

    displayed_status = _get_displayed_status(downtime_category)

    if (mesin_status.last_operator_id != operator_id) or (
        mesin_status.last_operator_id == operator_id
        and displayed_status == models.DisplayedStatus.IDLE
    ):
        operator_status_old = (
            session.query(models.OperatorStatus)
            .filter(models.OperatorStatus.id == mesin_status.last_operator_id)
            .one_or_none()
        )
        operator_status_old.status = models.DisplayedStatus.IDLE

    operator_status_new = (
        session.query(models.OperatorStatus)
        .filter(models.OperatorStatus.id == operator_id)
        .one_or_none()
    )
    operator_status_new.last_tooling_id = tooling_id
    operator_status_new.last_mesin_id = mesin_id
    operator_status_new.status = displayed_status

    # Update mesin's status and last stop
    mesin_status.status = _update_downtime_mesin_status(downtime_category)
    mesin_status.last_stop = stop_entity
    mesin_status.last_tooling_id = tooling_id
    mesin_status.last_operator_id = operator_id
    mesin_status.category_downtime = downtime_category

    mesin_status.displayed_status = displayed_status

    session.commit()


def continue_stop_activity(
    tooling_id, mesin_id, operator_id, downtime_category, reject, rework, session
):
    # Insert to Stop Table
    stop_entity = models.MesinLog(
        tooling_id=tooling_id,
        mesin_id=mesin_id,
        operator_id=operator_id,
        downtime_category=downtime_category,
        category=models.MesinLogEnum.STOP,
    )
    session.add(stop_entity)
    session.commit()

    # Get current mesin status
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is None:
        # Create mesin status, insert last start 5 seconds before stopping
        first_start_mesin = models.MesinLog(
            mesin_id=mesin_id,
            timestamp=stop_entity.timestamp - timedelta(seconds=5),
            category=models.MesinLogEnum.START,
        )
        session.add(first_start_mesin)
        session.commit()

        mesin_status = models.MesinStatus(
            id=mesin_id,
            status=models.Status.IDLE,
            last_stop=stop_entity,
            last_start=first_start_mesin,
            last_tooling_id=tooling_id,
            last_operator_id=operator_id,
        )
        session.add(mesin_status)

    if mesin_status.status == models.Status.RUNNING:
        raise HTTPException(status_code=403, detail="Machine is not running")

    prev_downtime_category = mesin_status.last_stop.downtime_category

    # Insert mesin's continued downtime table
    continued_downtime = models.ActivityMesin(
        mesin_id=mesin_id,
        operator_id=mesin_status.last_operator_id,
        start_time=mesin_status.last_stop,
        stop_time=stop_entity,
        reject=reject,
        rework=rework,
        downtime_category=prev_downtime_category,
    )
    session.add(continued_downtime)
    session.commit()

    displayed_status = _get_displayed_status(downtime_category)

    if (mesin_status.last_operator_id != operator_id) or (
        mesin_status.last_operator_id == operator_id
        and displayed_status == models.DisplayedStatus.IDLE
    ):
        operator_status_old = (
            session.query(models.OperatorStatus)
            .filter(models.OperatorStatus.id == mesin_status.last_operator_id)
            .one_or_none()
        )
        operator_status_old.status = models.DisplayedStatus.IDLE

    operator_status_new = (
        session.query(models.OperatorStatus)
        .filter(models.OperatorStatus.id == operator_id)
        .one_or_none()
    )
    operator_status_new.last_tooling_id = tooling_id
    operator_status_new.last_mesin_id = mesin_id
    operator_status_new.status = displayed_status

    # Update mesin's status and last stop
    mesin_status.status = _update_downtime_mesin_status(downtime_category)
    mesin_status.last_stop = stop_entity
    mesin_status.last_tooling_id = tooling_id
    mesin_status.last_operator_id = operator_id
    mesin_status.category_downtime = downtime_category

    mesin_status.displayed_status = displayed_status

    session.commit()


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


def insert_or_update_mesin(name: str, tonase: str, session) -> models.Mesin:
    if not validate_mesin_name(name) or not validate_tonase(tonase):
        raise HTTPException(status_code=400, detail="Invalid name or tonase")

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


def insert_or_update_operator(name: str, nik: str, session) -> models.Operator:
    if not validate_nik(nik) or not validate_name(name):
        raise HTTPException(status_code=400, detail="Invalid name or nik")

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
    return re.match(schema.ALPHABET_SPACE_PERIOD, name) is not None


def validate_mesin_name(name: str) -> bool:
    # Alphanumeric characters and hyphens
    return re.match(schema.ALPHANUMERIC_HYPHENS, name) is not None


def validate_tonase(tonase: str) -> bool:
    # Digits only
    return re.match(schema.DIGIT, tonase) is not None


def process_operator_row(row, session):
    name, nik = row[0].strip(), row[1].strip()
    insert_or_update_operator(name, nik, session)


def process_mesin_row(row, session):
    name, tonase = row[0].strip(), row[1].strip()
    insert_or_update_mesin(name, tonase, session)


def process_tooling_row(row, session):
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

        for row in csvreader:
            row_processor(row, session)
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
        items = session.query(models.Operator).with_entities(models.Operator.id).all()
        filename = "barcode_operator.xlsx"
    elif model == "mesin":
        items = session.query(models.Mesin).with_entities(models.Mesin.id).all()
        filename = "barcode_mesin.xlsx"
    elif model == "tooling":
        items = session.query(models.Tooling).with_entities(models.Tooling.id).all()
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


def _get_downtime_category(downtime_category):
    return downtime_category[:2].upper()


def _update_downtime_mesin_status(downtime_category):
    return (
        models.Status.SETUP
        if _get_downtime_category(downtime_category) in ["TP", "TS", "TL"]
        else models.Status.IDLE
    )


def _get_displayed_status(downtime_category):
    downtime_category_initial = _get_downtime_category(downtime_category)
    return (
        models.DisplayedStatus.IDLE
        if downtime_category_initial in ["NP", "BT", "BR"]
        else models.DisplayedStatus.DOWNTIME
    )
