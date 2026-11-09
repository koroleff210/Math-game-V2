"""Allow the protected-target outcome in Classic theft history."""

from alembic import op
import sqlalchemy as sa


revision = 'c93a01e6d512'
down_revision = 'b82d01f3c753'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('steal_event') as table:
        table.alter_column('outcome', existing_type=sa.String(20),
                           type_=sa.String(32), existing_nullable=False)


def downgrade():
    with op.batch_alter_table('steal_event') as table:
        table.alter_column('outcome', existing_type=sa.String(32),
                           type_=sa.String(20), existing_nullable=False)
