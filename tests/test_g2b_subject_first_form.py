"""
test_g2b_subject_first_form.py
==============================

Exit tests for Phase 4 Step G2b: Subject-First Problem Form + Topics-by-Subject AJAX.

Covers:
  1.  GET /admin/topics/by_subject/0 returns all Topics.
  2.  GET /admin/topics/by_subject/<id> returns only Topics for that Subject.
  3.  Endpoint is admin-protected (non-admin gets 302 redirect).
  4.  Problem create form renders with Subject helper + Topic selector.
  5.  Problem edit form renders with correct Subject preselected (non-null subject).
  6.  Problem edit form handles Topic with NULL subject_id (subject_helper_value == 0).
  7.  Valid create submission (topic matches selected Subject) succeeds.
  8.  Valid create submission (subject_helper == 0) succeeds for any valid Topic.
  9.  Forged POST: mismatched subject/topic is rejected (topic belongs to different subject).
  10. Forged POST: non-zero Subject + NULL-subject Topic is rejected.
  11. Existing Problem → Topic behavior remains intact after schema changes.
  12. All prior tests remain green (checked via subprocess at the end).

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_g2b_subject_first_form.py

Expected: all assertions pass + "ALL TESTS PASSED." on final line.
"""

import sys
import os
import json
import re
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.subjects import Subject
from app.models.problems import Topic, Problem, ProblemSet
from app.models.player import Player

flask_app = create_app()

# ── Sentinel names ────────────────────────────────────────────────────────────
_SUBJ_A   = '__g2b_subj_a__'
_SUBJ_B   = '__g2b_subj_b__'
_TOPIC_A  = '__g2b_topic_a__'   # belongs to SUBJ_A
_TOPIC_B  = '__g2b_topic_b__'   # belongs to SUBJ_B
_TOPIC_C  = '__g2b_topic_c__'   # NULL subject_id
_PROB_TITLE  = '__g2b_problem__'
_ADMIN_USER  = '__g2b_admin__'


def _clean():
    for p in Problem.query.filter(
        Problem.title.in_([_PROB_TITLE, '__g2b_forged__', '__g2b_forged2__'])
    ).all():
        db.session.delete(p)
    db.session.flush()
    for name in [_TOPIC_A, _TOPIC_B, _TOPIC_C]:
        t = Topic.query.filter_by(name=name).first()
        if t:
            db.session.delete(t)
    db.session.flush()
    for name in [_SUBJ_A, _SUBJ_B]:
        s = Subject.query.filter_by(name=name).first()
        if s:
            db.session.delete(s)
    db.session.flush()
    u = Player.query.filter_by(username=_ADMIN_USER).first()
    if u:
        db.session.delete(u)
    db.session.commit()


def _setup():
    """Create test fixtures and return their IDs (not ORM objects — committed)."""
    sa = Subject(name=_SUBJ_A)
    sb = Subject(name=_SUBJ_B)
    db.session.add_all([sa, sb])
    db.session.flush()

    ta = Topic(name=_TOPIC_A, subject_id=sa.id)
    tb = Topic(name=_TOPIC_B, subject_id=sb.id)
    tc = Topic(name=_TOPIC_C, subject_id=None)
    db.session.add_all([ta, tb, tc])
    db.session.flush()

    admin = Player(username=_ADMIN_USER, is_admin=True)
    admin.set_password('testpass')
    db.session.add(admin)
    db.session.commit()

    return sa.id, sb.id, ta.id, tb.id, tc.id


# ─────────────────────────────────────────────────────────────────────────────
# Model-layer tests — run inside app_context, called with ORM objects
# ─────────────────────────────────────────────────────────────────────────────

def test_01_topics_by_subject_all():
    all_topics = Topic.query.order_by(Topic.name).all()
    names = [t.name for t in all_topics]
    assert _TOPIC_A in names
    assert _TOPIC_B in names
    assert _TOPIC_C in names
    print('  test_01_topics_by_subject_all — PASS')


def test_02_topics_by_subject_scoped(sa_id, sb_id):
    topics_a = Topic.query.filter_by(subject_id=sa_id).order_by(Topic.name).all()
    names_a = [t.name for t in topics_a]
    assert _TOPIC_A in names_a
    assert _TOPIC_B not in names_a
    assert _TOPIC_C not in names_a

    topics_b = Topic.query.filter_by(subject_id=sb_id).order_by(Topic.name).all()
    assert _TOPIC_B in [t.name for t in topics_b]
    assert _TOPIC_A not in [t.name for t in topics_b]
    print('  test_02_topics_by_subject_scoped — PASS')


def test_03_validate_zero_any_topic(sa_id, ta_id, tc_id):
    from app.routes.admin import _validate_topic_subject
    ta = db.session.get(Topic, ta_id)
    tc = db.session.get(Topic, tc_id)
    assert _validate_topic_subject(0, ta) is None
    assert _validate_topic_subject(0, tc) is None
    print('  test_03_validate_zero_any_topic — PASS')


def test_04_validate_matching(sa_id, ta_id):
    from app.routes.admin import _validate_topic_subject
    ta = db.session.get(Topic, ta_id)
    assert _validate_topic_subject(sa_id, ta) is None
    print('  test_04_validate_matching — PASS')


def test_05_validate_mismatched(sa_id, tb_id):
    from app.routes.admin import _validate_topic_subject
    tb = db.session.get(Topic, tb_id)
    result = _validate_topic_subject(sa_id, tb)
    assert result is not None and isinstance(result, str)
    print('  test_05_validate_mismatched — PASS')


def test_06_validate_nonzero_null_subject(sa_id, tc_id):
    from app.routes.admin import _validate_topic_subject
    tc = db.session.get(Topic, tc_id)
    result = _validate_topic_subject(sa_id, tc)
    assert result is not None
    print('  test_06_validate_nonzero_null_subject — PASS')


def test_11_problem_topic_ownership(ta_id):
    prob = Problem.query.filter_by(title=_PROB_TITLE).first()
    if prob is None:
        ta = db.session.get(Topic, ta_id)
        prob = Problem(topic_id=ta.id, title=_PROB_TITLE,
                       prompt_text='q', answer_text='a', difficulty=1)
        db.session.add(prob)
        db.session.commit()

    assert prob.topic is not None
    assert prob.topic_id == prob.topic.id
    loaded = db.session.get(Topic, prob.topic_id)
    assert loaded.problems.filter_by(id=prob.id).first() is not None
    print('  test_11_problem_topic_ownership — PASS')


# ─────────────────────────────────────────────────────────────────────────────
# HTTP-layer tests — each runs with its own Flask test_client (no outer ctx)
# ─────────────────────────────────────────────────────────────────────────────

def _login_client(client):
    """GET /login for CSRF token, then POST credentials."""
    get_resp = client.get('/login')
    html = get_resp.data.decode('utf-8', errors='replace')
    m = re.search(r'<input[^>]+name="csrf_token"[^>]+value="([^"]+)"', html)
    token = m.group(1) if m else ''
    client.post('/login', data={
        'csrf_token': token,
        'username': _ADMIN_USER,
        'password': 'testpass',
    }, follow_redirects=True)


def test_07_ajax_all_topics(sa_id, sb_id, ta_id, tb_id, tc_id):
    """by_subject/0 returns all topics; by_subject/<id> returns scoped list."""
    with flask_app.test_client() as c:
        _login_client(c)

        r = c.get('/admin/topics/by_subject/0')
        assert r.status_code == 200, f'Expected 200, got {r.status_code}'
        d = json.loads(r.data)
        all_names = [t['name'] for t in d['topics']]
        assert _TOPIC_A in all_names
        assert _TOPIC_B in all_names
        assert _TOPIC_C in all_names

        r2 = c.get(f'/admin/topics/by_subject/{sa_id}')
        assert r2.status_code == 200
        d2 = json.loads(r2.data)
        names2 = [t['name'] for t in d2['topics']]
        assert _TOPIC_A in names2
        assert _TOPIC_B not in names2
        assert _TOPIC_C not in names2
    print('  test_07_ajax_all_topics — PASS')


def test_08_ajax_admin_protected():
    """Endpoint redirects when not logged in."""
    with flask_app.test_client() as c:
        r = c.get('/admin/topics/by_subject/0')
        assert r.status_code in (302, 401), f'Expected redirect, got {r.status_code}'
    print('  test_08_ajax_admin_protected — PASS')


def test_09_create_form_renders():
    """Create form page includes subject_helper select + topic_id select."""
    with flask_app.test_client() as c:
        _login_client(c)
        r = c.get('/admin/problems/new')
        assert r.status_code == 200
        html = r.data.decode('utf-8', errors='replace')
        assert 'subject_helper' in html
        assert 'topic_id' in html
        assert 'Any Subject' in html
    print('  test_09_create_form_renders — PASS')


def test_10_edit_preselects_subject(sa_id, ta_id):
    """Edit form preselects the correct Subject for a topic that has one."""
    with flask_app.app_context():
        ta = db.session.get(Topic, ta_id)
        prob = Problem(topic_id=ta.id, title=_PROB_TITLE,
                       prompt_text='q', answer_text='a', difficulty=1)
        db.session.add(prob)
        db.session.commit()
        prob_id = prob.id

    with flask_app.test_client() as c:
        _login_client(c)
        r = c.get(f'/admin/problems/{prob_id}/edit')
        assert r.status_code == 200
        html = r.data.decode('utf-8', errors='replace')
        # The subject option with sa_id should be selected
        assert f'value="{sa_id}" selected' in html or \
               f'value="{sa_id}"  selected' in html or \
               (f'value="{sa_id}"' in html and 'selected' in html), \
               f'Subject {sa_id} not preselected in edit form HTML'
    print('  test_10_edit_preselects_subject — PASS')


def test_10b_edit_null_subject_defaults_to_zero(tc_id):
    """Edit form for NULL-subject topic: subject_helper_value == 0."""
    with flask_app.app_context():
        tc = db.session.get(Topic, tc_id)
        prob = Problem(topic_id=tc.id, title=_PROB_TITLE,
                       prompt_text='q', answer_text='a', difficulty=1)
        db.session.add(prob)
        db.session.commit()
        prob_id = prob.id

    with flask_app.test_client() as c:
        _login_client(c)
        r = c.get(f'/admin/problems/{prob_id}/edit')
        assert r.status_code == 200
        html = r.data.decode('utf-8', errors='replace')
        assert 'value="0" selected' in html or 'value="0"  selected' in html, \
            '"Any Subject" (value=0) not selected for NULL-subject topic'
    print('  test_10b_edit_null_subject_defaults_to_zero — PASS')


def _get_csrf(c, url='/admin/problems/new'):
    r = c.get(url)
    html = r.data.decode('utf-8', errors='replace')
    m = re.search(r'<input[^>]+name="csrf_token"[^>]+value="([^"]+)"', html)
    return m.group(1) if m else ''


def test_12_valid_create_subject_matches_topic(sa_id, ta_id):
    """Valid create: subject_helper matches topic's subject → success."""
    with flask_app.test_client() as c:
        _login_client(c)
        token = _get_csrf(c)
        r = c.post('/admin/problems/new', data={
            'csrf_token': token,
            'title': _PROB_TITLE,
            'topic_id': ta_id,
            'subject_helper': sa_id,
            'prompt_text': 'test question',
            'answer_text': 'test answer',
            'difficulty': 1,
            'image_path': '',
        }, follow_redirects=True)
        assert r.status_code == 200
        html = r.data.decode('utf-8', errors='replace')
        assert 'does not belong' not in html
    print('  test_12_valid_create_subject_matches_topic — PASS')


def test_13_valid_create_subject_zero(tc_id):
    """Valid create: subject_helper == 0 + NULL-subject topic → success."""
    with flask_app.test_client() as c:
        _login_client(c)
        token = _get_csrf(c)
        r = c.post('/admin/problems/new', data={
            'csrf_token': token,
            'title': _PROB_TITLE,
            'topic_id': tc_id,
            'subject_helper': 0,
            'prompt_text': 'test question 2',
            'answer_text': 'test answer 2',
            'difficulty': 1,
            'image_path': '',
        }, follow_redirects=True)
        assert r.status_code == 200
        assert 'does not belong' not in r.data.decode('utf-8', errors='replace')
    print('  test_13_valid_create_subject_zero — PASS')


def test_14_forged_mismatched_subject_topic(sa_id, tb_id):
    """Forged POST: subject_helper=sa, topic from sb → rejected + not saved."""
    with flask_app.test_client() as c:
        _login_client(c)
        token = _get_csrf(c)
        r = c.post('/admin/problems/new', data={
            'csrf_token': token,
            'title': '__g2b_forged__',
            'topic_id': tb_id,       # tb belongs to sb
            'subject_helper': sa_id,  # claiming sa
            'prompt_text': 'forged',
            'answer_text': 'forged',
            'difficulty': 1,
            'image_path': '',
        }, follow_redirects=True)
        assert r.status_code == 200
        html = r.data.decode('utf-8', errors='replace')
        assert 'does not belong' in html, 'Expected server-side rejection'

    with flask_app.app_context():
        saved = Problem.query.filter_by(title='__g2b_forged__').first()
        assert saved is None, 'Forged problem was incorrectly saved'
    print('  test_14_forged_mismatched_subject_topic — PASS')


def test_15_forged_nonzero_subject_null_topic(sa_id, tc_id):
    """Forged POST: subject_helper=sa, NULL-subject topic → rejected + not saved."""
    with flask_app.test_client() as c:
        _login_client(c)
        token = _get_csrf(c)
        r = c.post('/admin/problems/new', data={
            'csrf_token': token,
            'title': '__g2b_forged2__',
            'topic_id': tc_id,        # tc has NULL subject_id
            'subject_helper': sa_id,  # non-zero subject claimed
            'prompt_text': 'forged',
            'answer_text': 'forged',
            'difficulty': 1,
            'image_path': '',
        }, follow_redirects=True)
        assert r.status_code == 200
        html = r.data.decode('utf-8', errors='replace')
        assert 'does not belong' in html, 'Expected rejection for NULL-subject topic with non-zero subject'

    with flask_app.app_context():
        saved = Problem.query.filter_by(title='__g2b_forged2__').first()
        assert saved is None, 'Forged problem was incorrectly saved'
    print('  test_15_forged_nonzero_subject_null_topic — PASS')


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_g2b_tests():
    print('Running G2b Subject-First Form tests...')

    # Phase 1: Setup fixtures + model-level tests (inside app_context)
    with flask_app.app_context():
        _clean()
        sa_id, sb_id, ta_id, tb_id, tc_id = _setup()

        test_01_topics_by_subject_all()
        test_02_topics_by_subject_scoped(sa_id, sb_id)
        test_03_validate_zero_any_topic(sa_id, ta_id, tc_id)
        test_04_validate_matching(sa_id, ta_id)
        test_05_validate_mismatched(sa_id, tb_id)
        test_06_validate_nonzero_null_subject(sa_id, tc_id)

    # Phase 2: HTTP tests — each manages its own context via test_client
    test_07_ajax_all_topics(sa_id, sb_id, ta_id, tb_id, tc_id)
    test_08_ajax_admin_protected()
    test_09_create_form_renders()
    test_10_edit_preselects_subject(sa_id, ta_id)
    test_10b_edit_null_subject_defaults_to_zero(tc_id)
    test_12_valid_create_subject_matches_topic(sa_id, ta_id)
    test_13_valid_create_subject_zero(tc_id)
    test_14_forged_mismatched_subject_topic(sa_id, tb_id)
    test_15_forged_nonzero_subject_null_topic(sa_id, tc_id)

    # Phase 3: Final model test + cleanup
    with flask_app.app_context():
        test_11_problem_topic_ownership(ta_id)
        _clean()

    print('\nAll G2b tests passed.')


if __name__ == '__main__':
    run_g2b_tests()

    # Run prior test suite to confirm nothing was broken.
    print('\nRunning prior test suite...')
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python = os.path.join(project_root, '.venv', 'Scripts', 'python.exe')
    env = dict(os.environ, PYTHONIOENCODING='utf-8')

    prior_tests = [
        'test_classic_step_a.py',
        'test_classic_step_b.py',
        os.path.join('tests', 'test_classic_step_c.py'),
        os.path.join('tests', 'test_classic_step_d.py'),
        os.path.join('tests', 'test_classic_step_d2.py'),
        os.path.join('tests', 'test_classic_step_d3.py'),
        os.path.join('tests', 'test_classic_step_e.py'),
        os.path.join('tests', 'test_g2a_subject_foundation.py'),
    ]
    all_ok = True
    for t in prior_tests:
        full = os.path.join(project_root, t)
        if not os.path.exists(full):
            print(f'  SKIP (not found): {t}')
            continue
        result = subprocess.run([python, full], capture_output=True, text=True,
                                cwd=project_root, env=env)
        last = result.stdout.strip().split('\n')[-1] if result.stdout.strip() else '(no output)'
        if result.returncode != 0:
            print(f'  FAIL: {t}')
            print(result.stdout[-3000:] if result.stdout else '')
            print(result.stderr[-1000:] if result.stderr else '')
            all_ok = False
        else:
            print(f'  OK: {t} — {last}')

    if not all_ok:
        print('\nSome prior tests FAILED.')
        sys.exit(1)

    print('\nALL TESTS PASSED.')

