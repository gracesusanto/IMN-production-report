"""Add proses field to report_activity_fact

Revision ID: 107a44957f8b
Revises: a801eb47e1c2
Create Date: 2026-04-20 21:40:02.007835

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '107a44957f8b'
down_revision = 'a801eb47e1c2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "report_activity_fact",
        sa.Column("proses", sa.String(), nullable=True),
    )

    op.execute(
        """
        UPDATE report_activity_fact raf
        SET proses = t.proses
        FROM tooling t
        WHERE raf.tooling_id = t.id
          AND raf.proses IS NULL
          AND t.proses IS NOT NULL
        """
    )


def downgrade():
    op.drop_column("report_activity_fact", "proses")
