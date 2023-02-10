from enum import Enum
from typing import Optional
from datetime import date
from fastapi import HTTPException

from pydantic import BaseModel, validator
from pydantic_sqlalchemy import sqlalchemy_to_pydantic

import app.model.models as models

from typing import TypeVar, Optional

T = TypeVar('T')

Mesin = sqlalchemy_to_pydantic(models.Mesin, exclude=['id', 'time_created', 'time_updated'])

Tooling = sqlalchemy_to_pydantic(models.Tooling, exclude=['id', 'time_created', 'time_updated'])

Operator = sqlalchemy_to_pydantic(models.Operator, exclude=['id', 'time_created', 'time_updated'])

Start = sqlalchemy_to_pydantic(models.Start)

class ActivityType(str, Enum):
    START = "start"
    FIRST_STOP = "first_stop"
    CONTINUE_STOP = "continue_stop"


class Detail(BaseModel):
    tooling_id: str
    mesin_id: str
    operator_id: str

    @validator("tooling_id")
    def tooling_validation(cls, v):
        if v and not v.startswith('TL-'):
            raise HTTPException(status_code=400, detail="Invalid Tooling ID")
        return v

    @validator("mesin_id")
    def mesin_validation(cls, v):
        if v and not v.startswith('MC-'):
            raise HTTPException(status_code=400, detail="Invalid Mesin ID")
        return v

    @validator("operator_id")
    def operator_validation(cls, v):
        if v and not v.startswith('OP-'):
            raise HTTPException(status_code=400, detail="Invalid Operator ID")
        return v

class Activity(Detail):
    type: ActivityType
    category_downtime: Optional[str]
    output: Optional[int] = None
    reject: Optional[int] = None
    rework: Optional[int] = None

class ReportRequest(BaseModel):
    date: Optional[date]
    shift: Optional[int] = 1

# class MesinStatusAll(BaseModel):
#     Mesin: str
#     Tooling: str
#     Operator: Optional[str]
#     Status: models.DisplayedStatus
#     Kategori_Downtime: str

#     class Config:
#         orm_mode = True

class DetailSchema(BaseModel):
    status: str
    message: str
    result: Optional[T] = None

class ResponseSchema(BaseModel):
    detail: str
    result: Optional[T] = None