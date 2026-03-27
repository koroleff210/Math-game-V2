"""add_gear_diamond_cost

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-03-20 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'gear_item_definition',
        sa.Column('diamond_cost', sa.Integer(), nullable=False, server_default='0'),
    )

    gear_table = table(
        'gear_item_definition',
        column('id', sa.String),
        column('diamond_cost', sa.Integer),
    )
    updates = {
        'bronze_pickaxe': 8,
        'oak_buckler': 8,
        'linen_hood': 4,
        'padded_vest': 5,
        'trail_boots': 5,
        'lucky_coin': 6,
        'time_charm': 6,
    }
    for item_id, cost in updates.items():
        op.execute(
            gear_table.update()
            .where(gear_table.c.id == item_id)
            .values(diamond_cost=cost)
        )


def downgrade():
    op.drop_column('gear_item_definition', 'diamond_cost')
