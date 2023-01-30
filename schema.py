from enum import Enum
from typing import Union
from datetime import date

from pydantic import BaseModel, Field
from pydantic_sqlalchemy import sqlalchemy_to_pydantic

import models

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

class ReportRequest(BaseModel):
    date: Union[date, None]
    shift: Union[int, None] = 1
