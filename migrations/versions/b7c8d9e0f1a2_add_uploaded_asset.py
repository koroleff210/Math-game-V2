"""add persistent uploaded asset metadata

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
"""

from alembic import op
import sqlalchemy as sa


revision = 'b7c8d9e0f1a2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'uploaded_asset',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('display_name', sa.String(length=128), nullable=False),
        sa.Column('asset_key', sa.String(length=64), nullable=True),
        sa.Column('gear_item_id', sa.String(length=64), sa.ForeignKey('gear_item_definition.id'), nullable=True),
        sa.Column('variant', sa.String(length=8), nullable=True),
        sa.Column('layer', sa.String(length=16), nullable=True),
        sa.Column('storage_name', sa.String(length=96), nullable=False, unique=True),
        sa.Column('media_type', sa.String(length=32), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_uploaded_asset_category', 'uploaded_asset', ['category'])
    op.create_index('ix_uploaded_asset_asset_key', 'uploaded_asset', ['asset_key'])
    op.create_index('ix_uploaded_asset_gear_item_id', 'uploaded_asset', ['gear_item_id'])
    with op.batch_alter_table('problem_choice_option') as batch_op:
        batch_op.add_column(sa.Column('image_asset_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_problem_choice_option_image_asset', 'uploaded_asset', ['image_asset_id'], ['id'])


def downgrade():
    with op.batch_alter_table('problem_choice_option') as batch_op:
        batch_op.drop_constraint('fk_problem_choice_option_image_asset', type_='foreignkey')
        batch_op.drop_column('image_asset_id')
    op.drop_index('ix_uploaded_asset_gear_item_id', table_name='uploaded_asset')
    op.drop_index('ix_uploaded_asset_asset_key', table_name='uploaded_asset')
    op.drop_index('ix_uploaded_asset_category', table_name='uploaded_asset')
    op.drop_table('uploaded_asset')
