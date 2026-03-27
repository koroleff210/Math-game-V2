"""
Problem System V1 - Slice 2 focused tests.

Verifies:
  - Classic join_ack includes structured problem-body HTML
  - legacy-only problems still render through the shared fallback path
  - block-based problems override legacy prompt display
  - Classic game page contains the body-frame container
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.player import Player
from app.models.problems import Problem, ProblemBlock, ProblemSet, Topic
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.classic import PlayerClassicState, PlayerWallet
from app.services.problem_content import PROBLEM_BLOCK_TYPE_IMAGE, PROBLEM_BLOCK_TYPE_RICH_TEXT


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'problem-slice2-secret'
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


def _make_player(username, password='pass1234'):
    player = Player(username=username, is_admin=False)
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
        player = _make_player('__ps2_player__')
        topic = Topic(name='__ps2_topic__', subject='Test')
        db.session.add(topic)
        db.session.flush()

        legacy_problem = Problem(
            topic_id=topic.id,
            title='Legacy Problem Slice2',
            prompt_text='Legacy prompt with $x$',
            answer_text='legacy',
            difficulty=1,
            image_path='images/legacy-slice2.png',
        )
        db.session.add(legacy_problem)
        db.session.flush()

        block_problem = Problem(
            topic_id=topic.id,
            title='Block Problem Slice2',
            prompt_text='Old prompt should not display',
            answer_text='block',
            difficulty=1,
        )
        db.session.add(block_problem)
        db.session.flush()
        db.session.add_all([
            ProblemBlock(
                problem_id=block_problem.id,
                position=1,
                block_type=PROBLEM_BLOCK_TYPE_RICH_TEXT,
                text_content='Structured **body** with $y$',
            ),
            ProblemBlock(
                problem_id=block_problem.id,
                position=2,
                block_type=PROBLEM_BLOCK_TYPE_IMAGE,
                image_path='images/block-slice2.png',
                image_width_pct=70,
            ),
        ])

        problem_set = ProblemSet(name='__ps2_set__')
        db.session.add(problem_set)
        db.session.flush()
        problem_set.problems.append(legacy_problem)
        problem_set.problems.append(block_problem)
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

        db.session.add(RoundPlayer(session_id=game_session.id, player_id=player.id))
        db.session.add(PlayerWallet(player_id=player.id, session_id=game_session.id, gold=0, gems=0, steal_tokens=0))
        db.session.add(PlayerClassicState(player_id=player.id, session_id=game_session.id))
        db.session.commit()

        return {'session_id': game_session.id}


def run_tests():
    ids = _setup_db()

    with flask_app.test_client() as client:
        _login(client, '__ps2_player__')

        r = client.get(f'/classic/game/{ids["session_id"]}')
        html = r.get_data(as_text=True)
        check(
            'PS2-01: classic game page contains body frame container',
            r.status_code == 200 and 'problem-body-frame' in html and 'problem-body' in html,
        )

        socket_client = socketio.test_client(flask_app, flask_test_client=client)
        check('PS2-02: socket test client connected', socket_client.is_connected())

        socket_client.emit('classic_join', {'session_id': ids['session_id']})
        received = socket_client.get_received()
        join_ack = next((event for event in received if event['name'] == 'join_ack'), None)
        check('PS2-03: classic_join returns join_ack', join_ack is not None)

        payload = join_ack['args'][0]
        problem_list = {row['title']: row for row in payload['problem_list']}

        legacy_payload = problem_list['Legacy Problem Slice2']
        check(
            'PS2-04: legacy-only problem includes fallback body HTML',
            'Legacy prompt with $x$' in legacy_payload.get('problem_body_html', '')
            and 'legacy-slice2.png' in legacy_payload.get('problem_body_html', ''),
        )

        block_payload = problem_list['Block Problem Slice2']
        check(
            'PS2-05: block-based problem includes structured body HTML',
            '<strong>body</strong>' in block_payload.get('problem_body_html', '')
            and 'block-slice2.png' in block_payload.get('problem_body_html', ''),
        )
        check(
            'PS2-06: structured body HTML does not fall back to old prompt text',
            'Old prompt should not display' not in block_payload.get('problem_body_html', ''),
        )

        socket_client.disconnect()


if __name__ == '__main__':
    print('\nProblem System V1 Slice 2 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL PROBLEM SYSTEM SLICE 2 TESTS PASSED.')
    else:
        print('SOME PROBLEM SYSTEM SLICE 2 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
