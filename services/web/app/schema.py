from enum import Enum
from typing import Union, Optional, Dict
from datetime import date
import re

from pydantic import BaseModel, constr, validator
from pydantic_sqlalchemy import sqlalchemy_to_pydantic

import app.model.models as models

Mesin = sqlalchemy_to_pydantic(models.Mesin, exclude=["time_created", "time_updated"])

Tooling = sqlalchemy_to_pydantic(
    models.Tooling, exclude=["time_created", "time_updated"]
)

Operator = sqlalchemy_to_pydantic(
    models.Operator, exclude=["time_created", "time_updated"]
)

ALPHANUMERIC_SPACE_PERIOD = "^[A-Za-z0-9.\s]+$"
ALPHANUMERIC_HYPHENS = "^[A-Za-z0-9\-]+$"
DIGIT = "^[0-9]+$"
DIGIT_SLASH_DIGIT = "^\d+/\d+$"


class OperatorCreate(BaseModel):
    nik: str
    name: str

    @validator('nik')
    def validate_nik(cls, v, field):
        if not re.match(ALPHANUMERIC_HYPHENS, v):
            raise ValueError(f"{field.name}: {v} must contain only alphanumeric characters or hyphens")
        return v

    @validator('name')
    def validate_name(cls, v, field):
        if not re.match(ALPHANUMERIC_SPACE_PERIOD, v):
            raise ValueError(f"{field.name}: {v} must contain only alphanumeric characters, spaces, or periods")
        return v

class MesinCreate(BaseModel):
    name: str
    tonase: str

    @validator('name')
    def validate_name(cls, v, field):
        if not re.match(ALPHANUMERIC_HYPHENS, v):
            raise ValueError(f"{field.name}: {v} must contain only alphanumeric characters or hyphens")
        return v

    @validator('tonase')
    def validate_tonase(cls, v, field):
        if not re.match(DIGIT, v):
            raise ValueError(f"{field.name}: {v} must contain only digits")
        return v


class ToolingCreate(BaseModel):
    customer: str
    part_no: str
    part_name: str
    child_part_name: str
    kode_tooling: str
    common_tooling_name: str
    proses: str
    std_jam: str

    @validator('part_no')
    def check_alphanumeric_hyphens(cls, value, field):
        if not re.match(ALPHANUMERIC_HYPHENS, value):
            raise ValueError(f"{field.name}: {value} must contain only alphanumeric characters or hyphens")
        return value

    @validator('std_jam')
    def check_digits(cls, value, field):
        if not re.match(DIGIT, value):
            raise ValueError(f"{field.name}: {value} must contain only digits")
        return value

    @validator('proses')
    def check_digit_slash_digit(cls, value, field):
        if not re.match(DIGIT_SLASH_DIGIT, value):
            raise ValueError(f"{field.name}: {value} must be in the format 'digit/digit'")
        return value

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


class FieldFilter(BaseModel):
    lt: Optional[float] = None
    gt: Optional[float] = None


class SortConfig(BaseModel):
    sort_by: Optional[str] = None  # The field name to sort by
    direction: Optional[str] = (
        "ascending"  # The direction to sort ('ascending' or 'descending')
    )


class Pagination(BaseModel):
    page: Optional[int] = 1
    page_size: Optional[int] = 10


class ReportRequest(BaseModel):
    format: FormatType
    date_from: Union[date, None] = None
    shift_from: Union[int, None] = 1
    date_to: Union[date, None] = None
    shift_to: Union[int, None] = 3
    pagination: Union[Pagination, None] = None
    filters: Optional[Dict[str, FieldFilter]] = None
    sort: Optional[SortConfig] = None


class CheckOperatorStatus(BaseModel):
    tooling_id: str
    mesin_id: str
    operator_id: str

class ReportBackupRequest(BaseModel):
    month: Union[int, None] = None
    year: Union[int, None] = None
