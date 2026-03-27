"""step_d4b_unify_treasure_sc

Add is_system column to store_item (hidden system items).
Remove has_treasure_second_chance from player_classic_state (unified via inventory).

Revision ID: d4b1a2b3c4d5
Revises: d4a1b2c3e4f5
Create Date: 2026-03-18 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4b1a2b3c4d5'
down_revision = 'd4a1b2c3e4f5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('store_item', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0')
        )

    with op.batch_alter_table('player_classic_state', schema=None) as batch_op:
        batch_op.drop_column('has_treasure_second_chance')


def downgrade():
    with op.batch_alter_table('player_classic_state', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('has_treasure_second_chance', sa.Boolean(), nullable=False, server_default='0')
        )

    with op.batch_alter_table('store_item', schema=None) as batch_op:
        batch_op.drop_column('is_system')
