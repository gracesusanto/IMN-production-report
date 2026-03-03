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


class ActivityReport(Base):
    """
    Denormalized table storing completed activities with all join data pre-computed.

    This table improves report generation performance by avoiding expensive joins
    between ActivityMesin, MesinLog, Operator, Mesin, and Tooling tables.

    Each row represents a completed activity (stop_time_id is NOT NULL).

    Decision on NON_MACHINE_CATEGORY: We INCLUDE them in this table for consistency
    and complete audit trail. Mesin_id/tooling_id will be NULL for these categories.
    """
    __tablename__ = "activity_report"

    # Primary key and unique constraint
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True, index=True)
    activity_id = sa.Column(sa.Integer, sa.ForeignKey('activity_mesin.id', ondelete='CASCADE'),
                           nullable=False, unique=True, index=True)
    start_time_id = sa.Column(sa.Integer, sa.ForeignKey('mesin_log.id', ondelete='CASCADE'),
                             nullable=False)
    stop_time_id = sa.Column(sa.Integer, sa.ForeignKey('mesin_log.id', ondelete='CASCADE'),
                            nullable=False)

    # Activity info
    category = sa.Column(sa.String, nullable=False, index=True)

    # Operator info (denormalized) - always present
    operator_id = sa.Column(sa.String, sa.ForeignKey('operator.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    operator_name = sa.Column(sa.String, nullable=False)
    operator_nik = sa.Column(sa.String, nullable=False)

    # Machine info (nullable for NON_MACHINE_CATEGORY)
    mesin_id = sa.Column(sa.String, sa.ForeignKey('mesin.id', ondelete='CASCADE'),
                        nullable=True)
    mesin_name = sa.Column(sa.String, nullable=True)

    # Tooling info (nullable)
    tooling_id = sa.Column(sa.String, sa.ForeignKey('tooling.id', ondelete='CASCADE'),
                          nullable=True)
    kode_tooling = sa.Column(sa.String, nullable=True)
    common_tooling_name = sa.Column(sa.String, nullable=True)
    part_no = sa.Column(sa.String, nullable=True)
    part_name = sa.Column(sa.String, nullable=True)
    std_jam = sa.Column(sa.Integer, nullable=True)

    # Production data - consistent with ActivityMesin defaults
    output = sa.Column(sa.Integer, nullable=False, default=0, server_default=sa.text('0'))
    reject = sa.Column(sa.Integer, nullable=False, default=0, server_default=sa.text('0'))
    rework = sa.Column(sa.Integer, nullable=False, default=0, server_default=sa.text('0'))
    coil_no = sa.Column(sa.String, nullable=True)
    lot_no = sa.Column(sa.String, nullable=True)
    pack_no = sa.Column(sa.String, nullable=True)
    keterangan = sa.Column(sa.Text, nullable=True)

    # Timestamps (indexed for fast range queries) - NOT NULL for completed activities
    start_ts_utc = sa.Column(sa.DateTime(timezone=True), nullable=False, index=True)
    stop_ts_utc = sa.Column(sa.DateTime(timezone=True), nullable=False, index=True)

    # Pre-computed Jakarta timezone columns for optimized report generation
    start_date_jakarta = sa.Column(sa.String(10), nullable=True, index=True, comment='dd/mm/yyyy')
    stop_date_jakarta = sa.Column(sa.String(10), nullable=True, comment='dd/mm/yyyy')
    start_time_jakarta = sa.Column(sa.String(8), nullable=True, comment='HH:MM:SS')
    stop_time_jakarta = sa.Column(sa.String(8), nullable=True, comment='HH:MM:SS')
    start_datetime_jakarta = sa.Column(sa.String(19), nullable=True, comment='mm/dd/yyyy HH:MM:SS')
    stop_datetime_jakarta = sa.Column(sa.String(19), nullable=True, comment='mm/dd/yyyy HH:MM:SS')
    shift = sa.Column(sa.Integer, nullable=True, comment='Pre-computed shift number (1, 2, or 3)')

    # Pre-computed derived metrics for optimized report generation
    duration_seconds = sa.Column(sa.Integer, nullable=True, comment='Duration in seconds')
    productivity_percent = sa.Column(sa.Numeric(5,2), nullable=True, index=True, comment='Productivity percentage')
    reject_ratio_percent = sa.Column(sa.Numeric(5,2), nullable=True, comment='Reject ratio percentage')
    rework_ratio_percent = sa.Column(sa.Numeric(5,2), nullable=True, comment='Rework ratio percentage')
    # NOTE: Formatting is now done at presentation time for better performance and flexibility
    plant = sa.Column(sa.String(1), nullable=True, index=True, comment='Plant identifier from machine name')
    awal_limax = sa.Column(sa.String(4), nullable=True, comment='Start time for LIMAX format (HHMM)')
    akhir_limax = sa.Column(sa.String(4), nullable=True, comment='Stop time for LIMAX format (HHMM)')
    kode_keterangan = sa.Column(sa.String(2), nullable=True, comment='Category code (first 2 chars of description)')

    # NOTE: Removed time_updated as it's not needed for denormalized report table
    time_created = sa.Column(sa.DateTime(timezone=True), server_default=sa.sql.func.now())

