"""Allow multiple operators on multiple machines

Revision ID: 69d891d620dc
Revises: 6cf58c47d50f
Create Date: 2025-02-13 01:52:22.041138

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "69d891d620dc"
down_revision = "6cf58c47d50f"
branch_labels = None
depends_on = None


# ----------------------------
# Helpers (safe / idempotent)
# ----------------------------
def _table_exists(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _cols(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def _fk_exists(insp, table: str, fk_name: str) -> bool:
    return any(fk.get("name") == fk_name for fk in insp.get_foreign_keys(table))


def upgrade():
    bind = op.get_bind()
    insp = inspect(bind)

    # ------------------------------------------------------------------
    # 1) Drop obsolete tables safely
    # ------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_operator_status_id")
    op.execute("DROP TABLE IF EXISTS operator_status CASCADE")

    op.execute("DROP INDEX IF EXISTS ix_mesin_status_id")
    op.execute("DROP TABLE IF EXISTS mesin_status CASCADE")

    # ------------------------------------------------------------------
    # 2) Modify activity_mesin safely
    # ------------------------------------------------------------------
    if _table_exists(insp, "activity_mesin"):
        activity_cols = _cols(insp, "activity_mesin")

        if "tooling_id" not in activity_cols:
            op.add_column("activity_mesin", sa.Column("tooling_id", sa.String(), nullable=True))

        if "keterangan" not in activity_cols:
            op.add_column("activity_mesin", sa.Column("keterangan", sa.String(), nullable=True))

        # refresh cols after add
        activity_cols = _cols(insp, "activity_mesin")

        # loosen constraint (safe)
        if "mesin_id" in activity_cols:
            op.alter_column("activity_mesin", "mesin_id", existing_type=sa.VARCHAR(), nullable=True)

        # rename downtime_category -> category (guarded; raw SQL is most reliable)
        activity_cols = _cols(insp, "activity_mesin")
        if "downtime_category" in activity_cols and "category" not in activity_cols:
            op.execute("ALTER TABLE activity_mesin RENAME COLUMN downtime_category TO category")

        # stop_time_id nullable
        activity_cols = _cols(insp, "activity_mesin")
        if "stop_time_id" in activity_cols:
            op.alter_column("activity_mesin", "stop_time_id", existing_type=sa.INTEGER(), nullable=True)

        # FK: only create if it does not already exist
        activity_cols = _cols(insp, "activity_mesin")
        if "tooling_id" in activity_cols and _table_exists(insp, "tooling"):
            if not _fk_exists(insp, "activity_mesin", "fk_activity_mesin_tooling"):
                op.create_foreign_key(
                    "fk_activity_mesin_tooling",
                    "activity_mesin",
                    "tooling",
                    ["tooling_id"],
                    ["id"],
                )

    # ------------------------------------------------------------------
    # 3) Modify mesin_log safely
    # ------------------------------------------------------------------
    if _table_exists(insp, "mesin_log"):
        mesin_log_cols = _cols(insp, "mesin_log")

        if "curr_category" not in mesin_log_cols:
            op.add_column("mesin_log", sa.Column("curr_category", sa.String(), nullable=True))

        if "next_category" not in mesin_log_cols:
            op.add_column("mesin_log", sa.Column("next_category", sa.String(), nullable=True))

        # refresh cols after add
        mesin_log_cols = _cols(insp, "mesin_log")

        # loosen constraint (safe)
        if "mesin_id" in mesin_log_cols:
            op.alter_column("mesin_log", "mesin_id", existing_type=sa.VARCHAR(), nullable=True)

        # ------------------------------------------------------------------
        # 4) Backfill operator_id BEFORE NOT NULL
        #    Create SYSTEM operator with OP- prefix.
        # ------------------------------------------------------------------
        if _table_exists(insp, "operator"):
            op.execute("""
                INSERT INTO operator (id, nik, name)
                VALUES ('OP-SYSTEM', 'SYSTEM', 'SYSTEM')
                ON CONFLICT (id) DO NOTHING
            """)

            # Set OP-SYSTEM for NULL operator_id
            if "operator_id" in mesin_log_cols:
                op.execute("""
                    UPDATE mesin_log
                    SET operator_id = 'OP-SYSTEM'
                    WHERE operator_id IS NULL
                """)

                # Optional but safer: if some rows have operator_id not existing in operator table
                op.execute("""
                    UPDATE mesin_log ml
                    SET operator_id = 'OP-SYSTEM'
                    WHERE NOT EXISTS (SELECT 1 FROM operator o WHERE o.id = ml.operator_id)
                """)

        # enforce NOT NULL safely (only if column exists)
        mesin_log_cols = _cols(insp, "mesin_log")
        if "operator_id" in mesin_log_cols:
            op.alter_column("mesin_log", "operator_id", existing_type=sa.VARCHAR(), nullable=False)

        # tooling_id nullable (safe)
        if "tooling_id" in mesin_log_cols:
            op.alter_column("mesin_log", "tooling_id", existing_type=sa.VARCHAR(), nullable=True)

        # drop obsolete columns (guarded)
        mesin_log_cols = _cols(insp, "mesin_log")
        for col in ("category", "output", "downtime_category"):
            if col in mesin_log_cols:
                op.drop_column("mesin_log", col)


def downgrade():
    # Best-effort downgrade (destructive). Use only if you really must.

    bind = op.get_bind()
    insp = inspect(bind)

    # Restore mesin_log columns
    if _table_exists(insp, "mesin_log"):
        mesin_log_cols = _cols(insp, "mesin_log")

        if "downtime_category" not in mesin_log_cols:
            op.add_column("mesin_log", sa.Column("downtime_category", sa.VARCHAR(), nullable=True))

        if "output" not in mesin_log_cols:
            op.add_column("mesin_log", sa.Column("output", sa.INTEGER(), nullable=True))

        if "category" not in mesin_log_cols:
            # Ensure enum exists (create if missing)
            # Note: creating the enum explicitly avoids errors if it doesn't exist.
            op.execute("DO $$ BEGIN CREATE TYPE category AS ENUM ('START','STOP'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
            op.add_column("mesin_log", sa.Column("category", postgresql.ENUM("START", "STOP", name="category"), nullable=True))

        mesin_log_cols = _cols(insp, "mesin_log")
        if "next_category" in mesin_log_cols:
            op.drop_column("mesin_log", "next_category")

        if "curr_category" in mesin_log_cols:
            op.drop_column("mesin_log", "curr_category")

        # operator_id back to nullable (if you want to reverse NOT NULL)
        mesin_log_cols = _cols(insp, "mesin_log")
        if "operator_id" in mesin_log_cols:
            op.alter_column("mesin_log", "operator_id", existing_type=sa.VARCHAR(), nullable=True)

    # Restore activity_mesin column name
    if _table_exists(insp, "activity_mesin"):
        activity_cols = _cols(insp, "activity_mesin")

        if "category" in activity_cols and "downtime_category" not in activity_cols:
            op.execute("ALTER TABLE activity_mesin RENAME COLUMN category TO downtime_category")

        # Drop FK only if exists
        if _fk_exists(insp, "activity_mesin", "fk_activity_mesin_tooling"):
            op.drop_constraint("fk_activity_mesin_tooling", "activity_mesin", type_="foreignkey")

        activity_cols = _cols(insp, "activity_mesin")
        if "keterangan" in activity_cols:
            op.drop_column("activity_mesin", "keterangan")

        if "tooling_id" in activity_cols:
            op.drop_column("activity_mesin", "tooling_id")

    # ------------------------------------------------------------------
    # Recreate operator_status table
    # ------------------------------------------------------------------
    if not _table_exists(insp, "operator_status"):
        op.execute("""
        DO $$ BEGIN
            CREATE TYPE operator_status_enum AS ENUM ('RUNNING','IDLE','DOWNTIME');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

        op.create_table(
            "operator_status",
            sa.Column("id", sa.VARCHAR(), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM(
                    "RUNNING", "IDLE", "DOWNTIME",
                    name="operator_status_enum",
                ),
                nullable=False,
            ),
            sa.Column("last_tooling_id", sa.VARCHAR(), nullable=False),
            sa.Column("last_mesin_id", sa.VARCHAR(), nullable=False),
            sa.Column(
                "time_created",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column("time_updated", postgresql.TIMESTAMP(timezone=True)),
            sa.ForeignKeyConstraint(["id"], ["operator.id"]),
            sa.ForeignKeyConstraint(["last_mesin_id"], ["mesin.id"]),
            sa.ForeignKeyConstraint(["last_tooling_id"], ["tooling.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

        op.create_index("ix_operator_status_id", "operator_status", ["id"])

    # ------------------------------------------------------------------
    # Recreate mesin_status table
    # ------------------------------------------------------------------
    if not _table_exists(insp, "mesin_status"):
        op.execute("""
        DO $$ BEGIN
            CREATE TYPE status AS ENUM ('RUNNING','IDLE','SETUP');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

        op.execute("""
        DO $$ BEGIN
            CREATE TYPE displayed_status AS ENUM ('RUNNING','IDLE','DOWNTIME');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """)

        op.create_table(
            "mesin_status",
            sa.Column("id", sa.VARCHAR(), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM("RUNNING","IDLE","SETUP", name="status"),
            ),
            sa.Column("last_start_id", sa.INTEGER(), nullable=False),
            sa.Column("last_stop_id", sa.INTEGER(), nullable=False),
            sa.Column("last_tooling_id", sa.VARCHAR(), nullable=False),
            sa.Column("last_operator_id", sa.VARCHAR()),
            sa.Column("category_downtime", sa.VARCHAR()),
            sa.Column(
                "displayed_status",
                postgresql.ENUM(
                    "RUNNING","IDLE","DOWNTIME",
                    name="displayed_status",
                ),
            ),
            sa.Column(
                "time_created",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column("time_updated", postgresql.TIMESTAMP(timezone=True)),
            sa.ForeignKeyConstraint(["id"], ["mesin.id"]),
            sa.ForeignKeyConstraint(["last_operator_id"], ["operator.id"]),
            sa.ForeignKeyConstraint(["last_start_id"], ["mesin_log.id"]),
            sa.ForeignKeyConstraint(["last_stop_id"], ["mesin_log.id"]),
            sa.ForeignKeyConstraint(["last_tooling_id"], ["tooling.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

        op.create_index("ix_mesin_status_id", "mesin_status", ["id"])
