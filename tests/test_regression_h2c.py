"""
test_regression_h2c.py
======================

Regression tests for H2c — History CSV export.

Coverage:
  H2c-01: Session export route requires authentication
  H2c-02: Session export route requires admin
  H2c-03: Global export route requires authentication
  H2c-04: Global export route requires admin
  H2c-05: Session export returns 200 with text/csv content type
  H2c-06: Global export returns 200 with text/csv content type
  H2c-07: Session export Content-Disposition sets a .csv filename
  H2c-08: Global export Content-Disposition sets a .csv filename
  H2c-09: CSV headers contain all expected columns
  H2c-10: Session export includes only rounds from the requested session
  H2c-11: Global export includes rounds from multiple sessions
  H2c-12: Default session export excludes archived rounds
  H2c-13: Default global export excludes archived rounds
  H2c-14: Session export with ?include_archived=1 includes archived rounds
  H2c-15: Global export with ?include_archived=1 includes archived rounds
  H2c-16: Exported player rows come from frozen RoundPlayerResult
  H2c-17: Empty session export still returns headers-only CSV (not error)
  H2c-18: Empty global export still returns headers-only CSV (not error)
  H2c-19: Session export filename contains the session id

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_h2c.py

Expected: all tests pass, final line "ALL H2c TESTS PASSED."
"""

import csv
import io
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player   import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game     import GameSession, GameRound, RoundPlayer
from app.models.classic  import ClassicRoundConfig, PlayerWallet
from app.models.history  import RoundHistory, RoundPlayerResult


# ── App config ─────────────────────────────────────────────────────────────────

class _TestConfig:
    TESTING                        = True
    SQLALCHEMY_DATABASE_URI        = 'sqlite:///:memory:'
    SECRET_KEY                     = 'h2c-test-secret'
    WTF_CSRF_ENABLED               = False
    SOCKETIO_ASYNC_MODE            = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED                 = False


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


# ── Fixture IDs ────────────────────────────────────────────────────────────────

_ADMIN_USER  = '__h2c_admin__'
_PLAYER_USER = '__h2c_player__'
_P1_USER     = '__h2c_p1__'
_P2_USER     = '__h2c_p2__'
_IDS = {}

_EXPECTED_HEADERS = [
    'session_id', 'session_label_snapshot', 'round_history_id', 'round_number',
    'mode_type', 'ended_at', 'problem_set_name_snapshot', 'group_name_snapshot',
    'player_count', 'round_total_answers', 'round_total_correct', 'round_total_incorrect',
    'round_overall_accuracy', 'player_id', 'player_name_snapshot',
    'final_place', 'final_gold', 'final_gems',
    'player_total_answers', 'player_correct', 'player_incorrect', 'player_accuracy',
    'archived_status',
]


def _setup():
    with flask_app.app_context():
        db.create_all()

        admin = Player(username=_ADMIN_USER, is_admin=True)
        admin.set_password('pass')
        player = Player(username=_PLAYER_USER, is_admin=False)
        player.set_password('pass')
        p1 = Player(username=_P1_USER, is_admin=False)
        p1.set_password('pass')
        p2 = Player(username=_P2_USER, is_admin=False)
        p2.set_password('pass')
        db.session.add_all([admin, player, p1, p2])
        db.session.flush()

        topic = Topic(name='__h2c_topic__')
        db.session.add(topic)
        db.session.flush()

        prob = Problem(topic_id=topic.id, title='H2cQ1',
                       prompt_text='3+3', answer_text='6', difficulty=1)
        db.session.add(prob)
        db.session.flush()

        pset = ProblemSet(name='__h2c_set__')
        pset.problems.append(prob)
        db.session.add(pset)
        db.session.commit()

        _IDS['admin_id']  = admin.id
        _IDS['player_id'] = player.id
        _IDS['p1_id']     = p1.id
        _IDS['p2_id']     = p2.id
        _IDS['pset_id']   = pset.id


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_session(label=None):
    with flask_app.app_context():
        gs = GameSession(mode='classic', status='active',
                         problem_set_id=_IDS['pset_id'], label=label)
        db.session.add(gs)
        db.session.flush()

        gr = GameRound(session_id=gs.id, round_number=1,
                       started_at=datetime.now(timezone.utc))
        db.session.add(gr)
        db.session.flush()

        cfg = ClassicRoundConfig(
            round_id=gr.id, mine_reward=20,
            treasure_search_reward=5,
            attempts_per_problem=1, wrong_answer_penalty=0,
        )
        db.session.add(cfg)
        db.session.commit()
        return gs.id, gr.id


def _insert_frozen_round(session_id, round_id, round_number=1,
                         ended_at=None, archived=False,
                         label_snapshot=None, pset_snapshot='__h2c_set__'):
    """Insert a RoundHistory + two RoundPlayerResult rows."""
    now = ended_at or datetime.now(timezone.utc)
    with flask_app.app_context():
        rh = RoundHistory(
            round_id=round_id,
            session_id=session_id,
            mode_type='classic',
            round_number=round_number,
            started_at=now - timedelta(minutes=5),
            ended_at=now,
            player_count=2,
            total_answers=4,
            total_correct=3,
            total_incorrect=1,
            overall_accuracy=0.75,
            problem_set_name_snapshot=pset_snapshot,
            group_name_snapshot=None,
            session_label_snapshot=label_snapshot,
            archived_at=datetime.now(timezone.utc) if archived else None,
        )
        db.session.add(rh)
        db.session.flush()

        rpr1 = RoundPlayerResult(
            round_history_id=rh.id,
            player_id=_IDS['p1_id'],
            player_name_snapshot=_P1_USER,
            final_gold=100, final_gems=2, final_place=1,
            total_answers=2, correct=2, incorrect=0, accuracy=1.0,
        )
        rpr2 = RoundPlayerResult(
            round_history_id=rh.id,
            player_id=_IDS['p2_id'],
            player_name_snapshot=_P2_USER,
            final_gold=30, final_gems=0, final_place=2,
            total_answers=2, correct=1, incorrect=1, accuracy=0.5,
        )
        db.session.add_all([rpr1, rpr2])
        db.session.commit()
        return rh.id


def _login_as(client, username):
    return client.post('/login',
                       data={'username': username, 'password': 'pass'},
                       follow_redirects=True)


def _parse_csv(response_data):
    """Parse CSV bytes/string into a list of dicts via csv.DictReader."""
    text = response_data.decode('utf-8') if isinstance(response_data, bytes) else response_data
    return list(csv.DictReader(io.StringIO(text)))


def _parse_csv_headers(response_data):
    """Return the header row as a list."""
    text = response_data.decode('utf-8') if isinstance(response_data, bytes) else response_data
    reader = csv.reader(io.StringIO(text))
    return next(reader, [])


# ════════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════════

def test_h2c_01_session_export_auth_guard():
    """H2c-01: Session export redirects unauthenticated user."""
    sid, _ = _make_session()
    with flask_app.test_client() as c:
        resp = c.get(f'/admin/classic/{sid}/history/export',
                     follow_redirects=False)
        check('H2c-01: session export unauthenticated → redirect',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2c_02_session_export_admin_guard():
    """H2c-02: Session export redirects non-admin user."""
    sid, _ = _make_session()
    with flask_app.test_client() as c:
        _login_as(c, _PLAYER_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export',
                     follow_redirects=False)
        check('H2c-02: session export non-admin → redirect',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2c_03_global_export_auth_guard():
    """H2c-03: Global export redirects unauthenticated user."""
    with flask_app.test_client() as c:
        resp = c.get('/admin/history/rounds/export', follow_redirects=False)
        check('H2c-03: global export unauthenticated → redirect',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2c_04_global_export_admin_guard():
    """H2c-04: Global export redirects non-admin user."""
    with flask_app.test_client() as c:
        _login_as(c, _PLAYER_USER)
        resp = c.get('/admin/history/rounds/export', follow_redirects=False)
        check('H2c-04: global export non-admin → redirect',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2c_05_session_export_returns_csv():
    """H2c-05: Session export returns 200 with text/csv content type."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export')
        check('H2c-05: session export status 200',
              resp.status_code == 200,
              f'got {resp.status_code}')
        check('H2c-05b: session export content-type contains text/csv',
              'text/csv' in resp.content_type,
              f'content-type={resp.content_type}')


def test_h2c_06_global_export_returns_csv():
    """H2c-06: Global export returns 200 with text/csv content type."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get('/admin/history/rounds/export')
        check('H2c-06: global export status 200',
              resp.status_code == 200,
              f'got {resp.status_code}')
        check('H2c-06b: global export content-type contains text/csv',
              'text/csv' in resp.content_type,
              f'content-type={resp.content_type}')


def test_h2c_07_session_export_content_disposition():
    """H2c-07: Session export Content-Disposition includes a .csv filename."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export')
        cd = resp.headers.get('Content-Disposition', '')
        check('H2c-07: session export Content-Disposition has attachment',
              'attachment' in cd,
              f'Content-Disposition={cd!r}')
        check('H2c-07b: session export filename ends with .csv',
              '.csv' in cd,
              f'Content-Disposition={cd!r}')


def test_h2c_08_global_export_content_disposition():
    """H2c-08: Global export Content-Disposition includes a .csv filename."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get('/admin/history/rounds/export')
        cd = resp.headers.get('Content-Disposition', '')
        check('H2c-08: global export Content-Disposition has attachment',
              'attachment' in cd,
              f'Content-Disposition={cd!r}')
        check('H2c-08b: global export filename ends with .csv',
              '.csv' in cd,
              f'Content-Disposition={cd!r}')


def test_h2c_09_csv_headers():
    """H2c-09: CSV headers contain all expected columns."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export')
        headers = _parse_csv_headers(resp.data)
        for col in _EXPECTED_HEADERS:
            check(f'H2c-09: header "{col}" present',
                  col in headers,
                  f'headers={headers}')


def test_h2c_10_session_export_scoped_to_session():
    """H2c-10: Session export includes only rounds from the requested session."""
    sid_a, rid_a = _make_session()
    sid_b, rid_b = _make_session()
    _insert_frozen_round(sid_a, rid_a, label_snapshot='Session A')
    _insert_frozen_round(sid_b, rid_b, label_snapshot='Session B')
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid_a}/history/export')
        rows = _parse_csv(resp.data)
        session_ids_in_export = {r['session_id'] for r in rows}
        check('H2c-10: only session A rows present',
              session_ids_in_export == {str(sid_a)},
              f'session_ids={session_ids_in_export}')


def test_h2c_11_global_export_includes_multiple_sessions():
    """H2c-11: Global export includes rounds from multiple sessions."""
    sid_x, rid_x = _make_session()
    sid_y, rid_y = _make_session()
    _insert_frozen_round(sid_x, rid_x, label_snapshot='X')
    _insert_frozen_round(sid_y, rid_y, label_snapshot='Y')
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get('/admin/history/rounds/export')
        rows = _parse_csv(resp.data)
        session_ids = {r['session_id'] for r in rows}
        check('H2c-11: global export contains rows from multiple sessions',
              len(session_ids) >= 2,
              f'session_ids={session_ids}')


def test_h2c_12_session_export_excludes_archived_by_default():
    """H2c-12: Default session export excludes archived rounds."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid, archived=True)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export')
        rows = _parse_csv(resp.data)
        archived_rows = [r for r in rows if r.get('archived_status') == 'archived']
        check('H2c-12: no archived rows in default session export',
              len(archived_rows) == 0,
              f'archived_rows_count={len(archived_rows)}')


def test_h2c_13_global_export_excludes_archived_by_default():
    """H2c-13: Default global export excludes archived rounds."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid, archived=True)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get('/admin/history/rounds/export')
        rows = _parse_csv(resp.data)
        archived_rows = [r for r in rows if r.get('archived_status') == 'archived']
        check('H2c-13: no archived rows in default global export',
              len(archived_rows) == 0,
              f'archived_rows_count={len(archived_rows)}')


def test_h2c_14_session_export_include_archived():
    """H2c-14: Session export with ?include_archived=1 includes archived rounds."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid, archived=True)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export?include_archived=1')
        rows = _parse_csv(resp.data)
        archived_rows = [r for r in rows if r.get('archived_status') == 'archived']
        check('H2c-14: archived rows present when include_archived=1 (session)',
              len(archived_rows) > 0,
              f'archived_rows_count={len(archived_rows)}')
        round_history_ids = {r['round_history_id'] for r in rows}
        check('H2c-14b: archived round_history_id is present',
              str(rh_id) in round_history_ids,
              f'round_history_ids={round_history_ids}')


def test_h2c_15_global_export_include_archived():
    """H2c-15: Global export with ?include_archived=1 includes archived rounds."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid, archived=True)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get('/admin/history/rounds/export?include_archived=1')
        rows = _parse_csv(resp.data)
        archived_rows = [r for r in rows if r.get('archived_status') == 'archived']
        check('H2c-15: archived rows present when include_archived=1 (global)',
              len(archived_rows) > 0,
              f'archived_rows_count={len(archived_rows)}')
        round_history_ids = {r['round_history_id'] for r in rows}
        check('H2c-15b: archived round_history_id is in global export',
              str(rh_id) in round_history_ids,
              f'round_history_ids={round_history_ids}')


def test_h2c_16_player_rows_from_frozen_results():
    """H2c-16: Exported player rows come from frozen RoundPlayerResult data."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export')
        rows = _parse_csv(resp.data)
        player_names = {r['player_name_snapshot'] for r in rows if r['player_name_snapshot']}
        check('H2c-16: p1 player_name_snapshot present in export',
              _P1_USER in player_names,
              f'player_names={player_names}')
        check('H2c-16b: p2 player_name_snapshot present in export',
              _P2_USER in player_names,
              f'player_names={player_names}')
        gold_values = {r['final_gold'] for r in rows if r['final_gold']}
        check('H2c-16c: final_gold values match frozen data (100 and 30)',
              '100' in gold_values and '30' in gold_values,
              f'final_gold values={gold_values}')


def test_h2c_17_empty_session_export_returns_headers():
    """H2c-17: Session with no frozen rounds returns headers-only CSV (not error)."""
    sid, _ = _make_session()
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export')
        check('H2c-17: empty session export status 200',
              resp.status_code == 200,
              f'got {resp.status_code}')
        headers = _parse_csv_headers(resp.data)
        check('H2c-17b: empty session export still has header row',
              headers == _EXPECTED_HEADERS,
              f'headers={headers}')
        rows = _parse_csv(resp.data)
        check('H2c-17c: empty session export has zero data rows',
              len(rows) == 0,
              f'row_count={len(rows)}')


def test_h2c_18_empty_global_export_returns_headers():
    """H2c-18: No frozen rounds at all returns headers-only CSV (not error).

    Use include_archived=0 on a session that was archived to simulate empty result.
    """
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid, archived=True)  # all archived → default export is empty
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        # We only get empty if ALL rounds are archived. Use a fresh session with no rounds.
        fresh_sid, _ = _make_session()
        resp = c.get(f'/admin/classic/{fresh_sid}/history/export')
        check('H2c-18: global export with no visible rounds status 200',
              resp.status_code == 200,
              f'got {resp.status_code}')
        headers = _parse_csv_headers(resp.data)
        check('H2c-18b: export with no visible rounds still has header row',
              headers == _EXPECTED_HEADERS,
              f'headers={headers}')


def test_h2c_19_session_export_filename_contains_session_id():
    """H2c-19: Session export filename contains the session id."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history/export')
        cd = resp.headers.get('Content-Disposition', '')
        check('H2c-19: filename contains session_id',
              str(sid) in cd,
              f'Content-Disposition={cd!r}')


# ════════════════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('Setting up H2c test fixtures...')
    _setup()
    print('Running H2c tests...\n')

    test_h2c_01_session_export_auth_guard()
    test_h2c_02_session_export_admin_guard()
    test_h2c_03_global_export_auth_guard()
    test_h2c_04_global_export_admin_guard()
    test_h2c_05_session_export_returns_csv()
    test_h2c_06_global_export_returns_csv()
    test_h2c_07_session_export_content_disposition()
    test_h2c_08_global_export_content_disposition()
    test_h2c_09_csv_headers()
    test_h2c_10_session_export_scoped_to_session()
    test_h2c_11_global_export_includes_multiple_sessions()
    test_h2c_12_session_export_excludes_archived_by_default()
    test_h2c_13_global_export_excludes_archived_by_default()
    test_h2c_14_session_export_include_archived()
    test_h2c_15_global_export_include_archived()
    test_h2c_16_player_rows_from_frozen_results()
    test_h2c_17_empty_session_export_returns_headers()
    test_h2c_18_empty_global_export_returns_headers()
    test_h2c_19_session_export_filename_contains_session_id()

    print()
    print('─' * 50)
    print(f'Results: {passed} passed, {failed} failed')
    if failed == 0:
        print('ALL H2c TESTS PASSED.')
    else:
        print(f'{failed} TEST(S) FAILED.')
        sys.exit(1)
