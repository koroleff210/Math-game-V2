"""
Problem editor workflow consolidation focused tests.

Verifies:
  - the structured editor is the canonical create page
  - new text-input problems scaffold accepted answers + first block
  - new multiple-choice problems scaffold four default options
  - old edit route redirects into the canonical editor
  - metadata save now works on the canonical editor page
  - content editor shows only the relevant answer-editing section
  - block insertion still works in top-to-bottom add-below flow
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
    PROBLEM_BLOCK_TYPE_IMAGE,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    Problem,
    Topic,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'problem-workflow-pass-secret'
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
        _make_player('__workflow_admin__', is_admin=True)
        topic = Topic(name='__workflow_topic__', subject='Workflow')
        db.session.add(topic)
        db.session.commit()
        return topic.id


def run_tests():
    topic_id = _setup_db()

    with flask_app.test_client() as client:
        _login(client, '__workflow_admin__')

        r = client.get('/admin/problems/new')
        html = r.get_data(as_text=True)
        check(
            'PWF-00: new problem page is the canonical editor with metadata, answer sections, and body seed',
            r.status_code == 200
            and 'Metadata' in html
            and 'name="title"' in html
            and 'name="prompt_text"' in html
            and 'readonly' not in html.split('name="prompt_text"', 1)[1].split('>', 1)[0]
            and 'name="mc_option_1"' in html
            and 'name="mc_correct_option"' in html
            and 'Create Problem and Continue Editing' in html,
        )

        r = client.post(
            '/admin/problems/new',
            data={
                'title': 'Workflow Text Problem',
                'topic_id': topic_id,
                'subject_helper': 0,
                'answer_type': PROBLEM_ANSWER_TYPE_TEXT_INPUT,
                'prompt_text': 'Seeded text block',
                'answer_text': 'Alpha',
                'difficulty': 2,
                'image_path': '',
            },
            follow_redirects=False,
        )
        check(
            'PWF-01: text-input create redirects directly to content editor',
            r.status_code == 302 and '/admin/problems/' in r.headers.get('Location', '') and '/content' in r.headers.get('Location', ''),
        )

        with flask_app.app_context():
            text_problem = Problem.query.filter_by(title='Workflow Text Problem').first()
            check(
                'PWF-02: text-input create scaffolds one rich-text block and one accepted answer',
                text_problem is not None
                and text_problem.answer_type == PROBLEM_ANSWER_TYPE_TEXT_INPUT
                and len(text_problem.blocks) == 1
                and text_problem.blocks[0].block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT
                and text_problem.blocks[0].text_content == 'Seeded text block'
                and len(text_problem.accepted_answers) == 1
                and text_problem.accepted_answers[0].answer_text == 'Alpha',
            )
            text_problem_id = text_problem.id
            first_block_id = text_problem.blocks[0].id

        r = client.get(f'/admin/problems/{text_problem_id}/content')
        html = r.get_data(as_text=True)
        check(
            'PWF-03: text-input content editor shows accepted answers and hides MC options section',
            'Metadata' in html and 'Accepted Answers' in html and 'Multiple-Choice Options' not in html,
        )

        r = client.get(f'/admin/problems/{text_problem_id}/edit', follow_redirects=False)
        check(
            'PWF-03b: old edit route serves the canonical editor page for compatibility',
            r.status_code == 200 and 'Metadata' in r.get_data(as_text=True),
        )

        r = client.post(
            '/admin/problems/new',
            data={
                'title': 'Workflow MC Problem',
                'topic_id': topic_id,
                'subject_helper': 0,
                'answer_type': PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
                'prompt_text': 'Seeded MC block',
                'answer_text': '',
                'mc_correct_option': '3',
                'mc_option_1': 'Choice A',
                'mc_option_2': 'Choice B',
                'mc_option_3': 'Choice C',
                'mc_option_4': 'Choice D',
                'difficulty': 3,
                'image_path': '',
            },
            follow_redirects=False,
        )
        check(
            'PWF-04: multiple-choice create redirects directly to content editor',
            r.status_code == 302 and '/admin/problems/' in r.headers.get('Location', '') and '/content' in r.headers.get('Location', ''),
        )

        with flask_app.app_context():
            mc_problem = Problem.query.filter_by(title='Workflow MC Problem').first()
            check(
                'PWF-05: multiple-choice create scaffolds four default options and first block',
                mc_problem is not None
                and mc_problem.answer_type == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE
                and len(mc_problem.blocks) == 1
                and mc_problem.blocks[0].block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT
                and len(mc_problem.choice_options) == 4
                and [option.position for option in mc_problem.choice_options] == [1, 2, 3, 4]
                and [option.option_text for option in mc_problem.choice_options] == ['Choice A', 'Choice B', 'Choice C', 'Choice D']
                and sum(1 for option in mc_problem.choice_options if option.is_correct) == 1
                and mc_problem.choice_options[2].is_correct,
            )
            mc_problem_id = mc_problem.id

        r = client.get(f'/admin/problems/{mc_problem_id}/content')
        html = r.get_data(as_text=True)
        check(
            'PWF-06: multiple-choice content editor shows options and hides accepted answers section',
            'Metadata' in html and 'Multiple-Choice Options' in html and 'Accepted Answers' not in html,
        )

        r = client.post(
            f'/admin/problems/{text_problem_id}/content',
            data={
                'title': 'Workflow Text Problem Updated',
                'topic_id': topic_id,
                'subject_helper': 0,
                'difficulty': 4,
                'answer_type': PROBLEM_ANSWER_TYPE_TEXT_INPUT,
                'accepted_answers_text': 'Beta',
                f'block_{first_block_id}_text_content': 'Seeded text block updated',
            },
            follow_redirects=True,
        )
        check(
            'PWF-06b: canonical editor saves metadata and content together',
            r.status_code == 200 and 'Problem content for' in r.get_data(as_text=True),
        )
        with flask_app.app_context():
            updated = db.session.get(Problem, text_problem_id)
            check(
                'PWF-06c: metadata changes persist through canonical editor save',
                updated.title == 'Workflow Text Problem Updated' and updated.difficulty == 4 and updated.topic_id == topic_id,
            )

        r = client.post(
            f'/admin/problems/{text_problem_id}/blocks/add',
            data={'block_type': PROBLEM_BLOCK_TYPE_IMAGE, 'after_block_id': first_block_id},
            follow_redirects=True,
        )
        check('PWF-07: add-below block route responds successfully', r.status_code == 200)

        r = client.post(
            f'/admin/problems/{text_problem_id}/blocks/add',
            data={'block_type': PROBLEM_BLOCK_TYPE_RICH_TEXT, 'after_block_id': first_block_id},
            follow_redirects=True,
        )
        check('PWF-08: second add-below insertion also responds successfully', r.status_code == 200)

        with flask_app.app_context():
            text_problem = db.session.get(Problem, text_problem_id)
            ordered_types = [block.block_type for block in text_problem.blocks]
            check(
                'PWF-09: add-below inserts blocks immediately after the selected block',
                ordered_types == [
                    PROBLEM_BLOCK_TYPE_RICH_TEXT,
                    PROBLEM_BLOCK_TYPE_RICH_TEXT,
                    PROBLEM_BLOCK_TYPE_IMAGE,
                ],
            )


if __name__ == '__main__':
    print('\nProblem Editor Workflow Pass - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL PROBLEM EDITOR WORKFLOW TESTS PASSED.')
    else:
        print('SOME PROBLEM EDITOR WORKFLOW TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
