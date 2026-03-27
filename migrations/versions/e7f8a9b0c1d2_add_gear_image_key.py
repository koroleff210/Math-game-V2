"""add_gear_image_key

Revision ID: e7f8a9b0c1d2
Revises: d6a7b8c9d0e1
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa


revision = 'e7f8a9b0c1d2'
down_revision = 'd6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'gear_item_definition',
        sa.Column('image_key', sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column('gear_item_definition', 'image_key')
