"""Keep editable PNG sources and transforms alongside exported avatar layers."""
from alembic import op
import sqlalchemy as sa

revision = 'd9e0f1a2b3c4'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('uploaded_asset') as batch:
        batch.add_column(sa.Column('editor_state', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('uploaded_asset') as batch:
        batch.drop_column('editor_state')
