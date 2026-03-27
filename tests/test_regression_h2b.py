"""
test_regression_h2b.py
======================

Regression tests for H2b — Safe delete/archive controls for history.

Coverage:
  H2b-01: POST archive route redirects unauthenticated users
  H2b-02: POST archive route redirects non-admin users
  H2b-03: POST delete route redirects unauthenticated users
  H2b-04: POST delete route redirects non-admin users
  H2b-05: Archive sets archived_at on RoundHistory
  H2b-06: Archived round is hidden from H1 by default
  H2b-07: Archived round is hidden from H2a by default
  H2b-08: H1 ?include_archived=1 shows archived round
  H2b-09: H2a ?include_archived=1 shows archived round
  H2b-10: Unarchive clears archived_at and restores visibility in H1 default view
  H2b-11: Unarchive clears archived_at and restores visibility in H2a default view
  H2b-12: Delete removes RoundHistory row
  H2b-13: Delete also removes associated RoundPlayerResult rows (cascade)
  H2b-14: Deleting one round does not affect other rounds in the same session
  H2b-15: Delete does not touch live GameSession or GameRound rows
  H2b-16: H1 still renders correctly with a mix of active and archived rounds
  H2b-17: H2a still renders correctly with a mix of active and archived rounds
  H2b-18: Archive does not mutate any historical values (immutability check)
  H2b-19: Unarchive after archive restores original history values unchanged
  H2b-20: H1 shows include_archived toggle link

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_h2b.py

Expected: all tests pass, final line "ALL H2b TESTS PASSED."
"""

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
    SECRET_KEY                     = 'h2b-test-secret'
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

_ADMIN_USER  = '__h2b_admin__'
_PLAYER_USER = '__h2b_player__'
_P1_USER     = '__h2b_p1__'
_P2_USER     = '__h2b_p2__'
_IDS = {}


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

        topic = Topic(name='__h2b_topic__')
        db.session.add(topic)
        db.session.flush()

        prob = Problem(topic_id=topic.id, title='H2bQ1',
                       prompt_text='2+2', answer_text='4', difficulty=1)
        db.session.add(prob)
        db.session.flush()

        pset = ProblemSet(name='__h2b_set__')
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
                         ended_at=None, archived=False):
    """Insert a RoundHistory + two RoundPlayerResult rows directly."""
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
            problem_set_name_snapshot='__h2b_set__',
            group_name_snapshot=None,
            session_label_snapshot=None,
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


# ════════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════════

def test_h2b_01_archive_auth_guard():
    """H2b-01: POST archive redirects unauthenticated user."""
    sid, _ = _make_session()
    rh_id = _insert_frozen_round(sid, _make_session()[1])
    # Make a separate round to archive
    sid2, rid2 = _make_session()
    rh_id2 = _insert_frozen_round(sid2, rid2)
    with flask_app.test_client() as c:
        resp = c.post(f'/admin/history/rounds/{rh_id2}/archive',
                      follow_redirects=False)
        check('H2b-01: archive unauthenticated → redirect (not 200)',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2b_02_archive_admin_guard():
    """H2b-02: POST archive redirects non-admin user."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _PLAYER_USER)
        resp = c.post(f'/admin/history/rounds/{rh_id}/archive',
                      follow_redirects=False)
        check('H2b-02: archive non-admin → redirect (not 200)',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2b_03_delete_auth_guard():
    """H2b-03: POST delete redirects unauthenticated user."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        resp = c.post(f'/admin/history/rounds/{rh_id}/delete',
                      follow_redirects=False)
        check('H2b-03: delete unauthenticated → redirect (not 200)',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2b_04_delete_admin_guard():
    """H2b-04: POST delete redirects non-admin user."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _PLAYER_USER)
        resp = c.post(f'/admin/history/rounds/{rh_id}/delete',
                      follow_redirects=False)
        check('H2b-04: delete non-admin → redirect (not 200)',
              resp.status_code in (302, 401, 403),
              f'got {resp.status_code}')


def test_h2b_05_archive_sets_archived_at():
    """H2b-05: Archive action sets archived_at on RoundHistory (was None)."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
    with flask_app.app_context():
        rh = db.session.get(RoundHistory, rh_id)
        check('H2b-05: archived_at is non-None after archive',
              rh is not None and rh.archived_at is not None,
              f'archived_at={rh.archived_at if rh else "None (row missing)"}')


def test_h2b_06_archived_hidden_from_h1_default():
    """H2b-06: Archived round is hidden from H1 by default."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
        resp = c.get(f'/admin/classic/{sid}/history')
        body = resp.data.decode('utf-8', errors='replace')
        check('H2b-06: H1 default view hides archived round (Round 1 absent)',
              resp.status_code == 200 and f'id="round-{rh_id}"' not in body,
              'archived round still visible in H1 default')


def test_h2b_07_archived_hidden_from_h2a_default():
    """H2b-07: Archived round is hidden from H2a by default."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
        resp = c.get('/admin/history/rounds')
        body = resp.data.decode('utf-8', errors='replace')
        # Should not link to this specific round's anchor
        check('H2b-07: H2a default view hides archived round (anchor absent)',
              resp.status_code == 200 and f'#round-{rh_id}' not in body,
              'archived round still visible in H2a default')


def test_h2b_08_include_archived_h1():
    """H2b-08: ?include_archived=1 shows archived round on H1."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
        resp = c.get(f'/admin/classic/{sid}/history?include_archived=1')
        body = resp.data.decode('utf-8', errors='replace')
        check('H2b-08: H1 ?include_archived=1 shows archived round',
              resp.status_code == 200 and f'id="round-{rh_id}"' in body,
              'archived round not found with include_archived=1')


def test_h2b_09_include_archived_h2a():
    """H2b-09: ?include_archived=1 shows archived round on H2a."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
        resp = c.get('/admin/history/rounds?include_archived=1')
        body = resp.data.decode('utf-8', errors='replace')
        check('H2b-09: H2a ?include_archived=1 shows archived round',
              resp.status_code == 200 and f'#round-{rh_id}' in body,
              'archived round not found with include_archived=1 on H2a')


def test_h2b_10_unarchive_restores_h1():
    """H2b-10: Unarchive clears archived_at and round reappears in H1 default."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
        c.post(f'/admin/history/rounds/{rh_id}/unarchive', follow_redirects=True)
        resp = c.get(f'/admin/classic/{sid}/history')
        body = resp.data.decode('utf-8', errors='replace')
        check('H2b-10: H1 default shows unarchived round again',
              resp.status_code == 200 and f'id="round-{rh_id}"' in body,
              'round not found after unarchive')
    with flask_app.app_context():
        rh = db.session.get(RoundHistory, rh_id)
        check('H2b-10b: archived_at is None after unarchive',
              rh is not None and rh.archived_at is None)


def test_h2b_11_unarchive_restores_h2a():
    """H2b-11: Unarchive restores round visibility in H2a default view."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
        c.post(f'/admin/history/rounds/{rh_id}/unarchive', follow_redirects=True)
        resp = c.get('/admin/history/rounds')
        body = resp.data.decode('utf-8', errors='replace')
        check('H2b-11: H2a default shows unarchived round again',
              resp.status_code == 200 and f'#round-{rh_id}' in body,
              'round anchor not found in H2a after unarchive')


def test_h2b_12_delete_removes_roundhistory():
    """H2b-12: Delete removes the RoundHistory row from the database."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.post(f'/admin/history/rounds/{rh_id}/delete',
                      follow_redirects=True)
        check('H2b-12: delete returns 200 (redirect followed)',
              resp.status_code == 200)
    with flask_app.app_context():
        rh = db.session.get(RoundHistory, rh_id)
        check('H2b-12b: RoundHistory row is gone after delete',
              rh is None,
              'RoundHistory row still present')


def test_h2b_13_delete_cascades_player_results():
    """H2b-13: Deleting a RoundHistory also removes its RoundPlayerResult rows."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.app_context():
        result_ids = [r.id for r in
                      RoundPlayerResult.query.filter_by(round_history_id=rh_id).all()]
    check('H2b-13 pre: result rows exist before delete',
          len(result_ids) > 0, f'found {len(result_ids)} rows')

    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/delete', follow_redirects=True)

    with flask_app.app_context():
        remaining = RoundPlayerResult.query.filter_by(round_history_id=rh_id).count()
        check('H2b-13: RoundPlayerResult rows gone after delete',
              remaining == 0,
              f'{remaining} result rows still present')


def test_h2b_14_delete_does_not_affect_other_rounds():
    """H2b-14: Deleting one round does not remove other rounds in the same session."""
    sid, rid = _make_session()
    rh_id_a = _insert_frozen_round(sid, rid, round_number=1)

    # Second round in same session — needs its own GameRound row
    with flask_app.app_context():
        gr2 = GameRound(session_id=sid, round_number=2,
                        started_at=datetime.now(timezone.utc))
        db.session.add(gr2)
        db.session.flush()
        cfg2 = ClassicRoundConfig(
            round_id=gr2.id, mine_reward=20,
            treasure_search_reward=5,
            attempts_per_problem=1, wrong_answer_penalty=0,
        )
        db.session.add(cfg2)
        db.session.commit()
        rid2 = gr2.id

    rh_id_b = _insert_frozen_round(sid, rid2, round_number=2)

    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id_a}/delete', follow_redirects=True)

    with flask_app.app_context():
        rh_b = db.session.get(RoundHistory, rh_id_b)
        check('H2b-14: other round not deleted after deleting round A',
              rh_b is not None,
              'round B was also deleted')


def test_h2b_15_delete_does_not_touch_live_tables():
    """H2b-15: Delete only removes frozen history rows; live session/round remain."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/delete', follow_redirects=True)
    with flask_app.app_context():
        gs = db.session.get(GameSession, sid)
        gr = db.session.get(GameRound, rid)
        check('H2b-15: GameSession row untouched after history delete',
              gs is not None, 'GameSession deleted')
        check('H2b-15b: GameRound row untouched after history delete',
              gr is not None, 'GameRound deleted')


def test_h2b_16_mixed_active_archived_h1():
    """H2b-16: H1 renders correctly with a mix of active and archived rounds."""
    sid, rid = _make_session()
    rh_active = _insert_frozen_round(sid, rid, round_number=1)

    with flask_app.app_context():
        gr2 = GameRound(session_id=sid, round_number=2,
                        started_at=datetime.now(timezone.utc))
        db.session.add(gr2)
        db.session.flush()
        cfg2 = ClassicRoundConfig(
            round_id=gr2.id, mine_reward=20,
            treasure_search_reward=5,
            attempts_per_problem=1, wrong_answer_penalty=0,
        )
        db.session.add(cfg2)
        db.session.commit()
        rid2 = gr2.id

    rh_archived = _insert_frozen_round(sid, rid2, round_number=2)

    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_archived}/archive', follow_redirects=True)
        # Default view: only active visible
        resp_default = c.get(f'/admin/classic/{sid}/history')
        body_default = resp_default.data.decode('utf-8', errors='replace')
        check('H2b-16: H1 default — active round visible',
              f'id="round-{rh_active}"' in body_default)
        check('H2b-16b: H1 default — archived round hidden',
              f'id="round-{rh_archived}"' not in body_default)
        # include_archived: both visible
        resp_all = c.get(f'/admin/classic/{sid}/history?include_archived=1')
        body_all = resp_all.data.decode('utf-8', errors='replace')
        check('H2b-16c: H1 include_archived — active round visible',
              f'id="round-{rh_active}"' in body_all)
        check('H2b-16d: H1 include_archived — archived round visible',
              f'id="round-{rh_archived}"' in body_all)


def test_h2b_17_mixed_active_archived_h2a():
    """H2b-17: H2a renders correctly with a mix of active and archived rounds."""
    sid, rid = _make_session()
    rh_active = _insert_frozen_round(sid, rid, round_number=1)

    with flask_app.app_context():
        gr2 = GameRound(session_id=sid, round_number=2,
                        started_at=datetime.now(timezone.utc))
        db.session.add(gr2)
        db.session.flush()
        cfg2 = ClassicRoundConfig(
            round_id=gr2.id, mine_reward=20,
            treasure_search_reward=5,
            attempts_per_problem=1, wrong_answer_penalty=0,
        )
        db.session.add(cfg2)
        db.session.commit()
        rid2 = gr2.id

    rh_archived = _insert_frozen_round(sid, rid2, round_number=2)

    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_archived}/archive', follow_redirects=True)
        resp_default = c.get('/admin/history/rounds')
        body_default = resp_default.data.decode('utf-8', errors='replace')
        check('H2b-17: H2a default — active round visible',
              f'#round-{rh_active}' in body_default)
        check('H2b-17b: H2a default — archived round hidden',
              f'#round-{rh_archived}' not in body_default)
        resp_all = c.get('/admin/history/rounds?include_archived=1')
        body_all = resp_all.data.decode('utf-8', errors='replace')
        check('H2b-17c: H2a include_archived — both rounds visible',
              f'#round-{rh_active}' in body_all and f'#round-{rh_archived}' in body_all)


def test_h2b_18_archive_does_not_mutate_values():
    """H2b-18: Archive sets only archived_at; all stored history values remain unchanged."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.app_context():
        before = db.session.get(RoundHistory, rh_id)
        orig_total_correct = before.total_correct
        orig_accuracy = before.overall_accuracy
        orig_player_count = before.player_count
        orig_ended_at = before.ended_at

    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)

    with flask_app.app_context():
        after = db.session.get(RoundHistory, rh_id)
        check('H2b-18: total_correct unchanged after archive',
              after.total_correct == orig_total_correct)
        check('H2b-18b: overall_accuracy unchanged after archive',
              after.overall_accuracy == orig_accuracy)
        check('H2b-18c: player_count unchanged after archive',
              after.player_count == orig_player_count)
        check('H2b-18d: ended_at unchanged after archive',
              after.ended_at == orig_ended_at)
        check('H2b-18e: archived_at now set (only archive-state changed)',
              after.archived_at is not None)


def test_h2b_19_unarchive_restores_original_values():
    """H2b-19: After archive+unarchive the original history values are unchanged."""
    sid, rid = _make_session()
    rh_id = _insert_frozen_round(sid, rid)
    with flask_app.app_context():
        orig = db.session.get(RoundHistory, rh_id)
        orig_correct = orig.total_correct
        orig_accuracy = orig.overall_accuracy

    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        c.post(f'/admin/history/rounds/{rh_id}/archive', follow_redirects=True)
        c.post(f'/admin/history/rounds/{rh_id}/unarchive', follow_redirects=True)

    with flask_app.app_context():
        after = db.session.get(RoundHistory, rh_id)
        check('H2b-19: archived_at is None after unarchive',
              after.archived_at is None)
        check('H2b-19b: total_correct unchanged after archive+unarchive cycle',
              after.total_correct == orig_correct)
        check('H2b-19c: overall_accuracy unchanged after archive+unarchive cycle',
              after.overall_accuracy == orig_accuracy)


def test_h2b_20_h1_toggle_link_present():
    """H2b-20: H1 default view contains the 'Show archived rounds' toggle link."""
    sid, rid = _make_session()
    _insert_frozen_round(sid, rid)
    with flask_app.test_client() as c:
        _login_as(c, _ADMIN_USER)
        resp = c.get(f'/admin/classic/{sid}/history')
        body = resp.data.decode('utf-8', errors='replace')
        check('H2b-20: H1 default view has include_archived toggle link',
              'include_archived' in body,
              'no include_archived toggle link found')


# ════════════════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('Setting up H2b test fixtures...')
    _setup()
    print('Running H2b tests...\n')

    test_h2b_01_archive_auth_guard()
    test_h2b_02_archive_admin_guard()
    test_h2b_03_delete_auth_guard()
    test_h2b_04_delete_admin_guard()
    test_h2b_05_archive_sets_archived_at()
    test_h2b_06_archived_hidden_from_h1_default()
    test_h2b_07_archived_hidden_from_h2a_default()
    test_h2b_08_include_archived_h1()
    test_h2b_09_include_archived_h2a()
    test_h2b_10_unarchive_restores_h1()
    test_h2b_11_unarchive_restores_h2a()
    test_h2b_12_delete_removes_roundhistory()
    test_h2b_13_delete_cascades_player_results()
    test_h2b_14_delete_does_not_affect_other_rounds()
    test_h2b_15_delete_does_not_touch_live_tables()
    test_h2b_16_mixed_active_archived_h1()
    test_h2b_17_mixed_active_archived_h2a()
    test_h2b_18_archive_does_not_mutate_values()
    test_h2b_19_unarchive_restores_original_values()
    test_h2b_20_h1_toggle_link_present()

    print(f'\n{"─"*50}')
    print(f'Results: {passed} passed, {failed} failed')
    if failed == 0:
        print('ALL H2b TESTS PASSED.')
    else:
        print(f'SOME H2b TESTS FAILED.')
        sys.exit(1)
