"""boss rush phase 3 rewards snapshot

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('boss_rush_battle_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('final_rewards_json', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('boss_rush_battle_state', schema=None) as batch_op:
        batch_op.drop_column('final_rewards_json')
