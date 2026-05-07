"""add_character_lock_field

Revision ID: f4a5b6c7d8e9
Revises: d5e6f7a8b9c0
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = 'f4a5b6c7d8e9'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'player',
        sa.Column('character_locked_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column('player', 'character_locked_at')
