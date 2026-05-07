"""
Phase H6 admin analytics CSV export tests.

Run:
    .venv\\Scripts\\python.exe tests\\test_analytics_h6.py
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
    SECRET_KEY = 'analytics-h6-secret'
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


def _make_round(group, pset, *, mode, label, round_number):
    now = datetime.now(timezone.utc)
    session = GameSession(mode=mode, status='finished', problem_set_id=pset.id, group_id=group.id, label=label)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=round_number, started_at=now, ended_at=now)
    db.session.add(game_round)
    db.session.flush()
    analytics_round = AnalyticsRound(
        session_id=session.id,
        round_id=game_round.id,
        mode=mode,
        round_number=round_number,
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


def _seed_exports():
    db.session.remove()
    db.drop_all()
    db.create_all()
    admin = _make_player('__h6_admin__', is_admin=True)
    non_admin = _make_player('__h6_student__')
    player = _make_player('__h6_export_player__')
    group = PlayerGroup(name='H6 Export Class')
    group.members.append(player)
    db.session.add(group)
    subject = Subject(name='Physics')
    db.session.add(subject)
    db.session.flush()

    problem, pset = _make_problem('Forces', 'Force Diagram', subject)
    classic_ar, classic_round = _make_round(group, pset, mode='classic', label='H6 Classic', round_number=1)
    db.session.add(AnalyticsRoundProblem(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        problem_id=problem.id,
        problem_title_snapshot=problem.title,
        answer_type_snapshot='multiple_choice',
        subject_id=subject.id,
        subject_name_snapshot=subject.name,
        topic_id=problem.topic_id,
        topic_name_snapshot=problem.topic.name,
        mode_context='classic',
    ))
    db.session.add(AnalyticsPlayerRound(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        player_id=player.id,
        player_name_snapshot=player.username,
        problems_seen=1,
        problems_attempted=1,
        correct_attempts=1,
        accuracy=0.5,
        gold_start=0,
        gold_end=10,
        gold_net=10,
        summary_json={'classic_economy': {'gold_mined': 10}},
    ))
    db.session.add(AnalyticsPlayerProblem(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        player_id=player.id,
        problem_id=problem.id,
        problem_title_snapshot=problem.title,
        mode_context='classic',
        status='incorrect',
        attempt_count=2,
        first_attempt_correct=False,
        eventual_correct=True,
        first_seen_at=classic_round.started_at,
        completed_at=classic_round.ended_at,
    ))
    wrong_attempt = AnalyticsAnswerAttempt(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        player_id=player.id,
        problem_id=problem.id,
        attempt_number=1,
        submitted_at=classic_round.started_at,
        submitted_answer_text='wrong, with comma',
        selected_option_id=5,
        selected_option_label_snapshot='B',
        selected_option_text_snapshot='Common wrong option',
        is_correct=False,
        mode_context='classic',
        action_context='mine',
    )
    db.session.add(wrong_attempt)
    db.session.flush()
    db.session.add(AnalyticsAnswerAttempt(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        player_id=player.id,
        problem_id=problem.id,
        attempt_number=2,
        submitted_at=classic_round.ended_at,
        submitted_answer_text='answer',
        is_correct=True,
        mode_context='classic',
        action_context='mine',
    ))
    db.session.add(AnalyticsClassicEconomyEvent(
        analytics_round_id=classic_ar.id,
        round_id=classic_round.id,
        session_id=classic_ar.session_id,
        event_type='mine_success',
        actor_player_id=player.id,
        actor_name_snapshot=player.username,
        linked_answer_attempt_id=wrong_attempt.id,
        linked_problem_id=problem.id,
        action_context='mine',
        gold_delta_actor=10,
        actor_gold_after=10,
        problem_id=problem.id,
        details_json={'base_reward': 10},
    ))

    boss_ar, boss_round = _make_round(group, pset, mode='boss_rush', label='H6 Boss', round_number=2)
    db.session.add(AnalyticsRoundProblem(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        problem_id=problem.id,
        problem_title_snapshot=problem.title,
        answer_type_snapshot='multiple_choice',
        subject_id=subject.id,
        subject_name_snapshot=subject.name,
        topic_id=problem.topic_id,
        topic_name_snapshot=problem.topic.name,
        mode_context='boss_rush_attack',
    ))
    db.session.add(AnalyticsPlayerRound(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        player_id=player.id,
        player_name_snapshot=player.username,
        damage_dealt=7,
        max_combo=3,
        final_combo=3,
        hp_final=1,
        diamonds_awarded=4,
    ))
    db.session.add(AnalyticsAnswerAttempt(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        player_id=player.id,
        problem_id=problem.id,
        attempt_number=1,
        submitted_at=boss_round.started_at,
        submitted_answer_text='answer',
        is_correct=True,
        mode_context='boss_rush_attack',
        action_context='boss_damage',
    ))
    db.session.add(AnalyticsBossRushBattleEvent(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        session_id=boss_ar.session_id,
        event_type='boss_damage',
        player_id=player.id,
        player_name_snapshot=player.username,
        linked_problem_id=problem.id,
        boss_type='fire_giant',
        boss_hp_before=9,
        boss_hp_after=2,
        player_hp_before=1,
        player_hp_after=1,
        combo_before=2,
        combo_after=3,
        damage_intended=7,
        damage_applied=7,
        details_json={'source': 'test'},
    ))
    db.session.commit()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return admin.username, non_admin.username, group.id, subject.id, classic_ar.id, boss_ar.id, today


def _csv_text(response):
    return response.get_data(as_text=True)


def run_tests():
    with flask_app.app_context():
        admin_username, non_admin_username, group_id, subject_id, classic_id, boss_id, today = _seed_exports()

    with flask_app.test_client() as client:
        _login(client, admin_username)

        r = client.get(f'/admin/analytics/class-dashboard?group_id={group_id}')
        html = r.get_data(as_text=True)
        check('H6-01 class dashboard has export link', r.status_code == 200 and '/admin/analytics/class-dashboard/export.csv' in html)

        url = f'/admin/analytics/class-dashboard/export.csv?group_id={group_id}&subject_id={subject_id}&mode=classic&date_from={today}&date_to={today}'
        r = client.get(url)
        csv_text = _csv_text(r)
        check('H6-02 class CSV export returns attachment', r.status_code == 200 and 'text/csv' in r.headers.get('Content-Type', '') and 'attachment;' in r.headers.get('Content-Disposition', ''))
        check('H6-03 class CSV preserves filters', 'mode,classic' in csv_text and f'date_from,{today}' in csv_text and f'subject_id,{subject_id}' in csv_text)
        check('H6-04 class CSV includes dashboard sections', all(label in csv_text for label in ['Topic Summary', 'Player Summary', 'Most Missed Problems', 'Recent Rounds']))
        check('H6-05 class CSV includes topic/player/missed data', 'Forces' in csv_text and '__h6_export_player__' in csv_text and 'Common wrong option' in csv_text)
        check('H6-06 class mode filter excludes Boss Rush data', 'boss_damage' not in csv_text and 'H6 Boss' not in csv_text)

        r = client.get(f'/admin/analytics/rounds/{classic_id}')
        html = r.get_data(as_text=True)
        check('H6-07 round detail has export link', r.status_code == 200 and f'/admin/analytics/rounds/{classic_id}/export.csv' in html)

        r = client.get(f'/admin/analytics/rounds/{classic_id}/export.csv')
        csv_text = _csv_text(r)
        check('H6-08 Classic round CSV returns player and answer sections', r.status_code == 200 and 'Player Summaries' in csv_text and 'Answer Attempts' in csv_text)
        check('H6-09 Classic round CSV includes economy events', 'Classic Economy Events' in csv_text and 'mine_success' in csv_text)

        r = client.get(f'/admin/analytics/rounds/{boss_id}/export.csv')
        csv_text = _csv_text(r)
        check('H6-10 Boss Rush round CSV includes battle events', r.status_code == 200 and 'Boss Rush Battle Events' in csv_text and 'boss_damage' in csv_text)

    with flask_app.test_client() as client:
        _login(client, non_admin_username)
        r = client.get(f'/admin/analytics/class-dashboard/export.csv?group_id={group_id}')
        check('H6-11 non-admin class export blocked', r.status_code == 403)
        r = client.get(f'/admin/analytics/rounds/{classic_id}/export.csv')
        check('H6-12 non-admin round export blocked', r.status_code == 403)


if __name__ == '__main__':
    print('\nPhase H6 Admin Analytics Export Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL H6 ADMIN ANALYTICS EXPORT TESTS PASSED.')
    else:
        print('SOME H6 ADMIN ANALYTICS EXPORT TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
