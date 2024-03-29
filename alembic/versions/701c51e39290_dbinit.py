"""dbinit

Revision ID: 701c51e39290
Revises: 
Create Date: 2023-02-03 07:51:16.855397

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "701c51e39290"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "mesin",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("tonase", sa.Integer(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mesin_id"), "mesin", ["id"], unique=False)
    op.create_table(
        "operator",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operator_id"), "operator", ["id"], unique=False)
    op.create_table(
        "tooling",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("customer", sa.String(), nullable=True),
        sa.Column("part_no", sa.String(), nullable=True),
        sa.Column("part_name", sa.String(), nullable=True),
        sa.Column("child_part_name", sa.String(), nullable=True),
        sa.Column("kode_tooling", sa.String(), nullable=True),
        sa.Column("common_tooling_name", sa.String(), nullable=True),
        sa.Column("proses", sa.String(), nullable=True),
        sa.Column("std_jam", sa.Integer(), nullable=True),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("time_updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tooling_id"), "tooling", ["id"], unique=False)
    op.create_table(
        "operator_status",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("RUNNING", "IDLE", "DOWNTIME", name="operator_status_enum"),
            nullable=False,
        ),
        sa.Column("last_tooling_id", sa.String(), nullable=False),
        sa.Column("last_mesin_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"],
            ["operator.id"],
        ),
        sa.ForeignKeyConstraint(
            ["last_mesin_id"],
            ["mesin.id"],
        ),
        sa.ForeignKeyConstraint(
            ["last_tooling_id"],
            ["tooling.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operator_status_id"), "operator_status", ["id"], unique=False)
    op.create_table(
        "start",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tooling_id", sa.String(), nullable=True),
        sa.Column("mesin_id", sa.String(), nullable=True),
        sa.Column("operator_id", sa.String(), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["mesin_id"],
            ["mesin.id"],
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operator.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tooling_id"],
            ["tooling.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "stop",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tooling_id", sa.String(), nullable=True),
        sa.Column("mesin_id", sa.String(), nullable=True),
        sa.Column("operator_id", sa.String(), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column("output", sa.Integer(), nullable=True),
        sa.Column("downtime_category", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mesin_id"],
            ["mesin.id"],
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operator.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tooling_id"],
            ["tooling.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "continued_downtime_mesin",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mesin_id", sa.String(), nullable=False),
        sa.Column("start_time_id", sa.Integer(), nullable=False),
        sa.Column("stop_time_id", sa.Integer(), nullable=False),
        sa.Column("reject", sa.Integer(), nullable=True),
        sa.Column("rework", sa.Integer(), nullable=True),
        sa.Column("downtime_category", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mesin_id"],
            ["mesin.id"],
        ),
        sa.ForeignKeyConstraint(
            ["start_time_id"],
            ["stop.id"],
        ),
        sa.ForeignKeyConstraint(
            ["stop_time_id"],
            ["stop.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "continued_downtime_operator",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operator_id", sa.String(), nullable=False),
        sa.Column("start_time_id", sa.Integer(), nullable=False),
        sa.Column("stop_time_id", sa.Integer(), nullable=False),
        sa.Column("reject", sa.Integer(), nullable=True),
        sa.Column("rework", sa.Integer(), nullable=True),
        sa.Column("downtime_category", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operator.id"],
        ),
        sa.ForeignKeyConstraint(
            ["start_time_id"],
            ["stop.id"],
        ),
        sa.ForeignKeyConstraint(
            ["stop_time_id"],
            ["stop.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "last_downtime_mesin",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mesin_id", sa.String(), nullable=False),
        sa.Column("start_time_id", sa.Integer(), nullable=False),
        sa.Column("stop_time_id", sa.Integer(), nullable=False),
        sa.Column("reject", sa.Integer(), nullable=True),
        sa.Column("rework", sa.Integer(), nullable=True),
        sa.Column("downtime_category", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mesin_id"],
            ["mesin.id"],
        ),
        sa.ForeignKeyConstraint(
            ["start_time_id"],
            ["stop.id"],
        ),
        sa.ForeignKeyConstraint(
            ["stop_time_id"],
            ["start.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "last_downtime_operator",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operator_id", sa.String(), nullable=False),
        sa.Column("start_time_id", sa.Integer(), nullable=False),
        sa.Column("stop_time_id", sa.Integer(), nullable=False),
        sa.Column("reject", sa.Integer(), nullable=True),
        sa.Column("rework", sa.Integer(), nullable=True),
        sa.Column("downtime_category", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operator.id"],
        ),
        sa.ForeignKeyConstraint(
            ["start_time_id"],
            ["stop.id"],
        ),
        sa.ForeignKeyConstraint(
            ["stop_time_id"],
            ["start.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "mesin_status",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("status", sa.Enum("RUNNING", "IDLE", "SETUP", name="status"), nullable=True),
        sa.Column("last_start_id", sa.Integer(), nullable=False),
        sa.Column("last_stop_id", sa.Integer(), nullable=False),
        sa.Column("last_tooling_id", sa.String(), nullable=False),
        sa.Column("last_operator_id", sa.String(), nullable=True),
        sa.Column("category_downtime", sa.String(), nullable=True),
        sa.Column(
            "displayed_status",
            sa.Enum("RUNNING", "IDLE", "DOWNTIME", name="displayed_status"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["mesin.id"],
        ),
        sa.ForeignKeyConstraint(
            ["last_operator_id"],
            ["operator.id"],
        ),
        sa.ForeignKeyConstraint(
            ["last_start_id"],
            ["start.id"],
        ),
        sa.ForeignKeyConstraint(
            ["last_stop_id"],
            ["stop.id"],
        ),
        sa.ForeignKeyConstraint(
            ["last_tooling_id"],
            ["tooling.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mesin_status_id"), "mesin_status", ["id"], unique=False)
    op.create_table(
        "utility_mesin",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mesin_id", sa.String(), nullable=False),
        sa.Column("start_time_id", sa.Integer(), nullable=False),
        sa.Column("stop_time_id", sa.Integer(), nullable=False),
        sa.Column("output", sa.Integer(), nullable=True),
        sa.Column("reject", sa.Integer(), nullable=True),
        sa.Column("rework", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mesin_id"],
            ["mesin.id"],
        ),
        sa.ForeignKeyConstraint(
            ["start_time_id"],
            ["start.id"],
        ),
        sa.ForeignKeyConstraint(
            ["stop_time_id"],
            ["stop.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "utility_operator",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operator_id", sa.String(), nullable=False),
        sa.Column("start_time_id", sa.Integer(), nullable=False),
        sa.Column("stop_time_id", sa.Integer(), nullable=False),
        sa.Column("output", sa.Integer(), nullable=True),
        sa.Column("reject", sa.Integer(), nullable=True),
        sa.Column("rework", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operator.id"],
        ),
        sa.ForeignKeyConstraint(
            ["start_time_id"],
            ["start.id"],
        ),
        sa.ForeignKeyConstraint(
            ["stop_time_id"],
            ["stop.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("utility_operator")
    op.drop_table("utility_mesin")
    op.drop_index(op.f("ix_mesin_status_id"), table_name="mesin_status")
    op.drop_table("mesin_status")
    op.drop_table("last_downtime_operator")
    op.drop_table("last_downtime_mesin")
    op.drop_table("continued_downtime_operator")
    op.drop_table("continued_downtime_mesin")
    op.drop_table("stop")
    op.drop_table("start")
    op.drop_index(op.f("ix_operator_status_id"), table_name="operator_status")
    op.drop_table("operator_status")
    op.drop_index(op.f("ix_tooling_id"), table_name="tooling")
    op.drop_table("tooling")
    op.drop_index(op.f("ix_operator_id"), table_name="operator")
    op.drop_table("operator")
    op.drop_index(op.f("ix_mesin_id"), table_name="mesin")
    op.drop_table("mesin")

    sa_enum_operator_status = sa.Enum(name="operator_status_enum")
    sa_enum_operator_status.drop(op.get_bind(), checkfirst=True)

    sa_enum_status = sa.Enum(name="status")
    sa_enum_status.drop(op.get_bind(), checkfirst=True)

    sa_enum_displayed_status = sa.Enum(name="displayed_status")
    sa_enum_displayed_status.drop(op.get_bind(), checkfirst=True)
    # ### end Alembic commands ###
