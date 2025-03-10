import os
import io

import fastapi
from fastapi import UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from fastapi_sqlalchemy import DBSessionMiddleware
from fastapi.responses import StreamingResponse

from sqlalchemy.orm import aliased
from sqlalchemy import case, func, desc

import app.service.business_logic as business_logic
import app.model.models as models
import app.schema as schema
from app.database import Sessioner
import app.cmd.generate_report as generate_report
import app.cmd.db_ingestion as db_ingestion
import app.cmd.backup_csv.backup as backup
import app.cmd.get_id as get_id
import app.cmd.mock_data as mock_data

load_dotenv(".env")

app = fastapi.FastAPI()

app.add_middleware(DBSessionMiddleware, db_url=os.environ["DATABASE_URL"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # prod
        "http://localhost:3333",
        "http://192.168.0.103:3333",
        "http://192.168.0.218:3333",
        # dev
        "http://localhost:3334",
        "http://192.168.0.103:3334",
        "http://192.168.0.218:3334",
    ],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.get("/operator/status/{operator_id}")
def get_operator_status(operator_id: str, session=Sessioner):
    """
    API to return the list of machines an operator is working on.
    Used by Main Screen to present current active machines operator can choose from.
    """

    # No need to show active activities that are not related to machine
    activities = business_logic.get_operator_active_machines(operator_id, business_logic.NO_PLAN_CATEGORY, session)

    # If the operator has no active activities, set isRunning to False
    # IN which case app will only display "Mulai Aktivitas Baru"
    if not activities:
        return {
            "isRunning": False,
            "machines": []  # No active machines
        }

    # Used to determine where to go in Main Screen
    # U                                 --> RUNNING  --> Can input "output"
    # NP, BR, BT (Non Machine Category) --> STOP     --> Mulai Aktivitas Baru dan Akhiri {category} --> Pick new activity
    # Others: machine related downtime  --> DOWNTIME --> Ganti kategori downtime with the appropriate input boxes
    def get_mesin_status_from_category(category):
        if category == "U ":
            return "RUNNING"
        elif business_logic.is_non_machine_category(category):
            return "STOP"
        else:
            return "DOWNTIME"

    # Build the response with multiple machines
    # If the activity is non-machine related (BR, BT, RP), dont send duplicate
    machines = []
    seen_categories = set()  # Track categories that have already been included

    for activity in activities:
        if business_logic.is_non_machine_category(activity.category):
            if activity.category in seen_categories:
                continue  # Skip duplicate category
            seen_categories.add(activity.category)  # Mark category as processed

        machines.append({
            "mesinId": activity.mesin_id,
            "toolingId": activity.tooling_id,
            "category": activity.category,
            "mesinStatus": get_mesin_status_from_category(activity.category[:2])
        })


    return {
        "isRunning": True,
        "machines": machines  # List of active machines
    }

@app.post("/activity")
def post_activity(activity: schema.Activity, session=Sessioner):
    """
    API when Operator wants to stop an activity and/or start an activity
    1. Add event to mesin_log
    2. Stop operator's active NP activity (in activity_mesin)
    3. Stop current category activity as specified by operator (in activity_mesin)
    4. Start a new activity with next category, the newly created mesin_log entry as start id, and null stop id
    """

    # frontend is sending "null" instead of Null or None or empty string
    def normalize_null(value):
        """Convert 'null' (string), None, or empty strings to None."""
        return None if value in ["null", None, ""] else value

    # Apply it to the fields
    activity.curr_category = normalize_null(activity.curr_category)
    activity.mesin_id = normalize_null(activity.mesin_id)
    activity.tooling_id = normalize_null(activity.tooling_id)

    if activity.mesin_id and activity.tooling_id:
        # Validate that mesin, tooling, and operator exist
        if not all([
            session.query(models.Mesin).filter(models.Mesin.id == activity.mesin_id).first(),
            session.query(models.Tooling).filter(models.Tooling.id == activity.tooling_id).first(),
            session.query(models.Operator).filter(models.Operator.id == activity.operator_id).first()
        ]):
            raise fastapi.HTTPException(404, "Invalid input")
    else:
        activity.mesin_id = None
        activity.tooling_id = None
        # Empty mesin_id and tooling_id mean "Mulai Aktivitas Baru" is chosen
        if not session.query(models.Operator).filter(models.Operator.id == activity.operator_id).first():
            raise fastapi.HTTPException(404, "Invalid input")

    business_logic.process_activity(activity, session)

    return {"isSuccess": True}



@app.post("/activity/status")
def get_activity_status(request: schema.ActivityStatusRequest, session=Sessioner):
    """
    Returns the current status of a machine and the activities of the requesting operator.
    Used in ConfirmScreen to determine navigation and display warnings.
    """

    mesin_id = request.mesin_id
    operator_id = request.operator_id
    curr_category = request.curr_category

    active_activities = (
        session.query(models.ActivityMesin)
        .filter(models.ActivityMesin.mesin_id == mesin_id)
        .filter(models.ActivityMesin.operator_id == operator_id)
        .filter(models.ActivityMesin.stop_time_id == None)  # Only active activities
        .all()
    )

    error = ""

    # Empty category means "Mulai Aktivitas Baru"
    # If operator is trying to work on the same mesin, disallow.
    if curr_category == "" and active_activities is not None:
        for active_activity in active_activities:
            # mesin only matters on machine-related categories
            # So it is okay to have multiple NP/BR/BT ongoing activities
            if not business_logic.is_non_machine_category(active_activity.category):
                error = f"Operator {operator_id} sedang menjalankan {active_activity.category} pada mesin {mesin_id}."
                break

    # Get all operator's current active activities
    # But no need to show NP category
    active_operator_activities = business_logic.get_operator_active_machines(operator_id, business_logic.NO_PLAN_CATEGORY, session)

    # Get all operators currently using the requested machine
    # But no need to show Non-Machine related active activities
    active_machine_activities = business_logic.get_machine_active_operators(mesin_id, business_logic.NON_MACHINE_CATEGORY, session)

    # Returns the current machine status (the one the operator is about to end)
    # to determine which screen frontend app is to go next (which input field to show)
    # U          --> RUNNING --> output, reject, rework
    # TS, TL, TP --> SETUP   --> reject, rework
    # else       --> IDLE    --> no need to submit anything
    def get_mesin_status_from_category(full_category):
        category = full_category[:2]
        if category == "U ":
            return "RUNNING"
        elif business_logic.is_setup_category(category):
            return "SETUP"
        else:
            return "IDLE"

    # current mesin status to determine which screen to go next
    if curr_category != "":
        mesin_status = get_mesin_status_from_category(curr_category)
    else:
        mesin_status = "IDLE"

    # List all operators currently running the machine
    operators_on_machine = []
    for activity in active_machine_activities:
        if not (activity.operator_id == request.operator_id and activity.category == curr_category):
            operators_on_machine.append({"operator_id": activity.operator_id, "tooling_id": activity.tooling_id or "", "category": activity.category or ""})

    # List all machines currently operated by this operator
    machines_by_operator = []
    for activity in active_operator_activities:
        if not (activity.mesin_id == request.mesin_id and activity.category == curr_category):
            machines_by_operator.append({"mesin_id": activity.mesin_id or "", "tooling_id": activity.tooling_id or "", "category": activity.category or ""})

    return {
        "error": error,                 # Prevent operator from creating another entry on the same machine that he is currently active on
        "mesin_status": mesin_status,   # Used in ConfirmScreen to determine navigation
        "operators_on_machine": operators_on_machine, # List of operators running on submitted mesin
        "machines_by_operator": machines_by_operator, # List of mesin the submitted operator is running at
    }

# ----- REPORT APIs ----- #
@app.post("/report/mesin")
def get_report(request: schema.ReportRequest):
    df, filename = generate_report.get_mesin_report(
        format=request.format,
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
        pagination=request.pagination,
        filters=request.filters,
        sort=request.sort,
    )
    return business_logic.generate_report_response(df, filename, request.format)

@app.post("/report/operator")
def get_report(request: schema.ReportRequest):
    df, filename = generate_report.get_operator_report(
        format=request.format,
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
        pagination=request.pagination,
        filters=request.filters,
        sort=request.sort,
    )
    return business_logic.generate_report_response(df, filename, request.format)

# ---- DB INGESTION APIs ---#
@app.post("/db-ingestion")
def import_to_db():
    db_ingestion.import_to_db("data/db/data_all.csv")
    return True

@app.get("/mock-data")
async def mock_data_api():
    mock_data.run_activity()
    return

# ----- BACKUP APIs ----- #
@app.post("/db-backup")
def backup_to_csv():
    backup.backup_to_csv()
    return True


@app.post("/db-import-backup")
def backup_from_csv():
    backup.backup_from_csv()
    return True

@app.get("/get-id")
def get_all_ids():
    get_id.get_csv(models.Tooling, "tooling")
    get_id.get_csv(models.Mesin, "mesin")
    get_id.get_csv(models.Operator, "operator")
    return True

@app.post("/report-backup")
def backup_report(request: schema.ReportBackupRequest):

    for fmt in [schema.FormatType.LIMAX, schema.FormatType.IMN]:
        df, filename = generate_report.get_operator_report(
            format=fmt,
            is_backup=True,
            backup_year=request.year, backup_month=request.month
        )
        df.to_csv(filename)

        df, filename = generate_report.get_mesin_report(
            format=fmt,
            is_backup=True,
            backup_year=request.year, backup_month=request.month
        )
        df.to_csv(filename)
    return

@app.delete("/activity-and-log")
def delete_old_data():
    for model in [models.ActivityMesin, models.MesinLog]:
        backup.delete_old_data(model)

@app.get("/mesin-status-all/")
def get_mesin_status(session=Sessioner):
    start_log_alias = aliased(models.MesinLog, name="start_log")

    # Get active activities (stop_time_id is None)
    mesin_status = (
        session.query(
            func.to_char(
                func.timezone("Asia/Jakarta", start_log_alias.timestamp),
                "YYYY-MM-DD HH24:MI:SS"
            ).label("Start Time"),
            models.ActivityMesin.mesin_id.label("Mesin"),
            models.ActivityMesin.tooling_id.label("Tooling"),
            models.ActivityMesin.operator_id.label("Operator"),
            models.ActivityMesin.category.label("Status"),
        )
        .join(start_log_alias, models.ActivityMesin.start_time_id == start_log_alias.id)
        .filter(models.ActivityMesin.stop_time_id.is_(None))  # Only active machines
        .filter(~models.ActivityMesin.category.startswith("NP"))  # Exclude "No Plan"
        .order_by(desc(start_log_alias.timestamp))  # Latest active activities first
        .all()
    )

    return {"details": mesin_status}

# ----- READ APIs ----- #
@app.get("/tooling/{tooling_id}", response_model=schema.Tooling)
def get_tooling(tooling_id: str, session=Sessioner):
    tooling = (
        session.query(models.Tooling)
        .filter(models.Tooling.id == tooling_id)
        .one_or_none()
    )
    if tooling is None:
        raise fastapi.HTTPException(404, f"No Tooling with id {tooling_id} found.")
    return tooling


@app.get("/mesin/{mesin_id}", response_model=schema.Mesin)
def get_mesin(mesin_id: str, session=Sessioner):
    mesin = (
        session.query(models.Mesin).filter(models.Mesin.id == mesin_id).one_or_none()
    )
    if mesin is None:
        raise fastapi.HTTPException(404, f"No Machine with id {mesin_id} found.")
    return mesin


@app.get("/operator/{operator_id}", response_model=schema.Operator)
def get_operator(operator_id: str, session=Sessioner):
    operator = (
        session.query(models.Operator)
        .filter(models.Operator.id == operator_id)
        .one_or_none()
    )
    if operator is None:
        raise fastapi.HTTPException(404, f"No Operator with id {operator_id} found.")
    return operator


# ----- READ APIs ----- #
@app.get("/tooling/")
def get_tooling(session=Sessioner):
    toolings = session.query(models.Tooling).order_by(models.Tooling.id).all()
    return toolings


@app.get("/mesin/")
def get_mesin(session=Sessioner):
    mesin = session.query(models.Mesin).order_by(models.Mesin.id).all()
    return mesin


@app.get("/operator/")
def get_operator(session=Sessioner):
    operators = session.query(models.Operator).order_by(models.Operator.id).all()
    return operators


@app.get("/activity-mesin/")
def get_activity_mesin(session=Sessioner):
    activity_mesin = session.query(models.ActivityMesin).all()
    return activity_mesin


@app.get("/mesin-log/")
def get_start(session=Sessioner):
    mesin_log = session.query(models.MesinLog).all()
    return mesin_log

# ----- CREATE & UPDATE APIs ----- #
@app.post("/operator/", response_model=schema.Operator)
def create_operator(operator_data: schema.OperatorCreate, session=Sessioner):
    operator = business_logic.insert_or_update_operator(
        operator_data, session
    )

    try:
        session.commit()
        return operator
    except Exception as e:
        session.rollback()
        raise fastapi.HTTPException(status_code=400, detail=str(e))


@app.post("/mesin/", response_model=schema.Mesin)
def create_mesin(mesin_data: schema.MesinCreate, session=Sessioner):
    mesin = business_logic.insert_or_update_mesin(
        mesin_data, session
    )
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        raise fastapi.HTTPException(status_code=400, detail=str(e))
    return mesin


@app.post("/tooling/", response_model=schema.Tooling)
def create_tooling(tooling_data: schema.ToolingCreate, session=Sessioner):
    tooling = business_logic.insert_or_update_tooling(tooling_data, session)

    try:
        session.commit()
        return tooling
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/operator/upload_csv")
async def upload_operator_csv(file: UploadFile = File(...), session=Sessioner):
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="Invalid file format")
    content = await file.read()
    try:
        business_logic.process_csv(
            content, business_logic.process_operator_row, session
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {e}")
    return {"detail": "Operators updated successfully"}


@app.post("/mesin/upload_csv")
async def upload_mesin_csv(file: UploadFile = File(...), session=Sessioner):
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="Invalid file format")
    content = await file.read()
    try:
        business_logic.process_csv(content, business_logic.process_mesin_row, session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {e}")
    return {"detail": "Mesin updated successfully"}


@app.post("/tooling/upload_csv")
async def upload_tooling_csv(file: UploadFile = File(...), session=Sessioner):
    if file.content_type != "text/csv":
        raise HTTPException(status_code=400, detail="Invalid file format")
    content = await file.read()
    try:
        business_logic.process_csv(content, business_logic.process_tooling_row, session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing CSV: {e}")
    return {"detail": "Tooling updated successfully"}

# ----- DELETE APIs ----- #
@app.delete("/tooling/{tooling_id}", status_code=204)
async def delete_tooling(tooling_id: str, session=Sessioner):
    business_logic.delete_item(models.Tooling, tooling_id, session)
    return fastapi.Response(status_code=204)


@app.delete("/mesin/{mesin_id}", status_code=204)
async def delete_mesin(mesin_id: str, session=Sessioner):
    business_logic.delete_item(models.Mesin, mesin_id, session)
    return fastapi.Response(status_code=204)


@app.delete("/operator/{operator_id}", status_code=204)
async def delete_operator(operator_id: str, session=Sessioner):
    business_logic.delete_item(models.Operator, operator_id, session)
    return fastapi.Response(status_code=204)


@app.get("/download-barcode/{model}/")
async def download_barcode(model: str, session=Sessioner):
    excel_file, filename = business_logic.generate_barcode(model, session)

    # Stream the Excel file directly without saving it to disk on the server
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
