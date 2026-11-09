"""Saved gold, session economy v2 and configurable balancing.

Existing sessions remain version 1 and receive no retroactive saved gold.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a71c90e2b642'
down_revision = 'e0f1a2b3c4d5'
branch_labels = None
depends_on = None

CLASSIC = {
    'correct_answer_gold': (sa.Integer, '5'), 'combo_start': (sa.Integer, '3'),
    'combo_gold': (sa.Integer, '2'), 'treasure_pity_increment': (sa.Float, '0.10'),
    'treasure_pity_cap': (sa.Float, '0.75'), 'treasure_double_mine_chance': (sa.Float, '0.30'),
    'steal_attempt_limit': (sa.Integer, '2'), 'active_bonus_limit': (sa.Integer, '3'),
    'permanent_bonus_cap': (sa.Float, '0.10'), 'standardized_competition': (sa.Boolean, sa.false()),
}
WALLET = {'correct_answers': (sa.Integer, '0'), 'correct_streak': (sa.Integer, '0'),
          'treasure_failures': (sa.Integer, '0'), 'steal_attempts': (sa.Integer, '0'),
          'gear_bonus_remainder': (sa.Float, '0')}


def upgrade():
    op.add_column('game_session', sa.Column('economy_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('game_session', sa.Column('economy_settled_at', sa.DateTime(), nullable=True))
    op.add_column('player_progression', sa.Column('saved_gold', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('gear_item_definition', sa.Column('gold_cost', sa.Integer(), nullable=False, server_default='300'))
    # Flat bonuses remain intact; runtime caps all permanent earning advantages.
    op.execute("UPDATE gear_item_definition SET gold_cost = CASE WHEN diamond_cost >= 8 OR mine_gold_delta >= 3 OR steal_gold_delta >= 3 THEN 500 WHEN diamond_cost >= 5 THEN 400 ELSE 300 END")
    for table, fields in [('classic_round_config', CLASSIC), ('player_wallet', WALLET)]:
        for name, (kind, default) in fields.items():
            op.add_column(table, sa.Column(name, kind(), nullable=False, server_default=default))
    for name, default in [('attack_gold', '10'), ('defeat_gold', '25')]:
        op.add_column('boss_rush_round_config', sa.Column(name, sa.Integer(), nullable=False, server_default=default))
    op.create_table('gold_transaction',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('player.id'), nullable=False),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('game_session.id'), nullable=True),
        sa.Column('event_key', sa.String(160), nullable=False, unique=True),
        sa.Column('amount_delta', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table('gold_transaction')
    for name in ['attack_gold', 'defeat_gold']:
        op.drop_column('boss_rush_round_config', name)
    for table, fields in [('classic_round_config', CLASSIC), ('player_wallet', WALLET)]:
        for name in reversed(fields): op.drop_column(table, name)
    op.drop_column('gear_item_definition', 'gold_cost')
    op.drop_column('player_progression', 'saved_gold')
    op.drop_column('game_session', 'economy_settled_at')
    op.drop_column('game_session', 'economy_version')

