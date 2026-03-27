"""
test_regression_history.py
===========================

Regression tests for round-history persistence (Step H0).

Coverage:
  H01: Ending a Classic round creates exactly one RoundHistory record
  H02: RoundHistory.round_id matches the ended round
  H03: RoundHistory.mode_type is 'classic'
  H04: RoundHistory.round_number matches GameRound.round_number
  H05: RoundHistory.player_count equals the number of enrolled players with wallets
  H06: Ending a round creates one RoundPlayerResult per player
  H07: RoundPlayerResult.final_gold is frozen at round-end gold (not later reset value)
  H08: RoundPlayerResult.final_gems is frozen at round-end gems
  H09: RoundPlayerResult.final_place reflects leaderboard order (highest gold = place 1)
  H10: Tied gold → same final_place (competition ranking)
  H11: RoundPlayerResult.total_answers matches sum of PlayerProblemState.attempts_used
  H12: RoundPlayerResult.correct matches count of is_solved=True rows
  H13: RoundPlayerResult.incorrect = total_answers - correct
  H14: RoundPlayerResult.accuracy = correct / total_answers (0 if no answers)
  H15: RoundHistory.total_answers aggregates across all players
  H16: RoundHistory.total_correct aggregates across all players
  H17: RoundHistory.total_incorrect = total_answers - total_correct
  H18: RoundHistory.overall_accuracy = total_correct / total_answers
  H19: Multi-round session creates separate RoundHistory rows (one per round)
  H20: Later carry-over gold reset (next_round, carry_over_gold=False) does NOT
       change the previous round's frozen final_gold
  H21: Later carry-over gems reset does NOT change the previous round's frozen final_gems
  H22: Store purchase (wallet gold deduction) after round end does NOT change history
  H23: Duplicate end_round call does NOT create duplicate RoundHistory rows
  H24: RoundHistory.ended_at is set on the snapshot
  H25: RoundHistory with no players has player_count=0, totals=0
  H26: RoundPlayerResult.player_name_snapshot captures username at round end
  H27: problem_set_name_snapshot is stored when session has a problem set
  H28: group_name_snapshot is None for open (no-group) sessions
  Regression:
  H_R1: test_regression_multi_round still green
  H_R2: test_classic_step_e still green

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_history.py

Expected: all tests pass, final line "ALL HISTORY TESTS PASSED."
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from app import create_app
from app.extensions import db
from app.models.player   import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game     import GameSession, GameRound, RoundPlayer
from app.models.classic  import ClassicRoundConfig, PlayerWallet, PlayerProblemState
from app.models.history  import RoundHistory, RoundPlayerResult


# ── Test config ────────────────────────────────────────────────────────────────

class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'history-test-secret'
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

_ADMIN_USER = '__hist_admin__'
_P1_USER    = '__hist_p1__'
_P2_USER    = '__hist_p2__'
_P3_USER    = '__hist_p3__'
_SET_NAME   = '__hist_set__'
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
        p3 = Player(username=_P3_USER, is_admin=False)
        p3.set_password('pass')
        db.session.add_all([admin, p1, p2, p3])
        db.session.flush()

        topic = Topic(name='__hist_topic__')
        db.session.add(topic)
        db.session.flush()

        prob1 = Problem(topic_id=topic.id, title='HQ1', prompt_text='1+1', answer_text='2', difficulty=1)
        prob2 = Problem(topic_id=topic.id, title='HQ2', prompt_text='2+2', answer_text='4', difficulty=1)
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
        _IDS['p3_id']    = p3.id
        _IDS['pset_id']  = pset.id
        _IDS['prob1_id'] = prob1.id
        _IDS['prob2_id'] = prob2.id


def _make_session(started=True):
    """Create GameSession + GameRound + ClassicRoundConfig. Returns (session_id, round_id)."""
    with flask_app.app_context():
        gs = GameSession(mode='classic', status='active' if started else 'waiting',
                         problem_set_id=_IDS['pset_id'])
        db.session.add(gs)
        db.session.flush()

        now = datetime.now(timezone.utc)
        gr = GameRound(session_id=gs.id, round_number=1,
                       started_at=now if started else None)
        db.session.add(gr)
        db.session.flush()

        cfg = ClassicRoundConfig(round_id=gr.id, mine_reward=20, treasure_search_reward=5,
                                 attempts_per_problem=1, wrong_answer_penalty=0)
        db.session.add(cfg)
        db.session.commit()
        return gs.id, gr.id


def _add_wallet(session_id, player_id, gold=0, gems=0):
    with flask_app.app_context():
        w = PlayerWallet(player_id=player_id, session_id=session_id, gold=gold, gems=gems)
        db.session.add(w)
        # Enroll too
        rp = RoundPlayer(session_id=session_id, player_id=player_id)
        db.session.add(rp)
        db.session.commit()


def _add_pps(player_id, round_id, problem_id, attempts_used=1, is_solved=True):
    """Add a PlayerProblemState row (answer history for this player/round/problem)."""
    with flask_app.app_context():
        pps = PlayerProblemState(
            player_id=player_id, round_id=round_id, problem_id=problem_id,
            attempts_used=attempts_used, is_solved=is_solved,
            is_closed=True,
        )
        db.session.add(pps)
        db.session.commit()


def _login(client):
    return client.post('/login',
                       data={'username': _ADMIN_USER, 'password': 'pass'},
                       follow_redirects=True)


def _end_round(client, session_id):
    return client.post(f'/admin/classic/{session_id}/end', follow_redirects=True)


def _next_round(client, session_id, carry_gold=True, carry_gems=True):
    data = {}
    if carry_gold:
        data['carry_over_gold'] = '1'
    if carry_gems:
        data['carry_over_gems'] = '1'
    return client.post(f'/admin/classic/{session_id}/next_round',
                       data=data, follow_redirects=True)


# ── Test functions ─────────────────────────────────────────────────────────────

def test_h01_end_round_creates_one_history():
    """H01: Ending a Classic round creates exactly one RoundHistory record."""
    session_id, round_id = _make_session()
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rows = RoundHistory.query.filter_by(round_id=round_id).all()
        check('H01 exactly one RoundHistory created', len(rows) == 1, f'got {len(rows)}')


def test_h02_history_round_id_matches():
    """H02: RoundHistory.round_id matches the ended round."""
    session_id, round_id = _make_session()
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H02 history.round_id matches ended round', rh is not None and rh.round_id == round_id)


def test_h03_mode_type_is_classic():
    """H03: RoundHistory.mode_type is 'classic'."""
    session_id, round_id = _make_session()
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H03 mode_type is classic', rh is not None and rh.mode_type == 'classic')


def test_h04_round_number_correct():
    """H04: RoundHistory.round_number matches GameRound.round_number."""
    session_id, round_id = _make_session()
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        gr = db.session.get(GameRound, round_id)
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H04 round_number matches', rh is not None and rh.round_number == gr.round_number,
              f'history={rh.round_number if rh else None} gr={gr.round_number}')


def test_h05_player_count():
    """H05: RoundHistory.player_count equals the number of enrolled players with wallets."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=100)
    _add_wallet(session_id, _IDS['p2_id'], gold=50)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H05 player_count == 2', rh is not None and rh.player_count == 2,
              f'got {rh.player_count if rh else None}')


def test_h06_one_player_result_per_player():
    """H06: Ending a round creates one RoundPlayerResult per enrolled player."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=80)
    _add_wallet(session_id, _IDS['p2_id'], gold=40)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        results = RoundPlayerResult.query.filter_by(round_history_id=rh.id).all()
        check('H06 two player results created', len(results) == 2, f'got {len(results)}')


def test_h07_final_gold_frozen():
    """H07: RoundPlayerResult.final_gold is frozen at round-end gold."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=120)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H07 final_gold frozen at 120', rpr is not None and rpr.final_gold == 120,
              f'got {rpr.final_gold if rpr else None}')


def test_h08_final_gems_frozen():
    """H08: RoundPlayerResult.final_gems is frozen at round-end gems."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50, gems=7)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H08 final_gems frozen at 7', rpr is not None and rpr.final_gems == 7,
              f'got {rpr.final_gems if rpr else None}')


def test_h09_final_place_order():
    """H09: final_place reflects leaderboard order (highest gold = place 1)."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=200)   # should be place 1
    _add_wallet(session_id, _IDS['p2_id'], gold=100)   # should be place 2
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh   = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr1 = RoundPlayerResult.query.filter_by(
                 round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        rpr2 = RoundPlayerResult.query.filter_by(
                 round_history_id=rh.id, player_id=_IDS['p2_id']).first()
        check('H09 p1 place=1', rpr1 is not None and rpr1.final_place == 1,
              f'got {rpr1.final_place if rpr1 else None}')
        check('H09 p2 place=2', rpr2 is not None and rpr2.final_place == 2,
              f'got {rpr2.final_place if rpr2 else None}')


def test_h10_tied_gold_same_place():
    """H10: Tied gold → same final_place (competition ranking)."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=100)
    _add_wallet(session_id, _IDS['p2_id'], gold=100)  # tied with p1
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh   = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr1 = RoundPlayerResult.query.filter_by(
                 round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        rpr2 = RoundPlayerResult.query.filter_by(
                 round_history_id=rh.id, player_id=_IDS['p2_id']).first()
        both_place_1 = (rpr1 is not None and rpr2 is not None and
                        rpr1.final_place == 1 and rpr2.final_place == 1)
        check('H10 tied gold gives same place (both 1)', both_place_1,
              f'p1={rpr1.final_place if rpr1 else None} p2={rpr2.final_place if rpr2 else None}')


def test_h11_total_answers():
    """H11: total_answers = sum of PlayerProblemState.attempts_used."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=3, is_solved=True)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob2_id'], attempts_used=1, is_solved=False)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H11 total_answers==4', rpr is not None and rpr.total_answers == 4,
              f'got {rpr.total_answers if rpr else None}')


def test_h12_correct_count():
    """H12: correct = count of is_solved=True PlayerProblemState rows."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=1, is_solved=True)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob2_id'], attempts_used=2, is_solved=False)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H12 correct==1', rpr is not None and rpr.correct == 1,
              f'got {rpr.correct if rpr else None}')


def test_h13_incorrect():
    """H13: incorrect = total_answers - correct."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    # 3 attempts, 1 solved → 2 incorrect
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=3, is_solved=True)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H13 incorrect==2', rpr is not None and rpr.incorrect == 2,
              f'got {rpr.incorrect if rpr else None}')


def test_h14_accuracy():
    """H14: accuracy = correct / total_answers."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=1, is_solved=True)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob2_id'], attempts_used=1, is_solved=True)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        # 2 correct / 2 total = 1.0
        check('H14 accuracy==1.0', rpr is not None and abs(rpr.accuracy - 1.0) < 0.001,
              f'got {rpr.accuracy if rpr else None}')


def test_h14b_accuracy_zero_when_no_answers():
    """H14b: accuracy == 0.0 when player has no answer attempts."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=0)
    # no PlayerProblemState rows for p1 → total_answers == 0
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H14b accuracy==0.0 when no answers', rpr is not None and rpr.accuracy == 0.0,
              f'got {rpr.accuracy if rpr else None}')


def test_h15_round_total_answers():
    """H15: RoundHistory.total_answers aggregates across all players."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    _add_wallet(session_id, _IDS['p2_id'], gold=30)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=2, is_solved=True)
    _add_pps(_IDS['p2_id'], round_id, _IDS['prob1_id'], attempts_used=3, is_solved=False)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H15 total_answers==5', rh is not None and rh.total_answers == 5,
              f'got {rh.total_answers if rh else None}')


def test_h16_round_total_correct():
    """H16: RoundHistory.total_correct aggregates across all players."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    _add_wallet(session_id, _IDS['p2_id'], gold=30)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=1, is_solved=True)
    _add_pps(_IDS['p2_id'], round_id, _IDS['prob1_id'], attempts_used=1, is_solved=True)
    _add_pps(_IDS['p2_id'], round_id, _IDS['prob2_id'], attempts_used=1, is_solved=False)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H16 total_correct==2', rh is not None and rh.total_correct == 2,
              f'got {rh.total_correct if rh else None}')


def test_h17_round_total_incorrect():
    """H17: RoundHistory.total_incorrect = total_answers - total_correct."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    # 2 attempts, 1 solved → 1 incorrect
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=2, is_solved=True)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H17 total_incorrect==1', rh is not None and rh.total_incorrect == 1,
              f'got {rh.total_incorrect if rh else None}')


def test_h18_overall_accuracy():
    """H18: overall_accuracy = total_correct / total_answers."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob1_id'], attempts_used=2, is_solved=True)   # 1 correct, 1 wrong
    _add_pps(_IDS['p1_id'], round_id, _IDS['prob2_id'], attempts_used=2, is_solved=True)   # 1 correct, 1 wrong
    # total_answers=4, total_correct=2 → accuracy=0.5
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H18 overall_accuracy==0.5', rh is not None and abs(rh.overall_accuracy - 0.5) < 0.001,
              f'got {rh.overall_accuracy if rh else None}')


def test_h19_multi_round_separate_history():
    """H19: Multi-round session creates separate RoundHistory rows per round."""
    session_id, round1_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=100)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
        # Add gold before next round
        with flask_app.app_context():
            w = PlayerWallet.query.filter_by(
                player_id=_IDS['p1_id'], session_id=session_id).first()
            w.gold = 150
            db.session.commit()
        _next_round(client, session_id, carry_gold=True, carry_gems=True)
        # End round 2
        _end_round(client, session_id)
    with flask_app.app_context():
        all_rh = RoundHistory.query.filter_by(session_id=session_id).all()
        check('H19 two separate RoundHistory rows', len(all_rh) == 2,
              f'got {len(all_rh)}')
        # Confirm they are for different rounds
        round_numbers = sorted(r.round_number for r in all_rh)
        check('H19 round numbers are 1 and 2', round_numbers == [1, 2],
              f'got {round_numbers}')


def test_h20_carry_over_reset_does_not_alter_history():
    """H20: next_round with carry_over_gold=False does NOT change previous round's frozen gold."""
    session_id, round1_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=200, gems=5)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
        # Start next round WITHOUT carrying over gold or gems
        _next_round(client, session_id, carry_gold=False, carry_gems=False)
    with flask_app.app_context():
        # Wallet should now be reset to 0
        w = PlayerWallet.query.filter_by(
            player_id=_IDS['p1_id'], session_id=session_id).first()
        check('H20 wallet gold reset to 0 after next_round',
              w is not None and w.gold == 0, f'wallet gold={w.gold if w else None}')
        # But the frozen history for round 1 must still show gold=200
        rh  = RoundHistory.query.filter_by(round_id=round1_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H20 frozen final_gold still 200 after carry-over reset',
              rpr is not None and rpr.final_gold == 200,
              f'frozen gold={rpr.final_gold if rpr else None}')


def test_h21_carry_over_gems_reset_does_not_alter_history():
    """H21: carry-over gems reset does NOT change previous round's frozen final_gems."""
    session_id, round1_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50, gems=9)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
        _next_round(client, session_id, carry_gold=True, carry_gems=False)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round1_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H21 frozen final_gems still 9 after gems reset',
              rpr is not None and rpr.final_gems == 9,
              f'frozen gems={rpr.final_gems if rpr else None}')


def test_h22_store_purchase_does_not_alter_history():
    """H22: Direct wallet gold deduction (simulating store purchase) after round end
    does NOT change the frozen final_gold in history."""
    session_id, round1_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=300)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    # Simulate a post-round wallet deduction (e.g. store purchase)
    with flask_app.app_context():
        w = PlayerWallet.query.filter_by(
            player_id=_IDS['p1_id'], session_id=session_id).first()
        w.gold -= 50   # deduct 50 (store purchase)
        db.session.commit()
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round1_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H22 frozen final_gold still 300 after wallet deduction',
              rpr is not None and rpr.final_gold == 300,
              f'frozen gold={rpr.final_gold if rpr else None}')


def test_h23_duplicate_end_round_no_duplicates():
    """H23: Calling end_round twice does NOT create duplicate RoundHistory rows."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=50)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)  # first call
        # Second call — round already ended so game_round query returns None; safe
        _end_round(client, session_id)
    with flask_app.app_context():
        rows = RoundHistory.query.filter_by(round_id=round_id).all()
        check('H23 no duplicate history rows', len(rows) == 1, f'got {len(rows)}')


def test_h24_ended_at_set():
    """H24: RoundHistory.ended_at is set (not None)."""
    session_id, round_id = _make_session()
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H24 ended_at is not None', rh is not None and rh.ended_at is not None)


def test_h25_no_players():
    """H25: RoundHistory with no players has player_count=0 and zero totals."""
    session_id, round_id = _make_session()
    # no wallets, no enrollments
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H25 player_count==0', rh is not None and rh.player_count == 0)
        check('H25 total_answers==0', rh is not None and rh.total_answers == 0)
        check('H25 overall_accuracy==0.0', rh is not None and rh.overall_accuracy == 0.0)


def test_h26_player_name_snapshot():
    """H26: player_name_snapshot captures the player's username at round end."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=10)
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh  = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr = RoundPlayerResult.query.filter_by(
                round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        check('H26 player_name_snapshot == _P1_USER',
              rpr is not None and rpr.player_name_snapshot == _P1_USER,
              f'got {rpr.player_name_snapshot if rpr else None}')


def test_h27_problem_set_name_snapshot():
    """H27: problem_set_name_snapshot is stored when session has a problem set."""
    session_id, round_id = _make_session()
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H27 problem_set_name_snapshot == SET_NAME',
              rh is not None and rh.problem_set_name_snapshot == _SET_NAME,
              f'got {rh.problem_set_name_snapshot if rh else None}')


def test_h28_no_group_snapshot_is_none():
    """H28: group_name_snapshot is None for open (no-group) sessions."""
    session_id, round_id = _make_session()   # no group_id set
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh = RoundHistory.query.filter_by(round_id=round_id).first()
        check('H28 group_name_snapshot is None for open session',
              rh is not None and rh.group_name_snapshot is None,
              f'got {rh.group_name_snapshot if rh else None}')


def test_h29_three_player_ranking():
    """H29: Three players with distinct gold values get places 1, 2, 3."""
    session_id, round_id = _make_session()
    _add_wallet(session_id, _IDS['p1_id'], gold=300)   # 1st
    _add_wallet(session_id, _IDS['p2_id'], gold=200)   # 2nd
    _add_wallet(session_id, _IDS['p3_id'], gold=100)   # 3rd
    with flask_app.test_client() as client:
        _login(client)
        _end_round(client, session_id)
    with flask_app.app_context():
        rh   = RoundHistory.query.filter_by(round_id=round_id).first()
        rpr1 = RoundPlayerResult.query.filter_by(
                 round_history_id=rh.id, player_id=_IDS['p1_id']).first()
        rpr2 = RoundPlayerResult.query.filter_by(
                 round_history_id=rh.id, player_id=_IDS['p2_id']).first()
        rpr3 = RoundPlayerResult.query.filter_by(
                 round_history_id=rh.id, player_id=_IDS['p3_id']).first()
        check('H29 p1 place=1', rpr1 is not None and rpr1.final_place == 1)
        check('H29 p2 place=2', rpr2 is not None and rpr2.final_place == 2)
        check('H29 p3 place=3', rpr3 is not None and rpr3.final_place == 3)


# ── Regression suites ──────────────────────────────────────────────────────────

def test_hr1_multi_round_regression():
    """H_R1: test_regression_multi_round still green."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, 'tests/test_regression_multi_round.py'],
        capture_output=True, text=True, cwd=root,
    )
    ok = result.returncode == 0
    if not ok:
        print(result.stdout[-2000:] if result.stdout else '')
        print(result.stderr[-1000:] if result.stderr else '')
    check('H_R1 test_regression_multi_round all green', ok)


def test_hr2_step_e_regression():
    """H_R2: test_classic_step_e still green."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, 'tests/test_classic_step_e.py'],
        capture_output=True, text=True, cwd=root,
    )
    ok = result.returncode == 0
    if not ok:
        print(result.stdout[-2000:] if result.stdout else '')
        print(result.stderr[-1000:] if result.stderr else '')
    check('H_R2 test_classic_step_e all green', ok)


# ── Main ───────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    ('H01', test_h01_end_round_creates_one_history),
    ('H02', test_h02_history_round_id_matches),
    ('H03', test_h03_mode_type_is_classic),
    ('H04', test_h04_round_number_correct),
    ('H05', test_h05_player_count),
    ('H06', test_h06_one_player_result_per_player),
    ('H07', test_h07_final_gold_frozen),
    ('H08', test_h08_final_gems_frozen),
    ('H09', test_h09_final_place_order),
    ('H10', test_h10_tied_gold_same_place),
    ('H11', test_h11_total_answers),
    ('H12', test_h12_correct_count),
    ('H13', test_h13_incorrect),
    ('H14', test_h14_accuracy),
    ('H14b', test_h14b_accuracy_zero_when_no_answers),
    ('H15', test_h15_round_total_answers),
    ('H16', test_h16_round_total_correct),
    ('H17', test_h17_round_total_incorrect),
    ('H18', test_h18_overall_accuracy),
    ('H19', test_h19_multi_round_separate_history),
    ('H20', test_h20_carry_over_reset_does_not_alter_history),
    ('H21', test_h21_carry_over_gems_reset_does_not_alter_history),
    ('H22', test_h22_store_purchase_does_not_alter_history),
    ('H23', test_h23_duplicate_end_round_no_duplicates),
    ('H24', test_h24_ended_at_set),
    ('H25', test_h25_no_players),
    ('H26', test_h26_player_name_snapshot),
    ('H27', test_h27_problem_set_name_snapshot),
    ('H28', test_h28_no_group_snapshot_is_none),
    ('H29', test_h29_three_player_ranking),
    ('H_R1', test_hr1_multi_round_regression),
    ('H_R2', test_hr2_step_e_regression),
]

if __name__ == '__main__':
    _setup()
    for name, fn in ALL_TESTS:
        print(f'\n--- {name} ---')
        fn()

    total = passed + failed
    print(f'\nResults: {passed} passed, {failed} failed out of {total} tests.')
    if failed == 0:
        print('ALL HISTORY TESTS PASSED.')
        sys.exit(0)
    else:
        print('SOME HISTORY TESTS FAILED.')
        sys.exit(1)
