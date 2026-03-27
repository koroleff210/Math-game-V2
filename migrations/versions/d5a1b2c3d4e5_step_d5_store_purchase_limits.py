"""step_d5_store_purchase_limits

Rename store_item.quantity → session_stock (session-wide stock cap).
Add store_item.per_player_limit (per-player purchase cap, default -1 = unlimited).

Existing rows: quantity value maps to session_stock; per_player_limit defaults
to -1 (unlimited), preserving backward-compatible behavior.

Revision ID: d5a1b2c3d4e5
Revises: d4b1a2b3c4d5
Create Date: 2026-03-18 00:00:02.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5a1b2c3d4e5'
down_revision = 'd4b1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('store_item', schema=None) as batch_op:
        batch_op.alter_column('quantity', new_column_name='session_stock')
        batch_op.add_column(
            sa.Column('per_player_limit', sa.Integer(), nullable=False, server_default='-1')
        )


def downgrade():
    with op.batch_alter_table('store_item', schema=None) as batch_op:
        batch_op.drop_column('per_player_limit')
        batch_op.alter_column('session_stock', new_column_name='quantity')
