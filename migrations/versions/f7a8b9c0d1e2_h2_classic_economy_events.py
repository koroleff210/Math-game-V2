"""H2 Classic economy analytics events

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = 'f7a8b9c0d1e2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analytics_classic_economy_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analytics_round_id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('event_key', sa.String(length=255), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('actor_player_id', sa.Integer(), nullable=False),
        sa.Column('actor_name_snapshot', sa.String(length=80), nullable=True),
        sa.Column('target_player_id', sa.Integer(), nullable=True),
        sa.Column('target_name_snapshot', sa.String(length=80), nullable=True),
        sa.Column('linked_answer_attempt_id', sa.Integer(), nullable=True),
        sa.Column('linked_problem_id', sa.Integer(), nullable=True),
        sa.Column('action_context', sa.String(length=64), nullable=True),
        sa.Column('gold_delta_actor', sa.Integer(), nullable=False),
        sa.Column('gold_delta_target', sa.Integer(), nullable=False),
        sa.Column('gems_delta_actor', sa.Integer(), nullable=False),
        sa.Column('gems_delta_target', sa.Integer(), nullable=False),
        sa.Column('actor_gold_after', sa.Integer(), nullable=True),
        sa.Column('target_gold_after', sa.Integer(), nullable=True),
        sa.Column('item_key', sa.String(length=128), nullable=True),
        sa.Column('bonus_key', sa.String(length=128), nullable=True),
        sa.Column('problem_id', sa.Integer(), nullable=True),
        sa.Column('details_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['analytics_round_id'], ['analytics_round.id']),
        sa.ForeignKeyConstraint(['linked_answer_attempt_id'], ['analytics_answer_attempt.id']),
        sa.ForeignKeyConstraint(['linked_problem_id'], ['problem.id']),
        sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.ForeignKeyConstraint(['session_id'], ['game_session.id']),
        sa.ForeignKeyConstraint(['target_player_id'], ['player.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_key'),
    )
    op.create_index(op.f('ix_analytics_classic_economy_event_actor_player_id'), 'analytics_classic_economy_event', ['actor_player_id'], unique=False)
    op.create_index(op.f('ix_analytics_classic_economy_event_analytics_round_id'), 'analytics_classic_economy_event', ['analytics_round_id'], unique=False)
    op.create_index(op.f('ix_analytics_classic_economy_event_event_type'), 'analytics_classic_economy_event', ['event_type'], unique=False)
    op.create_index(op.f('ix_analytics_classic_economy_event_occurred_at'), 'analytics_classic_economy_event', ['occurred_at'], unique=False)
    op.create_index(op.f('ix_analytics_classic_economy_event_round_id'), 'analytics_classic_economy_event', ['round_id'], unique=False)
    op.create_index(op.f('ix_analytics_classic_economy_event_session_id'), 'analytics_classic_economy_event', ['session_id'], unique=False)
    op.create_index(op.f('ix_analytics_classic_economy_event_target_player_id'), 'analytics_classic_economy_event', ['target_player_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_analytics_classic_economy_event_target_player_id'), table_name='analytics_classic_economy_event')
    op.drop_index(op.f('ix_analytics_classic_economy_event_session_id'), table_name='analytics_classic_economy_event')
    op.drop_index(op.f('ix_analytics_classic_economy_event_round_id'), table_name='analytics_classic_economy_event')
    op.drop_index(op.f('ix_analytics_classic_economy_event_occurred_at'), table_name='analytics_classic_economy_event')
    op.drop_index(op.f('ix_analytics_classic_economy_event_event_type'), table_name='analytics_classic_economy_event')
    op.drop_index(op.f('ix_analytics_classic_economy_event_analytics_round_id'), table_name='analytics_classic_economy_event')
    op.drop_index(op.f('ix_analytics_classic_economy_event_actor_player_id'), table_name='analytics_classic_economy_event')
    op.drop_table('analytics_classic_economy_event')
