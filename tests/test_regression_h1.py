"""
test_regression_h1.py
=====================

Regression tests for H1 — Admin History UI.

Coverage:
  H1-01: /admin/classic/<id>/history redirects non-logged-in users (auth guard)
  H1-02: /admin/classic/<id>/history redirects non-admin users (admin guard)
  H1-03: History page renders 200 for an admin when frozen rounds exist
  H1-04: History page renders 200 and shows empty-state when no frozen rounds
  H1-05: History page returns 404 for a non-existent session
  H1-06: Rounds from a different session do NOT appear on our session's page
  H1-07: Multiple frozen rounds from the same session appear separately
  H1-08: Round summary fields from RoundHistory are present in the response
  H1-09: Per-player result rows from RoundPlayerResult are present
  H1-10: Ordering uses stored final_place (place 1 appears before place 2)
  H1-11: Manage page shows "View History" link only when history_count > 0
  H1-12: Manage page hides "View History" when history_count == 0
  H1-13: History page correctly shows group_name_snapshot when set
  H1-14: History page shows "Open session" when group_name_snapshot is None
  H1-15: session_label_snapshot rendered when present
  H1-16: History values do not change after a post-round wallet mutation
         (immutability regression)

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_h1.py

Expected: all tests pass, final line "ALL H1 TESTS PASSED."
"""

import os
import sys
from datetime import datetime, timezone

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
    SECRET_KEY                     = 'h1-test-secret'
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

_ADMIN_USER = '__h1_admin__'
_PLAYER_USER = '__h1_player__'
_P1_USER = '__h1_p1__'
_P2_USER = '__h1_p2__'
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

        topic = Topic(name='__h1_topic__')
        db.session.add(topic)
        db.session.flush()

        prob1 = Problem(topic_id=topic.id, title='H1Q1',
                        prompt_text='1+1', answer_text='2', difficulty=1)
        prob2 = Problem(topic_id=topic.id, title='H1Q2',
                        prompt_text='2+2', answer_text='4', difficulty=1)
        db.session.add_all([prob1, prob2])
        db.session.flush()

        pset = ProblemSet(name='__h1_set__')
        pset.problems.append(prob1)
        pset.problems.append(prob2)
        db.session.add(pset)
        db.session.commit()

        _IDS['admin_id']  = admin.id
        _IDS['player_id'] = player.id
        _IDS['p1_id']     = p1.id
        _IDS['p2_id']     = p2.id
        _IDS['pset_id']   = pset.id


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_session(label=None):
    """Create a bare GameSession + GameRound + config. Returns (session_id, round_id)."""
    with flask_app.app_context():
        gs = GameSession(mode='classic', status='active',
                         problem_set_id=_IDS['pset_id'], label=label)
        db.session.add(gs)
        db.session.flush()

        gr = GameRound(session_id=gs.id, round_number=1,
                       started_at=datetime.now(timezone.utc))
        db.session.add(gr)
        db.session.flush()

        cfg = ClassicRoundConfig(round_id=gr.id, mine_reward=20,
                                 treasure_search_reward=5, attempts_per_problem=1,
                                 wrong_answer_penalty=0)
        db.session.add(cfg)
        db.session.commit()
        return gs.id, gr.id


def _add_wallet(session_id, player_id, gold=0, gems=0):
    with flask_app.app_context():
        w = PlayerWallet(player_id=player_id, session_id=session_id, gold=gold, gems=gems)
        db.session.add(w)
        rp = RoundPlayer(session_id=session_id, player_id=player_id)
        db.session.add(rp)
        db.session.commit()


def _insert_frozen_round(session_id, round_id, round_number=1,
                         player_count=2,
                         total_answers=4, total_correct=3, total_incorrect=1,
                         overall_accuracy=0.75,
                         problem_set_name_snapshot='__h1_set__',
                         group_name_snapshot=None,
                         session_label_snapshot=None,
                         started_at=None):
    """Directly insert a RoundHistory + two RoundPlayerResult rows."""
    now = datetime.now(timezone.utc)
    with flask_app.app_context():
        rh = RoundHistory(
            round_id=round_id,
            session_id=session_id,
            mode_type='classic',
            round_number=round_number,
            started_at=started_at or now,
            ended_at=now,
            player_count=player_count,
            total_answers=total_answers,
            total_correct=total_correct,
            total_incorrect=total_incorrect,
            overall_accuracy=overall_accuracy,
            problem_set_name_snapshot=problem_set_name_snapshot,
            group_name_snapshot=group_name_snapshot,
            session_label_snapshot=session_label_snapshot,
        )
        db.session.add(rh)
        db.session.flush()

        rpr1 = RoundPlayerResult(
            round_history_id=rh.id,
            player_id=_IDS['p1_id'],
            player_name_snapshot=_P1_USER,
            final_gold=100,
            final_gems=3,
            final_place=1,
            total_answers=2,
            correct=2,
            incorrect=0,
            accuracy=1.0,
        )
        rpr2 = RoundPlayerResult(
            round_history_id=rh.id,
            player_id=_IDS['p2_id'],
            player_name_snapshot=_P2_USER,
            final_gold=40,
            final_gems=1,
            final_place=2,
            total_answers=2,
            correct=1,
            incorrect=1,
            accuracy=0.5,
        )
        db.session.add_all([rpr1, rpr2])
        db.session.commit()
        return rh.id


def _login_as(client, username):
    return client.post('/login',
                       data={'username': username, 'password': 'pass'},
                       follow_redirects=True)


def _end_round_via_http(client, session_id):
    return client.post(f'/admin/classic/{session_id}/end', follow_redirects=True)


# ════════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════════

def test_h1_01_auth_guard():
    """H1-01: Non-logged-in user is redirected away from history page."""
    session_id, _ = _make_session()
    with flask_app.test_client() as client:
        resp = client.get(f'/admin/classic/{session_id}/history')
    check('H1-01: unauthenticated → redirect (not 200)',
          resp.status_code in (302, 401),
          detail=f'got {resp.status_code}')


def test_h1_02_admin_guard():
    """H1-02: Non-admin user is refused access to history page."""
    session_id, _ = _make_session()
    with flask_app.test_client() as client:
        _login_as(client, _PLAYER_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')
    check('H1-02: non-admin → redirect or 403 (not 200)',
          resp.status_code in (302, 403),
          detail=f'got {resp.status_code}')


def test_h1_03_renders_with_history():
    """H1-03: History page returns 200 when frozen rounds exist."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=100)
    _add_wallet(session_id, _IDS['p2_id'], gold=40)
    _insert_frozen_round(session_id, round_id)
    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')
    check('H1-03: 200 when history exists',
          resp.status_code == 200,
          detail=f'got {resp.status_code}')


def test_h1_04_empty_state():
    """H1-04: History page returns 200 with empty-state message when no history."""
    session_id, _ = _make_session()
    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')
    html = resp.data.decode('utf-8', errors='replace')
    check('H1-04: 200 on empty history',
          resp.status_code == 200,
          detail=f'got {resp.status_code}')
    check('H1-04: empty-state message present',
          'No frozen round history' in html or 'no frozen' in html.lower(),
          detail='empty-state text not found')


def test_h1_05_nonexistent_session_404():
    """H1-05: 404 for a session that does not exist."""
    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get('/admin/classic/999999/history')
    check('H1-05: nonexistent session → 404',
          resp.status_code == 404,
          detail=f'got {resp.status_code}')


def test_h1_06_rounds_scoped_to_session():
    """H1-06: Rounds from a different session do NOT appear on our session's page."""
    # Create two sessions, each with one frozen round
    sid_a, rid_a = _make_session()
    sid_b, rid_b = _make_session()

    _insert_frozen_round(sid_a, rid_a, round_number=1,
                         problem_set_name_snapshot='SET_A_MARKER')
    _insert_frozen_round(sid_b, rid_b, round_number=1,
                         problem_set_name_snapshot='SET_B_MARKER')

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp_a = client.get(f'/admin/classic/{sid_a}/history')
        resp_b = client.get(f'/admin/classic/{sid_b}/history')

    html_a = resp_a.data.decode('utf-8', errors='replace')
    html_b = resp_b.data.decode('utf-8', errors='replace')

    check('H1-06: session A page contains SET_A_MARKER',
          'SET_A_MARKER' in html_a)
    check('H1-06: session A page does NOT contain SET_B_MARKER',
          'SET_B_MARKER' not in html_a)
    check('H1-06: session B page contains SET_B_MARKER',
          'SET_B_MARKER' in html_b)
    check('H1-06: session B page does NOT contain SET_A_MARKER',
          'SET_A_MARKER' not in html_b)


def test_h1_07_multiple_rounds_separate():
    """H1-07: Multiple frozen rounds appear separately on the history page."""
    # Use HTTP end_round to create two real frozen rounds
    session_id, round_id_1 = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    _add_wallet(session_id, _IDS['p2_id'], gold=30)

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)

        # End round 1 → creates first RoundHistory
        _end_round_via_http(client, session_id)

        # Start round 2
        client.post(f'/admin/classic/{session_id}/next_round',
                    data={'carry_over_gold': '1', 'carry_over_gems': '1'},
                    follow_redirects=True)

        # End round 2 → creates second RoundHistory
        _end_round_via_http(client, session_id)

        resp = client.get(f'/admin/classic/{session_id}/history')

    html = resp.data.decode('utf-8', errors='replace')

    check('H1-07: 200 for multi-round session',
          resp.status_code == 200,
          detail=f'got {resp.status_code}')
    check('H1-07: "Round 1" appears in page',
          'Round 1' in html)
    check('H1-07: "Round 2" appears in page',
          'Round 2' in html)

    with flask_app.app_context():
        count = RoundHistory.query.filter_by(session_id=session_id).count()
    check('H1-07: exactly 2 RoundHistory rows in DB',
          count == 2,
          detail=f'got {count}')


def test_h1_08_round_summary_fields():
    """H1-08: Round summary fields from RoundHistory are rendered in the response."""
    session_id, round_id = _make_session()
    _insert_frozen_round(session_id, round_id,
                         player_count=2,
                         total_answers=6,
                         total_correct=4,
                         total_incorrect=2,
                         overall_accuracy=0.667,
                         problem_set_name_snapshot='__h1_set__')

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')

    html = resp.data.decode('utf-8', errors='replace')

    check('H1-08: player_count rendered', '2' in html)
    check('H1-08: total_answers rendered', '6' in html)
    check('H1-08: total_correct rendered', '4' in html)
    check('H1-08: total_incorrect rendered', '2' in html)
    check('H1-08: problem_set_name_snapshot rendered', '__h1_set__' in html)
    check('H1-08: accuracy percentage rendered',
          '66.7%' in html or '66.6%' in html or '66.8%' in html)


def test_h1_09_player_result_rows():
    """H1-09: Per-player result rows from RoundPlayerResult are present."""
    session_id, round_id = _make_session()
    _insert_frozen_round(session_id, round_id)

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')

    html = resp.data.decode('utf-8', errors='replace')

    check('H1-09: p1 name snapshot present', _P1_USER in html)
    check('H1-09: p2 name snapshot present', _P2_USER in html)
    check('H1-09: p1 final_gold (100) present', '100' in html)
    check('H1-09: p2 final_gold (40) present', '40' in html)


def test_h1_10_ordering_by_place():
    """H1-10: Place 1 player appears before place 2 in the rendered page."""
    session_id, round_id = _make_session()
    _insert_frozen_round(session_id, round_id)  # p1→place1, p2→place2

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')

    html = resp.data.decode('utf-8', errors='replace')
    pos_p1 = html.find(_P1_USER)
    pos_p2 = html.find(_P2_USER)

    check('H1-10: both players found in page', pos_p1 >= 0 and pos_p2 >= 0)
    check('H1-10: place-1 player (__h1_p1__) appears before place-2 (__h1_p2__)',
          pos_p1 < pos_p2,
          detail=f'pos_p1={pos_p1} pos_p2={pos_p2}')


def test_h1_11_manage_shows_view_history_link():
    """H1-11: Manage page shows "View History" when history_count > 0."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=80)

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        _end_round_via_http(client, session_id)
        resp = client.get(f'/admin/classic/{session_id}/manage')

    html = resp.data.decode('utf-8', errors='replace')
    check('H1-11: "View History" link is visible after round end',
          'View History' in html or 'history' in html.lower(),
          detail='"View History" not found in manage page')
    check('H1-11: history URL is in manage page',
          f'/admin/classic/{session_id}/history' in html)


def test_h1_12_manage_hides_view_history_link():
    """H1-12: Manage page does NOT show "View History" when no history exists."""
    session_id, _ = _make_session()  # no round ended → no history

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/manage')

    html = resp.data.decode('utf-8', errors='replace')
    check('H1-12: history URL absent from manage page when no history',
          f'/admin/classic/{session_id}/history' not in html)


def test_h1_13_group_name_snapshot():
    """H1-13: group_name_snapshot is rendered when set."""
    session_id, round_id = _make_session()
    _insert_frozen_round(session_id, round_id, group_name_snapshot='Alpha Group')

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')

    html = resp.data.decode('utf-8', errors='replace')
    check('H1-13: group_name_snapshot "Alpha Group" rendered',
          'Alpha Group' in html)


def test_h1_14_open_session_indicator():
    """H1-14: "Open session" indicator shown when group_name_snapshot is None."""
    session_id, round_id = _make_session()
    _insert_frozen_round(session_id, round_id, group_name_snapshot=None)

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')

    html = resp.data.decode('utf-8', errors='replace')
    check('H1-14: "Open session" indicator rendered',
          'Open session' in html or 'open session' in html.lower())


def test_h1_15_session_label_snapshot():
    """H1-15: session_label_snapshot is rendered when present."""
    session_id, round_id = _make_session(label='Test Label Q4')
    _insert_frozen_round(session_id, round_id,
                         session_label_snapshot='Test Label Q4')

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        resp = client.get(f'/admin/classic/{session_id}/history')

    html = resp.data.decode('utf-8', errors='replace')
    check('H1-15: session_label_snapshot rendered',
          'Test Label Q4' in html)


def test_h1_16_history_immutable_after_wallet_mutation():
    """H1-16: Mutating a wallet after round end does not change frozen history."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=200)

    with flask_app.test_client() as client:
        _login_as(client, _ADMIN_USER)
        _end_round_via_http(client, session_id)

    # Mutate wallet gold directly after round end
    with flask_app.app_context():
        wallet = PlayerWallet.query.filter_by(
            session_id=session_id, player_id=_IDS['p1_id']
        ).first()
        if wallet:
            wallet.gold = 1  # post-round mutation
            db.session.commit()

    # Frozen result should still show 200
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(session_id=session_id).first()
        rpr = RoundPlayerResult.query.filter_by(
            round_history_id=rh.id, player_id=_IDS['p1_id']
        ).first() if rh else None

    check('H1-16: frozen final_gold still 200 after wallet mutation',
          rpr is not None and rpr.final_gold == 200,
          detail=f'got {rpr.final_gold if rpr else None}')


# ════════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════════

ALL_TESTS = [
    ('H1-01', test_h1_01_auth_guard),
    ('H1-02', test_h1_02_admin_guard),
    ('H1-03', test_h1_03_renders_with_history),
    ('H1-04', test_h1_04_empty_state),
    ('H1-05', test_h1_05_nonexistent_session_404),
    ('H1-06', test_h1_06_rounds_scoped_to_session),
    ('H1-07', test_h1_07_multiple_rounds_separate),
    ('H1-08', test_h1_08_round_summary_fields),
    ('H1-09', test_h1_09_player_result_rows),
    ('H1-10', test_h1_10_ordering_by_place),
    ('H1-11', test_h1_11_manage_shows_view_history_link),
    ('H1-12', test_h1_12_manage_hides_view_history_link),
    ('H1-13', test_h1_13_group_name_snapshot),
    ('H1-14', test_h1_14_open_session_indicator),
    ('H1-15', test_h1_15_session_label_snapshot),
    ('H1-16', test_h1_16_history_immutable_after_wallet_mutation),
]


if __name__ == '__main__':
    print('=== H1 Admin History UI regression tests ===\n')
    _setup()
    for label, fn in ALL_TESTS:
        print(f'--- {label} ---')
        fn()
    print(f'\n  passed={passed}  failed={failed}')
    if failed:
        print(f'\n  FAILED — {failed} test(s) did not pass.')
        sys.exit(1)
    else:
        print('\nALL H1 TESTS PASSED.')
