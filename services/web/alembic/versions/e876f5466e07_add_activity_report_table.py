"""add_activity_report_table

Revision ID: e876f5466e07
Revises: 69d891d620dc
Create Date: 2026-03-03 16:04:17.634425

"""
from alembic import op
import sqlalchemy as sa

revision = "e876f5466e07"
down_revision = "69d891d620dc"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activity_report",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),

        # linkage
        sa.Column("activity_id", sa.Integer, nullable=False),
        sa.Column("start_time_id", sa.Integer, nullable=False),
        sa.Column("stop_time_id", sa.Integer, nullable=False),

        # activity info
        sa.Column("category", sa.String, nullable=False),

        # operator (denormalized)
        sa.Column("operator_id", sa.String, nullable=False),
        sa.Column("operator_name", sa.String, nullable=False),
        sa.Column("operator_nik", sa.String, nullable=False),

        # machine (nullable)
        sa.Column("mesin_id", sa.String, nullable=True),
        sa.Column("mesin_name", sa.String, nullable=True),

        # tooling (nullable)
        sa.Column("tooling_id", sa.String, nullable=True),
        sa.Column("kode_tooling", sa.String, nullable=True),
        sa.Column("common_tooling_name", sa.String, nullable=True),
        sa.Column("part_no", sa.String, nullable=True),
        sa.Column("part_name", sa.String, nullable=True),
        sa.Column("std_jam", sa.Integer, nullable=True),

        # production data (NOT NULL defaults)
        sa.Column("output", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("reject", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("rework", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("coil_no", sa.String, nullable=True),
        sa.Column("lot_no", sa.String, nullable=True),
        sa.Column("pack_no", sa.String, nullable=True),
        sa.Column("keterangan", sa.Text, nullable=True),

        # UTC timestamps
        sa.Column("start_ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stop_ts_utc", sa.DateTime(timezone=True), nullable=False),

        # precomputed Jakarta time strings (kept nullable; you can backfill later)
        sa.Column("start_date_jakarta", sa.String(10), nullable=True, comment="dd/mm/yyyy"),
        sa.Column("stop_date_jakarta", sa.String(10), nullable=True, comment="dd/mm/yyyy"),
        sa.Column("start_time_jakarta", sa.String(8), nullable=True, comment="HH:MM:SS"),
        sa.Column("stop_time_jakarta", sa.String(8), nullable=True, comment="HH:MM:SS"),
        sa.Column("start_datetime_jakarta", sa.String(19), nullable=True, comment="mm/dd/yyyy HH:MM:SS"),
        sa.Column("stop_datetime_jakarta", sa.String(19), nullable=True, comment="mm/dd/yyyy HH:MM:SS"),
        sa.Column("shift", sa.Integer, nullable=True, comment="Shift number (1,2,3)"),

        # computed metrics (store decimals; format at presentation time)
        sa.Column("duration_seconds", sa.Integer, nullable=True, comment="Duration in seconds"),
        sa.Column("productivity_percent", sa.Numeric(5, 2), nullable=True, comment="Productivity %"),
        sa.Column("reject_ratio_percent", sa.Numeric(5, 2), nullable=True, comment="Reject ratio %"),
        sa.Column("rework_ratio_percent", sa.Numeric(5, 2), nullable=True, comment="Rework ratio %"),
        sa.Column("plant", sa.String(1), nullable=True, comment="Plant from machine name"),
        sa.Column("awal_limax", sa.String(4), nullable=True, comment="HHMM"),
        sa.Column("akhir_limax", sa.String(4), nullable=True, comment="HHMM"),
        sa.Column("kode_keterangan", sa.String(2), nullable=True, comment="First 2 chars of Desc"),

        # metadata
        sa.Column("time_created", sa.DateTime(timezone=True), server_default=sa.sql.func.now()),

        # constraints
        sa.ForeignKeyConstraint(["activity_id"], ["activity_mesin.id"], name="fk_activity_report_activity_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["start_time_id"], ["mesin_log.id"], name="fk_activity_report_start_time_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stop_time_id"], ["mesin_log.id"], name="fk_activity_report_stop_time_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"], name="fk_activity_report_operator_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mesin_id"], ["mesin.id"], name="fk_activity_report_mesin_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tooling_id"], ["tooling.id"], name="fk_activity_report_tooling_id", ondelete="CASCADE"),
        sa.UniqueConstraint("activity_id", name="uq_activity_report_activity_id"),
    )

    # core indexes
    op.create_index("idx_activity_report_start_ts_utc", "activity_report", ["start_ts_utc"])
    op.create_index("idx_activity_report_stop_ts_utc", "activity_report", ["stop_ts_utc"])
    op.create_index("idx_activity_report_operator_start", "activity_report", ["operator_id", "start_ts_utc"])
    op.create_index("idx_activity_report_category", "activity_report", ["category"])

    # partial index for mesin_id
    op.execute(
        "CREATE INDEX idx_activity_report_mesin_start "
        "ON activity_report (mesin_id, start_ts_utc) "
        "WHERE mesin_id IS NOT NULL"
    )

    # indexes for computed fields (optional but OK)
    op.create_index("idx_activity_report_productivity", "activity_report", ["productivity_percent"])
    op.create_index("idx_activity_report_plant", "activity_report", ["plant"])
    op.create_index("idx_activity_report_start_date_jakarta", "activity_report", ["start_date_jakarta"])


def downgrade():
    # drop extra indexes
    op.drop_index("idx_activity_report_start_date_jakarta", table_name="activity_report")
    op.drop_index("idx_activity_report_plant", table_name="activity_report")
    op.drop_index("idx_activity_report_productivity", table_name="activity_report")

    # drop partial index
    op.execute("DROP INDEX IF EXISTS idx_activity_report_mesin_start")

    # drop core indexes
    op.drop_index("idx_activity_report_category", table_name="activity_report")
    op.drop_index("idx_activity_report_operator_start", table_name="activity_report")
    op.drop_index("idx_activity_report_stop_ts_utc", table_name="activity_report")
    op.drop_index("idx_activity_report_start_ts_utc", table_name="activity_report")

    op.drop_table("activity_report")
