import os
import io

import fastapi
import uvicorn
from dotenv import load_dotenv
from fastapi_sqlalchemy import DBSessionMiddleware, db


import business_logic
import models
import schema
from database import Sessioner
import generate_report
import db_ingestion
import get_id

load_dotenv(".env")

app = fastapi.FastAPI()

app.add_middleware(DBSessionMiddleware, db_url=os.environ["DATABASE_URL"])


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/add-tooling/", response_model=schema.Tooling)
def add_tooling(tooling: schema.Tooling, session=Sessioner):
    tooling = models.Tooling(**dict(tooling))
    session.add(tooling)
    session.commit()
    return tooling


@app.post("/report/mesin")
def get_report(request: schema.ReportRequest):
    df, filename = generate_report.get_mesin_report(
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
    )
    response = fastapi.responses.StreamingResponse(
        io.StringIO(df.to_csv(index=False)), media_type="text/csv"
    )

    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.post("/report/operator")
def get_report(request: schema.ReportRequest):
    df, filename = generate_report.get_operator_report(
        date_time_from=request.date_from,
        shift_from=request.shift_from,
        date_time_to=request.date_to,
        shift_to=request.shift_to,
    )
    response = fastapi.responses.StreamingResponse(
        io.StringIO(df.to_csv(index=False)), media_type="text/csv"
    )

    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.post("/db-ingestion")
def import_to_db():
    db_ingestion.import_to_db("data_all.csv")
    return True


@app.get("/get-id")
def get_all_ids():
    get_id.get_csv(models.Tooling, "tooling")
    get_id.get_csv(models.Mesin, "mesin")
    get_id.get_csv(models.Operator, "operator")
    return True


@app.get("/mesin-status-all/")
def get_mesin_status(session=Sessioner):
    mesin_status_idle = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.displayed_status == models.DisplayedStatus.IDLE)
        .with_entities(
            models.MesinStatus.id.label("Mesin"),
            models.MesinStatus.last_tooling_id.label("Tooling"),
            models.MesinStatus.displayed_status.label("Status"),
            models.MesinStatus.category_downtime.label("Categori Downtime"),
        )
        .order_by(models.MesinStatus.id.asc())
        .all()
    )
    mesin_status = (
        session.query(models.MesinStatus)
        .filter(models.MesinStatus.displayed_status != models.DisplayedStatus.IDLE)
        .with_entities(
            models.MesinStatus.id.label("Mesin"),
            models.MesinStatus.last_tooling_id.label("Tooling"),
            models.MesinStatus.last_operator_id.label("Operator"),
            models.MesinStatus.displayed_status.label("Status"),
            models.MesinStatus.category_downtime.label("Categori Downtime"),
        )
        .order_by(models.MesinStatus.id.asc())
        .all()
    )
    return {"details": mesin_status + mesin_status_idle}


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
            business_logic.start_activity(
                tooling_id=activity.tooling_id,
                mesin_id=activity.mesin_id,
                operator_id=activity.operator_id,
                reject=activity.reject,
                rework=activity.rework,
                session=session,
            )

        case schema.ActivityType.FIRST_STOP:
            business_logic.first_stop_activity(
                tooling_id=activity.tooling_id,
                mesin_id=activity.mesin_id,
                operator_id=activity.operator_id,
                output=activity.output,
                reject=activity.reject,
                rework=activity.rework,
                coil_no=activity.coil_no,
                lot_no=activity.lot_no,
                pack_no=activity.pack_no,
                downtime_category=activity.category_downtime,
                session=session,
            )

        case schema.ActivityType.CONTINUE_STOP:
            business_logic.continue_stop_activity(
                tooling_id=activity.tooling_id,
                mesin_id=activity.mesin_id,
                operator_id=activity.operator_id,
                reject=activity.reject,
                rework=activity.rework,
                downtime_category=activity.category_downtime,
                session=session,
            )
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
    toolings = session.query(models.Tooling).all()
    return toolings


@app.get("/mesin/")
def get_mesin(session=Sessioner):
    mesin = session.query(models.Mesin).all()
    return mesin


@app.get("/operator/")
def get_operator(session=Sessioner):
    operators = session.query(models.Operator).all()
    return operators


@app.get("/utility-mesin/")
def get_utility_mesin(session=Sessioner):
    utility_mesin = session.query(models.UtilityMesin).all()
    return utility_mesin


@app.get("/last-downtime-mesin/")
def get_last_downtime_mesin(session=Sessioner):
    last_downtime_mesin = session.query(models.LastDowntimeMesin).all()
    return last_downtime_mesin


@app.get("/continued-downtime-mesin/")
def get_continued_downtime_mesin(session=Sessioner):
    continued_downtime_mesin = session.query(models.ContinuedDowntimeMesin).all()
    return continued_downtime_mesin


@app.get("/utility-operator/")
def get_utility_operator(session=Sessioner):
    utility_operator = session.query(models.UtilityOperator).all()
    return utility_operator


@app.get("/last-downtime-operator/")
def get_last_downtime_operator(session=Sessioner):
    last_downtime_operator = session.query(models.LastDowntimeOperator).all()
    return last_downtime_operator


@app.get("/continued-downtime-operator/")
def get_continued_downtime_operator(session=Sessioner):
    continued_downtime_operator = session.query(models.ContinuedDowntimeOperator).all()
    return continued_downtime_operator


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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
