"""
Phase H4 admin analytics viewer tests.

Run:
    .venv\\Scripts\\python.exe tests\\test_analytics_h4.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.analytics import (
    AnalyticsAnswerAttempt,
    AnalyticsBossRushBattleEvent,
    AnalyticsClassicEconomyEvent,
    AnalyticsPlayerProblem,
    AnalyticsPlayerRound,
    AnalyticsRound,
    AnalyticsRoundProblem,
)
from app.models.game import GameRound, GameSession
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'analytics-h4-secret'
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
            msg += f' ({detail})'
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


def _make_problem(prefix):
    topic = Topic(name=f'{prefix} Topic')
    db.session.add(topic)
    db.session.flush()
    problem = Problem(topic_id=topic.id, title=f'{prefix} Problem', prompt_text='2+2', answer_text='4', difficulty=1)
    pset = ProblemSet(name=f'{prefix} Set')
    db.session.add_all([problem, pset])
    db.session.flush()
    pset.problems.append(problem)
    db.session.flush()
    return problem, pset


def _make_round(prefix, mode):
    problem, pset = _make_problem(prefix)
    session = GameSession(mode=mode, status='waiting', problem_set_id=pset.id, label=f'{prefix} Session')
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(
        session_id=session.id,
        round_number=1,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
    )
    db.session.add(game_round)
    db.session.flush()
    analytics_round = AnalyticsRound(
        session_id=session.id,
        round_id=game_round.id,
        mode=mode,
        round_number=1,
        session_label_snapshot=session.label,
        problem_set_id=pset.id,
        problem_set_name_snapshot=pset.name,
        started_at=game_round.started_at,
        ended_at=game_round.ended_at,
        finalized_at=datetime.now(timezone.utc),
    )
    db.session.add(analytics_round)
    db.session.flush()
    return analytics_round, game_round, problem


def _seed_analytics():
    db.session.remove()
    db.drop_all()
    db.create_all()
    admin = _make_player('__h4_admin__', is_admin=True)
    player = _make_player('__h4_player__')

    classic_ar, classic_round, classic_problem = _make_round('__h4_classic', 'classic')
    db.session.add_all([
        AnalyticsRoundProblem(
            analytics_round_id=classic_ar.id,
            round_id=classic_round.id,
            problem_id=classic_problem.id,
            problem_title_snapshot=classic_problem.title,
            answer_type_snapshot='text_input',
            topic_id=classic_problem.topic_id,
            topic_name_snapshot=classic_problem.topic.name,
            mode_context='classic',
        ),
        AnalyticsPlayerRound(
            analytics_round_id=classic_ar.id,
            round_id=classic_round.id,
            player_id=player.id,
            player_name_snapshot=player.username,
            problems_seen=1,
            problems_attempted=1,
            problems_solved=1,
            correct_attempts=1,
            accuracy=1.0,
            gold_start=0,
            gold_end=10,
            summary_json={'classic_economy': {'gold_mined': 10}},
        ),
        AnalyticsPlayerProblem(
            analytics_round_id=classic_ar.id,
            round_id=classic_round.id,
            player_id=player.id,
            problem_id=classic_problem.id,
            problem_title_snapshot=classic_problem.title,
            mode_context='classic',
            status='solved',
            attempt_count=1,
            first_attempt_correct=True,
            eventual_correct=True,
            first_seen_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        ),
    ])
    db.session.flush()
    attempt = AnalyticsAnswerAttempt(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        player_id=player.id,
        problem_id=classic_problem.id,
        attempt_number=1,
        submitted_at=datetime.now(timezone.utc),
        submitted_answer_text='4',
        is_correct=True,
        mode_context='classic',
        action_context='mine',
    )
    db.session.add(attempt)
    db.session.flush()
    db.session.add(AnalyticsClassicEconomyEvent(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        session_id=classic_ar.session_id,
        event_type='mine_success',
        actor_player_id=player.id,
        actor_name_snapshot=player.username,
        linked_answer_attempt_id=attempt.id,
        linked_problem_id=classic_problem.id,
        action_context='mine',
        gold_delta_actor=10,
        actor_gold_after=10,
        problem_id=classic_problem.id,
        details_json={'base_reward': 10},
    ))

    boss_ar, boss_round, boss_problem = _make_round('__h4_boss', 'boss_rush')
    db.session.add_all([
        AnalyticsRoundProblem(
            analytics_round_id=boss_ar.id,
            round_id=boss_round.id,
            problem_id=boss_problem.id,
            problem_title_snapshot=boss_problem.title,
            answer_type_snapshot='text_input',
            topic_id=boss_problem.topic_id,
            topic_name_snapshot=boss_problem.topic.name,
            mode_context='boss_rush_attack',
        ),
        AnalyticsPlayerRound(
            analytics_round_id=boss_ar.id,
            round_id=boss_round.id,
            player_id=player.id,
            player_name_snapshot=player.username,
            problems_seen=1,
            problems_attempted=1,
            problems_solved=1,
            correct_attempts=1,
            accuracy=1.0,
            damage_dealt=3,
            max_combo=2,
            final_combo=2,
            hp_final=1,
            diamonds_awarded=5,
        ),
        AnalyticsBossRushBattleEvent(
            analytics_round_id=boss_ar.id,
            round_id=boss_round.id,
            session_id=boss_ar.session_id,
            event_type='boss_damage',
            player_id=player.id,
            player_name_snapshot=player.username,
            linked_problem_id=boss_problem.id,
            boss_type='fire_giant',
            boss_hp_before=5,
            boss_hp_after=2,
            player_hp_before=1,
            player_hp_after=1,
            combo_before=1,
            combo_after=2,
            damage_intended=3,
            damage_applied=3,
        ),
    ])
    db.session.commit()
    return admin.username, classic_ar.id, boss_ar.id


def run_tests():
    with flask_app.app_context():
        admin_username, classic_id, boss_id = _seed_analytics()
    with flask_app.test_client() as client:
        _login(client, admin_username)
        r = client.get('/admin/analytics/rounds')
        html = r.get_data(as_text=True)
        check('H4-01 analytics index loads', r.status_code == 200 and 'Analytics Rounds' in html)
        check('H4-02 analytics index links both modes', 'classic' in html and 'boss_rush' in html)

        r = client.get(f'/admin/analytics/rounds/{classic_id}')
        html = r.get_data(as_text=True)
        check('H4-03 Classic detail loads player/problem/attempt sections', r.status_code == 200 and 'Player Summaries' in html and 'Problem Summaries' in html and 'Answer Attempts' in html)
        check('H4-04 Classic detail shows economy ledger', 'Classic Economy Events' in html and 'mine_success' in html)

        r = client.get(f'/admin/analytics/rounds/{boss_id}')
        html = r.get_data(as_text=True)
        check('H4-05 Boss Rush detail shows battle ledger', r.status_code == 200 and 'Boss Rush Battle Events' in html and 'boss_damage' in html)


if __name__ == '__main__':
    print('\nPhase H4 Admin Analytics Viewer Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL H4 ADMIN ANALYTICS VIEWER TESTS PASSED.')
    else:
        print('SOME H4 ADMIN ANALYTICS VIEWER TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
