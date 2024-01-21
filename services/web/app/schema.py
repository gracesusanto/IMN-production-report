from enum import Enum
from typing import Union
from datetime import date

from pydantic import BaseModel, constr
from pydantic_sqlalchemy import sqlalchemy_to_pydantic

import app.model.models as models

Mesin = sqlalchemy_to_pydantic(models.Mesin, exclude=["time_created", "time_updated"])

Tooling = sqlalchemy_to_pydantic(
    models.Tooling, exclude=["time_created", "time_updated"]
)

Operator = sqlalchemy_to_pydantic(
    models.Operator, exclude=["time_created", "time_updated"]
)

ALPHABET_SPACE_PERIOD = "^[A-Za-z.\s]+$"
ALPHANUMERIC_HYPHENS = "^[A-Za-z0-9\-]+$"
DIGIT = "^[0-9]+$"
DIGIT_SLASH_DIGIT = "^\d+/\d+$"


class OperatorCreate(BaseModel):
    nik: constr(regex=ALPHANUMERIC_HYPHENS)  # Alphanumeric characters and hyphens
    name: constr(regex=ALPHABET_SPACE_PERIOD)  # Alphabetic characters and periods


class MesinCreate(BaseModel):
    name: constr(regex=ALPHANUMERIC_HYPHENS)  # Alphabetic characters and hyphens
    tonase: constr(regex=DIGIT)


class ToolingCreate(BaseModel):
    customer: constr(regex=ALPHABET_SPACE_PERIOD)
    part_no: constr(regex=ALPHANUMERIC_HYPHENS)
    child_part_name: str
    common_tooling_name: str
    std_jam: constr(regex=DIGIT)
    part_name: str
    kode_tooling: str
    proses: constr(regex=DIGIT_SLASH_DIGIT)

    class Config:
        orm_mode = True


class ActivityType(str, Enum):
    START = "start"
    FIRST_STOP = "first_stop"
    CONTINUE_STOP = "continue_stop"


class FormatType(str, Enum):
    LIMAX = "limax"
    IMN = "imn"
    LIMAX_DASHBOARD = "limax_dashboard"
    IMN_DASHBOARD = "imn_dashboard"


class Activity(BaseModel):
    type: ActivityType
    tooling_id: str
    mesin_id: str
    operator_id: str
    category_downtime: Union[str, None]
    output: Union[int, None] = None
    reject: Union[int, None] = None
    rework: Union[int, None] = None
    coil_no: Union[str, None] = None
    lot_no: Union[str, None] = None
    pack_no: Union[str, None] = None


class ReportRequest(BaseModel):
    format: FormatType
    date_from: Union[date, None] = None
    shift_from: Union[int, None] = 1
    date_to: Union[date, None] = None
    shift_to: Union[int, None] = 3


class CheckOperatorStatus(BaseModel):
    tooling_id: str
    mesin_id: str
    operator_id: str
