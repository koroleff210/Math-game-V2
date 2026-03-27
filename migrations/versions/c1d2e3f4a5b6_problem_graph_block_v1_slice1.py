"""Problem Graph Block V1 Slice 1

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa


revision = 'c1d2e3f4a5b6'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('problem_block', schema=None) as batch_op:
        batch_op.add_column(sa.Column('graph_config_json', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('problem_block', schema=None) as batch_op:
        batch_op.drop_column('graph_config_json')
