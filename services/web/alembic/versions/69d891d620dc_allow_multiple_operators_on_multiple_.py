"""Allow multiple operators on multiple machines

Revision ID: 69d891d620dc
Revises: 6cf58c47d50f
Create Date: 2025-02-13 01:52:22.041138

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '69d891d620dc'
down_revision = '6cf58c47d50f'
branch_labels = None
depends_on = None


def upgrade():
    # Drop obsolete tables
    op.drop_index('ix_operator_status_id', table_name='operator_status')
    op.drop_table('operator_status')
    op.drop_index('ix_mesin_status_id', table_name='mesin_status')
    op.drop_table('mesin_status')

    # Modify activity_mesin
    op.add_column('activity_mesin', sa.Column('tooling_id', sa.String(), nullable=True))
    op.add_column('activity_mesin', sa.Column('keterangan', sa.String(), nullable=True))
    op.alter_column('activity_mesin', 'mesin_id', existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column('activity_mesin', 'downtime_category', new_column_name='category', existing_type=sa.String(), nullable=False)
    op.alter_column('activity_mesin', 'stop_time_id', existing_type=sa.INTEGER(), nullable=True)
    op.create_foreign_key('fk_activity_mesin_tooling', 'activity_mesin', 'tooling', ['tooling_id'], ['id'])

    # Modify mesin_log
    op.add_column('mesin_log', sa.Column('curr_category', sa.String(), nullable=True))
    op.add_column('mesin_log', sa.Column('next_category', sa.String(), nullable=True))
    op.alter_column('mesin_log', 'mesin_id', existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column('mesin_log', 'operator_id', existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column('mesin_log', 'tooling_id', existing_type=sa.VARCHAR(), nullable=True)
    op.drop_column('mesin_log', 'category')
    op.drop_column('mesin_log', 'output')
    op.drop_column('mesin_log', 'downtime_category')


def downgrade():
    # First, change any column that still uses the enum to TEXT
    # op.alter_column('mesin_log', 'category', type_=sa.String())

    # # Then drop the enum type safely
    # op.execute("DROP TYPE IF EXISTS category CASCADE")

    sa.Enum('RUNNING', 'IDLE', 'DOWNTIME', name='operator_status_enum').drop(op.get_bind())
    sa.Enum('RUNNING', 'IDLE', 'SETUP', name='status').drop(op.get_bind())
    sa.Enum('RUNNING', 'IDLE', 'DOWNTIME', name='displayed_status').drop(op.get_bind())

    # Restore dropped columns in mesin_log
    op.add_column('mesin_log', sa.Column('downtime_category', sa.VARCHAR(), nullable=True))
    op.add_column('mesin_log', sa.Column('output', sa.INTEGER(), nullable=True))
    op.add_column('mesin_log', sa.Column('category', postgresql.ENUM('START', 'STOP', name='category'), nullable=True))
    op.alter_column('mesin_log', 'tooling_id', existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column('mesin_log', 'operator_id', existing_type=sa.VARCHAR(), nullable=True)
    op.alter_column('mesin_log', 'mesin_id', existing_type=sa.VARCHAR(), nullable=True)
    op.drop_column('mesin_log', 'next_category')
    op.drop_column('mesin_log', 'curr_category')

    # Restore activity_mesin category name
    op.alter_column('activity_mesin', 'category', new_column_name='downtime_category', existing_type=sa.String(), nullable=False)

    # Drop and recreate tooling foreign key constraint
    op.drop_constraint('fk_activity_mesin_tooling', 'activity_mesin', type_='foreignkey')
    op.alter_column('activity_mesin', 'stop_time_id', existing_type=sa.INTEGER(), nullable=True)
    op.drop_column('activity_mesin', 'keterangan')
    op.drop_column('activity_mesin', 'tooling_id')

    # Restore operator_status table
    op.create_table('operator_status',
        sa.Column('id', sa.VARCHAR(), nullable=False),
        sa.Column('status', postgresql.ENUM('RUNNING', 'IDLE', 'DOWNTIME', name='operator_status_enum'), nullable=False),
        sa.Column('last_tooling_id', sa.VARCHAR(), nullable=False),
        sa.Column('last_mesin_id', sa.VARCHAR(), nullable=False),
        sa.Column('time_created', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('time_updated', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['id'], ['operator.id'], name='fk_operator_status_operator'),
        sa.ForeignKeyConstraint(['last_mesin_id'], ['mesin.id'], name='fk_operator_status_mesin'),
        sa.ForeignKeyConstraint(['last_tooling_id'], ['tooling.id'], name='fk_operator_status_tooling'),
        sa.PrimaryKeyConstraint('id', name='pk_operator_status')
    )
    op.create_index('ix_operator_status_id', 'operator_status', ['id'], unique=False)

    # Restore mesin_status table
    op.create_table('mesin_status',
        sa.Column('id', sa.VARCHAR(), nullable=False),
        sa.Column('status', postgresql.ENUM('RUNNING', 'IDLE', 'SETUP', name='status'), nullable=True),
        sa.Column('last_start_id', sa.INTEGER(), nullable=False),
        sa.Column('last_stop_id', sa.INTEGER(), nullable=False),
        sa.Column('last_tooling_id', sa.VARCHAR(), nullable=False),
        sa.Column('last_operator_id', sa.VARCHAR(), nullable=True),
        sa.Column('category_downtime', sa.VARCHAR(), nullable=True),
        sa.Column('displayed_status', postgresql.ENUM('RUNNING', 'IDLE', 'DOWNTIME', name='displayed_status'), nullable=True),
        sa.Column('time_created', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('time_updated', postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['id'], ['mesin.id'], name='fk_mesin_status_mesin'),
        sa.ForeignKeyConstraint(['last_operator_id'], ['operator.id'], name='fk_mesin_status_operator'),
        sa.ForeignKeyConstraint(['last_start_id'], ['mesin_log.id'], name='fk_mesin_status_start_log'),
        sa.ForeignKeyConstraint(['last_stop_id'], ['mesin_log.id'], name='fk_mesin_status_stop_log'),
        sa.ForeignKeyConstraint(['last_tooling_id'], ['tooling.id'], name='fk_mesin_status_tooling'),
        sa.PrimaryKeyConstraint('id', name='pk_mesin_status')
    )
    op.create_index('ix_mesin_status_id', 'mesin_status', ['id'], unique=False)
