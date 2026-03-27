"""step_d1_steal_system

Revision ID: c4f7e8d21a30
Revises: bde9f2a62232
Create Date: 2026-03-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f7e8d21a30'
down_revision = 'bde9f2a62232'
branch_labels = None
depends_on = None


def upgrade():
    # server_default is required for NOT NULL columns added via ALTER TABLE in SQLite (BF-06).

    # ── ClassicRoundConfig: 8 new steal-system columns ───────────────────────
    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('steal_percent',               sa.Float(),   nullable=False, server_default='0.1'))
        batch_op.add_column(sa.Column('steal_min_cap',               sa.Integer(), nullable=False, server_default='10'))
        batch_op.add_column(sa.Column('steal_max_cap',               sa.Integer(), nullable=False, server_default='50'))
        batch_op.add_column(sa.Column('steal_fallback_gold',         sa.Integer(), nullable=False, server_default='5'))
        batch_op.add_column(sa.Column('steal_chest_count',           sa.Integer(), nullable=False, server_default='2'))
        batch_op.add_column(sa.Column('steal_winning_chest_count',   sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('shield_duration',             sa.Integer(), nullable=False, server_default='60'))
        batch_op.add_column(sa.Column('steal_token_treasure_chance', sa.Float(),   nullable=False, server_default='0.0'))

    # ── PlayerWallet: 2 new steal-system columns ─────────────────────────────
    # steal_tokens: existing rows default to 0 (server_default);
    #   Python model default=1 ensures new wallets start with 1 token.
    # shield_expires_at: nullable; no server_default needed.
    with op.batch_alter_table('player_wallet', schema=None) as batch_op:
        batch_op.add_column(sa.Column('steal_tokens',     sa.Integer(),  nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('shield_expires_at', sa.DateTime(), nullable=True))

    # ── StealEvent: new audit table ───────────────────────────────────────────
    op.create_table(
        'steal_event',
        sa.Column('id',             sa.Integer(),     nullable=False),
        sa.Column('session_id',     sa.Integer(),     nullable=False),
        sa.Column('round_id',       sa.Integer(),     nullable=False),
        sa.Column('actor_id',       sa.Integer(),     nullable=False),
        sa.Column('target_id',      sa.Integer(),     nullable=True),
        sa.Column('outcome',        sa.String(20),    nullable=False),
        sa.Column('gold_exchanged', sa.Integer(),     nullable=False),
        sa.Column('mini_game_pick', sa.Integer(),     nullable=True),
        sa.Column('created_at',     sa.DateTime(),    nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['game_session.id']),
        sa.ForeignKeyConstraint(['round_id'],   ['game_round.id']),
        sa.ForeignKeyConstraint(['actor_id'],   ['player.id']),
        sa.ForeignKeyConstraint(['target_id'],  ['player.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_steal_event_session_id', 'steal_event', ['session_id'], unique=False)


def downgrade():
    op.drop_index('ix_steal_event_session_id', table_name='steal_event')
    op.drop_table('steal_event')

    with op.batch_alter_table('player_wallet', schema=None) as batch_op:
        batch_op.drop_column('shield_expires_at')
        batch_op.drop_column('steal_tokens')

    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.drop_column('steal_token_treasure_chance')
        batch_op.drop_column('shield_duration')
        batch_op.drop_column('steal_winning_chest_count')
        batch_op.drop_column('steal_chest_count')
        batch_op.drop_column('steal_fallback_gold')
        batch_op.drop_column('steal_max_cap')
        batch_op.drop_column('steal_min_cap')
        batch_op.drop_column('steal_percent')
