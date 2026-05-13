"""add avatar body variant

Revision ID: f9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-05-07 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9b0c1d2e3f4'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'player',
        sa.Column('avatar_body_variant', sa.String(length=8), nullable=True, server_default='m'),
    )
    op.execute("UPDATE player SET avatar_body_variant = 'm' WHERE avatar_body_variant IS NULL")
    with op.batch_alter_table('player') as batch_op:
        batch_op.alter_column('avatar_body_variant', nullable=False, server_default='m')


def downgrade():
    op.drop_column('player', 'avatar_body_variant')
