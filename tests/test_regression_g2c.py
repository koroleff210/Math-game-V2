"""
test_regression_g2c.py
======================

Regression tests for G2c — Subject filter on Problems list and Problem Set
detail pages.

Coverage:
  G2c_01: Problems list returns 200 and contains Subject column header
  G2c_02: Unfiltered problems list shows all problems (including NULL-subject)
  G2c_03: Filtered by valid subject_id returns only matching problems
  G2c_04: Filtered by subject_id=0 (explicit "all") returns all problems
  G2c_05: Problem with NULL-subject Topic renders safely (no crash, shows em-dash)
  G2c_06: Problem Set detail page returns 200
  G2c_07: Problem Set detail unfiltered available list shows all available problems
  G2c_08: Problem Set detail filtered by subject_id returns only matching available
  G2c_09: Problem Set detail add-problem POST still works (existing behaviour)
  G2c_10: Problem Set detail remove-problem POST still works (existing behaviour)
  G2c_11: Subject column query: problem whose topic has subject_id returns subject name
  G2c_12: Problem with NULL-subject Topic appears in unfiltered set detail available list
  Regression:
  G2c_R1: All prior regression tests still pass (test_regression_8_9.py)

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_g2c.py

Expected: all tests pass, final line "ALL G2c TESTS PASSED."
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.subjects import Subject


# ── Test config ────────────────────────────────────────────────────────────────

class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'g2c-test-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

# ── Test runner ────────────────────────────────────────────────────────────────

passed = 0
failed = 0


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        msg = f'  FAIL  {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)
        failed += 1


# ── Fixtures ───────────────────────────────────────────────────────────────────

_ADMIN_USER = '__g2c_admin__'
_TOPIC_A    = '__g2c_topic_a__'   # has subject
_TOPIC_B    = '__g2c_topic_b__'   # has different subject
_TOPIC_NULL = '__g2c_topic_null__' # NULL subject_id
_SUBJ_A     = '__g2c_subj_a__'
_SUBJ_B     = '__g2c_subj_b__'
_SET_NAME   = '__g2c_set__'

_ids = {}  # populated during setup


def _setup():
    with flask_app.app_context():
        db.create_all()

        # Admin user
        admin = Player(username=_ADMIN_USER, is_admin=True)
        admin.set_password('testpass')
        db.session.add(admin)
        db.session.flush()

        # Subjects
        sa = Subject(name=_SUBJ_A, description='Test subject A')
        sb = Subject(name=_SUBJ_B, description='Test subject B')
        db.session.add_all([sa, sb])
        db.session.flush()

        # Topics
        ta = Topic(name=_TOPIC_A, subject_id=sa.id)
        tb = Topic(name=_TOPIC_B, subject_id=sb.id)
        tnull = Topic(name=_TOPIC_NULL, subject_id=None)
        db.session.add_all([ta, tb, tnull])
        db.session.flush()

        # Problems
        p1 = Problem(topic_id=ta.id, title='G2c-P1', prompt_text='Q1', answer_text='A1', difficulty=1)
        p2 = Problem(topic_id=tb.id, title='G2c-P2', prompt_text='Q2', answer_text='A2', difficulty=2)
        p3 = Problem(topic_id=tnull.id, title='G2c-P3-null', prompt_text='Q3', answer_text='A3', difficulty=1)
        db.session.add_all([p1, p2, p3])
        db.session.flush()

        # Problem set (empty)
        pset = ProblemSet(name=_SET_NAME)
        db.session.add(pset)
        db.session.commit()

        _ids['admin_id'] = admin.id
        _ids['sa_id'] = sa.id
        _ids['sb_id'] = sb.id
        _ids['p1_id'] = p1.id
        _ids['p2_id'] = p2.id
        _ids['p3_id'] = p3.id
        _ids['set_id'] = pset.id


def _login(client):
    return client.post('/login', data={'username': _ADMIN_USER, 'password': 'testpass'},
                       follow_redirects=True)


# ── Tests ──────────────────────────────────────────────────────────────────────

def run_tests():
    _setup()

    with flask_app.test_client() as client:
        _login(client)

        # ── G2c_01: Problems list returns 200, contains Subject column header ──
        r = client.get('/admin/problems')
        check('G2c_01: problems list returns 200', r.status_code == 200,
              f'got {r.status_code}')
        check('G2c_01: problems list has Subject column header',
              b'Subject' in r.data,
              'Subject header missing from problems table')

        # ── G2c_02: Unfiltered list shows all 3 problems ──────────────────────
        r = client.get('/admin/problems')
        html = r.data.decode()
        check('G2c_02: unfiltered list shows P1', 'G2c-P1' in html)
        check('G2c_02: unfiltered list shows P2', 'G2c-P2' in html)
        check('G2c_02: unfiltered list shows NULL-subject P3', 'G2c-P3-null' in html)

        # ── G2c_03: Filtered by subject A shows only P1 ───────────────────────
        r = client.get(f'/admin/problems?subject_id={_ids["sa_id"]}')
        html = r.data.decode()
        check('G2c_03: filter by subj A shows P1', 'G2c-P1' in html)
        check('G2c_03: filter by subj A hides P2', 'G2c-P2' not in html)
        check('G2c_03: filter by subj A hides NULL-subject P3', 'G2c-P3-null' not in html)

        # ── G2c_04: Explicit subject_id=0 acts as "all" ───────────────────────
        r = client.get('/admin/problems?subject_id=0')
        html = r.data.decode()
        check('G2c_04: subject_id=0 shows P1', 'G2c-P1' in html)
        check('G2c_04: subject_id=0 shows P2', 'G2c-P2' in html)
        check('G2c_04: subject_id=0 shows NULL-subject P3', 'G2c-P3-null' in html)

        # ── G2c_05: NULL-subject Topic renders safely (em-dash) ───────────────
        r = client.get('/admin/problems')
        html = r.data.decode()
        # p3 has NULL subject_id; template emits &mdash; (—) or literal em-dash
        check('G2c_05: NULL-subject problem renders without crash', r.status_code == 200)
        # Ensure the em-dash or mdash entity appears at least once
        check('G2c_05: em-dash shown for NULL-subject problem',
              '&mdash;' in html or '\u2014' in html,
              'expected &mdash; or em-dash char for NULL-subject rows')

        # ── G2c_06: Problem Set detail returns 200 ────────────────────────────
        sid = _ids['set_id']
        r = client.get(f'/admin/sets/{sid}')
        check('G2c_06: set detail returns 200', r.status_code == 200,
              f'got {r.status_code}')

        # ── G2c_07: Unfiltered available list shows all 3 problems ────────────
        r = client.get(f'/admin/sets/{sid}')
        html = r.data.decode()
        check('G2c_07: unfiltered available shows P1', 'G2c-P1' in html)
        check('G2c_07: unfiltered available shows P2', 'G2c-P2' in html)
        check('G2c_07: unfiltered available shows NULL-subject P3', 'G2c-P3-null' in html)

        # ── G2c_08: Filter available by subject A shows only P1 ──────────────
        r = client.get(f'/admin/sets/{sid}?subject_id={_ids["sa_id"]}')
        html = r.data.decode()
        check('G2c_08: filtered available shows P1', 'G2c-P1' in html)
        check('G2c_08: filtered available hides P2', 'G2c-P2' not in html)
        check('G2c_08: filtered available hides NULL P3', 'G2c-P3-null' not in html)

        # ── G2c_09: Add-problem POST still works ─────────────────────────────
        r = client.post(f'/admin/sets/{sid}/add',
                        data={'problem_id': str(_ids['p1_id'])},
                        follow_redirects=True)
        check('G2c_09: add problem returns 200', r.status_code == 200,
              f'got {r.status_code}')
        # After add, P1 should appear in "Problems in This Set" and NOT in available
        html = r.data.decode()
        check('G2c_09: P1 now in set', 'G2c-P1' in html)

        # Verify directly via ORM that P1 is in the set
        with flask_app.app_context():
            pset = db.session.get(ProblemSet, sid)
            set_ids = {p.id for p in pset.problems.all()}
            check('G2c_09: ORM confirms P1 in set', _ids['p1_id'] in set_ids,
                  f'set contains {set_ids}')

        # ── G2c_10: Remove-problem POST still works ───────────────────────────
        r = client.post(f'/admin/sets/{sid}/remove/{_ids["p1_id"]}',
                        follow_redirects=True)
        check('G2c_10: remove problem returns 200', r.status_code == 200,
              f'got {r.status_code}')
        with flask_app.app_context():
            pset = db.session.get(ProblemSet, sid)
            set_ids = {p.id for p in pset.problems.all()}
            check('G2c_10: ORM confirms P1 removed from set', _ids['p1_id'] not in set_ids,
                  f'set still contains {set_ids}')

        # ── G2c_11: Subject name shown in Problems list for subject-linked problem ──
        r = client.get(f'/admin/problems?subject_id={_ids["sa_id"]}')
        html = r.data.decode()
        check('G2c_11: subject A name visible in filtered problems page',
              _SUBJ_A.lstrip('_').rstrip('_') in html or _SUBJ_A in html,
              'subject name not found in page')

        # ── G2c_12: NULL-subject problem appears in unfiltered set detail ─────
        r = client.get(f'/admin/sets/{sid}')
        html = r.data.decode()
        check('G2c_12: NULL-subject P3 in unfiltered set detail available', 'G2c-P3-null' in html)


def run_regression_r8_9():
    """Run prior regression batch via subprocess to confirm still green."""
    script = os.path.join(os.path.dirname(__file__), 'test_regression_8_9.py')
    python = sys.executable
    result = subprocess.run([python, script], capture_output=True, text=True)
    lines = (result.stdout + result.stderr).strip().splitlines()
    last = lines[-1] if lines else ''
    ok = result.returncode == 0 and 'PASSED' in last
    check('G2c_R1: test_regression_8_9 still green', ok,
          f'returncode={result.returncode} last_line={last!r}')


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=== G2c regression tests ===')
    run_tests()
    print()
    print('=== Prior regression batch ===')
    run_regression_r8_9()
    print()
    print(f'Results: {passed} passed, {failed} failed.')
    if failed == 0:
        print('ALL G2c TESTS PASSED.')
    else:
        print(f'FAILED: {failed} test(s) did not pass.')
        sys.exit(1)
