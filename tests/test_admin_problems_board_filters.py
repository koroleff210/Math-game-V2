"""
Focused regression tests for builder-style filters on the admin Problems board.

Run:
    .venv\\Scripts\\python.exe tests\\test_admin_problems_board_filters.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_CONTENT_KIND_DEFINITION,
    PROBLEM_CONTENT_KIND_PROBLEM,
    Problem,
    Topic,
)
from app.models.subjects import Subject


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'admin-problems-board-filters-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0
_IDS = {}


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


def _login(client):
    return client.post(
        '/login',
        data={'username': '__problem_filter_admin__', 'password': 'pass1234'},
        follow_redirects=True,
    )


def _make_problem(topic, title, *, difficulty=1, answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT, content_kind=PROBLEM_CONTENT_KIND_PROBLEM):
    problem = Problem(
        topic_id=topic.id,
        title=title,
        prompt_text=f'Prompt for {title}',
        answer_text='answer',
        difficulty=difficulty,
        answer_type=answer_type,
        content_kind=content_kind,
    )
    db.session.add(problem)
    db.session.flush()
    return problem


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin = Player(username='__problem_filter_admin__', is_admin=True)
        admin.set_password('pass1234')
        db.session.add(admin)

        physics = Subject(name='Physics')
        chemistry = Subject(name='Chemistry')
        db.session.add_all([physics, chemistry])
        db.session.flush()

        mechanics = Topic(name='Mechanics', subject_id=physics.id)
        waves = Topic(name='Waves', subject_id=physics.id)
        organic = Topic(name='Organic', subject_id=chemistry.id)
        db.session.add_all([mechanics, waves, organic])
        db.session.flush()

        _make_problem(mechanics, 'Mechanics Text Problem', difficulty=2)
        _make_problem(
            mechanics,
            'Mechanics Multiple Choice',
            difficulty=2,
            answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
        )
        _make_problem(waves, 'Waves Definition', difficulty=4, content_kind=PROBLEM_CONTENT_KIND_DEFINITION)
        _make_problem(organic, 'Organic Chemistry Problem', difficulty=2)

        db.session.commit()
        _IDS['physics_id'] = physics.id
        _IDS['mechanics_id'] = mechanics.id
        _IDS['waves_id'] = waves.id


def test_subject_filter_reveals_builder_style_topic_filters():
    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(f'/admin/problems?subject_id={_IDS["physics_id"]}')
        html = resp.get_data(as_text=True)

        check('APF-01 subject-filtered page loads', resp.status_code == 200)
        check('APF-02 topic checkbox list is visible', 'Mechanics' in html and 'Waves' in html)
        check('APF-03 selected subject excludes other subjects', 'Organic Chemistry Problem' not in html)


def test_combined_problem_board_filters():
    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(
            '/admin/problems'
            f'?subject_id={_IDS["physics_id"]}'
            f'&topic_id={_IDS["mechanics_id"]}'
            '&difficulty=2'
            '&answer_type=multiple_choice'
            '&content_kind=problem'
        )
        html = resp.get_data(as_text=True)

        check('APF-04 combined filters load', resp.status_code == 200)
        check('APF-05 matching multiple-choice problem remains', 'Mechanics Multiple Choice' in html)
        check('APF-06 non-matching same-topic text problem is hidden', 'Mechanics Text Problem' not in html)
        check('APF-07 non-matching topic is hidden', 'Waves Definition' not in html)
        check(
            'APF-08 selected topic remains checked',
            f'value="{_IDS["mechanics_id"]}" checked' in html,
        )


def test_invalid_topic_selection_is_ignored_outside_subject():
    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(
            '/admin/problems'
            f'?subject_id={_IDS["physics_id"]}'
            f'&topic_id={_IDS["waves_id"]}'
            '&difficulty=2'
        )
        html = resp.get_data(as_text=True)

        check('APF-09 valid topic plus difficulty filters load', resp.status_code == 200)
        check('APF-10 no problem leaks through mismatched topic/difficulty filters', 'Mechanics Text Problem' not in html and 'Waves Definition' not in html)


def run_all():
    _setup_db()
    test_subject_filter_reveals_builder_style_topic_filters()
    test_combined_problem_board_filters()
    test_invalid_topic_selection_is_ignored_outside_subject()
    if failed:
        print(f'\nADMIN PROBLEMS FILTER TESTS FAILED: {failed} failed, {passed} passed.')
        raise SystemExit(1)
    print(f'\nALL ADMIN PROBLEMS FILTER TESTS PASSED. ({passed} checks)')


if __name__ == '__main__':
    run_all()
