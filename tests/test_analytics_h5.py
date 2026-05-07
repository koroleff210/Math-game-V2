"""
Phase H5 admin class/topic analytics dashboard tests.

Run:
    .venv\\Scripts\\python.exe tests\\test_analytics_h5.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.analytics import (
    AnalyticsAnswerAttempt,
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
    SECRET_KEY = 'analytics-h5-secret'
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


def _make_problem(topic_name, problem_title, subject):
    topic = Topic(name=topic_name, subject=subject.name, subject_id=subject.id)
    db.session.add(topic)
    db.session.flush()
    problem = Problem(topic_id=topic.id, title=problem_title, prompt_text='prompt', answer_text='answer', difficulty=1)
    pset = ProblemSet(name=f'{topic_name} Set')
    db.session.add_all([problem, pset])
    db.session.flush()
    pset.problems.append(problem)
    db.session.flush()
    return problem, pset


def _make_analytics_round(group, pset, *, mode='classic', label='H5 Session', round_number=1):
    session = GameSession(mode=mode, status='waiting', problem_set_id=pset.id, group_id=group.id, label=label)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=round_number, started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc))
    db.session.add(game_round)
    db.session.flush()
    ar = AnalyticsRound(
        session_id=session.id,
        round_id=game_round.id,
        mode=mode,
        round_number=round_number,
        session_label_snapshot=session.label,
        group_id=group.id,
        group_name_snapshot=group.name,
        problem_set_id=pset.id,
        problem_set_name_snapshot=pset.name,
        started_at=game_round.started_at,
        ended_at=game_round.ended_at,
        finalized_at=datetime.now(timezone.utc),
    )
    db.session.add(ar)
    db.session.flush()
    return ar, game_round


def _seed_dashboard():
    db.session.remove()
    db.drop_all()
    db.create_all()
    admin = _make_player('__h5_admin__', is_admin=True)
    p1 = _make_player('__h5_ada__')
    p2 = _make_player('__h5_bert__')
    group = PlayerGroup(name='H5 Physics')
    group.members.append(p1)
    group.members.append(p2)
    db.session.add(group)
    db.session.flush()
    other_group = PlayerGroup(name='H5 Other Class')
    db.session.add(other_group)
    physics = Subject(name='Physics')
    math = Subject(name='Math')
    db.session.add_all([physics, math])
    db.session.flush()

    problem_a, pset_a = _make_problem('Forces', 'Newton 1', physics)
    problem_b, pset_b = _make_problem('Energy', 'Work Done', physics)
    problem_c, pset_c = _make_problem('Algebra', 'Linear Equation', math)
    other_problem, other_pset = _make_problem('OtherTopic', 'Other Problem', physics)

    ar, game_round = _make_analytics_round(group, pset_a, mode='classic', label='H5 Classic', round_number=1)

    for problem in (problem_a, problem_b, problem_c):
        db.session.add(AnalyticsRoundProblem(
            analytics_round_id=ar.id,
            round_id=game_round.id,
            problem_id=problem.id,
            problem_title_snapshot=problem.title,
            answer_type_snapshot='text_input',
            subject_id=problem.topic.subject_id,
            subject_name_snapshot=problem.topic.subject_obj.name,
            topic_id=problem.topic_id,
            topic_name_snapshot=problem.topic.name,
            mode_context='classic',
        ))

    db.session.add_all([
        AnalyticsPlayerRound(analytics_round_id=ar.id, round_id=game_round.id, player_id=p1.id, player_name_snapshot=p1.username, correct_attempts=2, incorrect_attempts=1, accuracy=2 / 3),
        AnalyticsPlayerRound(analytics_round_id=ar.id, round_id=game_round.id, player_id=p2.id, player_name_snapshot=p2.username, correct_attempts=1, incorrect_attempts=1, accuracy=0.5),
        AnalyticsPlayerProblem(analytics_round_id=ar.id, round_id=game_round.id, player_id=p1.id, problem_id=problem_a.id, problem_title_snapshot=problem_a.title, mode_context='classic', status='solved', attempt_count=1, first_attempt_correct=True, eventual_correct=True, first_seen_at=datetime.now(timezone.utc)),
        AnalyticsPlayerProblem(analytics_round_id=ar.id, round_id=game_round.id, player_id=p1.id, problem_id=problem_b.id, problem_title_snapshot=problem_b.title, mode_context='classic', status='solved', attempt_count=2, first_attempt_correct=False, eventual_correct=True, first_seen_at=datetime.now(timezone.utc)),
        AnalyticsPlayerProblem(analytics_round_id=ar.id, round_id=game_round.id, player_id=p2.id, problem_id=problem_b.id, problem_title_snapshot=problem_b.title, mode_context='classic', status='incorrect', attempt_count=1, first_attempt_correct=False, eventual_correct=False, first_seen_at=datetime.now(timezone.utc)),
        AnalyticsPlayerProblem(analytics_round_id=ar.id, round_id=game_round.id, player_id=p2.id, problem_id=problem_c.id, problem_title_snapshot=problem_c.title, mode_context='classic', status='solved', attempt_count=1, first_attempt_correct=True, eventual_correct=True, first_seen_at=datetime.now(timezone.utc)),
    ])
    db.session.flush()
    attempts = [
        (p1, problem_a, 1, True, 'answer'),
        (p1, problem_b, 1, False, 'wrong'),
        (p1, problem_b, 2, True, 'answer'),
        (p2, problem_b, 1, False, 'wrong'),
        (p2, problem_c, 1, True, 'answer'),
    ]
    for player, problem, attempt_number, correct, text in attempts:
        db.session.add(AnalyticsAnswerAttempt(
            analytics_round_id=ar.id,
            round_id=game_round.id,
            player_id=player.id,
            problem_id=problem.id,
            attempt_number=attempt_number,
            submitted_at=datetime.now(timezone.utc),
            submitted_answer_text=text,
            selected_option_id=101 if not correct else None,
            selected_option_label_snapshot='A' if not correct else None,
            selected_option_text_snapshot='Common wrong option' if not correct else None,
            is_correct=correct,
            mode_context='classic',
            action_context='mine',
        ))
    boss_ar, boss_round = _make_analytics_round(group, pset_a, mode='boss_rush', label='H5 Boss', round_number=2)
    db.session.add(AnalyticsRoundProblem(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        problem_id=problem_a.id,
        problem_title_snapshot=problem_a.title,
        answer_type_snapshot='text_input',
        subject_id=physics.id,
        subject_name_snapshot=physics.name,
        topic_id=problem_a.topic_id,
        topic_name_snapshot=problem_a.topic.name,
        mode_context='boss_rush_attack',
    ))
    db.session.add(AnalyticsPlayerRound(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        player_id=p1.id,
        player_name_snapshot=p1.username,
        damage_dealt=7,
        max_combo=3,
    ))
    db.session.add(AnalyticsPlayerProblem(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        player_id=p1.id,
        problem_id=problem_a.id,
        problem_title_snapshot=problem_a.title,
        mode_context='boss_rush_attack',
        status='solved',
        attempt_count=1,
        first_attempt_correct=True,
        eventual_correct=True,
        first_seen_at=datetime.now(timezone.utc),
    ))
    db.session.add(AnalyticsAnswerAttempt(
        analytics_round_id=boss_ar.id,
        round_id=boss_round.id,
        player_id=p1.id,
        problem_id=problem_a.id,
        attempt_number=1,
        submitted_at=datetime.now(timezone.utc),
        submitted_answer_text='answer',
        is_correct=True,
        mode_context='boss_rush_attack',
        action_context='boss_damage',
    ))

    other_ar, other_round = _make_analytics_round(other_group, other_pset, mode='classic', label='Other Session', round_number=1)
    db.session.add(AnalyticsRoundProblem(
        analytics_round_id=other_ar.id,
        round_id=other_round.id,
        problem_id=other_problem.id,
        problem_title_snapshot=other_problem.title,
        subject_id=physics.id,
        subject_name_snapshot=physics.name,
        topic_id=other_problem.topic_id,
        topic_name_snapshot=other_problem.topic.name,
        mode_context='classic',
    ))
    db.session.commit()
    return admin.username, p1.username, group.id, physics.id, math.id


def run_tests():
    with flask_app.app_context():
        admin_username, non_admin_username, group_id, physics_id, math_id = _seed_dashboard()
    with flask_app.test_client() as client:
        _login(client, admin_username)
        r = client.get('/admin/analytics/class-dashboard')
        html = r.get_data(as_text=True)
        check('H5-01 class dashboard route loads selector', r.status_code == 200 and 'Class Analytics' in html and 'H5 Physics' in html)

        r = client.get(f'/admin/analytics/class-dashboard?group_id={group_id}')
        html = r.get_data(as_text=True)
        check('H5-02 selected class dashboard loads sections', r.status_code == 200 and 'Topic Summary' in html and 'Per-Player Performance' in html and 'Problems Most Often Missed' in html)
        check('H5-03 topic rows include practiced topics', 'Forces' in html and 'Energy' in html)
        check('H5-04 player rows include players', '__h5_ada__' in html and '__h5_bert__' in html)
        check('H5-05 missed problem table includes most missed problem', 'Work Done' in html and 'Most Common Wrong MCQ Option' in html and 'Common wrong option' in html)
        check('H5-06 dashboard links to round detail', '/admin/analytics/rounds/' in html)
        check('H5-07 group filter excludes other class data', 'OtherTopic' not in html)

        r = client.get(f'/admin/analytics/class-dashboard?group_id={group_id}&mode=classic')
        html = r.get_data(as_text=True)
        check('H5-08 mode filter classic excludes Boss Rush-only damage', '1 analytics round(s) included' in html and '>7<' not in html)

        r = client.get(f'/admin/analytics/class-dashboard?group_id={group_id}&mode=boss_rush')
        html = r.get_data(as_text=True)
        check('H5-09 mode filter boss_rush includes boss data', 'Boss Damage' in html and '>7<' in html)

        r = client.get(f'/admin/analytics/class-dashboard?group_id={group_id}&subject_id={physics_id}')
        html = r.get_data(as_text=True)
        check('H5-10 subject filter includes Physics and excludes Math topic', 'Forces' in html and 'Energy' in html and 'Algebra' not in html)

        r = client.get(f'/admin/analytics/class-dashboard?group_id={group_id}&subject_id={math_id}')
        html = r.get_data(as_text=True)
        check('H5-11 subject filter includes Math topic', 'Algebra' in html and 'Energy' not in html)

    with flask_app.test_client() as client:
        _login(client, non_admin_username)
        r = client.get(f'/admin/analytics/class-dashboard?group_id={group_id}')
        check('H5-12 non-admin blocked', r.status_code == 403)


if __name__ == '__main__':
    print('\nPhase H5 Admin Class Analytics Dashboard Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL H5 ADMIN CLASS ANALYTICS DASHBOARD TESTS PASSED.')
    else:
        print('SOME H5 ADMIN CLASS ANALYTICS DASHBOARD TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
