"""
test_regression_multi_round.py
===============================

Regression tests for multi-round session support and carry-over controls.

Coverage:
  MR01: Starting next round with carry_over_gold=True keeps player gold
  MR02: Starting next round with carry_over_gold=False resets player gold to 0
  MR03: Starting next round with carry_over_gems=True keeps player gems
  MR04: Starting next round with carry_over_gems=False resets player gems to 0
  MR05: Gold and gems can be reset independently
  MR06: Multiple rounds can run within one session (round numbers increment)
  MR07: Player roster (RoundPlayer) persists across rounds
  MR08: PlayerProblemState resets for new round (new round_id = fresh state)
  MR09: No stale PlayerProblemState from round 1 leaks into round 2
  MR10: Round config is copied from previous round to next round
  MR11: end_round sets session.status='waiting' (not 'finished')
  MR12: end_session sets session.status='finished' and session.ended_at
  MR13: next_round only works when session.status='waiting'
  MR14: next_round creates a new ClassicRoundConfig row (not shared with prev)
  MR15: Three rounds can run in the same session (full lifecycle)
  Regression:
  MR_R1: test_regression_8_9 still green
  MR_R2: test_regression_g2c still green

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_multi_round.py

Expected: all tests pass, final line "ALL MULTI-ROUND TESTS PASSED."
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import ClassicRoundConfig, PlayerWallet, PlayerProblemState


# ── Test config ────────────────────────────────────────────────────────────────

class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'mr-test-secret'
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


# ── Fixture helpers ────────────────────────────────────────────────────────────

_ADMIN_USER = '__mr_admin__'
_P1_USER    = '__mr_player1__'
_P2_USER    = '__mr_player2__'
_SET_NAME   = '__mr_set__'
_IDS = {}


def _setup():
    with flask_app.app_context():
        db.create_all()

        admin = Player(username=_ADMIN_USER, is_admin=True)
        admin.set_password('pass')
        p1 = Player(username=_P1_USER, is_admin=False)
        p1.set_password('pass')
        p2 = Player(username=_P2_USER, is_admin=False)
        p2.set_password('pass')
        db.session.add_all([admin, p1, p2])
        db.session.flush()

        topic = Topic(name='__mr_topic__')
        db.session.add(topic)
        db.session.flush()

        prob1 = Problem(topic_id=topic.id, title='MR-Q1', prompt_text='1+1', answer_text='2', difficulty=1)
        prob2 = Problem(topic_id=topic.id, title='MR-Q2', prompt_text='2+2', answer_text='4', difficulty=1)
        db.session.add_all([prob1, prob2])
        db.session.flush()

        pset = ProblemSet(name=_SET_NAME)
        pset.problems.append(prob1)
        pset.problems.append(prob2)
        db.session.add(pset)
        db.session.commit()

        _IDS['admin_id'] = admin.id
        _IDS['p1_id']    = p1.id
        _IDS['p2_id']    = p2.id
        _IDS['pset_id']  = pset.id
        _IDS['prob1_id'] = prob1.id
        _IDS['prob2_id'] = prob2.id


def _make_session_with_round():
    """Create a GameSession + GameRound + ClassicRoundConfig. Returns (session_id, round_id)."""
    with flask_app.app_context():
        gs = GameSession(mode='classic', status='waiting', problem_set_id=_IDS['pset_id'])
        db.session.add(gs)
        db.session.flush()

        gr = GameRound(session_id=gs.id, round_number=1, started_at=None)
        db.session.add(gr)
        db.session.flush()

        cfg = ClassicRoundConfig(
            round_id=gr.id,
            mine_reward=20,
            treasure_search_reward=5,
            attempts_per_problem=1,
            wrong_answer_penalty=0,
        )
        db.session.add(cfg)
        db.session.commit()
        return gs.id, gr.id


def _login(client):
    return client.post('/login', data={'username': _ADMIN_USER, 'password': 'pass'},
                       follow_redirects=True)


def _start_round(client, session_id):
    return client.post(f'/admin/classic/{session_id}/start', follow_redirects=True)


def _end_round(client, session_id):
    return client.post(f'/admin/classic/{session_id}/end', follow_redirects=True)


def _end_session(client, session_id):
    return client.post(f'/admin/classic/{session_id}/end_session', follow_redirects=True)


def _next_round(client, session_id, carry_gold=True, carry_gems=True):
    data = {}
    if carry_gold:
        data['carry_over_gold'] = '1'
    if carry_gems:
        data['carry_over_gems'] = '1'
    return client.post(f'/admin/classic/{session_id}/next_round', data=data, follow_redirects=True)


def _enroll(session_id, player_id):
    with flask_app.app_context():
        rp = RoundPlayer(session_id=session_id, player_id=player_id)
        db.session.add(rp)
        db.session.commit()


def _set_wallet(session_id, player_id, gold, gems):
    with flask_app.app_context():
        wallet = PlayerWallet.query.filter_by(
            session_id=session_id, player_id=player_id
        ).first()
        if not wallet:
            wallet = PlayerWallet(session_id=session_id, player_id=player_id, gold=gold, gems=gems)
            db.session.add(wallet)
        else:
            wallet.gold = gold
            wallet.gems = gems
        db.session.commit()


def _get_wallet(session_id, player_id):
    with flask_app.app_context():
        w = PlayerWallet.query.filter_by(
            session_id=session_id, player_id=player_id
        ).first()
        return (w.gold, w.gems) if w else (None, None)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_carry_over_gold_true():
    """MR01: carry_over_gold=True → player gold is preserved."""
    sid, _ = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])
    _set_wallet(sid, _IDS['p1_id'], gold=100, gems=5)

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _next_round(client, sid, carry_gold=True, carry_gems=True)

    gold, gems = _get_wallet(sid, _IDS['p1_id'])
    check('MR01: carry_over_gold=True keeps gold', gold == 100, f'gold={gold}')


def test_carry_over_gold_false():
    """MR02: carry_over_gold=False → player gold reset to 0."""
    sid, _ = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])
    _set_wallet(sid, _IDS['p1_id'], gold=150, gems=7)

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _next_round(client, sid, carry_gold=False, carry_gems=True)

    gold, gems = _get_wallet(sid, _IDS['p1_id'])
    check('MR02: carry_over_gold=False resets gold to 0', gold == 0, f'gold={gold}')
    check('MR02: carry_over_gold=False leaves gems intact', gems == 7, f'gems={gems}')


def test_carry_over_gems_true():
    """MR03: carry_over_gems=True → gems preserved."""
    sid, _ = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])
    _set_wallet(sid, _IDS['p1_id'], gold=50, gems=12)

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _next_round(client, sid, carry_gold=True, carry_gems=True)

    _, gems = _get_wallet(sid, _IDS['p1_id'])
    check('MR03: carry_over_gems=True keeps gems', gems == 12, f'gems={gems}')


def test_carry_over_gems_false():
    """MR04: carry_over_gems=False → gems reset to 0."""
    sid, _ = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])
    _set_wallet(sid, _IDS['p1_id'], gold=50, gems=12)

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _next_round(client, sid, carry_gold=True, carry_gems=False)

    gold, gems = _get_wallet(sid, _IDS['p1_id'])
    check('MR04: carry_over_gems=False resets gems to 0', gems == 0, f'gems={gems}')
    check('MR04: carry_over_gems=False leaves gold intact', gold == 50, f'gold={gold}')


def test_independent_reset():
    """MR05: gold and gems can be reset independently — reset both at once."""
    sid, _ = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])
    _set_wallet(sid, _IDS['p1_id'], gold=200, gems=20)

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _next_round(client, sid, carry_gold=False, carry_gems=False)

    gold, gems = _get_wallet(sid, _IDS['p1_id'])
    check('MR05: reset both — gold = 0', gold == 0, f'gold={gold}')
    check('MR05: reset both — gems = 0', gems == 0, f'gems={gems}')


def test_multiple_rounds_increment():
    """MR06: round numbers increment correctly across multiple rounds."""
    sid, _ = _make_session_with_round()

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _next_round(client, sid)   # starts round 2
        _end_round(client, sid)
        _next_round(client, sid)   # starts round 3

    with flask_app.app_context():
        rounds = GameRound.query.filter_by(session_id=sid).order_by(GameRound.round_number).all()
        check('MR06: three rounds created', len(rounds) == 3, f'found {len(rounds)}')
        check('MR06: round numbers are 1, 2, 3',
              [r.round_number for r in rounds] == [1, 2, 3],
              str([r.round_number for r in rounds]))


def test_player_roster_persists():
    """MR07: RoundPlayer rows persist across rounds (same session)."""
    sid, _ = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])
    _enroll(sid, _IDS['p2_id'])

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _next_round(client, sid)

    with flask_app.app_context():
        enrolled = RoundPlayer.query.filter_by(session_id=sid).all()
        pids = {rp.player_id for rp in enrolled}
        check('MR07: both players still enrolled after round change',
              _IDS['p1_id'] in pids and _IDS['p2_id'] in pids,
              f'enrolled={pids}')


def test_problem_progress_resets_for_new_round():
    """MR08: PlayerProblemState is keyed by round_id — new round = fresh state."""
    sid, round1_id = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])

    # Manually create a "solved" PlayerProblemState for round 1
    with flask_app.app_context():
        pps = PlayerProblemState(
            player_id=_IDS['p1_id'],
            round_id=round1_id,
            problem_id=_IDS['prob1_id'],
            is_solved=True,
            is_closed=True,
        )
        db.session.add(pps)
        db.session.commit()

    with flask_app.test_client() as client:
        _login(client)
        # Manually set started_at (start_round needs active session)
        with flask_app.app_context():
            gr = db.session.get(GameRound, round1_id)
            gr.started_at = datetime.now(timezone.utc)
            gs = db.session.get(GameSession, sid)
            gs.status = 'active'
            db.session.commit()
        _end_round(client, sid)
        _next_round(client, sid)

    with flask_app.app_context():
        rounds = GameRound.query.filter_by(session_id=sid).order_by(GameRound.round_number).all()
        check('MR08: two rounds exist after next_round', len(rounds) == 2, f'{len(rounds)}')
        round2_id = rounds[1].id
        # No PlayerProblemState for round 2 yet (created lazily on client join)
        r2_pps = PlayerProblemState.query.filter_by(
            player_id=_IDS['p1_id'], round_id=round2_id
        ).count()
        check('MR08: no carry-over problem state in round 2', r2_pps == 0, f'count={r2_pps}')

        # Round 1 state still exists, not deleted
        r1_pps = PlayerProblemState.query.filter_by(
            player_id=_IDS['p1_id'], round_id=round1_id, is_solved=True
        ).count()
        check('MR08: round 1 problem state still intact', r1_pps == 1, f'count={r1_pps}')


def test_no_stale_problem_state_leak():
    """MR09: round-1 PlayerProblemState is NOT accessible via the round-2 round_id."""
    sid, round1_id = _make_session_with_round()

    with flask_app.app_context():
        pps = PlayerProblemState(
            player_id=_IDS['p1_id'],
            round_id=round1_id,
            problem_id=_IDS['prob1_id'],
            is_solved=True,
            is_closed=True,
        )
        db.session.add(pps)
        gs = db.session.get(GameSession, sid)
        gr = db.session.get(GameRound, round1_id)
        gr.started_at = datetime.now(timezone.utc)
        gs.status = 'active'
        db.session.commit()

    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, sid)
        _next_round(client, sid)

    with flask_app.app_context():
        rounds = GameRound.query.filter_by(session_id=sid).order_by(GameRound.round_number).all()
        round2_id = rounds[1].id
        # The solved state from round 1 must NOT appear under round 2's id
        r2_solved = PlayerProblemState.query.filter_by(
            player_id=_IDS['p1_id'],
            round_id=round2_id,
            is_solved=True,
        ).count()
        check('MR09: no solved problem state leaks to round 2', r2_solved == 0, f'{r2_solved}')


def test_config_copied_to_next_round():
    """MR10: ClassicRoundConfig is copied from previous round to next round."""
    sid, _ = _make_session_with_round()

    with flask_app.app_context():
        gr = GameRound.query.filter_by(session_id=sid).first()
        gr.started_at = datetime.now(timezone.utc)
        gs = db.session.get(GameSession, sid)
        gs.status = 'active'
        db.session.commit()

    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, sid)
        _next_round(client, sid)

    with flask_app.app_context():
        rounds = GameRound.query.filter_by(session_id=sid).order_by(GameRound.round_number).all()
        r1_cfg = rounds[0].classic_config
        r2_cfg = rounds[1].classic_config
        check('MR10: round 2 has a config', r2_cfg is not None)
        check('MR10: config is a separate row', r1_cfg.id != r2_cfg.id,
              f'r1={r1_cfg.id} r2={r2_cfg.id}')
        check('MR10: mine_reward copied', r2_cfg.mine_reward == r1_cfg.mine_reward,
              f'{r2_cfg.mine_reward}')
        check('MR10: steal_percent copied', r2_cfg.steal_percent == r1_cfg.steal_percent)


def test_end_round_sets_waiting():
    """MR11: end_round transitions session to 'waiting', not 'finished'."""
    sid, _ = _make_session_with_round()

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)

    with flask_app.app_context():
        gs = db.session.get(GameSession, sid)
        check('MR11: session.status == waiting after end_round',
              gs.status == 'waiting', f'status={gs.status}')
        check('MR11: session.ended_at is None after end_round',
              gs.ended_at is None, f'ended_at={gs.ended_at}')


def test_end_session_sets_finished():
    """MR12: end_session transitions session to 'finished' and sets ended_at."""
    sid, _ = _make_session_with_round()

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        _end_round(client, sid)
        _end_session(client, sid)

    with flask_app.app_context():
        gs = db.session.get(GameSession, sid)
        check('MR12: status == finished after end_session',
              gs.status == 'finished', f'status={gs.status}')
        check('MR12: ended_at set after end_session',
              gs.ended_at is not None, f'ended_at={gs.ended_at}')


def test_next_round_requires_waiting_status():
    """MR13: next_round is rejected if session is not in 'waiting' state."""
    sid, _ = _make_session_with_round()

    with flask_app.test_client() as client:
        _login(client)
        _start_round(client, sid)
        # Don't call end_round — session is still 'active'
        r = _next_round(client, sid)
        # Should redirect back to manage page (no crash, just flash error)
        check('MR13: next_round on active session returns 200 (redirected)',
              r.status_code == 200, f'status={r.status_code}')

    with flask_app.app_context():
        rounds = GameRound.query.filter_by(session_id=sid).count()
        check('MR13: no extra round created', rounds == 1, f'rounds={rounds}')


def test_new_config_row_not_shared():
    """MR14: next_round creates a NEW ClassicRoundConfig — not reusing round 1's row."""
    sid, _ = _make_session_with_round()

    with flask_app.app_context():
        gr = GameRound.query.filter_by(session_id=sid).first()
        gr.started_at = datetime.now(timezone.utc)
        db.session.get(GameSession, sid).status = 'active'
        db.session.commit()

    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, sid)
        _next_round(client, sid)

    with flask_app.app_context():
        cfg_count = ClassicRoundConfig.query.join(
            GameRound, ClassicRoundConfig.round_id == GameRound.id
        ).filter(GameRound.session_id == sid).count()
        check('MR14: two separate ClassicRoundConfig rows', cfg_count == 2, f'count={cfg_count}')


def test_three_round_lifecycle():
    """MR15: Three rounds can complete in the same session (full lifecycle)."""
    sid, _ = _make_session_with_round()
    _enroll(sid, _IDS['p1_id'])
    _set_wallet(sid, _IDS['p1_id'], gold=10, gems=2)

    with flask_app.test_client() as client:
        _login(client)

        # Round 1
        _start_round(client, sid)
        _set_wallet(sid, _IDS['p1_id'], gold=50, gems=5)  # simulate earning
        _end_round(client, sid)

        # Round 2: reset gold, keep gems
        _next_round(client, sid, carry_gold=False, carry_gems=True)
        gold, gems = _get_wallet(sid, _IDS['p1_id'])
        check('MR15: Round 2 start — gold reset', gold == 0, f'gold={gold}')
        check('MR15: Round 2 start — gems kept', gems == 5, f'gems={gems}')

        _set_wallet(sid, _IDS['p1_id'], gold=80, gems=8)  # simulate round 2 earning
        _end_round(client, sid)

        # Round 3: keep both
        _next_round(client, sid, carry_gold=True, carry_gems=True)
        gold, gems = _get_wallet(sid, _IDS['p1_id'])
        check('MR15: Round 3 start — gold kept', gold == 80, f'gold={gold}')
        check('MR15: Round 3 start — gems kept', gems == 8, f'gems={gems}')

        _end_round(client, sid)
        _end_session(client, sid)

    with flask_app.app_context():
        gs = db.session.get(GameSession, sid)
        rounds = GameRound.query.filter_by(session_id=sid).all()
        check('MR15: session finished', gs.status == 'finished', f'status={gs.status}')
        check('MR15: three rounds total', len(rounds) == 3, f'rounds={len(rounds)}')
        check('MR15: all rounds have ended_at', all(r.ended_at for r in rounds),
              str([(r.round_number, r.ended_at) for r in rounds]))


# ── Prior regression suites ────────────────────────────────────────────────────

def run_sub(script_name):
    script = os.path.join(os.path.dirname(__file__), script_name)
    result = subprocess.run([sys.executable, script], capture_output=True, text=True)
    lines = (result.stdout + result.stderr).strip().splitlines()
    last = lines[-1] if lines else ''
    ok = result.returncode == 0 and 'PASSED' in last
    check(f'{script_name} still green', ok,
          f'rc={result.returncode} last={last!r}')


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=== Multi-round session regression tests ===')
    _setup()

    test_carry_over_gold_true()
    test_carry_over_gold_false()
    test_carry_over_gems_true()
    test_carry_over_gems_false()
    test_independent_reset()
    test_multiple_rounds_increment()
    test_player_roster_persists()
    test_problem_progress_resets_for_new_round()
    test_no_stale_problem_state_leak()
    test_config_copied_to_next_round()
    test_end_round_sets_waiting()
    test_end_session_sets_finished()
    test_next_round_requires_waiting_status()
    test_new_config_row_not_shared()
    test_three_round_lifecycle()

    print()
    print('=== Prior regression suites ===')
    run_sub('test_regression_8_9.py')
    run_sub('test_regression_g2c.py')

    print()
    print(f'Results: {passed} passed, {failed} failed.')
    if failed == 0:
        print('ALL MULTI-ROUND TESTS PASSED.')
    else:
        print(f'FAILED: {failed} test(s) did not pass.')
        sys.exit(1)
