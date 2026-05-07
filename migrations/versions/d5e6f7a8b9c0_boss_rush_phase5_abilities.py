"""boss rush phase 5 abilities

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('boss_rush_round_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ability_enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')))
        batch_op.add_column(sa.Column('ability_interval_seconds', sa.Integer(), nullable=False, server_default='60'))
        batch_op.add_column(sa.Column('fire_burn_damage', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('fire_shield_max_stacks', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('swamp_regen_amount', sa.Integer(), nullable=False, server_default='2'))
        batch_op.add_column(sa.Column('stone_guard_combo_required', sa.Integer(), nullable=False, server_default='3'))
        batch_op.add_column(sa.Column('time_drain_damage', sa.Integer(), nullable=False, server_default='1'))

    with op.batch_alter_table('boss_rush_battle_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_ability_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('last_ability_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('ability_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('stone_guard_active', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('last_ability_summary_json', sa.JSON(), nullable=True))

    with op.batch_alter_table('boss_rush_player_state', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fire_shield_stacks', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('submitted_since_last_ability', sa.Boolean(), nullable=False, server_default=sa.text('1')))
        batch_op.add_column(sa.Column('last_ability_personal_message', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('boss_rush_player_state', schema=None) as batch_op:
        batch_op.drop_column('last_ability_personal_message')
        batch_op.drop_column('submitted_since_last_ability')
        batch_op.drop_column('fire_shield_stacks')

    with op.batch_alter_table('boss_rush_battle_state', schema=None) as batch_op:
        batch_op.drop_column('last_ability_summary_json')
        batch_op.drop_column('stone_guard_active')
        batch_op.drop_column('ability_count')
        batch_op.drop_column('last_ability_at')
        batch_op.drop_column('next_ability_at')

    with op.batch_alter_table('boss_rush_round_config', schema=None) as batch_op:
        batch_op.drop_column('time_drain_damage')
        batch_op.drop_column('stone_guard_combo_required')
        batch_op.drop_column('swamp_regen_amount')
        batch_op.drop_column('fire_shield_max_stacks')
        batch_op.drop_column('fire_burn_damage')
        batch_op.drop_column('ability_interval_seconds')
        batch_op.drop_column('ability_enabled')
