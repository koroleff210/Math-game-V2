"""boss rush phase 2 player pools

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('boss_rush_player_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attack_never_ids', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('attack_incorrect_ids', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('attack_solved_ids', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('recovery_never_ids', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('recovery_incorrect_ids', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('recovery_solved_ids', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('boss_rush_player_state', schema=None) as batch_op:
        batch_op.drop_column('recovery_solved_ids')
        batch_op.drop_column('recovery_incorrect_ids')
        batch_op.drop_column('recovery_never_ids')
        batch_op.drop_column('attack_solved_ids')
        batch_op.drop_column('attack_incorrect_ids')
        batch_op.drop_column('attack_never_ids')
