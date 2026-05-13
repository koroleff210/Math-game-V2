"""boss rush ability freeze flag

Revision ID: fab1c2d3e4f5
Revises: f9b0c1d2e3f4
Create Date: 2026-05-08 15:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fab1c2d3e4f5'
down_revision = 'f9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('boss_rush_battle_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ability_frozen', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('boss_rush_battle_state', schema=None) as batch_op:
        batch_op.drop_column('ability_frozen')

