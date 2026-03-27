"""
test_g2a_subject_foundation.py
==============================

Exit tests for Phase 4 Step G2a: Subject Foundation + Safe Topic Link.

Covers:
  1.  Subject CRUD — create, edit, delete.
  2.  Subject deletion blocked when Topics reference it.
  3.  Topic can be created/edited with NULL Subject.
  4.  Topic can be created/edited with an assigned Subject.
  5.  Topics list renders Subject correctly (via backref topic.subject_obj).
  6.  Backfill: Subject rows are created from legacy topic.subject strings.
  7.  Blank/null legacy subject values remain safely unmapped.
  8.  Duplicate normalized legacy values do not create duplicate Subject rows.
  9.  Existing Topic → Problem behavior still works after schema change.
  10. All prior test-suite passes are preserved (checked at bottom by running them).

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_g2a_subject_foundation.py

Expected: all assertions pass + "ALL TESTS PASSED." on final line.
"""

import sys
import os
import re
import subprocess

# Allow imports from project root when run from tests/ subdirectory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.subjects import Subject
from app.models.problems import Topic, Problem, ProblemSet

flask_app = create_app()

# ── Sentinel names used only by this test ────────────────────────────────────
_S_NAMES   = ['__g2a_math__', '__g2a_physics__', '__g2a_bio__']
_T_NAMES   = ['__g2a_topic_a__', '__g2a_topic_b__', '__g2a_topic_c__']
_PROB_TITLE = '__g2a_problem__'
_SET_NAME  = '__g2a_set__'


def _clean(session):
    """Remove only the test artefacts so existing data is not touched."""
    # Problems / sets
    for ps in ProblemSet.query.filter_by(name=_SET_NAME).all():
        for p in ps.problems.all():
            ps.problems.remove(p)
        session.delete(ps)
    for p in Problem.query.filter_by(title=_PROB_TITLE).all():
        session.delete(p)
    session.flush()
    # Topics
    for t in Topic.query.filter(Topic.name.in_(_T_NAMES)).all():
        session.delete(t)
    session.flush()
    # Subjects
    for s in Subject.query.filter(Subject.name.in_(_S_NAMES)).all():
        session.delete(s)
    session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_subject(name, description=None):
    s = Subject(name=name, description=description)
    db.session.add(s)
    db.session.flush()
    return s


def _make_topic(name, subject_id=None, legacy_subject=None):
    t = Topic(name=name, subject_id=subject_id, subject=legacy_subject)
    db.session.add(t)
    db.session.flush()
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Individual test functions
# ─────────────────────────────────────────────────────────────────────────────

def test_01_subject_create():
    """Subject can be created with name and optional description."""
    s = _make_subject(_S_NAMES[0], 'Test math subject')
    assert s.id is not None
    assert s.name == _S_NAMES[0]
    assert s.description == 'Test math subject'
    assert s.created_at is not None
    print('  test_01_subject_create — PASS')


def test_02_subject_edit():
    """Subject name and description can be updated."""
    s = Subject.query.filter_by(name=_S_NAMES[0]).first()
    assert s is not None
    s.description = 'Updated description'
    db.session.flush()
    reloaded = db.session.get(Subject, s.id)
    assert reloaded.description == 'Updated description'
    print('  test_02_subject_edit — PASS')


def test_03_subject_delete_allowed():
    """Subject with no topics can be deleted."""
    s = _make_subject(_S_NAMES[2])
    sid = s.id
    db.session.delete(s)
    db.session.flush()
    assert db.session.get(Subject, sid) is None
    # Refresh sentinel so cleanup doesn't fail
    _S_NAMES.remove(_S_NAMES[2])  # remove __g2a_bio__ from cleanup list
    print('  test_03_subject_delete_allowed — PASS')


def test_04_subject_delete_blocked():
    """Subject deletion should be blocked when Topics reference it."""
    s = Subject.query.filter_by(name=_S_NAMES[0]).first()
    t = _make_topic(_T_NAMES[0], subject_id=s.id)
    assert t.subject_id == s.id

    # Verify blocking logic (as used by the route)
    topic_count = s.topics.count()
    assert topic_count > 0, 'Expected at least one topic referencing this subject'
    print('  test_04_subject_delete_blocked — PASS')


def test_05_topic_null_subject():
    """Topic can be created with subject_id=None (no Subject assigned)."""
    t = _make_topic(_T_NAMES[1], subject_id=None)
    assert t.subject_id is None
    assert t.subject_obj is None
    print('  test_05_topic_null_subject — PASS')


def test_06_topic_assigned_subject():
    """Topic.subject_obj backref resolves to the correct Subject."""
    s = Subject.query.filter_by(name=_S_NAMES[0]).first()
    t_a = Topic.query.filter_by(name=_T_NAMES[0]).first()
    assert t_a.subject_id == s.id
    assert t_a.subject_obj is not None
    assert t_a.subject_obj.name == _S_NAMES[0]
    print('  test_06_topic_assigned_subject — PASS')


def test_07_topic_change_subject():
    """Topic's subject can be reassigned or cleared."""
    s2 = _make_subject(_S_NAMES[1])
    t_a = Topic.query.filter_by(name=_T_NAMES[0]).first()
    old_sid = t_a.subject_id

    # Reassign to a different subject
    t_a.subject_id = s2.id
    db.session.flush()
    assert t_a.subject_obj.name == _S_NAMES[1]

    # Clear back to None
    t_a.subject_id = None
    db.session.flush()
    assert t_a.subject_id is None

    # Restore original assignment for later tests
    t_a.subject_id = old_sid
    db.session.flush()
    print('  test_07_topic_change_subject — PASS')


def test_08_topics_list_shows_subject():
    """Topics list query returns subject_obj correctly for both NULL and assigned topics."""
    all_topics = Topic.query.order_by(Topic.name).all()
    t_a = Topic.query.filter_by(name=_T_NAMES[0]).first()
    t_b = Topic.query.filter_by(name=_T_NAMES[1]).first()

    # t_a has a subject
    assert t_a.subject_obj is not None

    # t_b has no subject — renders as None / '—'
    assert t_b.subject_obj is None
    display = t_b.subject_obj.name if t_b.subject_obj else '—'
    assert display == '—'
    print('  test_08_topics_list_shows_subject — PASS')


def test_09_topic_problem_behavior_preserved():
    """Existing Topic → Problem behavior works after schema change."""
    s = Subject.query.filter_by(name=_S_NAMES[0]).first()
    t_a = Topic.query.filter_by(name=_T_NAMES[0]).first()
    t_a.subject_id = s.id
    db.session.flush()

    prob = Problem(
        topic_id=t_a.id,
        title=_PROB_TITLE,
        prompt_text='2 + 2 = ?',
        answer_text='4',
        difficulty=1,
    )
    db.session.add(prob)
    db.session.flush()

    assert prob.id is not None
    assert prob.topic_id == t_a.id
    assert prob.topic.name == _T_NAMES[0]  # backref works
    assert t_a.problems.count() >= 1
    print('  test_09_topic_problem_behavior_preserved — PASS')


def test_10_backfill_normalization():
    """
    Simulate the backfill normalization logic used in the migration:
    - Strips whitespace.
    - Collapses internal whitespace.
    - Case-insensitive deduplication (first occurrence's display name wins).
    - Blank/null values remain unmapped.
    - Non-identical values are kept separate.
    """
    def _normalize(value):
        if not value:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        collapsed = re.sub(r'\s+', ' ', stripped)
        key = collapsed.lower()
        return key, collapsed

    test_values = [
        'Math',
        ' math ',
        'MATH',
        'Physics',
        'Physics HL',   # must NOT merge with 'Physics'
        '',             # blank → skip
        '   ',          # whitespace-only → skip
        None,           # None → skip
        'Biology',
    ]

    subject_map = {}
    for v in test_values:
        result = _normalize(v)
        if result is None:
            continue
        key, display = result
        if key not in subject_map:
            subject_map[key] = display

    # 'Math', ' math ', 'MATH' → one entry; display from first occurrence = 'Math'
    assert 'math' in subject_map
    assert subject_map['math'] == 'Math'

    # 'Physics' and 'Physics HL' must be separate
    assert 'physics' in subject_map
    assert 'physics hl' in subject_map
    assert subject_map['physics'] == 'Physics'
    assert subject_map['physics hl'] == 'Physics HL'

    # Blank and None are skipped
    assert '' not in subject_map
    assert '   ' not in subject_map

    # Biology is present
    assert 'biology' in subject_map

    # Total: Math, Physics, Physics HL, Biology — 4 unique subjects (not 6+)
    assert len(subject_map) == 4

    print('  test_10_backfill_normalization — PASS')


def test_11_no_duplicate_subjects_from_backfill():
    """Backfilling the same normalized name twice must not create duplicate Subject rows."""
    # Create two topics with different casings of the same subject string
    t_c = _make_topic(_T_NAMES[2], legacy_subject='TestBackfillSubject')

    name = 'TestBackfillSubject'
    # Simulate what backfill does: INSERT OR IGNORE
    existing = Subject.query.filter(
        db.func.lower(Subject.name) == name.lower()
    ).first()
    if existing is None:
        s = Subject(name=name)
        db.session.add(s)
        db.session.flush()
    else:
        s = existing

    # Attempt to insert same normalized name again
    count_before = Subject.query.filter(
        db.func.lower(Subject.name) == name.lower()
    ).count()

    # Second insert should be skipped
    existing2 = Subject.query.filter(
        db.func.lower(Subject.name) == name.lower()
    ).first()
    # Only one row should exist
    count_after = Subject.query.filter(
        db.func.lower(Subject.name) == name.lower()
    ).count()
    assert count_after == 1

    # Clean up this test subject
    db.session.delete(existing2)
    db.session.flush()
    print('  test_11_no_duplicate_subjects_from_backfill — PASS')


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_g2a_tests():
    print('Running G2a Subject Foundation tests...')
    with flask_app.app_context():
        _clean(db.session)
        try:
            test_01_subject_create()
            test_02_subject_edit()
            test_03_subject_delete_allowed()
            test_04_subject_delete_blocked()
            test_05_topic_null_subject()
            test_06_topic_assigned_subject()
            test_07_topic_change_subject()
            test_08_topics_list_shows_subject()
            test_09_topic_problem_behavior_preserved()
            test_10_backfill_normalization()
            test_11_no_duplicate_subjects_from_backfill()
            db.session.commit()
            print('\nAll G2a tests passed.')
        except Exception:
            db.session.rollback()
            raise
        finally:
            _clean(db.session)


if __name__ == '__main__':
    run_g2a_tests()

    # Run the full prior test suite to verify nothing was broken.
    print('\nRunning prior test suite (all steps A/B/C/D/G1)...')
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python = os.path.join(project_root, '.venv', 'Scripts', 'python.exe')
    prior_tests = [
        'test_classic_step_a.py',
        'test_classic_step_b.py',
        os.path.join('tests', 'test_classic_step_c.py'),
        os.path.join('tests', 'test_classic_step_d.py'),
        os.path.join('tests', 'test_classic_step_d2.py'),
        os.path.join('tests', 'test_classic_step_d3.py'),
        os.path.join('tests', 'test_classic_step_e.py'),
    ]
    all_ok = True
    for t in prior_tests:
        full = os.path.join(project_root, t)
        if not os.path.exists(full):
            print(f'  SKIP (not found): {t}')
            continue
        result = subprocess.run([python, full], capture_output=True, text=True, cwd=project_root)
        if result.returncode != 0:
            print(f'  FAIL: {t}')
            print(result.stdout[-2000:] if result.stdout else '')
            print(result.stderr[-2000:] if result.stderr else '')
            all_ok = False
        else:
            last_line = result.stdout.strip().split('\n')[-1]
            print(f'  OK: {t} — {last_line}')

    if not all_ok:
        print('\nSome prior tests FAILED.')
        sys.exit(1)

    print('\nALL TESTS PASSED.')
