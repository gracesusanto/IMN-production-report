"""add report_activity_fact

Revision ID: a801eb47e1c2
Revises: 69d891d620dc
Create Date: 2026-03-04 22:58:15.492373

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a801eb47e1c2'
down_revision = '69d891d620dc'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_activity_fact",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),

        sa.Column("activity_mesin_id", sa.Integer(), nullable=False),

        sa.Column("start_ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stop_ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),

        sa.Column("operator_id", sa.String(), nullable=False),
        sa.Column("mesin_id", sa.String(), nullable=True),
        sa.Column("tooling_id", sa.String(), nullable=True),

        sa.Column("category_full", sa.String(), nullable=False),
        sa.Column("category_code", sa.String(length=2), nullable=False),

        sa.Column("qty", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reject", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rework", sa.Integer(), server_default="0", nullable=False),

        sa.Column("keterangan_final", sa.Text(), server_default="", nullable=False),

        sa.Column("mc_name", sa.String(), nullable=True),
        sa.Column("operator_name", sa.String(), server_default="", nullable=False),
        sa.Column("operator_nik", sa.String(), server_default="", nullable=False),

        sa.Column("kode_tooling", sa.String(), nullable=True),
        sa.Column("common_tooling_name", sa.String(), nullable=True),
        sa.Column("part_no", sa.String(), nullable=True),
        sa.Column("part_name", sa.String(), nullable=True),
        sa.Column("target_std_jam", sa.Integer(), nullable=True),

        sa.Column("tanggal_local", sa.Date(), nullable=False),
        sa.Column("shift", sa.SmallInteger(), nullable=False),

        sa.Column("plant", sa.String(length=4), nullable=True),
        sa.Column("awal_hhmm", sa.String(length=4), nullable=True),
        sa.Column("akhir_hhmm", sa.String(length=4), nullable=True),

        sa.Column("productivity_pct", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("reject_ratio_pct", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("rework_ratio_pct", sa.Numeric(18, 4), server_default="0", nullable=False),

        sa.Column("time_created", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(["activity_mesin_id"], ["activity_mesin.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["operator.id"]),
        sa.ForeignKeyConstraint(["mesin_id"], ["mesin.id"]),
        sa.ForeignKeyConstraint(["tooling_id"], ["tooling.id"]),
        sa.UniqueConstraint("activity_mesin_id", name="uq_report_activity_fact_activity_mesin_id"),
    )

    # Indexes
    op.create_index("ix_report_activity_fact_start_ts_utc", "report_activity_fact", ["start_ts_utc"])
    op.create_index("ix_report_activity_fact_stop_ts_utc", "report_activity_fact", ["stop_ts_utc"])
    op.create_index("ix_report_activity_fact_duration_sec", "report_activity_fact", ["duration_sec"])
    op.create_index("ix_report_activity_fact_operator_id", "report_activity_fact", ["operator_id"])
    op.create_index("ix_report_activity_fact_mesin_id", "report_activity_fact", ["mesin_id"])
    op.create_index("ix_report_activity_fact_tooling_id", "report_activity_fact", ["tooling_id"])
    op.create_index("ix_report_activity_fact_category_code", "report_activity_fact", ["category_code"])
    op.create_index("ix_report_activity_fact_tanggal_local", "report_activity_fact", ["tanggal_local"])
    op.create_index("ix_report_activity_fact_shift", "report_activity_fact", ["shift"])

    # Composite indexes for report queries
    op.create_index("ix_report_fact_date_shift", "report_activity_fact", ["tanggal_local", "shift"])
    op.create_index("ix_report_fact_op_date_shift", "report_activity_fact", ["operator_id", "tanggal_local", "shift"])
    op.create_index("ix_report_fact_mc_date_shift", "report_activity_fact", ["mesin_id", "tanggal_local", "shift"])


def downgrade():
    op.drop_index("ix_report_fact_mc_date_shift", table_name="report_activity_fact")
    op.drop_index("ix_report_fact_op_date_shift", table_name="report_activity_fact")
    op.drop_index("ix_report_fact_date_shift", table_name="report_activity_fact")

    op.drop_index("ix_report_activity_fact_shift", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_tanggal_local", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_category_code", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_tooling_id", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_mesin_id", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_operator_id", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_duration_sec", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_stop_ts_utc", table_name="report_activity_fact")
    op.drop_index("ix_report_activity_fact_start_ts_utc", table_name="report_activity_fact")

    op.drop_table("report_activity_fact")
