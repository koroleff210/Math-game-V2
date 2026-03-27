"""add_persistent_gear_models

Revision ID: b4c5d6e7f8a9
Revises: a1b2c3d4e5f7
Create Date: 2026-03-20 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4c5d6e7f8a9'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'gear_item_definition',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('slot_type', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('mine_gold_delta', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('steal_gold_delta', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('shield_duration_delta', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_blacksmith_visible', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'player_gear_ownership',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['gear_item_definition.id']),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id', 'item_id', name='uq_player_gear_ownership'),
    )

    op.create_table(
        'player_gear_loadout',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('main_hand_item_id', sa.String(length=64), nullable=True),
        sa.Column('off_hand_item_id', sa.String(length=64), nullable=True),
        sa.Column('chest_item_id', sa.String(length=64), nullable=True),
        sa.Column('head_item_id', sa.String(length=64), nullable=True),
        sa.Column('boots_item_id', sa.String(length=64), nullable=True),
        sa.Column('pocket1_item_id', sa.String(length=64), nullable=True),
        sa.Column('pocket2_item_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['player.id']),
        sa.ForeignKeyConstraint(['main_hand_item_id'], ['gear_item_definition.id']),
        sa.ForeignKeyConstraint(['off_hand_item_id'], ['gear_item_definition.id']),
        sa.ForeignKeyConstraint(['chest_item_id'], ['gear_item_definition.id']),
        sa.ForeignKeyConstraint(['head_item_id'], ['gear_item_definition.id']),
        sa.ForeignKeyConstraint(['boots_item_id'], ['gear_item_definition.id']),
        sa.ForeignKeyConstraint(['pocket1_item_id'], ['gear_item_definition.id']),
        sa.ForeignKeyConstraint(['pocket2_item_id'], ['gear_item_definition.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id'),
    )


def downgrade():
    op.drop_table('player_gear_loadout')
    op.drop_table('player_gear_ownership')
    op.drop_table('gear_item_definition')
