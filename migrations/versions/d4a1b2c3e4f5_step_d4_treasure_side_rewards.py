"""step_d4_treasure_side_rewards

Add treasure_active_shield_chance and treasure_second_chance_chance to
classic_round_config (side-reward probabilities for weighted single-roll).
Add has_treasure_second_chance to player_classic_state (Treasure-granted
Second Chance flag).

Revision ID: d4a1b2c3e4f5
Revises: d1a2b3c4e5f6
Create Date: 2026-03-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4a1b2c3e4f5'
down_revision = 'd1a2b3c4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'treasure_active_shield_chance',
                sa.Float(),
                nullable=False,
                server_default='0.0',
            )
        )
        batch_op.add_column(
            sa.Column(
                'treasure_second_chance_chance',
                sa.Float(),
                nullable=False,
                server_default='0.0',
            )
        )

    with op.batch_alter_table('player_classic_state', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'has_treasure_second_chance',
                sa.Boolean(),
                nullable=False,
                server_default='0',
            )
        )


def downgrade():
    with op.batch_alter_table('player_classic_state', schema=None) as batch_op:
        batch_op.drop_column('has_treasure_second_chance')

    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.drop_column('treasure_second_chance_chance')
        batch_op.drop_column('treasure_active_shield_chance')
