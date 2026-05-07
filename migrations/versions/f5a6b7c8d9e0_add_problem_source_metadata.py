"""add problem source metadata

Revision ID: f5a6b7c8d9e0
Revises: f4a5b6c7d8e9
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = 'f5a6b7c8d9e0'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'problem_source_metadata',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('source_system', sa.String(length=128), nullable=False),
        sa.Column('source_bank_path', sa.String(length=512), nullable=True),
        sa.Column('source_id', sa.String(length=256), nullable=True),
        sa.Column('canonical_id', sa.String(length=256), nullable=False),
        sa.Column('content_hash', sa.String(length=128), nullable=True),
        sa.Column('answer_hash', sa.String(length=128), nullable=True),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
        sa.Column('import_batch_id', sa.String(length=64), nullable=False),
        sa.Column('raw_metadata_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('problem_id'),
        sa.UniqueConstraint('source_system', 'canonical_id', name='uq_problem_source_metadata_source_canonical'),
    )
    op.create_index(
        op.f('ix_problem_source_metadata_problem_id'),
        'problem_source_metadata',
        ['problem_id'],
        unique=True,
    )
    op.create_index(
        op.f('ix_problem_source_metadata_import_batch_id'),
        'problem_source_metadata',
        ['import_batch_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_problem_source_metadata_import_batch_id'), table_name='problem_source_metadata')
    op.drop_index(op.f('ix_problem_source_metadata_problem_id'), table_name='problem_source_metadata')
    op.drop_table('problem_source_metadata')
