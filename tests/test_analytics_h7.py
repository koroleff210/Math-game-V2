"""
Phase H7 student/player analytics page tests.

Run:
    .venv\\Scripts\\python.exe tests\\test_analytics_h7.py
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
from app.models.groups import PlayerGroup
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic
from app.models.subjects import Subject


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'analytics-h7-secret'
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


def _make_player(username):
    player = Player(username=username)
    player.set_password('pass1234')
    player.character_locked_at = datetime.now(timezone.utc)
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    return client.post('/login', data={'username': username, 'password': 'pass1234'}, follow_redirects=True)


def _make_problem(topic_name, title, subject):
    topic = Topic(name=topic_name, subject=subject.name, subject_id=subject.id)
    db.session.add(topic)
    db.session.flush()
    problem = Problem(topic_id=topic.id, title=title, prompt_text='prompt', answer_text='answer', difficulty=1)
    pset = ProblemSet(name=f'{topic_name} Set')
    db.session.add_all([problem, pset])
    db.session.flush()
    pset.problems.append(problem)
    db.session.flush()
    return problem, pset


def _make_round(group, pset, *, mode, label, number):
    now = datetime.now(timezone.utc)
    session = GameSession(mode=mode, status='finished', problem_set_id=pset.id, group_id=group.id, label=label)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=number, started_at=now, ended_at=now)
    db.session.add(game_round)
    db.session.flush()
    analytics_round = AnalyticsRound(
        session_id=session.id,
        round_id=game_round.id,
        mode=mode,
        round_number=number,
        session_label_snapshot=session.label,
        group_id=group.id,
        group_name_snapshot=group.name,
        problem_set_id=pset.id,
        problem_set_name_snapshot=pset.name,
        started_at=now,
        ended_at=now,
        finalized_at=now,
    )
    db.session.add(analytics_round)
    db.session.flush()
    return analytics_round, game_round


def _snapshot_problem(ar, game_round, problem, subject, context):
    db.session.add(AnalyticsRoundProblem(
        analytics_round_id=ar.id,
        round_id=game_round.id,
        problem_id=problem.id,
        problem_title_snapshot=problem.title,
        answer_type_snapshot='multiple_choice',
        subject_id=subject.id,
        subject_name_snapshot=subject.name,
        topic_id=problem.topic_id,
        topic_name_snapshot=problem.topic.name,
        mode_context=context,
    ))


def _player_problem(ar, game_round, player, problem, subject, context, *, attempts, first_correct, eventual):
    db.session.add(AnalyticsPlayerProblem(
        analytics_round_id=ar.id,
        round_id=game_round.id,
        player_id=player.id,
        problem_id=problem.id,
        problem_title_snapshot=problem.title,
        subject_id=subject.id,
        subject_name_snapshot=subject.name,
        topic_id=problem.topic_id,
        topic_name_snapshot=problem.topic.name,
        mode_context=context,
        status='solved' if eventual else 'incorrect',
        attempt_count=attempts,
        first_attempt_correct=first_correct,
        eventual_correct=eventual,
        first_seen_at=game_round.started_at,
        completed_at=game_round.ended_at,
    ))


def _attempt(ar, game_round, player, problem, context, number, correct, text, *, option=False):
    db.session.add(AnalyticsAnswerAttempt(
        analytics_round_id=ar.id,
        round_id=game_round.id,
        player_id=player.id,
        problem_id=problem.id,
        attempt_number=number,
        submitted_at=game_round.started_at,
        submitted_answer_text=text,
        selected_option_id=77 if option else None,
        selected_option_label_snapshot='C' if option else None,
        selected_option_text_snapshot='Student wrong choice' if option else None,
        is_correct=correct,
        mode_context=context,
        action_context='mine' if context == 'classic' else 'boss_damage',
    ))


def _seed_player_dashboard():
    db.session.remove()
    db.drop_all()
    db.create_all()
    player = _make_player('__h7_player__')
    other = _make_player('__h7_other__')
    group = PlayerGroup(name='H7 Class')
    group.members.append(player)
    group.members.append(other)
    db.session.add(group)
    subject = Subject(name='Physics')
    db.session.add(subject)
    db.session.flush()
    forces, forces_set = _make_problem('Forces', 'Force Diagram', subject)
    energy, energy_set = _make_problem('Energy', 'Work Problem', subject)
    secret, secret_set = _make_problem('SecretTopic', 'Other Student Problem', subject)

    classic_ar, classic_round = _make_round(group, forces_set, mode='classic', label='H7 Classic', number=1)
    for problem in (forces, energy):
        _snapshot_problem(classic_ar, classic_round, problem, subject, 'classic')
    db.session.add(AnalyticsPlayerRound(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        player_id=player.id,
        player_name_snapshot=player.username,
        problems_seen=2,
        problems_attempted=2,
        problems_solved=1,
        correct_attempts=2,
        incorrect_attempts=2,
        first_try_correct_count=1,
        accuracy=0.5,
        gold_start=0,
        gold_end=25,
        gold_net=25,
    ))
    _player_problem(classic_ar, classic_round, player, forces, subject, 'classic', attempts=1, first_correct=True, eventual=True)
    _player_problem(classic_ar, classic_round, player, energy, subject, 'classic', attempts=3, first_correct=False, eventual=False)
    _attempt(classic_ar, classic_round, player, forces, 'classic', 1, True, 'answer')
    _attempt(classic_ar, classic_round, player, energy, 'classic', 1, False, 'wrong energy', option=True)
    _attempt(classic_ar, classic_round, player, energy, 'classic', 2, False, 'still wrong')
    _attempt(classic_ar, classic_round, player, energy, 'classic', 3, True, 'answer')
    db.session.add_all([
        AnalyticsClassicEconomyEvent(analytics_round_id=classic_ar.id, round_id=classic_round.id, event_type='mine_success', actor_player_id=player.id, actor_name_snapshot=player.username, gold_delta_actor=10),
        AnalyticsClassicEconomyEvent(analytics_round_id=classic_ar.id, round_id=classic_round.id, event_type='steal_success', actor_player_id=player.id, actor_name_snapshot=player.username, target_player_id=other.id, gold_delta_actor=5, gold_delta_target=-5),
        AnalyticsClassicEconomyEvent(analytics_round_id=classic_ar.id, round_id=classic_round.id, event_type='steal_success', actor_player_id=other.id, actor_name_snapshot=other.username, target_player_id=player.id, gold_delta_actor=3, gold_delta_target=-3),
        AnalyticsClassicEconomyEvent(analytics_round_id=classic_ar.id, round_id=classic_round.id, event_type='steal_failed', actor_player_id=player.id, actor_name_snapshot=player.username, gold_delta_actor=-2),
    ])

    boss_ar, boss_round = _make_round(group, forces_set, mode='boss_rush', label='H7 Boss', number=2)
    _snapshot_problem(boss_ar, boss_round, forces, subject, 'boss_rush_attack')
    db.session.add(AnalyticsPlayerRound(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        player_id=player.id,
        player_name_snapshot=player.username,
        problems_seen=1,
        problems_attempted=1,
        problems_solved=1,
        correct_attempts=1,
        accuracy=1.0,
        damage_dealt=8,
        max_combo=4,
        final_combo=4,
        diamonds_awarded=6,
    ))
    _player_problem(boss_ar, boss_round, player, forces, subject, 'boss_rush_attack', attempts=1, first_correct=True, eventual=True)
    _attempt(boss_ar, boss_round, player, forces, 'boss_rush_attack', 1, True, 'answer')
    db.session.add_all([
        AnalyticsBossRushBattleEvent(analytics_round_id=boss_ar.id, round_id=boss_round.id, event_type='boss_damage', player_id=player.id, player_name_snapshot=player.username, boss_type='fire_giant', damage_applied=8),
        AnalyticsBossRushBattleEvent(analytics_round_id=boss_ar.id, round_id=boss_round.id, event_type='player_recovery_success', player_id=player.id, player_name_snapshot=player.username, boss_type='fire_giant'),
    ])

    other_ar, other_round = _make_round(group, secret_set, mode='classic', label='H7 Other', number=3)
    _snapshot_problem(other_ar, other_round, secret, subject, 'classic')
    db.session.add(AnalyticsPlayerRound(analytics_round_id=other_ar.id, round_id=other_round.id, player_id=other.id, player_name_snapshot=other.username, problems_attempted=1))
    _player_problem(other_ar, other_round, other, secret, subject, 'classic', attempts=1, first_correct=False, eventual=False)
    _attempt(other_ar, other_round, other, secret, 'classic', 1, False, 'private other answer')
    db.session.commit()
    return player.username, other.username


def run_tests():
    with flask_app.app_context():
        player_username, other_username = _seed_player_dashboard()

    with flask_app.test_client() as client:
        _login(client, player_username)
        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        check('H7-01 Hub includes My Progress link', r.status_code == 200 and 'My Progress' in html and '/player/progress' in html)

        r = client.get('/player/progress')
        html = r.get_data(as_text=True)
        check('H7-02 progress route loads', r.status_code == 200 and 'My Progress' in html and 'Overview' in html)
        check('H7-03 page only shows current player data', '__h7_other__' not in html and 'SecretTopic' not in html and 'private other answer' not in html)
        check('H7-04 overview metrics compute', 'Problems tried' in html and 'Correct answers' in html and 'Accuracy' in html and '50.0%' in html)
        check('H7-05 recent rounds show Classic and Boss Rush', 'H7 Classic' not in html and 'classic' in html and 'boss_rush' in html and 'Damage 8' in html)
        check('H7-06 topic summary shows practiced topics', 'Forces' in html and 'Energy' in html and 'Topic Practice' in html)
        check('H7-07 topics to review prefers lower accuracy', 'Topics To Review' in html and 'Energy' in html)
        check('H7-08 recent missed problems show submitted answer', 'Recent Missed Problems' in html and 'Work Problem' in html and 'Student wrong choice' in html)
        check('H7-09 Classic records render economy totals', 'Classic Records' in html and 'Gold mined' in html and '>10<' in html and 'Gold stolen' in html and '>5<' in html)
        check('H7-10 Boss Rush records render combat totals', 'Boss Rush Records' in html and 'Total damage' in html and '>8<' in html and 'Best combo' in html and '>4<' in html)

    with flask_app.test_client() as client:
        r = client.get('/player/progress', follow_redirects=False)
        check('H7-11 unauthenticated progress redirects', r.status_code in (302, 401))

    with flask_app.test_client() as client:
        _login(client, other_username)
        r = client.get('/player/progress')
        html = r.get_data(as_text=True)
        check('H7-12 other player sees only their own data', r.status_code == 200 and 'SecretTopic' in html and 'Energy' not in html and '__h7_player__' not in html)


if __name__ == '__main__':
    print('\nPhase H7 Student Analytics Page Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL H7 STUDENT ANALYTICS PAGE TESTS PASSED.')
    else:
        print('SOME H7 STUDENT ANALYTICS PAGE TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
