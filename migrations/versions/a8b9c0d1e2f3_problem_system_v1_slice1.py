"""Problem System V1 Slice 1 foundation

Revision ID: a8b9c0d1e2f3
Revises: f0a1b2c3d4e5
Create Date: 2026-03-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8b9c0d1e2f3'
down_revision = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    problem_columns = {column['name'] for column in inspector.get_columns('problem')}

    if 'answer_type' not in problem_columns:
        op.add_column(
            'problem',
            sa.Column('answer_type', sa.String(length=32), nullable=False, server_default='text_input'),
        )

    if 'problem_block' not in table_names:
        op.create_table(
            'problem_block',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('problem_id', sa.Integer(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('block_type', sa.String(length=32), nullable=False),
            sa.Column('text_content', sa.Text(), nullable=True),
            sa.Column('image_path', sa.String(length=512), nullable=True),
            sa.Column('image_width_pct', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    problem_block_indexes = {index['name'] for index in inspector.get_indexes('problem_block')} if 'problem_block' in set(sa.inspect(bind).get_table_names()) else set()
    if op.f('ix_problem_block_problem_id') not in problem_block_indexes:
        op.create_index(op.f('ix_problem_block_problem_id'), 'problem_block', ['problem_id'], unique=False)

    if 'problem_accepted_answer' not in table_names:
        op.create_table(
            'problem_accepted_answer',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('problem_id', sa.Integer(), nullable=False),
            sa.Column('position', sa.Integer(), nullable=False),
            sa.Column('answer_text', sa.String(length=512), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['problem_id'], ['problem.id']),
            sa.PrimaryKeyConstraint('id'),
        )
    accepted_answer_indexes = {index['name'] for index in inspector.get_indexes('problem_accepted_answer')} if 'problem_accepted_answer' in set(sa.inspect(bind).get_table_names()) else set()
    if op.f('ix_problem_accepted_answer_problem_id') not in accepted_answer_indexes:
        op.create_index(
            op.f('ix_problem_accepted_answer_problem_id'),
            'problem_accepted_answer',
            ['problem_id'],
            unique=False,
        )

def downgrade():
    op.drop_index(op.f('ix_problem_accepted_answer_problem_id'), table_name='problem_accepted_answer')
    op.drop_table('problem_accepted_answer')

    op.drop_index(op.f('ix_problem_block_problem_id'), table_name='problem_block')
    op.drop_table('problem_block')

    op.drop_column('problem', 'answer_type')
