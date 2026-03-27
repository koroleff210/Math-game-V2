"""
Equation-based graph authoring UI pass focused tests.

Verifies:
  - normalized graph elements reconstruct into equation + point editor rows
  - unsupported legacy trig phase elements are preserved and surfaced
  - admin graph save path accepts equation/point rows and keeps preview working
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
    Problem,
    ProblemBlock,
    Topic,
)
from app.services.problem_content import build_graph_block_editor_view, normalize_graph_block_config


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'graph-ui-pass-secret'
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
        _make_player('__graph_ui_admin__', is_admin=True)
        topic = Topic(name='__graph_ui_topic__', subject='Graph')
        db.session.add(topic)
        db.session.flush()

        problem = Problem(
            topic_id=topic.id,
            title='Equation UI Problem',
            prompt_text='Legacy prompt',
            answer_text='42',
            difficulty=2,
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
        )
        db.session.add(problem)
        db.session.flush()

        graph_block = ProblemBlock(
            problem_id=problem.id,
            position=1,
            block_type=PROBLEM_BLOCK_TYPE_GRAPH,
        )
        graph_block.graph_config_json = __import__('json').dumps(normalize_graph_block_config({
            'x_min': -5,
            'x_max': 5,
            'y_min': -5,
            'y_max': 5,
            'elements': [
                {
                    'id': 'eqlinear1',
                    'element_type': 'function',
                    'family': 'linear',
                    'label': 'L1',
                    'color': '#123456',
                    'm': 2,
                    'b': 1,
                    'x_min': -2,
                    'x_max': 3,
                },
                {
                    'id': 'pointabc1',
                    'element_type': 'point',
                    'label': 'A',
                    'color': '#654321',
                    'x': 1,
                    'y': 4,
                },
                {
                    'id': 'legacysin1',
                    'element_type': 'function',
                    'family': 'sine',
                    'label': 'Legacy',
                    'color': '#222222',
                    'amplitude': 1,
                    'frequency': 1,
                    'phase': 0.5,
                    'vertical_shift': 0,
                },
            ],
        }))
        db.session.add(graph_block)
        db.session.commit()
        return {'problem_id': problem.id, 'block_id': graph_block.id}


def run_tests():
    ids = _setup_db()

    with flask_app.app_context():
        problem = db.session.get(Problem, ids['problem_id'])
        block = next(row for row in problem.blocks if row.id == ids['block_id'])
        editor_view = build_graph_block_editor_view(block)
        check(
            'GEUI-01: supported normalized elements reconstruct into equation and point rows',
            len(editor_view['equations']) == 1
            and editor_view['equations'][0]['equation_text'] == 'y = 2x + 1'
            and editor_view['equations'][0]['x_min'] == '-2'
            and editor_view['equations'][0]['x_max'] == '3'
            and len(editor_view['points']) == 1
            and editor_view['points'][0]['coordinates_text'] == '(1, 4)',
        )
        check(
            'GEUI-02: non-roundtrippable legacy elements are surfaced as preserved rows',
            len(editor_view['unsupported_elements']) == 1
            and editor_view['unsupported_elements'][0]['id'] == 'legacysin1',
        )

    with flask_app.test_client() as admin_client:
        _login(admin_client, '__graph_ui_admin__')
        response = admin_client.post(
            f'/admin/problems/{ids["problem_id"]}/content',
            data={
                'title': 'Equation UI Problem',
                'topic_id': '1',
                'subject_helper': '0',
                'difficulty': '2',
                'answer_type': 'text_input',
                'accepted_answers_text': '42',
                f'block_{ids["block_id"]}_graph_x_min': '-8',
                f'block_{ids["block_id"]}_graph_x_max': '8',
                f'block_{ids["block_id"]}_graph_y_min': '-6',
                f'block_{ids["block_id"]}_graph_y_max': '6',
                f'block_{ids["block_id"]}_graph_x_label': 'time',
                f'block_{ids["block_id"]}_graph_y_label': 'height',
                f'block_{ids["block_id"]}_graph_show_grid': '1',
                f'block_{ids["block_id"]}_equation_eqlinear1_label': 'Main line',
                f'block_{ids["block_id"]}_equation_eqlinear1_color': '#123456',
                f'block_{ids["block_id"]}_equation_eqlinear1_equation_text': 'y = -x + 2',
                f'block_{ids["block_id"]}_equation_eqlinear1_x_min': '-4',
                f'block_{ids["block_id"]}_equation_eqlinear1_x_max': '4',
                f'block_{ids["block_id"]}_point_pointabc1_label': 'B',
                f'block_{ids["block_id"]}_point_pointabc1_color': '#654321',
                f'block_{ids["block_id"]}_point_pointabc1_coordinates_text': '(2; 3)',
            },
            follow_redirects=True,
        )
        html = response.get_data(as_text=True)
        check(
            'GEUI-03: admin content save accepts equation + point rows and still renders preview',
            response.status_code == 200
            and 'data-problem-graph-block' in html
            and 'Equations' in html
            and 'Points' in html,
        )

        with flask_app.app_context():
            problem = db.session.get(Problem, ids['problem_id'])
            block = next(row for row in problem.blocks if row.id == ids['block_id'])
            config = normalize_graph_block_config(__import__('json').loads(block.graph_config_json))
            check(
                'GEUI-04: equation rows save back into canonical normalized graph config',
                config['x_min'] == -8.0
                and config['x_max'] == 8.0
                and any(
                    element.get('family') == 'linear'
                    and element.get('m') == -1.0
                    and element.get('b') == 2.0
                    and element.get('x_min') == -4.0
                    and element.get('x_max') == 4.0
                    for element in config['elements']
                )
                and any(
                    element.get('element_type') == 'point'
                    and element.get('x') == 2.0
                    and element.get('y') == 3.0
                    for element in config['elements']
                ),
            )
            check(
                'GEUI-05: unsupported legacy graph elements are preserved during save',
                any(element.get('id') == 'legacysin1' for element in config['elements']),
            )


if __name__ == '__main__':
    print('\nGraph Equation UI Pass - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GRAPH EQUATION UI PASS TESTS PASSED.')
    else:
        print('SOME GRAPH EQUATION UI PASS TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
