"""g2a_topic_subject_fk

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-12 18:05:00.000000

Adds Topic.subject_id FK → Subject, then backfills from the legacy
Topic.subject string field using conservative normalization:
  - strip leading/trailing whitespace
  - collapse internal whitespace
  - case-insensitive deduplication (first occurrence's display name wins)
  - blank/null values remain unmapped (subject_id stays NULL)
  - no fuzzy matching; non-identical values stay separate

"""
import re
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def _normalize(value):
    """Return (key, display_name) for a raw legacy subject string, or None if blank."""
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    collapsed = re.sub(r'\s+', ' ', stripped)
    key = collapsed.lower()
    return key, collapsed


def upgrade():
    # Step 1: add subject_id column (nullable) to topic.
    with op.batch_alter_table('topic', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subject_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_topic_subject_id',
            'subject',
            ['subject_id'],
            ['id'],
        )

    # Step 2: backfill — read legacy topic.subject strings and populate subject table.
    conn = op.get_bind()

    rows = conn.execute(
        sa.text("SELECT id, subject FROM topic WHERE subject IS NOT NULL")
    ).fetchall()

    # Build ordered dedupe map: normalized_key -> display_name (first seen wins).
    subject_map = {}  # key -> display_name
    for row in rows:
        result = _normalize(row[1])
        if result is None:
            continue
        key, display = result
        if key not in subject_map:
            subject_map[key] = display

    if not subject_map:
        return  # No legacy subject data — nothing to backfill.

    # Insert Subject rows and collect their IDs.
    key_to_id = {}
    for key, display_name in subject_map.items():
        result = conn.execute(
            sa.text("SELECT id FROM subject WHERE name = :name"),
            {'name': display_name},
        ).fetchone()
        if result is None:
            conn.execute(
                sa.text("INSERT INTO subject (name, created_at) VALUES (:name, :created_at)"),
                {'name': display_name, 'created_at': datetime.now(timezone.utc)},
            )
            result = conn.execute(
                sa.text("SELECT id FROM subject WHERE name = :name"),
                {'name': display_name},
            ).fetchone()
        if result:
            key_to_id[key] = result[0]

    # Update topic.subject_id where we have a mapping.
    for row in rows:
        result = _normalize(row[1])
        if result is None:
            continue
        key, _ = result
        if key in key_to_id:
            conn.execute(
                sa.text("UPDATE topic SET subject_id = :sid WHERE id = :tid"),
                {'sid': key_to_id[key], 'tid': row[0]},
            )


def downgrade():
    with op.batch_alter_table('topic', schema=None) as batch_op:
        batch_op.drop_constraint('fk_topic_subject_id', type_='foreignkey')
        batch_op.drop_column('subject_id')
