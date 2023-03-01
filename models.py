import uuid
from enum import Enum

import sqlalchemy as sa
import strawberry
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

def generate_id(prefix):
    return prefix + str(uuid.uuid4())

class Mesin(Base):
    __tablename__ = "mesin"
    id = sa.Column(sa.String, default=generate_id("MC-"), primary_key=True, index=True)
    name = sa.Column(sa.String)
    tonase = sa.Column(sa.Integer)
    time_created = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())



class Tooling(Base):
    __tablename__ = "tooling"
    id = sa.Column(sa.String, default=generate_id("TL-"), primary_key=True, index=True)
    customer = sa.Column(sa.String)
    part_no = sa.Column(sa.String)
    part_name = sa.Column(sa.String)
    child_part_name = sa.Column(sa.String)
    kode_tooling = sa.Column(sa.String)
    common_tooling_name = sa.Column(sa.String)
    proses = sa.Column(sa.String)
    std_jam = sa.Column(sa.Integer)
    time_created = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())



class Operator(Base):
    __tablename__ = "operator"
    id = sa.Column(sa.String, default=generate_id("OP-"), primary_key=True, index=True)
    name = sa.Column(sa.String)
    time_created = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())


class Start(Base):
    __tablename__ = "start"
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    tooling_id = sa.Column(sa.String, sa.ForeignKey("tooling.id"))
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"))
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"))
    timestamp = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    # tooling = sa.orm.relationship("Tooling", backref="start", uselist=True)
    # mesin = sa.orm.relationship("Mesin", backref="start", uselist=True)
    # operator = sa.orm.relationship("Operator", backref="start", uselist=True)


class Stop(Base):
    __tablename__ = "stop"
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    tooling_id = sa.Column(sa.String, sa.ForeignKey("tooling.id"))
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"))
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"))
    timestamp = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    output = sa.Column(sa.Integer, nullable=True)
    downtime_category = sa.Column(sa.String)
    # tooling = sa.orm.relationship("Tooling", backref="stop", uselist=True)
    # mesin = sa.orm.relationship("Mesin", backref="stop", uselist=True)
    # operator = sa.orm.relationship("Operator", backref="stop", uselist=True)


class UtilityMesin(Base):
    __tablename__ = "utility_mesin"
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=False)
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=False)
    start_time_id = sa.Column(sa.Integer, sa.ForeignKey("start.id"), nullable=False)
    stop_time_id = sa.Column(sa.Integer, sa.ForeignKey("stop.id"), nullable=False)
    start_time = sa.orm.relationship("Start", backref="utility_mesin_start", uselist=False)
    stop_time = sa.orm.relationship("Stop", backref="utility_mesin_stop", uselist=False)
    output = sa.Column(sa.Integer)
    reject = sa.Column(sa.Integer, nullable=True)
    rework = sa.Column(sa.Integer, nullable=True)
    coil_no = sa.Column(sa.Integer, nullable=True)
    lot_no = sa.Column(sa.Integer, nullable=True)

class LastDowntimeMesin(Base):
    __tablename__ = "last_downtime_mesin"
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=False)
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=False)
    start_time_id = sa.Column(sa.Integer, sa.ForeignKey("stop.id"), nullable=False)
    stop_time_id = sa.Column(sa.Integer, sa.ForeignKey("start.id"), nullable=False)
    start_time = sa.orm.relationship("Stop", backref="last_downtime_mesin_start", uselist=False)
    stop_time = sa.orm.relationship("Start", backref="last_downtime_mesin_stop", uselist=False)
    reject = sa.Column(sa.Integer, nullable=True)
    rework = sa.Column(sa.Integer, nullable=True)
    downtime_category = sa.Column(sa.String)

class ContinuedDowntimeMesin(Base):
    __tablename__ = "continued_downtime_mesin"
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=False)
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=False)
    start_time_id = sa.Column(sa.Integer, sa.ForeignKey("stop.id"), nullable=False)
    stop_time_id = sa.Column(sa.Integer, sa.ForeignKey("stop.id"), nullable=False)
    start_time = sa.orm.relationship("Stop", foreign_keys=[start_time_id], backref="continued_downtime_mesin_start", uselist=False)
    stop_time = sa.orm.relationship("Stop", foreign_keys=[stop_time_id], backref="continued_downtime_mesin_stop", uselist=False)
    reject = sa.Column(sa.Integer, nullable=True)
    rework = sa.Column(sa.Integer, nullable=True)
    downtime_category = sa.Column(sa.String)

@strawberry.enum
class Status(Enum):
    """Status Type"""

    RUNNING = "RUNNING"
    IDLE = "IDLE"
    SETUP = "SETUP"

@strawberry.enum
class DisplayedStatus(Enum):
    """ Status to be displayed in Running Mesin All"""

    RUNNING = "RUNNING"
    IDLE = "IDLE"
    DOWNTIME = "DOWNTIME"

class MesinStatus(Base):
    __tablename__ = "mesin_status"
    id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=False, primary_key=True, index=True)
    status = sa.Column(sa.Enum(Status, name="status"), default=Status.IDLE, nullable=True)
    last_start_id = sa.Column(sa.Integer, sa.ForeignKey("start.id"), nullable=False)
    last_stop_id = sa.Column(sa.Integer, sa.ForeignKey("stop.id"), nullable=False)
    last_tooling_id = sa.Column(sa.String, sa.ForeignKey("tooling.id"), nullable=False)
    last_operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=True)
    last_start = sa.orm.relationship("Start", backref="mesin_status", uselist=False)
    last_stop = sa.orm.relationship("Stop", backref="mesin_status", uselist=False)
    last_tooling = sa.orm.relationship("Tooling", backref="curr_mesin", uselist=False)
    last_operator = sa.orm.relationship("Operator", backref="curr_mesin", uselist=False)
    category_downtime = sa.Column(sa.String, nullable=True)
    displayed_status = sa.Column(sa.Enum(DisplayedStatus, name="displayed_status"), default=DisplayedStatus.IDLE, nullable=True)

@strawberry.enum
class OperatorStatusEnum(Enum):
    """Operator Status Type"""

    RUNNING = "RUNNING"
    IDLE = "IDLE"
class OperatorStatus(Base):
    __tablename__ = "operator_status"
    id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=False, primary_key=True, index=True)
    status = sa.Column(sa.Enum(DisplayedStatus, name="operator_status_enum"), default=DisplayedStatus.IDLE, nullable=False)
    last_tooling_id = sa.Column(sa.String, sa.ForeignKey("tooling.id"), nullable=False)
    last_mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=False)
    last_tooling = sa.orm.relationship("Tooling", backref="curr_operator", uselist=False)
    last_mesin = sa.orm.relationship("Mesin", backref="curr_operator", uselist=False)