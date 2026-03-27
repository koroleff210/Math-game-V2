"""add_avatar_preview_fields

Revision ID: f0a1b2c3d4e5
Revises: e7f8a9b0c1d2
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa


revision = 'f0a1b2c3d4e5'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'player',
        sa.Column('selected_face_key', sa.String(length=16), nullable=False, server_default='001'),
    )
    op.add_column(
        'gear_item_definition',
        sa.Column('avatar_asset_key', sa.String(length=16), nullable=True),
    )


def downgrade():
    op.drop_column('gear_item_definition', 'avatar_asset_key')
    op.drop_column('player', 'selected_face_key')
