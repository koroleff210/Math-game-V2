"""boss rush phase 1 foundation

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('problem_set', schema=None) as batch_op:
        batch_op.add_column(sa.Column('usable_in_classic', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('usable_in_boss_rush', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('usable_as_recovery', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('usable_in_team', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        'boss_rush_round_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('boss_type', sa.String(length=64), nullable=False),
        sa.Column('boss_name', sa.String(length=128), nullable=True),
        sa.Column('boss_image_path', sa.String(length=255), nullable=True),
        sa.Column('boss_max_hp', sa.Integer(), nullable=False),
        sa.Column('player_max_hp', sa.Integer(), nullable=False),
        sa.Column('attack_problem_set_id', sa.Integer(), nullable=False),
        sa.Column('recovery_problem_set_id', sa.Integer(), nullable=False),
        sa.Column('first_place_diamonds', sa.Integer(), nullable=False),
        sa.Column('second_place_diamonds', sa.Integer(), nullable=False),
        sa.Column('third_place_diamonds', sa.Integer(), nullable=False),
        sa.Column('other_participant_diamonds', sa.Integer(), nullable=False),
        sa.Column('highest_combo_diamonds', sa.Integer(), nullable=False),
        sa.Column('combo_bonus_threshold', sa.Integer(), nullable=False),
        sa.Column('combo_bonus_damage', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['attack_problem_set_id'], ['problem_set.id']),
        sa.ForeignKeyConstraint(['recovery_problem_set_id'], ['problem_set.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id'),
    )
    op.create_index(op.f('ix_boss_rush_round_config_round_id'), 'boss_rush_round_config', ['round_id'], unique=False)

    op.create_table(
        'boss_rush_battle_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('current_boss_hp', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('is_defeated', sa.Boolean(), nullable=False),
        sa.Column('defeated_at', sa.DateTime(), nullable=True),
        sa.Column('rewards_finalized_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id'),
    )
    op.create_index(op.f('ix_boss_rush_battle_state_round_id'), 'boss_rush_battle_state', ['round_id'], unique=False)

    op.create_table(
        'boss_rush_player_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('hp', sa.Integer(), nullable=False),
        sa.Column('damage_dealt', sa.Integer(), nullable=False),
        sa.Column('current_combo', sa.Integer(), nullable=False),
        sa.Column('max_combo', sa.Integer(), nullable=False),
        sa.Column('correct_count', sa.Integer(), nullable=False),
        sa.Column('incorrect_count', sa.Integer(), nullable=False),
        sa.Column('recovery_correct_count', sa.Integer(), nullable=False),
        sa.Column('recovery_incorrect_count', sa.Integer(), nullable=False),
        sa.Column('is_observer', sa.Boolean(), nullable=False),
        sa.Column('is_completed', sa.Boolean(), nullable=False),
        sa.Column('current_problem_id', sa.Integer(), nullable=True),
        sa.Column('current_problem_kind', sa.String(length=16), nullable=True),
        sa.Column('last_contribution_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['current_problem_id'], ['problem.id']),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('round_id', 'player_id', name='uq_boss_rush_player_round_player'),
    )
    op.create_index(op.f('ix_boss_rush_player_state_player_id'), 'boss_rush_player_state', ['player_id'], unique=False)
    op.create_index(op.f('ix_boss_rush_player_state_round_id'), 'boss_rush_player_state', ['round_id'], unique=False)

    op.create_table(
        'boss_rush_problem_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('round_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('attempt_type', sa.String(length=16), nullable=False),
        sa.Column('submitted_answer', sa.String(length=512), nullable=True),
        sa.Column('selected_option_id', sa.Integer(), nullable=True),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.Column('damage_dealt', sa.Integer(), nullable=False),
        sa.Column('combo_before', sa.Integer(), nullable=False),
        sa.Column('combo_after', sa.Integer(), nullable=False),
        sa.Column('hp_before', sa.Integer(), nullable=False),
        sa.Column('hp_after', sa.Integer(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
        sa.ForeignKeyConstraint(['round_id'], ['game_round.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_boss_rush_problem_attempt_player_id'), 'boss_rush_problem_attempt', ['player_id'], unique=False)
    op.create_index(op.f('ix_boss_rush_problem_attempt_problem_id'), 'boss_rush_problem_attempt', ['problem_id'], unique=False)
    op.create_index(op.f('ix_boss_rush_problem_attempt_round_id'), 'boss_rush_problem_attempt', ['round_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_boss_rush_problem_attempt_round_id'), table_name='boss_rush_problem_attempt')
    op.drop_index(op.f('ix_boss_rush_problem_attempt_problem_id'), table_name='boss_rush_problem_attempt')
    op.drop_index(op.f('ix_boss_rush_problem_attempt_player_id'), table_name='boss_rush_problem_attempt')
    op.drop_table('boss_rush_problem_attempt')

    op.drop_index(op.f('ix_boss_rush_player_state_round_id'), table_name='boss_rush_player_state')
    op.drop_index(op.f('ix_boss_rush_player_state_player_id'), table_name='boss_rush_player_state')
    op.drop_table('boss_rush_player_state')

    op.drop_index(op.f('ix_boss_rush_battle_state_round_id'), table_name='boss_rush_battle_state')
    op.drop_table('boss_rush_battle_state')

    op.drop_index(op.f('ix_boss_rush_round_config_round_id'), table_name='boss_rush_round_config')
    op.drop_table('boss_rush_round_config')

    with op.batch_alter_table('problem_set', schema=None) as batch_op:
        batch_op.drop_column('usable_in_team')
        batch_op.drop_column('usable_as_recovery')
        batch_op.drop_column('usable_in_boss_rush')
        batch_op.drop_column('usable_in_classic')
