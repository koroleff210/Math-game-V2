"""h0_round_history

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-03-12 20:00:00.000000

Adds two tables for frozen round-history snapshots:
  round_history       — one record per finished game round
  round_player_result — one record per player per finished round

History unit = round (not session).
These records are written once at round-end and never mutated.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'round_history',
        sa.Column('id',         sa.Integer(), primary_key=True),
        sa.Column('round_id',   sa.Integer(), sa.ForeignKey('game_round.id'),   unique=True, nullable=False),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('game_session.id'), nullable=False),

        sa.Column('mode_type',    sa.String(32),  nullable=False),
        sa.Column('round_number', sa.Integer(),   nullable=False),

        # Frozen context snapshots (no FK on problem_set_id / group_id for durability)
        sa.Column('session_label_snapshot',    sa.String(256), nullable=True),
        sa.Column('problem_set_id',            sa.Integer(),   nullable=True),
        sa.Column('problem_set_name_snapshot', sa.String(128), nullable=True),
        sa.Column('group_id',                  sa.Integer(),   nullable=True),
        sa.Column('group_name_snapshot',       sa.String(128), nullable=True),

        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at',   sa.DateTime(), nullable=False),

        sa.Column('player_count',     sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_answers',    sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_correct',    sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_incorrect',  sa.Integer(), nullable=False, server_default='0'),
        sa.Column('overall_accuracy', sa.Float(),   nullable=False, server_default='0.0'),
    )

    op.create_table(
        'round_player_result',
        sa.Column('id',               sa.Integer(), primary_key=True),
        sa.Column('round_history_id', sa.Integer(), sa.ForeignKey('round_history.id'), nullable=False),
        sa.Column('player_id',        sa.Integer(), sa.ForeignKey('player.id'),        nullable=False),

        sa.Column('player_name_snapshot', sa.String(64), nullable=False),

        sa.Column('final_place', sa.Integer(), nullable=False),
        sa.Column('final_gold',  sa.Integer(), nullable=False),
        sa.Column('final_gems',  sa.Integer(), nullable=False, server_default='0'),

        sa.Column('total_answers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('correct',       sa.Integer(), nullable=False, server_default='0'),
        sa.Column('incorrect',     sa.Integer(), nullable=False, server_default='0'),
        sa.Column('accuracy',      sa.Float(),   nullable=False, server_default='0.0'),

        sa.UniqueConstraint('round_history_id', 'player_id', name='uq_rpr_history_player'),
    )


def downgrade():
    op.drop_table('round_player_result')
    op.drop_table('round_history')
