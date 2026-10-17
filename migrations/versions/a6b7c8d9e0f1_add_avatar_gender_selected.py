"""add avatar preliminary gender selection flag

Revision ID: a6b7c8d9e0f1
Revises: fbc1d2e3f4a5
Create Date: 2026-05-28 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a6b7c8d9e0f1'
down_revision = 'fbc1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'player',
        sa.Column('avatar_gender_selected', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_column('player', 'avatar_gender_selected')
