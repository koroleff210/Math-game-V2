"""add problem content kind

Revision ID: fbc1d2e3f4a5
Revises: fab1c2d3e4f5
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = 'fbc1d2e3f4a5'
down_revision = 'fab1c2d3e4f5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('problem', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('content_kind', sa.String(length=32), nullable=False, server_default='problem')
        )

    op.execute("UPDATE problem SET content_kind = 'problem' WHERE content_kind IS NULL")

    with op.batch_alter_table('problem', schema=None) as batch_op:
        batch_op.alter_column('content_kind', server_default=None)


def downgrade():
    with op.batch_alter_table('problem', schema=None) as batch_op:
        batch_op.drop_column('content_kind')
