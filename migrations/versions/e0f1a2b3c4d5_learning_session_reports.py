"""Session report publication and frozen question content."""
from alembic import op
import sqlalchemy as sa

revision = 'e0f1a2b3c4d5'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('analytics_round_problem', sa.Column('content_snapshot_json', sa.JSON(), nullable=True))
    op.create_table(
        'analytics_session_settings',
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('game_session.id'), primary_key=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('include_in_progress', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('exclusion_reason', sa.String(500), nullable=True),
        sa.Column('teacher_notes', sa.Text(), nullable=True),
        sa.Column('student_feedback', sa.Text(), nullable=True),
        sa.Column('roster_snapshot_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('analytics_session_settings')
    op.drop_column('analytics_round_problem', 'content_snapshot_json')
