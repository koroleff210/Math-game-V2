"""
Problem set builder focused tests.

Verifies:
  - subject/topic/difficulty/type filtering
  - left/right membership separation
  - preview selection and default preview behavior
  - immediate add/remove persistence
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.subjects import Subject
from app.models.problems import (
    Problem,
    ProblemAcceptedAnswer,
    ProblemBlock,
    ProblemChoiceOption,
    ProblemSourceMetadata,
    ProblemSet,
    Topic,
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_BLOCK_TYPE_GRAPH,
    PROBLEM_BLOCK_TYPE_IMAGE,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'problem-set-builder-secret'
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
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _make_problem(topic, title, *, answer_type, difficulty, prompt, answers=None, options=None, graph=False, image_path=None, source_meta=None):
    problem = Problem(
        topic_id=topic.id,
        title=title,
        prompt_text=prompt,
        answer_text=(answers or [''])[0],
        answer_type=answer_type,
        difficulty=difficulty,
    )
    db.session.add(problem)
    db.session.flush()
    db.session.add(ProblemBlock(
        problem_id=problem.id,
        position=1,
        block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
        text_content=prompt,
    ))
    if graph:
        db.session.add(ProblemBlock(
            problem_id=problem.id,
            position=2,
            block_type=PROBLEM_BLOCK_TYPE_GRAPH,
            graph_config_json=json.dumps({
                'x_min': 0,
                'x_max': 6,
                'y_min': 0,
                'y_max': 6,
                'x_label': 'x',
                'y_label': 'y',
                'show_grid': True,
                'elements': [
                    {'element_type': 'function', 'family': 'linear', 'm': 1, 'b': 1, 'label': 'Line'},
                    {'element_type': 'point', 'x': 2, 'y': 3, 'label': 'A'},
                ],
            }),
        ))
    if image_path:
        db.session.add(ProblemBlock(
            problem_id=problem.id,
            position=3 if graph else 2,
            block_type=PROBLEM_BLOCK_TYPE_IMAGE,
            image_path=image_path,
            image_width_pct=75,
        ))
    if answer_type == PROBLEM_ANSWER_TYPE_TEXT_INPUT:
        for idx, answer in enumerate(answers or [], start=1):
            db.session.add(ProblemAcceptedAnswer(problem_id=problem.id, position=idx, answer_text=answer))
    else:
        for idx, (text, is_correct) in enumerate(options or [], start=1):
            db.session.add(ProblemChoiceOption(
                problem_id=problem.id,
                position=idx,
                option_text=text,
                is_correct=is_correct,
            ))
    if source_meta:
        db.session.add(ProblemSourceMetadata(
            problem_id=problem.id,
            source_system=source_meta.get('source_system', 'ib_physics'),
            source_id=source_meta.get('source_id'),
            canonical_id=source_meta.get('canonical_id', f'canon-{problem.id}'),
            import_batch_id=source_meta.get('import_batch_id', 'test-batch'),
            raw_metadata_json=source_meta.get('raw_metadata_json') or {},
        ))
    db.session.flush()
    return problem


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        _make_player('__ps_builder_admin__', is_admin=True)

        subject_math = Subject(name='Math')
        subject_science = Subject(name='Science')
        db.session.add_all([subject_math, subject_science])
        db.session.flush()

        algebra = Topic(name='Algebra', subject='Math', subject_id=subject_math.id)
        geometry = Topic(name='Geometry', subject='Math', subject_id=subject_math.id)
        motion = Topic(name='Motion', subject='Science', subject_id=subject_science.id)
        db.session.add_all([algebra, geometry, motion])
        db.session.flush()

        math_text = _make_problem(
            algebra,
            'Math Text A',
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
            difficulty=2,
            prompt='Solve **3 + 4**.',
            answers=['7'],
        )
        math_mc = _make_problem(
            algebra,
            'Math MC A',
            answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
            difficulty=2,
            prompt='Pick the even number.',
            options=[('3', False), ('5', False), ('8', True), ('9', False)],
            image_path='images/math-mc.png',
            source_meta={
                'source_id': 'Paper1A-Q660',
                'canonical_id': 'canon-math-mc',
                'raw_metadata_json': {'level': 'SL', 'subtopics': ['A.1'], 'uses_artificial_options': False},
            },
        )
        graph_text = _make_problem(
            geometry,
            'Graph Text B',
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
            difficulty=3,
            prompt='Read the graph.',
            answers=['(2,3)'],
            graph=True,
        )
        science_text = _make_problem(
            motion,
            'Science Text C',
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
            difficulty=2,
            prompt='What unit measures speed?',
            answers=['meters per second'],
        )

        pset = ProblemSet(name='Builder Set', description='Builder test set')
        db.session.add(pset)
        db.session.flush()
        pset.problems.append(math_mc)
        db.session.commit()

        return {
            'set_id': pset.id,
            'subject_math_id': subject_math.id,
            'subject_science_id': subject_science.id,
            'topic_algebra_id': algebra.id,
            'topic_geometry_id': geometry.id,
            'math_text_id': math_text.id,
            'math_mc_id': math_mc.id,
            'graph_text_id': graph_text.id,
            'science_text_id': science_text.id,
        }


def run_tests():
    ids = _setup_db()

    with flask_app.test_client() as client:
        _login(client, '__ps_builder_admin__')

        r = client.get(f'/admin/sets/{ids["set_id"]}')
        html = r.get_data(as_text=True)
        check(
            'PSB-01: builder page renders 3-column workspace shell',
            r.status_code == 200
            and 'Problem Set Builder' in html
            and 'id="available-problems"' in html
            and 'id="problem-preview"' in html
            and 'id="set-problems"' in html,
        )
        check(
            'PSB-01c: left and right builder lists are internally scrollable',
            html.count('set-builder-scroll-pane') >= 2
            and '.set-builder-scroll-pane .set-builder-list' in html
            and 'overflow-y: auto' in html,
        )
        check(
            'PSB-01b: builder anchor exists on initial load',
            'id="builder-workspace"' in html,
        )
        check(
            'PSB-01d: builder loads player-compatible math renderer for preview formulae',
            'window.MathJax' in html
            and "inlineMath: [['$', '$'], ['\\\\(', '\\\\)']]" in html
            and 'cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js' in html,
        )

        r = client.get(
            f'/admin/sets/{ids["set_id"]}?subject_id={ids["subject_math_id"]}&topic_id={ids["topic_algebra_id"]}&difficulty=2&answer_type=text_input'
        )
        html = r.get_data(as_text=True)
        check(
            'PSB-02: filtering by subject/topic/difficulty/type narrows available problems',
            'Math Text A' in html
            and 'Math MC A' in html  # right column member
            and 'Science Text C' not in html
            and 'Graph Text B' not in html
            and 'class="set-builder-topic-list"' in html,
        )

        r = client.get(
            f'/admin/sets/{ids["set_id"]}?subject_id={ids["subject_math_id"]}&topic_id={ids["topic_geometry_id"]}&difficulty=3&answer_type=text_input'
        )
        html = r.get_data(as_text=True)
        check(
            'PSB-03: first available problem previews by default and graph preview renders',
            r.status_code == 200
            and 'Graph Text B' in html
            and 'data-problem-graph-block' in html,
        )

        r = client.get(
            f'/admin/sets/{ids["set_id"]}?subject_id={ids["subject_math_id"]}&answer_type=multiple_choice&preview_problem_id={ids["math_mc_id"]}'
        )
        html = r.get_data(as_text=True)
        check(
            'PSB-04: clicking a right-column problem can drive preview selection',
            r.status_code == 200
            and 'Pick the even number.' in html
            and 'Paper1A-Q660' in html
            and 'canon-math-mc' in html,
        )
        check(
            'PSB-04b: admin preview uses shared player-style body preview partial',
            'shared-player-problem-preview' in html
            and 'admin-player-style-mc-options' in html
            and 'mc-option-row admin-preview-mc-option' in html,
        )
        check(
            'PSB-04bb: whole problem cards can select preview, not title only',
            'data-preview-url=' in html
            and 'data-preview-api-url=' in html
            and 'role="link"' in html
            and "document.querySelectorAll('.set-builder-row[data-preview-url]')" in html
            and "fetch(apiUrl, { headers: { 'Accept': 'application/json' } })" in html
            and "preview.innerHTML = payload.html" in html,
        )
        r = client.get(f'/admin/sets/{ids["set_id"]}/preview/{ids["math_mc_id"]}')
        payload = r.get_json()
        check(
            'PSB-04bbb: preview API returns only center preview HTML',
            r.status_code == 200
            and payload
            and payload['problem_id'] == ids['math_mc_id']
            and 'Pick the even number.' in payload['html']
            and 'available-problems' not in payload['html']
            and 'set-problems' not in payload['html'],
        )
        check(
            'PSB-04c: MCQ options appear in admin preview with player option markup',
            '3' in html and '5' in html and '8' in html and '9' in html and 'mc-option-label' in html,
        )
        check(
            'PSB-04d: image problem preview includes shared image block',
            'problem-body-image' in html and 'images/math-mc.png' in html,
        )
        check(
            'PSB-04e: correct answer is hidden by default behind admin reveal control',
            '<details class="set-builder-answer-reveal">' in html and '<summary>Show correct answer</summary>' in html,
        )

        r = client.post(
            f'/admin/sets/{ids["set_id"]}/add',
            data={
                'problem_id': ids['math_text_id'],
                'subject_id': ids['subject_math_id'],
                'topic_id': ids['topic_algebra_id'],
                'difficulty': 2,
                'answer_type': 'text_input',
                'preview_problem_id': ids['math_text_id'],
            },
            follow_redirects=False,
        )
        check(
            'PSB-05: add action redirects back into filtered builder state',
            r.status_code == 302
            and 'subject_id=' in r.headers.get('Location', '')
            and 'preview_problem_id=' in r.headers.get('Location', '')
            and '#builder-workspace' in r.headers.get('Location', ''),
        )
        with flask_app.app_context():
            pset = db.session.get(ProblemSet, ids['set_id'])
            member_ids = {problem.id for problem in pset.problems.all()}
            check('PSB-06: add action updates actual set membership immediately', ids['math_text_id'] in member_ids)

        r = client.get(
            f'/admin/sets/{ids["set_id"]}?subject_id={ids["subject_math_id"]}&topic_id={ids["topic_algebra_id"]}&difficulty=2&answer_type=text_input'
        )
        html = r.get_data(as_text=True)
        check(
            'PSB-07: left/right columns stay separated after add',
            'No available problems match the current filters.' in html and 'Math Text A' in html,
        )

        r = client.post(
            f'/admin/sets/{ids["set_id"]}/remove/{ids["math_text_id"]}',
            data={
                'subject_id': ids['subject_math_id'],
                'topic_id': ids['topic_algebra_id'],
                'difficulty': 2,
                'answer_type': 'text_input',
            },
            follow_redirects=False,
        )
        check(
            'PSB-08: remove action redirects back into builder state',
            r.status_code == 302
            and '/admin/sets/' in r.headers.get('Location', '')
            and '#builder-workspace' in r.headers.get('Location', ''),
        )
        with flask_app.app_context():
            pset = db.session.get(ProblemSet, ids['set_id'])
            member_ids = {problem.id for problem in pset.problems.all()}
            check('PSB-09: remove action updates actual set membership immediately', ids['math_text_id'] not in member_ids)

        r = client.get(
            f'/admin/sets/{ids["set_id"]}?subject_id={ids["subject_math_id"]}&topic_id={ids["topic_algebra_id"]}&difficulty=2&answer_type=text_input'
        )
        html = r.get_data(as_text=True)
        check(
            'PSB-10: removed problem returns to available column when it still matches filters',
            'Math Text A' in html and 'No available problems match the current filters.' not in html,
        )


if __name__ == '__main__':
    print('\nProblem Set Builder - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL PROBLEM SET BUILDER TESTS PASSED.')
    else:
        print('SOME PROBLEM SET BUILDER TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
