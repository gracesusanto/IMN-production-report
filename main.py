import os

import fastapi
import uvicorn
from dotenv import load_dotenv
from fastapi_sqlalchemy import DBSessionMiddleware, db

import business_logic
import models
import schema
from database import Sessioner

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

@app.get("/utility_mesin/")
def get_utility_mesin(session=Sessioner):
    utility_mesin = session.query(models.UtilityMesin).all()
    return utility_mesin

@app.get("/last_downtime_mesin/")
def get_last_downtime_mesin(session=Sessioner):
    last_downtime_mesin = session.query(models.LastDowntimeMesin).all()
    return last_downtime_mesin

@app.get("/continued_downtime_mesin/")
def get_continued_downtime_mesin(session=Sessioner):
    continued_downtime_mesin = session.query(models.ContinuedDowntimeMesin).all()
    return continued_downtime_mesin

@app.get("/mesin_status/")
def get_mesin_status(session=Sessioner):
    mesin_status = session.query(models.MesinStatus).all()
    return mesin_status

@app.get("/start/")
def get_start(session=Sessioner):
    start = session.query(models.Start).all()
    return start
    
@app.get("/stop/")
def get_stop(session=Sessioner):
    stop = session.query(models.Stop).all()
    return stop

@app.get("/tooling/{tooling_id}", response_model=schema.Tooling)
def get_tooling(tooling_id: str, session=Sessioner):
    tooling = session.query(models.Tooling).filter(models.Tooling.id == tooling_id).one_or_none()
    if tooling is None:
        raise fastapi.HTTPException(404, f"No Tooling with id {tooling_id} found.")
    return tooling

@app.get("/mesin/{mesin_id}", response_model=schema.Mesin)
def get_mesin(mesin_id: str, session=Sessioner):
    mesin = session.query(models.Mesin).filter(models.Mesin.id == mesin_id).one_or_none()
    if mesin is None:
        raise fastapi.HTTPException(404, f"No Machine with id {mesin_id} found.")
    return mesin

@app.get("/operator/{operator_id}", response_model=schema.Operator)
def get_operator(operator_id: str, session=Sessioner):
    operator = session.query(models.Operator).filter(models.Operator.id == operator_id).one_or_none()
    if operator is None:
        raise fastapi.HTTPException(404, f"No Operator with id {operator_id} found.")
    return operator

@app.post("/activity")
def post_activity(activity: schema.Activity, session=Sessioner):
    if session.query(models.Mesin).filter(models.Mesin.id == activity.mesin_id).first() is None or \
        session.query(models.Tooling).filter(models.Tooling.id == activity.tooling_id).first() is None or \
        session.query(models.Operator).filter(models.Operator.id == activity.operator_id).first() is None:
        raise fastapi.HTTPException(404, "Invalid input")

    match activity.type:
        case schema.ActivityType.START:
            business_logic.start_activity(
                tooling_id=activity.tooling_id, 
                mesin_id=activity.mesin_id, 
                operator_id=activity.operator_id,
                session=session)

        case schema.ActivityType.FIRST_STOP:
            business_logic.first_stop_activity(
                tooling_id=activity.tooling_id, 
                mesin_id=activity.mesin_id, 
                operator_id=activity.operator_id,
                output=activity.output,
                downtime_category=activity.category_downtime,
                session=session
            )

        case schema.ActivityType.CONTINUE_STOP:
            business_logic.continue_stop_activity(
                tooling_id=activity.tooling_id, 
                mesin_id=activity.mesin_id, 
                operator_id=activity.operator_id,
                downtime_category=activity.category_downtime,
                session=session
            )
        case _:
            raise fastapi.HTTPException(404, "Invalid activity type")

    return {"isSuccess": True}

@app.get("/mesin/status/{mesin_id}")
def get_mesin_status(mesin_id: str, session=Sessioner):
    status = False
    mesin_status = session.query(models.MesinStatus).filter(models.MesinStatus.id == mesin_id).one_or_none()
    if mesin_status is not None:
        status = mesin_status.status
    return {"status": status}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
