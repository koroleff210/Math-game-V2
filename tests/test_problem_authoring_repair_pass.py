"""
Problem authoring repair pass focused tests.

Verifies:
  - "Start with Text Block" creates the first saved rich-text block
  - add-block redirects preserve useful anchor context
  - preview shows mixed saved blocks in authored order
  - graph blocks still appear in the editor preview path
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_BLOCK_TYPE_GRAPH,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    Problem,
    Topic,
)
from app.services.problem_content import add_problem_block


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'problem-authoring-repair-secret'
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


def _make_player(username, password='pass1234', is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password(password)
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        _make_player('__authoring_admin__', is_admin=True)
        topic = Topic(name='__authoring_topic__', subject='Authoring')
        db.session.add(topic)
        db.session.flush()

        legacy_problem = Problem(
            topic_id=topic.id,
            title='Legacy Only Authoring Problem',
            prompt_text='Legacy prompt text',
            answer_text='legacy answer',
            difficulty=1,
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
        )
        db.session.add(legacy_problem)
        db.session.flush()

        mixed_problem = Problem(
            topic_id=topic.id,
            title='Mixed Preview Problem',
            prompt_text='Unused prompt',
            answer_text='42',
            difficulty=1,
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
        )
        db.session.add(mixed_problem)
        db.session.flush()

        first_text = add_problem_block(mixed_problem, PROBLEM_BLOCK_TYPE_RICH_TEXT)
        first_text.text_content = 'First block text'
        db.session.commit()
        mixed_problem = db.session.get(Problem, mixed_problem.id)
        first_text = mixed_problem.blocks[0]
        graph_block = add_problem_block(mixed_problem, PROBLEM_BLOCK_TYPE_GRAPH, after_block_id=first_text.id)
        db.session.commit()
        mixed_problem = db.session.get(Problem, mixed_problem.id)
        graph_block = next(block for block in mixed_problem.blocks if block.block_type == PROBLEM_BLOCK_TYPE_GRAPH)
        second_text = add_problem_block(mixed_problem, PROBLEM_BLOCK_TYPE_RICH_TEXT, after_block_id=graph_block.id)
        second_text.text_content = 'Second block text'
        db.session.commit()

        return {
            'legacy_problem_id': legacy_problem.id,
            'mixed_problem_id': mixed_problem.id,
        }


def run_tests():
    ids = _setup_db()

    with flask_app.test_client() as client:
        _login(client, '__authoring_admin__')

        r = client.post(
            f'/admin/problems/{ids["legacy_problem_id"]}/blocks/add?block_type=rich_text',
            data={},
            follow_redirects=False,
        )
        check(
            'PAR-01: Start with Text Block route redirects back to the new block anchor',
            r.status_code == 302 and '#block-' in r.headers.get('Location', ''),
        )

        with flask_app.app_context():
            legacy_problem = db.session.get(Problem, ids['legacy_problem_id'])
            check(
                'PAR-02: Start with Text Block creates a persisted first rich-text block',
                len(legacy_problem.blocks) == 1
                and legacy_problem.blocks[0].block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT
                and legacy_problem.blocks[0].text_content == '',
            )

        r = client.get(r.headers['Location'].split('#', 1)[0])
        html = r.get_data(as_text=True)
        check(
            'PAR-03: preview shows an empty rich-text block visibly instead of omitting it',
            'Empty text block.' in html,
        )

        with flask_app.app_context():
            mixed_problem = db.session.get(Problem, ids['mixed_problem_id'])
            first_block = mixed_problem.blocks[0]
        r = client.post(
            f'/admin/problems/{ids["mixed_problem_id"]}/blocks/add?block_type=rich_text&after_block_id={first_block.id}',
            data={},
            follow_redirects=False,
        )
        check(
            'PAR-04: add-below flow preserves context with a block anchor redirect',
            r.status_code == 302 and '#block-' in r.headers.get('Location', ''),
        )

        r = client.get(f'/admin/problems/{ids["mixed_problem_id"]}/content')
        html = r.get_data(as_text=True)
        preview_start = html.find('<div class="problem-preview-frame">')
        preview_html = html[preview_start:] if preview_start != -1 else html
        first_idx = preview_html.find('First block text')
        graph_idx = preview_html.find('data-problem-graph-block')
        second_idx = preview_html.find('Second block text')
        check(
            'PAR-05: preview includes mixed saved blocks in authored order',
            first_idx != -1 and graph_idx != -1 and second_idx != -1 and first_idx < graph_idx < second_idx,
        )
        check(
            'PAR-06: graph blocks still render in the editor preview path',
            'problem_graph_renderer.js' in html and 'data-problem-graph-block' in html,
        )


if __name__ == '__main__':
    print('\nProblem Authoring Repair Pass - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL PROBLEM AUTHORING REPAIR TESTS PASSED.')
    else:
        print('SOME PROBLEM AUTHORING REPAIR TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
