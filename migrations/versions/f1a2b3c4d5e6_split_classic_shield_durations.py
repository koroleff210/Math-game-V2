"""split classic shield durations

Revision ID: f1a2b3c4d5e6
Revises: c1d2e3f4a5b6
Create Date: 2026-03-25 18:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active_shield_duration', sa.Integer(), nullable=False, server_default='60'))
        batch_op.add_column(sa.Column('reactive_shield_duration', sa.Integer(), nullable=False, server_default='60'))

    op.execute(
        """
        UPDATE classic_round_config
        SET active_shield_duration = shield_duration,
            reactive_shield_duration = shield_duration
        """
    )

    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.alter_column('active_shield_duration', server_default=None)
        batch_op.alter_column('reactive_shield_duration', server_default=None)


def downgrade():
    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.drop_column('reactive_shield_duration')
        batch_op.drop_column('active_shield_duration')
