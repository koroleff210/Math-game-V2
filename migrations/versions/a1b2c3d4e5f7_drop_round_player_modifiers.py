"""drop_round_player_modifiers

Revision ID: a1b2c3d4e5f7
Revises: 0a38914b8e02
Create Date: 2026-03-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = '0a38914b8e02'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('round_player_modifiers')


def downgrade():
    op.create_table(
        'round_player_modifiers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('effective_steal_token_cap', sa.Integer(), nullable=False),
        sa.Column('effective_mine_bonus', sa.Integer(), nullable=False),
        sa.Column('effective_treasure_bonus', sa.Integer(), nullable=False),
        sa.Column('effective_shield_bonus_pct', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id', 'player_id', name='uq_round_player_modifiers'),
    )
