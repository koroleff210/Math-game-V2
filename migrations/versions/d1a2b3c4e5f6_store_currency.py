"""store_currency

Add currency column to store_item.
Supported values: 'gold' (default) | 'gems'.
Existing rows default to 'gold' — no data-loss migration required.

Revision ID: d1a2b3c4e5f6
Revises: f3a1c7e92b84
Create Date: 2026-03-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1a2b3c4e5f6'
down_revision = 'b1a2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('store_item', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'currency',
                sa.String(length=10),
                nullable=False,
                server_default='gold',
            )
        )


def downgrade():
    with op.batch_alter_table('store_item', schema=None) as batch_op:
        batch_op.drop_column('currency')
