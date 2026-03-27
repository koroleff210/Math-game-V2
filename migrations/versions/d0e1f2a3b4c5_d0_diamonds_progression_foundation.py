"""d0_diamonds_progression_foundation

Revision ID: d0e1f2a3b4c5
Revises: b2c3d4e5f6a7
Create Date: 2026-03-14 00:00:00.000000

Phase D0 — add persistent meta-progression tables for the Diamonds/Upgrades system.

New tables:
  player_progression   — one row per player; holds persistent diamond balance
  diamond_transaction  — immutable ledger of every balance change
  player_upgrade       — one row per (player, upgrade_type); holds upgrade level
  round_player_modifiers — frozen effective values per player per round

No existing tables or columns are modified.
No existing data is changed.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0e1f2a3b4c5'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    # ── player_progression ────────────────────────────────────────────────────
    op.create_table(
        'player_progression',
        sa.Column('id',               sa.Integer(),  nullable=False),
        sa.Column('player_id',        sa.Integer(),  nullable=False),
        sa.Column('diamonds_balance', sa.Integer(),  nullable=False, server_default='0'),
        sa.Column('created_at',       sa.DateTime(), nullable=False),
        sa.Column('updated_at',       sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id', name='uq_player_progression_player'),
    )

    # ── diamond_transaction ───────────────────────────────────────────────────
    op.create_table(
        'diamond_transaction',
        sa.Column('id',              sa.Integer(),     nullable=False),
        sa.Column('player_id',       sa.Integer(),     nullable=False),
        sa.Column('amount_delta',    sa.Integer(),     nullable=False),
        sa.Column('balance_after',   sa.Integer(),     nullable=False),
        sa.Column('reason',          sa.String(64),    nullable=False),
        sa.Column('admin_player_id', sa.Integer(),     nullable=True),
        sa.Column('session_id',      sa.Integer(),     nullable=True),
        sa.Column('created_at',      sa.DateTime(),    nullable=False),
        sa.ForeignKeyConstraint(['admin_player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['player_id'],       ['player.id']),
        sa.ForeignKeyConstraint(['session_id'],      ['game_session.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── player_upgrade ────────────────────────────────────────────────────────
    op.create_table(
        'player_upgrade',
        sa.Column('id',           sa.Integer(),  nullable=False),
        sa.Column('player_id',    sa.Integer(),  nullable=False),
        sa.Column('upgrade_type', sa.String(64), nullable=False),
        sa.Column('level',        sa.Integer(),  nullable=False, server_default='0'),
        sa.Column('created_at',   sa.DateTime(), nullable=False),
        sa.Column('updated_at',   sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id', 'upgrade_type', name='uq_player_upgrade_type'),
    )

    # ── round_player_modifiers ────────────────────────────────────────────────
    op.create_table(
        'round_player_modifiers',
        sa.Column('id',                       sa.Integer(), nullable=False),
        sa.Column('round_id',                 sa.Integer(), nullable=False),
        sa.Column('player_id',                sa.Integer(), nullable=False),
        sa.Column('effective_steal_token_cap', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('effective_mine_bonus',      sa.Integer(), nullable=False, server_default='0'),
        sa.Column('effective_treasure_bonus',  sa.Integer(), nullable=False, server_default='0'),
        sa.Column('effective_shield_bonus_pct', sa.Float(),  nullable=False, server_default='0.0'),
        sa.Column('created_at',               sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['round_id'],  ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id', 'player_id', name='uq_round_player_modifiers'),
    )


def downgrade():
    op.drop_table('round_player_modifiers')
    op.drop_table('player_upgrade')
    op.drop_table('diamond_transaction')
    op.drop_table('player_progression')
