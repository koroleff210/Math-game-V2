"""
Phase H1 analytics capture tests.

Run:
    .venv\\Scripts\\python.exe tests\\test_analytics_h1.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.analytics import (
    AnalyticsAnswerAttempt,
    AnalyticsPlayerProblem,
    AnalyticsPlayerRound,
    AnalyticsRound,
    AnalyticsRoundProblem,
)
from app.models.boss_rush import BossRushBattleState, BossRushRoundConfig
from app.models.classic import ClassicRoundConfig, PlayerProblemState, PlayerWallet
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    Problem,
    ProblemChoiceOption,
    ProblemSet,
    Topic,
)
from app.modes.boss_rush.engine import initialize_player_state, submit_current_answer
from app.services.analytics import finalize_boss_rush_round, finalize_classic_round


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'analytics-h1-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

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


def _make_player(username, *, is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    return client.post('/login', data={'username': username, 'password': 'pass1234'}, follow_redirects=True)


def _make_mc_problem_set(prefix):
    topic = Topic(name=f'{prefix}_topic')
    db.session.add(topic)
    db.session.flush()
    problem = Problem(
        topic_id=topic.id,
        title=f'{prefix} Problem',
        prompt_text='Pick B',
        answer_text='B',
        answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
        difficulty=1,
    )
    db.session.add(problem)
    db.session.flush()
    wrong = ProblemChoiceOption(problem_id=problem.id, position=1, option_text='A option', is_correct=False)
    correct = ProblemChoiceOption(problem_id=problem.id, position=2, option_text='B option', is_correct=True)
    db.session.add_all([wrong, correct])
    db.session.flush()
    pset = ProblemSet(name=f'{prefix} Set', usable_in_classic=True, usable_in_boss_rush=True, usable_as_recovery=True)
    db.session.add(pset)
    db.session.flush()
    pset.problems.append(problem)
    db.session.flush()
    return problem, wrong, correct, pset


def test_classic_socket_answer_capture_and_finalize():
    with flask_app.app_context():
        admin = _make_player('__h1_classic_admin__', is_admin=True)
        player = _make_player('__h1_classic_player__')
        problem, wrong, correct, pset = _make_mc_problem_set('__h1_classic')
        session = GameSession(mode='classic', status='active', problem_set_id=pset.id)
        db.session.add(session)
        db.session.flush()
        game_round = GameRound(session_id=session.id, round_number=1, started_at=datetime.now(timezone.utc))
        db.session.add(game_round)
        db.session.flush()
        config = ClassicRoundConfig(round_id=game_round.id, attempts_per_problem=2, wrong_answer_penalty=0)
        wallet = PlayerWallet(player_id=player.id, session_id=session.id, gold=10, gems=1)
        round_player = RoundPlayer(session_id=session.id, player_id=player.id)
        pps = PlayerProblemState(player_id=player.id, round_id=game_round.id, problem_id=problem.id)
        db.session.add_all([config, wallet, round_player, pps])
        db.session.commit()
        ids = {
            'session_id': session.id,
            'round_id': game_round.id,
            'problem_id': problem.id,
            'wrong_option_id': wrong.id,
            'correct_option_id': correct.id,
        }

    with flask_app.test_client() as client:
        _login(client, '__h1_classic_player__')
        sock = socketio.test_client(flask_app, flask_test_client=client)
        sock.emit('classic_submit_answer', {
            'session_id': ids['session_id'],
            'problem_id': ids['problem_id'],
            'selected_option_id': ids['wrong_option_id'],
            'answer_text': '  wrong raw  ',
        })
        sock.get_received()
        sock.emit('classic_submit_answer', {
            'session_id': ids['session_id'],
            'problem_id': ids['problem_id'],
            'selected_option_id': ids['correct_option_id'],
            'answer_text': '',
        })
        sock.get_received()
        sock.disconnect()

    with flask_app.app_context():
        game_round = db.session.get(GameRound, ids['round_id'])
        game_round.ended_at = datetime.now(timezone.utc)
        finalize_classic_round(game_round)
        finalize_classic_round(game_round)
        db.session.commit()

        ar = AnalyticsRound.query.filter_by(round_id=ids['round_id']).first()
        attempts = AnalyticsAnswerAttempt.query.filter_by(round_id=ids['round_id']).order_by(AnalyticsAnswerAttempt.attempt_number).all()
        app_row = AnalyticsPlayerProblem.query.filter_by(round_id=ids['round_id']).first()
        apr = AnalyticsPlayerRound.query.filter_by(round_id=ids['round_id']).first()
        check('H1-C01: Classic analytics round exists', ar is not None and ar.mode == 'classic')
        check('H1-C02: Classic round problem snapshot exists', AnalyticsRoundProblem.query.filter_by(round_id=ids['round_id']).count() == 1)
        check('H1-C03: Classic stores both raw attempts', len(attempts) == 2, f'got {len(attempts)}')
        check('H1-C04: Classic preserves submitted text', attempts and attempts[0].submitted_answer_text == '  wrong raw  ')
        check('H1-C05: Classic snapshots MCQ option text/label', attempts and attempts[0].selected_option_label_snapshot == 'A' and attempts[1].selected_option_text_snapshot == 'B option')
        check('H1-C06: Classic player-problem lifecycle summarized', app_row and app_row.attempt_count == 2 and app_row.eventual_correct is True)
        check('H1-C07: Classic player-round summary finalized', apr and apr.correct_attempts == 1 and apr.incorrect_attempts == 1 and apr.first_try_correct_count == 0)
        check('H1-C08: repeated Classic finalization is idempotent', AnalyticsPlayerRound.query.filter_by(round_id=ids['round_id']).count() == 1 and AnalyticsRoundProblem.query.filter_by(round_id=ids['round_id']).count() == 1)


def test_boss_rush_engine_answer_capture_and_finalize():
    with flask_app.app_context():
        player = _make_player('__h1_boss_player__')
        attack_problem, wrong, correct, attack_set = _make_mc_problem_set('__h1_boss_attack')
        recovery_problem, recovery_wrong, recovery_correct, recovery_set = _make_mc_problem_set('__h1_boss_recovery')
        session = GameSession(mode='boss_rush', status='active', problem_set_id=attack_set.id)
        db.session.add(session)
        db.session.flush()
        game_round = GameRound(session_id=session.id, round_number=1, started_at=datetime.now(timezone.utc))
        db.session.add(game_round)
        db.session.flush()
        config = BossRushRoundConfig(
            round_id=game_round.id,
            attack_problem_set_id=attack_set.id,
            recovery_problem_set_id=recovery_set.id,
            boss_max_hp=10,
            player_max_hp=1,
        )
        battle = BossRushBattleState(round_id=game_round.id, current_boss_hp=10, status='active')
        round_player = RoundPlayer(session_id=session.id, player_id=player.id)
        db.session.add_all([config, battle, round_player])
        db.session.flush()
        state = initialize_player_state(game_round, player.id, config)
        attack_result = submit_current_answer(state, config, battle, submitted_text='', selected_option_id=correct.id)
        db.session.commit()
        ids = {'round_id': game_round.id, 'player_id': player.id}

    with flask_app.app_context():
        game_round = db.session.get(GameRound, ids['round_id'])
        game_round.ended_at = datetime.now(timezone.utc)
        finalize_boss_rush_round(game_round)
        finalize_boss_rush_round(game_round)
        db.session.commit()

        ar = AnalyticsRound.query.filter_by(round_id=ids['round_id']).first()
        attempts = AnalyticsAnswerAttempt.query.filter_by(round_id=ids['round_id']).all()
        apr = AnalyticsPlayerRound.query.filter_by(round_id=ids['round_id'], player_id=ids['player_id']).first()
        contexts = {
            row.mode_context
            for row in AnalyticsRoundProblem.query.filter_by(round_id=ids['round_id']).all()
        }
        check('H1-B01: Boss Rush analytics round exists', ar is not None and ar.mode == 'boss_rush')
        check('H1-B02: Boss Rush snapshots attack and recovery problems', {'boss_rush_attack', 'boss_rush_recovery'} <= contexts)
        check('H1-B03: Boss Rush shared answer attempt is captured', len(attempts) == 1 and attempts[0].action_context == 'boss_damage')
        check('H1-B04: Boss Rush MCQ option is snapshotted', attempts and attempts[0].selected_option_label_snapshot == 'B')
        check('H1-B05: Boss Rush player summary includes combat stats', apr and apr.attack_correct == 1 and apr.damage_dealt == attack_result['damage_dealt'])
        check('H1-B06: repeated Boss Rush finalization is idempotent', AnalyticsPlayerRound.query.filter_by(round_id=ids['round_id']).count() == 1 and len(attempts) == 1)


def run_tests():
    with flask_app.app_context():
        db.create_all()
    test_classic_socket_answer_capture_and_finalize()
    test_boss_rush_engine_answer_capture_and_finalize()


if __name__ == '__main__':
    print('\nPhase H1 Analytics Capture Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL H1 ANALYTICS TESTS PASSED.')
    else:
        print('SOME H1 ANALYTICS TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
