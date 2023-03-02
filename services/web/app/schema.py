from enum import Enum
from typing import Union
from datetime import date

from pydantic import BaseModel
from pydantic_sqlalchemy import sqlalchemy_to_pydantic

import app.model.models as models

Mesin = sqlalchemy_to_pydantic(models.Mesin, exclude=['id', 'time_created', 'time_updated'])

Tooling = sqlalchemy_to_pydantic(models.Tooling, exclude=['id', 'time_created', 'time_updated'])

Operator = sqlalchemy_to_pydantic(models.Operator, exclude=['id', 'time_created', 'time_updated'])

Start = sqlalchemy_to_pydantic(models.Start)

class ActivityType(str, Enum):
    START = "start"
    FIRST_STOP = "first_stop"
    CONTINUE_STOP = "continue_stop"

class Activity(BaseModel):
    type: ActivityType
    tooling_id: str
    mesin_id: str
    operator_id: str
    category_downtime: Union[str, None]
    output: Union[int, None] = None
    reject: Union[int, None] = None
    rework: Union[int, None] = None
    coil_no: Union[int, None] = None
    lot_no: Union[int, None] = None

class ReportRequest(BaseModel):
    date_from: Union[date, None] = None
    shift_from: Union[int, None] = 1
    date_to: Union[date, None] = None
    shift_to: Union[int, None] = 3

class CheckOperatorStatus(BaseModel):
    tooling_id: str
    mesin_id: str
    operator_id: str