"""Allow sessions to require a verified screen share."""
from alembic import op
import sqlalchemy as sa

revision = '3ab70f63dc51'
down_revision = 'c93a01e6d512'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('game_session', sa.Column('proctoring_required', sa.Boolean(),
                                           nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('game_session') as table:
        table.drop_column('proctoring_required')
