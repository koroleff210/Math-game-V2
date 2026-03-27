"""h2b_round_history_archive

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-13 10:00:00.000000

Adds archived_at (nullable DateTime) to round_history.

NULL  → active record (shown by default in H1/H2a views)
non-NULL → archived record (hidden by default; visible via ?include_archived=1)

Archive state is purely a visibility flag; it never mutates historical values.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'round_history',
        sa.Column('archived_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column('round_history', 'archived_at')
