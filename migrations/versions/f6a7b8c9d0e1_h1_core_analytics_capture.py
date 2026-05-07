"""H1 core analytics capture layer

Revision ID: f6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'analytics_round',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('mode', sa.String(length=32), nullable=False),
        sa.Column('round_number', sa.Integer(), nullable=True),
        sa.Column('session_label_snapshot', sa.String(length=255), nullable=True),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('group_name_snapshot', sa.String(length=255), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('subject_name_snapshot', sa.String(length=128), nullable=True),
        sa.Column('problem_set_id', sa.Integer(), nullable=True),
        sa.Column('problem_set_name_snapshot', sa.String(length=255), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('finalized_at', sa.DateTime(), nullable=True),
        sa.Column('round_settings_json', sa.JSON(), nullable=True),
        sa.Column('mode_settings_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['group_id'], ['player_group.id']),
        sa.ForeignKeyConstraint(['problem_set_id'], ['problem_set.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.ForeignKeyConstraint(['session_id'], ['game_session.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subject.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id'),
    )
    op.create_index(op.f('ix_analytics_round_ended_at'), 'analytics_round', ['ended_at'], unique=False)
    op.create_index(op.f('ix_analytics_round_finalized_at'), 'analytics_round', ['finalized_at'], unique=False)
    op.create_index(op.f('ix_analytics_round_group_id'), 'analytics_round', ['group_id'], unique=False)
    op.create_index(op.f('ix_analytics_round_mode'), 'analytics_round', ['mode'], unique=False)
    op.create_index(op.f('ix_analytics_round_round_id'), 'analytics_round', ['round_id'], unique=True)
    op.create_index(op.f('ix_analytics_round_session_id'), 'analytics_round', ['session_id'], unique=False)
    op.create_index(op.f('ix_analytics_round_subject_id'), 'analytics_round', ['subject_id'], unique=False)

    op.create_table(
        'analytics_round_problem',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analytics_round_id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('problem_title_snapshot', sa.String(length=256), nullable=True),
        sa.Column('answer_type_snapshot', sa.String(length=32), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('subject_name_snapshot', sa.String(length=128), nullable=True),
        sa.Column('topic_id', sa.Integer(), nullable=True),
        sa.Column('topic_name_snapshot', sa.String(length=128), nullable=True),
        sa.Column('mode_context', sa.String(length=64), nullable=False),
        sa.Column('problem_set_context', sa.JSON(), nullable=True),
        sa.Column('source_metadata_json', sa.JSON(), nullable=True),
        sa.Column('answer_key_snapshot_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['analytics_round_id'], ['analytics_round.id']),
        sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subject.id']),
        sa.ForeignKeyConstraint(['topic_id'], ['topic.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id', 'problem_id', 'mode_context', name='uq_analytics_round_problem_context'),
    )
    op.create_index(op.f('ix_analytics_round_problem_analytics_round_id'), 'analytics_round_problem', ['analytics_round_id'], unique=False)
    op.create_index(op.f('ix_analytics_round_problem_problem_id'), 'analytics_round_problem', ['problem_id'], unique=False)
    op.create_index(op.f('ix_analytics_round_problem_round_id'), 'analytics_round_problem', ['round_id'], unique=False)

    op.create_table(
        'analytics_player_round',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analytics_round_id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('player_name_snapshot', sa.String(length=80), nullable=True),
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('group_name_snapshot', sa.String(length=255), nullable=True),
        sa.Column('joined_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('finalized_at', sa.DateTime(), nullable=True),
        sa.Column('problems_seen', sa.Integer(), nullable=False),
        sa.Column('problems_attempted', sa.Integer(), nullable=False),
        sa.Column('problems_solved', sa.Integer(), nullable=False),
        sa.Column('correct_attempts', sa.Integer(), nullable=False),
        sa.Column('incorrect_attempts', sa.Integer(), nullable=False),
        sa.Column('first_try_correct_count', sa.Integer(), nullable=False),
        sa.Column('accuracy', sa.Float(), nullable=True),
        sa.Column('gold_start', sa.Integer(), nullable=True),
        sa.Column('gold_end', sa.Integer(), nullable=True),
        sa.Column('gems_start', sa.Integer(), nullable=True),
        sa.Column('gems_end', sa.Integer(), nullable=True),
        sa.Column('gold_net', sa.Integer(), nullable=True),
        sa.Column('gems_net', sa.Integer(), nullable=True),
        sa.Column('damage_dealt', sa.Integer(), nullable=False),
        sa.Column('max_combo', sa.Integer(), nullable=False),
        sa.Column('final_combo', sa.Integer(), nullable=False),
        sa.Column('hp_final', sa.Integer(), nullable=True),
        sa.Column('attack_correct', sa.Integer(), nullable=False),
        sa.Column('attack_incorrect', sa.Integer(), nullable=False),
        sa.Column('recovery_correct', sa.Integer(), nullable=False),
        sa.Column('recovery_incorrect', sa.Integer(), nullable=False),
        sa.Column('boss_rank', sa.Integer(), nullable=True),
        sa.Column('diamonds_awarded', sa.Integer(), nullable=False),
        sa.Column('summary_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['analytics_round_id'], ['analytics_round.id']),
        sa.ForeignKeyConstraint(['group_id'], ['player_group.id']),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id', 'player_id', name='uq_analytics_player_round_player'),
    )
    op.create_index(op.f('ix_analytics_player_round_analytics_round_id'), 'analytics_player_round', ['analytics_round_id'], unique=False)
    op.create_index(op.f('ix_analytics_player_round_player_id'), 'analytics_player_round', ['player_id'], unique=False)
    op.create_index(op.f('ix_analytics_player_round_round_id'), 'analytics_player_round', ['round_id'], unique=False)

    op.create_table(
        'analytics_player_problem',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analytics_round_id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('mode_context', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('first_attempt_correct', sa.Boolean(), nullable=True),
        sa.Column('eventual_correct', sa.Boolean(), nullable=True),
        sa.Column('problem_title_snapshot', sa.String(length=256), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('subject_name_snapshot', sa.String(length=128), nullable=True),
        sa.Column('topic_id', sa.Integer(), nullable=True),
        sa.Column('topic_name_snapshot', sa.String(length=128), nullable=True),
        sa.Column('source_metadata_json', sa.JSON(), nullable=True),
        sa.Column('extra_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['analytics_round_id'], ['analytics_round.id']),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subject.id']),
        sa.ForeignKeyConstraint(['topic_id'], ['topic.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id', 'player_id', 'problem_id', 'mode_context', name='uq_analytics_player_problem_context'),
    )
    op.create_index(op.f('ix_analytics_player_problem_analytics_round_id'), 'analytics_player_problem', ['analytics_round_id'], unique=False)
    op.create_index(op.f('ix_analytics_player_problem_player_id'), 'analytics_player_problem', ['player_id'], unique=False)
    op.create_index(op.f('ix_analytics_player_problem_problem_id'), 'analytics_player_problem', ['problem_id'], unique=False)
    op.create_index(op.f('ix_analytics_player_problem_round_id'), 'analytics_player_problem', ['round_id'], unique=False)

    op.create_table(
        'analytics_answer_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analytics_player_problem_id', sa.Integer(), nullable=True),
        sa.Column('analytics_round_id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=False),
        sa.Column('submitted_answer_text', sa.Text(), nullable=True),
        sa.Column('selected_option_id', sa.Integer(), nullable=True),
        sa.Column('selected_option_label_snapshot', sa.String(length=16), nullable=True),
        sa.Column('selected_option_text_snapshot', sa.Text(), nullable=True),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.Column('mode_context', sa.String(length=64), nullable=False),
        sa.Column('action_context', sa.String(length=64), nullable=True),
        sa.Column('extra_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['analytics_player_problem_id'], ['analytics_player_problem.id']),
        sa.ForeignKeyConstraint(['analytics_round_id'], ['analytics_round.id']),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id', 'player_id', 'problem_id', 'mode_context', 'attempt_number', name='uq_analytics_answer_attempt_number'),
    )
    op.create_index(op.f('ix_analytics_answer_attempt_analytics_player_problem_id'), 'analytics_answer_attempt', ['analytics_player_problem_id'], unique=False)
    op.create_index(op.f('ix_analytics_answer_attempt_analytics_round_id'), 'analytics_answer_attempt', ['analytics_round_id'], unique=False)
    op.create_index(op.f('ix_analytics_answer_attempt_player_id'), 'analytics_answer_attempt', ['player_id'], unique=False)
    op.create_index(op.f('ix_analytics_answer_attempt_problem_id'), 'analytics_answer_attempt', ['problem_id'], unique=False)
    op.create_index(op.f('ix_analytics_answer_attempt_round_id'), 'analytics_answer_attempt', ['round_id'], unique=False)
    op.create_index(op.f('ix_analytics_answer_attempt_selected_option_id'), 'analytics_answer_attempt', ['selected_option_id'], unique=False)
    op.create_index('ix_analytics_answer_player_submitted', 'analytics_answer_attempt', ['player_id', 'submitted_at'], unique=False)
    op.create_index('ix_analytics_answer_problem_correct', 'analytics_answer_attempt', ['problem_id', 'is_correct'], unique=False)
    op.create_index('ix_analytics_answer_round_submitted', 'analytics_answer_attempt', ['round_id', 'submitted_at'], unique=False)


def downgrade():
    op.drop_index('ix_analytics_answer_round_submitted', table_name='analytics_answer_attempt')
    op.drop_index('ix_analytics_answer_problem_correct', table_name='analytics_answer_attempt')
    op.drop_index('ix_analytics_answer_player_submitted', table_name='analytics_answer_attempt')
    op.drop_index(op.f('ix_analytics_answer_attempt_selected_option_id'), table_name='analytics_answer_attempt')
    op.drop_index(op.f('ix_analytics_answer_attempt_round_id'), table_name='analytics_answer_attempt')
    op.drop_index(op.f('ix_analytics_answer_attempt_problem_id'), table_name='analytics_answer_attempt')
    op.drop_index(op.f('ix_analytics_answer_attempt_player_id'), table_name='analytics_answer_attempt')
    op.drop_index(op.f('ix_analytics_answer_attempt_analytics_round_id'), table_name='analytics_answer_attempt')
    op.drop_index(op.f('ix_analytics_answer_attempt_analytics_player_problem_id'), table_name='analytics_answer_attempt')
    op.drop_table('analytics_answer_attempt')
    op.drop_index(op.f('ix_analytics_player_problem_round_id'), table_name='analytics_player_problem')
    op.drop_index(op.f('ix_analytics_player_problem_problem_id'), table_name='analytics_player_problem')
    op.drop_index(op.f('ix_analytics_player_problem_player_id'), table_name='analytics_player_problem')
    op.drop_index(op.f('ix_analytics_player_problem_analytics_round_id'), table_name='analytics_player_problem')
    op.drop_table('analytics_player_problem')
    op.drop_index(op.f('ix_analytics_player_round_round_id'), table_name='analytics_player_round')
    op.drop_index(op.f('ix_analytics_player_round_player_id'), table_name='analytics_player_round')
    op.drop_index(op.f('ix_analytics_player_round_analytics_round_id'), table_name='analytics_player_round')
    op.drop_table('analytics_player_round')
    op.drop_index(op.f('ix_analytics_round_problem_round_id'), table_name='analytics_round_problem')
    op.drop_index(op.f('ix_analytics_round_problem_problem_id'), table_name='analytics_round_problem')
    op.drop_index(op.f('ix_analytics_round_problem_analytics_round_id'), table_name='analytics_round_problem')
    op.drop_table('analytics_round_problem')
    op.drop_index(op.f('ix_analytics_round_subject_id'), table_name='analytics_round')
    op.drop_index(op.f('ix_analytics_round_session_id'), table_name='analytics_round')
    op.drop_index(op.f('ix_analytics_round_round_id'), table_name='analytics_round')
    op.drop_index(op.f('ix_analytics_round_mode'), table_name='analytics_round')
    op.drop_index(op.f('ix_analytics_round_group_id'), table_name='analytics_round')
    op.drop_index(op.f('ix_analytics_round_finalized_at'), table_name='analytics_round')
    op.drop_index(op.f('ix_analytics_round_ended_at'), table_name='analytics_round')
    op.drop_table('analytics_round')
