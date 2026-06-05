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
    time_created = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.sql.func.now()
    )
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
    time_created = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.sql.func.now()
    )
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())


class Operator(Base):
    __tablename__ = "operator"
    id = sa.Column(sa.String, default=generate_id("OP-"), primary_key=True, index=True)
    nik = sa.Column(sa.String)
    name = sa.Column(sa.String)
    time_created = sa.Column(
        sa.DateTime(timezone=True), server_default=sa.sql.func.now()
    )
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())

class MesinLog(Base):
    """
    MesinLog can only record time because this tracks the start of an activity

    START means mesin is entering RUNNING state
    STOP means mesin is entering non-RUNNING state

    Stores raw event logs for machine activity transitions.

    - Ensures strict chronological tracking of machine states.
    - Captures START and STOP events for reference.
    - Provides a timestamped history of machine operations.

    This table does not store production metrics. It is designed to log
    activity changes so that machine states remain sequential and non-overlapping.
    """
    __tablename__ = "mesin_log"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True, index=True)

    # mesin and tooling can be empty when operator is doing non-mesin related activity
    # Mulai Aktivitas Baru (bukan Mulai Aktivitas Baru dan Akhiri xyz)
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=True)
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=False)
    tooling_id = sa.Column(sa.String, sa.ForeignKey("tooling.id"), nullable=True)

    # Current category according to the app Main Screen
    # In main screen, we give operator list of their active activities
    # If the operator chooses to stop an existing activity, that will be curr_category
    curr_category = sa.Column(sa.String, nullable=True)

    # Next category is the category that the operator chooses to do next
    # This is chosen right before the POST /activity
    next_category = sa.Column(sa.String, nullable=True)
    timestamp = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())

    time_created = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())



class ActivityMesin(Base):
    """
    ActivityMesin records an event.

    It is created when an activity is started, with stop_id is null,
    and then completed when the activity is done
    (the mesin and operator is starting a diffeent event and therefore stopping previous event).

    Tracks machine activities by linking a start and stop event.

    - Created when a machine begins an activity (`stop_time_id = NULL` initially).
    - Completed when the machine starts another activity (previous stop is logged).
    - Stores production details, including output and downtime reasons.

    This ensures that every activity is properly tracked and prevents
    incorrect overlapping of machine operations.
    """
    __tablename__ = "activity_mesin"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    # mesin and tooling can be empty when operator is doing non-mesin related activity
    # Mulai Aktivitas Baru (bukan Mulai Aktivitas Baru dan Akhiri xyz)
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=True)
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=False)
    tooling_id = sa.Column(sa.String, sa.ForeignKey("tooling.id"), nullable=True)

    category = sa.Column(sa.String, nullable=False, default="U : Utility")

    # When an activity is created, there is only start time
    start_time_id = sa.Column(sa.Integer, sa.ForeignKey("mesin_log.id"), nullable=False, index=True)
    # stop time is null when an activity is first created
    stop_time_id = sa.Column(sa.Integer, sa.ForeignKey("mesin_log.id"), nullable=True, index=True)

    start_time = sa.orm.relationship("MesinLog", foreign_keys=[start_time_id], backref="activity_mesin_start", uselist=False)
    stop_time = sa.orm.relationship("MesinLog", foreign_keys=[stop_time_id], backref="activity_mesin_stop", uselist=False)

    output = sa.Column(sa.Integer, nullable=False, default=0)
    reject = sa.Column(sa.Integer, nullable=False, default=0)
    rework = sa.Column(sa.Integer, nullable=False, default=0)

    coil_no = sa.Column(sa.String, nullable=True)
    lot_no = sa.Column(sa.String, nullable=True)
    pack_no = sa.Column(sa.String, nullable=True)

    keterangan = sa.Column(sa.String, nullable=True)

    time_created = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())

class ReportActivityFact(Base):
    """
    Materialized / stored report facts.
    1 row == 1 finished ActivityMesin (atomic interval).

    NOTE:
    - This is NOT merged downtime. Merging stays at query/presentation layer.
    - Source of truth remains MesinLog + ActivityMesin.
    """
    __tablename__ = "report_activity_fact"

    id = sa.Column(sa.BigInteger, primary_key=True, autoincrement=True)

    # One-to-one with ActivityMesin (atomic)
    activity_mesin_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("activity_mesin.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Core timestamps (timestamptz)
    start_ts_utc = sa.Column(sa.DateTime(timezone=True), nullable=False, index=True)
    stop_ts_utc = sa.Column(sa.DateTime(timezone=True), nullable=False, index=True)
    duration_sec = sa.Column(sa.Integer, nullable=False, index=True)

    # Keys (nullable for non-machine categories like NP/BT/BR)
    operator_id = sa.Column(sa.String, sa.ForeignKey("operator.id"), nullable=False, index=True)
    mesin_id = sa.Column(sa.String, sa.ForeignKey("mesin.id"), nullable=True, index=True)
    tooling_id = sa.Column(sa.String, sa.ForeignKey("tooling.id"), nullable=True, index=True)

    category_full = sa.Column(sa.String, nullable=False)
    category_code = sa.Column(sa.String(2), nullable=False, index=True)

    # Output
    qty = sa.Column(sa.Integer, nullable=False, server_default="0")
    reject = sa.Column(sa.Integer, nullable=False, server_default="0")
    rework = sa.Column(sa.Integer, nullable=False, server_default="0")

    # Final combined text (your choice)
    keterangan_final = sa.Column(sa.Text, nullable=False, server_default="")

    # Denormalized snapshots (keep reports stable if names/targets change later)
    mc_name = sa.Column(sa.String, nullable=True)
    operator_name = sa.Column(sa.String, nullable=False, server_default="")
    operator_nik = sa.Column(sa.String, nullable=False, server_default="")

    kode_tooling = sa.Column(sa.String, nullable=True)
    common_tooling_name = sa.Column(sa.String, nullable=True)
    part_no = sa.Column(sa.String, nullable=True)
    part_name = sa.Column(sa.String, nullable=True)
    proses = sa.Column(sa.String, nullable=True)
    target_std_jam = sa.Column(sa.Integer, nullable=True)

    # Derived for fast summary/group/filter
    # tanggal_local = Jakarta date (date only)
    tanggal_local = sa.Column(sa.Date, nullable=False, index=True)
    shift = sa.Column(sa.SmallInteger, nullable=False, index=True)

    # Optional convenience (Limax / your logic)
    plant = sa.Column(sa.String(4), nullable=True)
    awal_hhmm = sa.Column(sa.String(4), nullable=True)
    akhir_hhmm = sa.Column(sa.String(4), nullable=True)

    # Stored as numbers for filtering (NOT formatted strings)
    # Use Numeric to avoid float drift
    productivity_pct = sa.Column(sa.Numeric(18, 4), nullable=False, server_default="0")
    reject_ratio_pct = sa.Column(sa.Numeric(18, 4), nullable=False, server_default="0")
    rework_ratio_pct = sa.Column(sa.Numeric(18, 4), nullable=False, server_default="0")

    time_created = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())
    time_updated = sa.Column(sa.DateTime(timezone=True), onupdate=sa.sql.func.now())

    __table_args__ = (
        # Typical report access patterns
        sa.Index("ix_report_fact_date_shift", "tanggal_local", "shift"),
        sa.Index("ix_report_fact_op_date_shift", "operator_id", "tanggal_local", "shift"),
        sa.Index("ix_report_fact_mc_date_shift", "mesin_id", "tanggal_local", "shift"),
    )
