"""
Problem Graph Block V1 - Slice 1 focused tests.

Verifies:
  - graph block config validation / normalization
  - admin graph block add + save path
  - shared preview/classic rendering emits graph container markup
  - existing image/text body behavior still coexists
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.player import Player
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    PROBLEM_BLOCK_TYPE_GRAPH,
    PROBLEM_BLOCK_TYPE_IMAGE,
    PROBLEM_BLOCK_TYPE_RICH_TEXT,
    Problem,
    ProblemBlock,
    ProblemSet,
    Topic,
)
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.classic import ClassicRoundConfig, PlayerClassicState, PlayerWallet
from app.services.problem_content import (
    add_problem_block,
    build_problem_body_view,
    normalize_graph_block_config,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'graph-slice1-secret'
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
        _make_player('__graph_admin__', is_admin=True)
        _make_player('__graph_player__')
        topic = Topic(name='__graph_topic__', subject='Graph')
        db.session.add(topic)
        db.session.flush()

        graph_problem = Problem(
            topic_id=topic.id,
            title='Graph Problem Slice1',
            prompt_text='Legacy prompt',
            answer_text='42',
            difficulty=1,
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
        )
        db.session.add(graph_problem)
        db.session.flush()
        db.session.add(ProblemBlock(
            problem_id=graph_problem.id,
            position=1,
            block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
            text_content='Read the graph.',
        ))
        db.session.add(ProblemBlock(
            problem_id=graph_problem.id,
            position=2,
            block_type=PROBLEM_BLOCK_TYPE_IMAGE,
            image_path='images/graph-reference.png',
            image_width_pct=50,
        ))

        problem_set = ProblemSet(name='__graph_set__')
        db.session.add(problem_set)
        db.session.flush()
        problem_set.problems.append(graph_problem)
        db.session.flush()

        game_session = GameSession(
            mode='classic',
            status='active',
            problem_set_id=problem_set.id,
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(game_session)
        db.session.flush()

        game_round = GameRound(
            session_id=game_session.id,
            round_number=1,
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(game_round)
        db.session.flush()

        db.session.add(ClassicRoundConfig(round_id=game_round.id, attempts_per_problem=1))
        graph_player = Player.query.filter_by(username='__graph_player__').first()
        db.session.add(RoundPlayer(session_id=game_session.id, player_id=graph_player.id))
        db.session.add(PlayerWallet(player_id=graph_player.id, session_id=game_session.id, gold=0, gems=0, steal_tokens=0))
        db.session.add(PlayerClassicState(player_id=graph_player.id, session_id=game_session.id))
        db.session.commit()

        return {'problem_id': graph_problem.id, 'session_id': game_session.id}


def run_tests():
    ids = _setup_db()

    with flask_app.app_context():
        normalized = normalize_graph_block_config({
            'x_min': -5,
            'x_max': 5,
            'y_min': -4,
            'y_max': 6,
            'x_label': 'Time',
            'y_label': 'Height',
            'show_grid': True,
            'elements': [
                {'element_type': 'function', 'family': 'linear', 'm': 2, 'b': 1, 'label': 'Line'},
                {'element_type': 'point', 'x': 1, 'y': 3, 'label': 'A'},
            ],
        })
        check(
            'PGB-01: graph config normalizes typed traces and points',
            normalized['x_label'] == 'Time'
            and len(normalized['elements']) == 2
            and normalized['elements'][0]['family'] == 'linear'
            and normalized['elements'][1]['element_type'] == 'point',
        )

        try:
            normalize_graph_block_config({'x_min': 5, 'x_max': -5, 'elements': []})
            invalid_ok = False
        except ValueError:
            invalid_ok = True
        check('PGB-02: invalid graph viewport is rejected', invalid_ok)

    with flask_app.test_client() as admin_client:
        _login(admin_client, '__graph_admin__')

        with flask_app.app_context():
            problem = db.session.get(Problem, ids['problem_id'])
            add_problem_block(problem, PROBLEM_BLOCK_TYPE_GRAPH, after_block_id=problem.blocks[0].id)
            db.session.commit()
            graph_block = next(block for block in problem.blocks if block.block_type == PROBLEM_BLOCK_TYPE_GRAPH)
            graph_block_id = graph_block.id

        admin_client.post(
            f'/admin/problems/{ids["problem_id"]}/blocks/{graph_block_id}/graph-elements/add',
            data={'graph_element_type': 'equation'},
            follow_redirects=True,
        )
        admin_client.post(
            f'/admin/problems/{ids["problem_id"]}/blocks/{graph_block_id}/graph-elements/add',
            data={'graph_element_type': 'point'},
            follow_redirects=True,
        )

        with flask_app.app_context():
            problem = db.session.get(Problem, ids['problem_id'])
            graph_block = next(block for block in problem.blocks if block.id == graph_block_id)
            graph_view = build_problem_body_view(problem)
            graph_body = next(block for block in graph_view['blocks'] if block['type'] == PROBLEM_BLOCK_TYPE_GRAPH)
            editor_elements = graph_body['graph_config']['elements']
            linear_id = next(element['id'] for element in editor_elements if element['element_type'] == 'function')
            point_id = next(element['id'] for element in editor_elements if element['element_type'] == 'point')

        r = admin_client.post(
            f'/admin/problems/{ids["problem_id"]}/content',
            data={
                'answer_type': 'text_input',
                'accepted_answers_text': '42',
                f'block_{graph_block_id}_graph_x_min': '-6',
                f'block_{graph_block_id}_graph_x_max': '6',
                f'block_{graph_block_id}_graph_y_min': '-3',
                f'block_{graph_block_id}_graph_y_max': '9',
                f'block_{graph_block_id}_graph_x_label': 'x',
                f'block_{graph_block_id}_graph_y_label': 'y',
                f'block_{graph_block_id}_graph_show_grid': '1',
                f'block_{graph_block_id}_equation_{linear_id}_label': 'Slope line',
                f'block_{graph_block_id}_equation_{linear_id}_color': '#3366cc',
                f'block_{graph_block_id}_equation_{linear_id}_equation_text': 'y = 2x + 1',
                f'block_{graph_block_id}_equation_{linear_id}_x_min': '-2',
                f'block_{graph_block_id}_equation_{linear_id}_x_max': '4',
                f'block_{graph_block_id}_point_{point_id}_label': 'A',
                f'block_{graph_block_id}_point_{point_id}_color': '#cc3333',
                f'block_{graph_block_id}_point_{point_id}_coordinates_text': '(2, 5)',
                f'block_{ids["problem_id"]}_block_unused': '',
                f'block_{problem.blocks[0].id}_text_content': 'Read the graph.',
                f'block_{problem.blocks[2].id}_image_path': 'images/graph-reference.png',
                f'block_{problem.blocks[2].id}_image_width_pct': '50',
            },
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        check(
            'PGB-03: admin content save persists graph block settings and preview markup',
            r.status_code == 200 and 'data-problem-graph-block' in html and 'problem_graph_renderer.js' in html,
        )
        check(
            'PGB-03b: admin graph color authoring uses curated swatches',
            'graph-color-palette' in html
            and 'graph-color-swatch' in html
            and 'value="#2563eb"' in html
            and 'placeholder="#1f77b4"' not in html,
        )

        with flask_app.app_context():
            problem = db.session.get(Problem, ids['problem_id'])
            body_view = build_problem_body_view(problem)
            graph_body = next(block for block in body_view['blocks'] if block['type'] == PROBLEM_BLOCK_TYPE_GRAPH)
            check(
                'PGB-04: graph block view includes normalized config and plot payload',
                graph_body['graph_config']['x_min'] == -6.0
                and len(graph_body['graph_config']['elements']) == 2
                and graph_body['graph_config']['elements'][0]['x_min'] == -2.0
                and graph_body['graph_config']['elements'][0]['x_max'] == 4.0
                and len(graph_body['graph_payload']['data']) == 2,
            )
            graph_payload = graph_body['graph_payload']
            function_trace = graph_payload['data'][0]
            point_trace = graph_payload['data'][1]
            check(
                'PGB-04b: graph payload keeps authored colors and one-decimal hover templates',
                function_trace['line']['color'] == '#3366cc'
                and point_trace['marker']['color'] == '#cc3333'
                and '%{x:.1f}, %{y:.1f}' in function_trace['hovertemplate']
                and '(%{x:.1f}, %{y:.1f})' in point_trace['hovertemplate'],
            )
            check(
                'PGB-04c: graph payload carries shared polished layout defaults',
                graph_payload['layout']['hovermode'] == 'closest'
                and graph_payload['layout']['xaxis']['gridcolor'] == '#d7dde5'
                and graph_payload['layout']['hoverlabel']['bgcolor'] == '#111827',
            )
            check(
                'PGB-04d: graph payload uses equal unit scale and minor grid hierarchy',
                graph_payload['layout']['yaxis']['scaleanchor'] == 'x'
                and graph_payload['layout']['yaxis']['scaleratio'] == 1
                and graph_payload['layout']['xaxis']['minor']['gridcolor'] == '#f3f5f8'
                and graph_payload['layout']['xaxis']['tickmode'] == 'auto'
                and graph_payload['layout']['xaxis']['nticks'] == 11
                and 'dtick' not in graph_payload['layout']['xaxis']
                and graph_payload['layout']['xaxis']['tickangle'] == 0
                and graph_payload['layout']['yaxis']['zerolinecolor'] == '#1f2937',
            )
            check(
                'PGB-05: existing text and image blocks remain in the structured body view',
                [block['type'] for block in body_view['blocks']] == [
                    PROBLEM_BLOCK_TYPE_RICH_TEXT,
                    PROBLEM_BLOCK_TYPE_GRAPH,
                    PROBLEM_BLOCK_TYPE_IMAGE,
                ],
            )

    with flask_app.test_client() as player_client:
        _login(player_client, '__graph_player__')

        r = player_client.get(f'/classic/game/{ids["session_id"]}')
        game_html = r.get_data(as_text=True)
        check(
            'PGB-06: classic page loads shared graph renderer assets',
            r.status_code == 200 and 'problem_graph_renderer.js' in game_html and 'cdn.plot.ly' in game_html,
        )

        socket_client = socketio.test_client(flask_app, flask_test_client=player_client)
        socket_client.emit('classic_join', {'session_id': ids['session_id']})
        received = socket_client.get_received()
        join_ack = next((event for event in received if event['name'] == 'join_ack'), None)
        problem_payload = join_ack['args'][0]['problem_list'][0]
        check(
            'PGB-07: Classic join payload includes rendered graph container HTML',
            join_ack is not None and 'data-problem-graph-block' in problem_payload.get('problem_body_html', ''),
        )
        socket_client.disconnect()


if __name__ == '__main__':
    print('\nProblem Graph Block V1 Slice 1 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL PROBLEM GRAPH BLOCK TESTS PASSED.')
    else:
        print('SOME PROBLEM GRAPH BLOCK TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
