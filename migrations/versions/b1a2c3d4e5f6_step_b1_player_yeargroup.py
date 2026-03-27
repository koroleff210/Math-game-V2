"""step_b1_player_yeargroup

Add yeargroup column to player table (Step B1).
Nullable string for year/grade group (e.g. "Year 7", "Grade 10").

Revision ID: b1a2c3d4e5f6
Revises: d0e1f2a3b4c5
Create Date: 2026-03-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1a2c3d4e5f6'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('yeargroup', sa.String(length=32), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('player', schema=None) as batch_op:
        batch_op.drop_column('yeargroup')
