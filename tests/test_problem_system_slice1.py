"""
Problem System V1 — Slice 1 focused tests.

Verifies:
  - accepted-answer normalization + legacy fallback
  - block-body view model + legacy fallback
  - admin content editor scaffolding
  - new problem bootstraps the canonical editor shell and defers answers to content save
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import (
    Problem,
    ProblemAcceptedAnswer,
    ProblemBlock,
    ProblemSet,
    Topic,
)
from app.services.problem_content import (
    PROBLEM_BLOCK_TYPE_IMAGE,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    build_problem_body_view,
    check_problem_text_input_answer,
    render_rich_text_html,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'problem-slice1-secret'
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
        admin = _make_player('__ps1_admin__', is_admin=True)
        topic = Topic(name='__ps1_topic__', subject='Test')
        db.session.add(topic)
        db.session.flush()

        legacy_problem = Problem(
            topic_id=topic.id,
            title='Legacy Problem',
            prompt_text='Legacy prompt',
            answer_text='Legacy Answer',
            difficulty=1,
            image_path='images/legacy.png',
        )
        db.session.add(legacy_problem)
        db.session.flush()

        block_problem = Problem(
            topic_id=topic.id,
            title='Block Problem',
            prompt_text='Old prompt',
            answer_text='fallback only',
            difficulty=2,
        )
        db.session.add(block_problem)
        db.session.flush()

        db.session.add_all([
            ProblemBlock(
                problem_id=block_problem.id,
                position=1,
                block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
                text_content='First **block**',
            ),
            ProblemBlock(
                problem_id=block_problem.id,
                position=2,
                block_type=PROBLEM_BLOCK_TYPE_IMAGE,
                image_path='images/block.png',
                image_width_pct=60,
            ),
            ProblemAcceptedAnswer(
                problem_id=block_problem.id,
                position=1,
                answer_text='(2,3)',
            ),
            ProblemAcceptedAnswer(
                problem_id=block_problem.id,
                position=2,
                answer_text='(2;3)',
            ),
        ])

        ps = ProblemSet(name='__ps1_set__')
        db.session.add(ps)
        db.session.flush()
        ps.problems.append(legacy_problem)
        ps.problems.append(block_problem)
        db.session.commit()


def test_services_and_admin():
    with flask_app.app_context():
        legacy_problem = Problem.query.filter_by(title='Legacy Problem').first()
        block_problem = Problem.query.filter_by(title='Block Problem').first()

        legacy_view = build_problem_body_view(legacy_problem)
        check('PS1-01: legacy problem falls back to rich_text + image body view',
              legacy_view['uses_legacy_fallback'] and len(legacy_view['blocks']) == 2)
        check('PS1-02: legacy image_path becomes fallback image block',
              any(block['type'] == PROBLEM_BLOCK_TYPE_IMAGE for block in legacy_view['blocks']))

        block_view = build_problem_body_view(block_problem)
        check('PS1-03: saved blocks take precedence over legacy prompt_text',
              not block_view['uses_legacy_fallback'] and len(block_view['blocks']) == 2)
        check('PS1-04: rich_text block renders simple HTML',
              '<strong>block</strong>' in block_view['blocks'][0]['rendered_html'])
        check('PS1-04b: imported inline latex textup is normalized for MathJax',
              '\\text{' in render_rich_text_html('Value is $2.0\\:\\textup{mol}$')
              and '\\textup{' not in render_rich_text_html('Value is $2.0\\:\\textup{mol}$'))

        check('PS1-05: accepted answers use modest normalization',
              check_problem_text_input_answer(block_problem, '   (2,3)   '))
        check('PS1-06: teacher-entered second variant is accepted explicitly',
              check_problem_text_input_answer(block_problem, '(2;3)'))
        check('PS1-07: legacy answer_text still works when accepted-answer rows are absent',
              check_problem_text_input_answer(legacy_problem, ' legacy   answer '))

    with flask_app.test_client() as client:
        _login(client, '__ps1_admin__')

        with flask_app.app_context():
            block_problem = Problem.query.filter_by(title='Block Problem').first()
            legacy_problem = Problem.query.filter_by(title='Legacy Problem').first()
            first_topic_id = db.session.query(Topic.id).order_by(Topic.id).first()[0]
            legacy_block_count_before = ProblemBlock.query.filter_by(problem_id=legacy_problem.id).count()
            legacy_answer_count_before = ProblemAcceptedAnswer.query.filter_by(problem_id=legacy_problem.id).count()

        r = client.get(f'/admin/problems/{legacy_problem.id}/content')
        check('PS1-08: content editor GET does not create blocks or accepted-answer rows',
              r.status_code == 200)
        with flask_app.app_context():
            legacy_problem = Problem.query.filter_by(title='Legacy Problem').first()
            legacy_block_count_after = ProblemBlock.query.filter_by(problem_id=legacy_problem.id).count()
            legacy_answer_count_after = ProblemAcceptedAnswer.query.filter_by(problem_id=legacy_problem.id).count()
            check('PS1-09: content editor GET leaves legacy-only records unchanged',
                  legacy_block_count_before == legacy_block_count_after == 0 and legacy_answer_count_before == legacy_answer_count_after == 0)

        r = client.get(f'/admin/problems/{block_problem.id}/content')
        html = r.get_data(as_text=True)
        check('PS1-10: admin content editor renders for an existing problem',
              r.status_code == 200 and 'Accepted Answers' in html and 'Body Blocks' in html)
        check('PS1-11: content editor preview uses shared block preview partial',
              'Preview' in html and '<strong>block</strong>' in html and 'images/block.png' in html)

        r = client.post(
            f'/admin/problems/new',
            data={
                'title': 'New Slice1 Problem',
                'topic_id': first_topic_id,
                'subject_helper': 0,
                'prompt_text': 'Brand new prompt',
                'answer_text': 'Brand new answer',
                'difficulty': 1,
                'image_path': '',
            },
            follow_redirects=True,
        )
        check('PS1-12: existing admin create route still works after model additions',
              r.status_code == 200)

        with flask_app.app_context():
            created = Problem.query.filter_by(title='New Slice1 Problem').first()
            check('PS1-13: new problem gets a default rich_text block',
                  created is not None and len(created.blocks) == 1 and created.blocks[0].block_type == PROBLEM_BLOCK_TYPE_RICH_TEXT)
            check('PS1-14: new problem create stays lightweight and defers accepted answers to content save',
                  created is not None and len(created.accepted_answers) == 0 and (created.answer_text or '') == '')

        with flask_app.app_context():
            created = Problem.query.filter_by(title='New Slice1 Problem').first()
            created_id = created.id
            created_block_id = created.blocks[0].id
        r = client.post(
            f'/admin/problems/{created_id}/content',
            data={
                'answer_type': 'text_input',
                'accepted_answers_text': 'Alpha\nalpha beta',
                f'block_{created_block_id}_text_content': 'Line 1\n\nLine 2',
            },
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        check('PS1-15: content editor save path updates accepted answers and block content',
              r.status_code == 200 and 'Problem content for' in html)

        with flask_app.app_context():
            updated = db.session.get(Problem, created_id)
            check('PS1-16: accepted answers are replaced from textarea input',
                  [row.answer_text for row in updated.accepted_answers] == ['Alpha', 'alpha beta'])
            check('PS1-17: rich_text block content is updated through editor save',
                  updated.blocks[0].text_content == 'Line 1\n\nLine 2')

        with flask_app.app_context():
            block_problem = Problem.query.filter_by(title='Block Problem').first()
            block_ids = [block.id for block in block_problem.blocks]
        r = client.post(
            f'/admin/problems/{block_problem.id}/blocks/{block_ids[1]}/move',
            data={'direction': 'up'},
            follow_redirects=True,
        )
        check('PS1-18: block move route still responds successfully',
              r.status_code == 200)
        with flask_app.app_context():
            block_problem = Problem.query.filter_by(title='Block Problem').first()
            ordered_types = [block.block_type for block in block_problem.blocks]
            check('PS1-19: block move updates stored order',
                  ordered_types == [PROBLEM_BLOCK_TYPE_IMAGE, PROBLEM_BLOCK_TYPE_RICH_TEXT])

        with flask_app.app_context():
            block_problem = Problem.query.filter_by(title='Block Problem').first()
            image_block = next(block for block in block_problem.blocks if block.block_type == PROBLEM_BLOCK_TYPE_IMAGE)
        r = client.post(
            f'/admin/problems/{block_problem.id}/blocks/{image_block.id}/delete',
            follow_redirects=True,
        )
        check('PS1-20: block delete route still responds successfully',
              r.status_code == 200)
        with flask_app.app_context():
            block_problem = Problem.query.filter_by(title='Block Problem').first()
            remaining_types = [block.block_type for block in block_problem.blocks]
            check('PS1-21: block delete removes the targeted block and normalizes order',
                  remaining_types == [PROBLEM_BLOCK_TYPE_RICH_TEXT] and block_problem.blocks[0].position == 1)

        r = client.post(
            f'/admin/problems/{block_problem.id}/edit',
            data={
                'title': 'Block Problem',
                'topic_id': first_topic_id,
                'subject_helper': 0,
                'difficulty': 2,
                'answer_type': 'text_input',
                'accepted_answers_text': '(2,3)\n(2;3)',
                f'block_{block_problem.blocks[0].id}_text_content': 'First **block**',
            },
            follow_redirects=True,
        )
        check('PS1-22: compatibility edit route still posts through the canonical content-save contract',
              r.status_code == 200)
        with flask_app.app_context():
            block_problem = Problem.query.filter_by(title='Block Problem').first()
            block_view = build_problem_body_view(block_problem)
            check('PS1-23: structured body remains authoritative and syncs the legacy prompt mirror on save',
                  block_view['blocks'][0]['text_content'] == 'First **block**' and block_problem.prompt_text == 'First **block**')
            check('PS1-24: structured accepted answers remain authoritative and sync the legacy answer mirror on save',
                  check_problem_text_input_answer(block_problem, '(2;3)') and block_problem.answer_text == '(2,3)')


if __name__ == '__main__':
    print('\nProblem System V1 Slice 1 - Tests')
    print('-' * 60)
    _setup_db()
    test_services_and_admin()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL PROBLEM SYSTEM SLICE 1 TESTS PASSED.')
    else:
        print('SOME PROBLEM SYSTEM SLICE 1 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
