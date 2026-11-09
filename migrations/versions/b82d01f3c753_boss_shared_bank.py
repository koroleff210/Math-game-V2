"""Boss Rush secured rewards, shared bank and configurable victory loot."""
from alembic import op
import sqlalchemy as sa

revision = 'b82d01f3c753'
down_revision = 'a71c90e2b642'
branch_labels = None
depends_on = None

CONFIG = {
    'shared_bank_enabled': (sa.Boolean, sa.false()),
    'bank_gold': (sa.Integer, '7'), 'reward_combo_start': (sa.Integer, '3'),
    'reward_combo_high': (sa.Integer, '6'), 'combo_gold_low': (sa.Integer, '1'),
    'combo_gold_high': (sa.Integer, '2'), 'bank_combo_low': (sa.Integer, '1'),
    'bank_combo_high': (sa.Integer, '2'), 'bank_equal_percent': (sa.Integer, '50'),
    'defeat_diamonds': (sa.Integer, '0'), 'defeat_gear_chance': (sa.Float, '1'),
    'loot_duplicate_gold': (sa.Integer, '150'),
}


def upgrade():
    # Existing rounds retain their reward contract. New rounds opt in via ORM.
    for name, (kind, default) in CONFIG.items():
        op.add_column('boss_rush_round_config', sa.Column(name, kind(), nullable=False, server_default=default))
    op.add_column('boss_rush_round_config', sa.Column('defeat_gear_id', sa.String(64), nullable=True))
    op.add_column('boss_rush_battle_state', sa.Column('team_bank_gold', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('boss_rush_battle_state', sa.Column('bank_expired_at', sa.DateTime(), nullable=True))
    for name in ['secured_gold', 'bank_contributed']:
        op.add_column('boss_rush_player_state', sa.Column(name, sa.Integer(), nullable=False, server_default='0'))
    for name in ['secured_gold_delta', 'bank_gold_delta']:
        op.add_column('boss_rush_problem_attempt', sa.Column(name, sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    for name in ['bank_gold_delta', 'secured_gold_delta']:op.drop_column('boss_rush_problem_attempt', name)
    for name in ['bank_contributed', 'secured_gold']:op.drop_column('boss_rush_player_state', name)
    for name in ['bank_expired_at', 'team_bank_gold']:op.drop_column('boss_rush_battle_state', name)
    op.drop_column('boss_rush_round_config', 'defeat_gear_id')
    for name in reversed(CONFIG):op.drop_column('boss_rush_round_config', name)
