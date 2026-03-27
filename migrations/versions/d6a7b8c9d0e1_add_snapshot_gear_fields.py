"""add_snapshot_gear_fields

Revision ID: d6a7b8c9d0e1
Revises: c5d6e7f8a9b0
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd6a7b8c9d0e1'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'session_participant_snapshot',
        sa.Column('effective_gear_mine_gold_delta', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'session_participant_snapshot',
        sa.Column('effective_gear_steal_gold_delta', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'session_participant_snapshot',
        sa.Column('effective_gear_shield_duration_delta', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade():
    op.drop_column('session_participant_snapshot', 'effective_gear_shield_duration_delta')
    op.drop_column('session_participant_snapshot', 'effective_gear_steal_gold_delta')
    op.drop_column('session_participant_snapshot', 'effective_gear_mine_gold_delta')
