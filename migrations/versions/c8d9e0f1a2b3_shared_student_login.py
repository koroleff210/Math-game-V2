"""Shared student identity and password setup; preserve existing credentials."""
from alembic import op
import sqlalchemy as sa

revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('player') as batch:
        batch.add_column(sa.Column('shared_email', sa.String(254), nullable=True))
        batch.add_column(sa.Column('shared_identity_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('credential_version', sa.Integer(), nullable=False, server_default='0'))
        batch.create_unique_constraint('uq_player_shared_email', ['shared_email'])
        batch.create_unique_constraint('uq_player_shared_identity_id', ['shared_identity_id'])


def downgrade():
    with op.batch_alter_table('player') as batch:
        batch.drop_constraint('uq_player_shared_email', type_='unique')
        batch.drop_constraint('uq_player_shared_identity_id', type_='unique')
        batch.drop_column('shared_email')
        batch.drop_column('shared_identity_id')
        batch.drop_column('credential_version')
