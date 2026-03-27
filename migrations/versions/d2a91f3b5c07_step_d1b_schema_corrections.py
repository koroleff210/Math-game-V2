"""step_d1b_schema_corrections

Two corrections to the Step D-1 schema:
  1. Rename classic_round_config.steal_token_treasure_chance
         → classic_round_config.treasure_steal_token_chance
     Rationale: this is a treasure-system reward, not a steal mechanic.

  2. Remove player_wallet.shield_expires_at (placed there in D-1 by mistake).
     Add new table player_classic_state with shield_expires_at instead.
     Rationale: PlayerWallet is pure economy data; gameplay state belongs
     in a separate model. See AD-27.

Revision ID: d2a91f3b5c07
Revises: c4f7e8d21a30
Create Date: 2026-03-10 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd2a91f3b5c07'
down_revision = 'c4f7e8d21a30'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Rename steal_token_treasure_chance → treasure_steal_token_chance ──
    # SQLite does not support RENAME COLUMN directly in older versions; use
    # batch_alter_table which rebuilds the table safely.
    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.alter_column('steal_token_treasure_chance',
                              new_column_name='treasure_steal_token_chance')

    # ── 2. Drop shield_expires_at from player_wallet ──────────────────────────
    with op.batch_alter_table('player_wallet', schema=None) as batch_op:
        batch_op.drop_column('shield_expires_at')

    # ── 3. Create player_classic_state table ──────────────────────────────────
    op.create_table(
        'player_classic_state',
        sa.Column('id',                sa.Integer(),  nullable=False),
        sa.Column('player_id',         sa.Integer(),  nullable=False),
        sa.Column('session_id',        sa.Integer(),  nullable=False),
        sa.Column('shield_expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['player_id'],  ['player.id']),
        sa.ForeignKeyConstraint(['session_id'], ['game_session.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id', 'session_id', name='uq_pcs_player_session'),
    )


def downgrade():
    op.drop_table('player_classic_state')

    with op.batch_alter_table('player_wallet', schema=None) as batch_op:
        batch_op.add_column(sa.Column('shield_expires_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('classic_round_config', schema=None) as batch_op:
        batch_op.alter_column('treasure_steal_token_chance',
                              new_column_name='steal_token_treasure_chance')
