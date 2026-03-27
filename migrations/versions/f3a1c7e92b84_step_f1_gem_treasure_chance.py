"""step_f1_gem_treasure_chance

Add gem_treasure_chance to classic_round_config.
This column stores the probability (0.0–1.0) that a Treasure Search action
awards 1 gem. Default 0.10 (10%).

Revision ID: f3a1c7e92b84
Revises: d2a91f3b5c07
Create Date: 2026-03-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a1c7e92b84'
down_revision = 'd2a91f3b5c07'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'gem_treasure_chance',
                sa.Float(),
                nullable=False,
                server_default='0.1',
            )
        )


def downgrade():
    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.drop_column('gem_treasure_chance')
