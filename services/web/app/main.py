import os
from datetime import timedelta

import fastapi
from fastapi import UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv
from fastapi_sqlalchemy import DBSessionMiddleware
from fastapi.responses import StreamingResponse
from passlib.context import CryptContext

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
import app.auth as auth

load_dotenv(".env")

app = fastapi.FastAPI()

app.add_middleware(DBSessionMiddleware, db_url=os.environ["DATABASE_URL"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3333",
        "http://192.168.0.103:3333",
        "http://192.168.0.218:3333",
    ],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.post("/token")
async def login_for_access_token(form_data: fastapi.security.OAuth2PasswordRequestForm = Depends(), db=Sessioner):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=schema.User)
async def read_users_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_user(username: str, password: str, role_name: str, db_session):
    hashed_password = pwd_context.hash(password)
    role = db_session.query(models.Role).filter(models.Role.role == role_name).first()
    if role is None:
        raise ValueError(f"No such role: {role_name}")

    new_user = models.User(username=username, hashed_password=hashed_password, role=role)
    db_session.add(new_user)
    db_session.commit()
    return new_user

@app.post("/users/")
def create_user_endpoint(username: str, password: str, role: str, db=Sessioner):
    db_user = db.query(models.User).filter(models.User.username == username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    try:
        user = create_user(username, password, role, db)
        return {"username": user.username, "id": user.id, "role": user.role}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/db-ingestion")
def import_to_db():
    db_ingestion.import_to_db("data/db/data_all.csv")
    return True


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
    stop_log_alias = aliased(models.MesinLog, name="stop_log")

    start_time = case(
        [
            (
                models.MesinStatus.last_stop_id != None,
                func.timezone("Asia/Jakarta", start_log_alias.timestamp),
            ),
        ],
        else_=func.timezone("Asia/Jakarta", stop_log_alias.timestamp),
    ).label("Start Time")

    mesin_status = (
        session.query(
            start_time.label("Start Time"),
            models.MesinStatus.id.label("Mesin"),
            models.MesinStatus.last_tooling_id.label("Tooling"),
            case(
                [
                    (
                        models.MesinStatus.displayed_status
                        != models.DisplayedStatus.IDLE,
                        models.MesinStatus.last_operator_id,
                    ),
                ],
                else_=None,
            ).label("Operator"),
            models.MesinStatus.displayed_status.label("Status"),
            models.MesinStatus.category_downtime.label("Kategori Downtime"),
        )
        .outerjoin(
            models.Operator, models.Operator.id == models.MesinStatus.last_operator_id
        )
        .outerjoin(
            start_log_alias, models.MesinStatus.last_start_id == start_log_alias.id
        )
        .outerjoin(stop_log_alias, models.MesinStatus.last_stop_id == stop_log_alias.id)
        .order_by(desc(start_time))
        .all()
    )

    return {"details": mesin_status}


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

# check_operator_status
@app.post("/operator-status")
def check_operator_status(request: schema.CheckOperatorStatus, session=Sessioner):
    mesin_status_ok, mesin_error_msg = business_logic.check_mesin(
        mesin_id=request.mesin_id, operator_id=request.operator_id, session=session
    )

    operator_status_ok = False
    operator_error_msg = ""
    if mesin_status_ok:
        operator_status_ok, operator_error_msg = business_logic.check_operator(
            tooling_id=request.tooling_id,
            mesin_id=request.mesin_id,
            operator_id=request.operator_id,
            session=session,
        )

    return {
        "isSuccess": operator_status_ok and mesin_status_ok,
        "errorMessage": operator_error_msg + mesin_error_msg,
    }


@app.post("/activity")
def post_activity(activity: schema.Activity, session=Sessioner):
    if (
        session.query(models.Mesin).filter(models.Mesin.id == activity.mesin_id).first()
        is None
        or session.query(models.Tooling)
        .filter(models.Tooling.id == activity.tooling_id)
        .first()
        is None
        or session.query(models.Operator)
        .filter(models.Operator.id == activity.operator_id)
        .first()
        is None
    ):
        raise fastapi.HTTPException(404, "Invalid input")

    match activity.type:
        case schema.ActivityType.START:
            business_logic.start_activity(activity, session)
        case schema.ActivityType.FIRST_STOP:
            business_logic.first_stop_activity(activity, session)
        case schema.ActivityType.CONTINUE_STOP:
            business_logic.continue_stop_activity(activity, session)
        case _:
            raise fastapi.HTTPException(404, "Invalid activity type")

    return {"isSuccess": True}


@app.get("/mesin/status/{mesin_id}")
def get_mesin_status(mesin_id: str, session=Sessioner):
    status = models.Status.IDLE
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.id == mesin_id)
        .one_or_none()
    )
    if mesin_status is not None:
        status = mesin_status.status
    return {"status": status}


# ----- GET APIs ----- #
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


@app.get("/operator-status-all/")
def get_operator_status_all(session=Sessioner):
    operator_status = session.query(models.OperatorStatus).all()
    return operator_status


@app.get("/operator/status/{operator_id}")
def get_operator_status(operator_id: str, session=Sessioner):
    (
        is_running,
        operator_status,
        tooling_id,
        mesin_id,
    ) = business_logic.is_operator_running(operator_id, session)
    return {
        "isRunning": is_running,
        "operatorStatus": operator_status,
        "toolingId": tooling_id,
        "mesinId": mesin_id,
    }


@app.get("/start/")
def get_start(session=Sessioner):
    start = session.query(models.Start).all()
    return start


@app.get("/stop/")
def get_stop(session=Sessioner):
    stop = session.query(models.Stop).all()
    return stop


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
    print(tooling.id)

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


@app.delete("/tooling/{tooling_id}", status_code=204)
async def delete_tooling(tooling_id: str, session=Sessioner):
    try:
        # Logic to delete tooling from database
        tooling = (
            session.query(models.Tooling)
            .filter(models.Tooling.id == tooling_id)
            .first()
        )
        if tooling is None:
            raise HTTPException(status_code=404, detail="Tooling not found")

        session.delete(tooling)
        session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting tooling: {e}")

    return fastapi.Response(status_code=204)


@app.get("/mock-data")
async def mock_data_api():
    mock_data.run_activity()
    return

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
