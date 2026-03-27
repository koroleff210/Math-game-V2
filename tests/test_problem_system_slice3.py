"""
Problem System V1 - Slice 3 focused tests.

Verifies:
  - multiple-choice options live under Problem
  - admin can author multiple-choice options and set one correct answer
  - Classic join payload exposes answer_type + option IDs
  - Classic submit validates multiple choice by option ID
  - existing text-input flow still works
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.player import Player
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    Problem,
    ProblemChoiceOption,
    ProblemSet,
    Topic,
)
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.classic import ClassicRoundConfig, PlayerClassicState, PlayerWallet
from app.core.problem_engine import check_answer


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'problem-slice3-secret'
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

        admin = _make_player('__ps3_admin__', is_admin=True)
        player = _make_player('__ps3_player__')
        topic = Topic(name='__ps3_topic__', subject='Test')
        db.session.add(topic)
        db.session.flush()

        text_problem = Problem(
            topic_id=topic.id,
            title='Text Problem Slice3',
            prompt_text='Type the answer',
            answer_text='alpha',
            difficulty=1,
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
        )
        db.session.add(text_problem)
        db.session.flush()

        mc_problem = Problem(
            topic_id=topic.id,
            title='MC Problem Slice3',
            prompt_text='Select the correct option',
            answer_text='legacy fallback ignored',
            difficulty=1,
            answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
        )
        db.session.add(mc_problem)
        db.session.flush()
        db.session.add_all([
            ProblemChoiceOption(
                problem_id=mc_problem.id,
                position=1,
                option_text='Wrong $x$',
                is_correct=False,
            ),
            ProblemChoiceOption(
                problem_id=mc_problem.id,
                position=2,
                option_text='Correct **y**',
                is_correct=True,
            ),
            ProblemChoiceOption(
                problem_id=mc_problem.id,
                position=3,
                option_text='Wrong $z$',
                is_correct=False,
            ),
        ])

        admin_problem = Problem(
            topic_id=topic.id,
            title='Admin MC Problem Slice3',
            prompt_text='Admin-edit target',
            answer_text='legacy admin answer',
            difficulty=1,
            answer_type=PROBLEM_ANSWER_TYPE_TEXT_INPUT,
        )
        db.session.add(admin_problem)
        db.session.flush()

        problem_set = ProblemSet(name='__ps3_set__')
        db.session.add(problem_set)
        db.session.flush()
        problem_set.problems.append(text_problem)
        problem_set.problems.append(mc_problem)
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

        db.session.add(ClassicRoundConfig(round_id=game_round.id, attempts_per_problem=2))
        db.session.add(RoundPlayer(session_id=game_session.id, player_id=player.id))
        db.session.add(PlayerWallet(player_id=player.id, session_id=game_session.id, gold=0, gems=0, steal_tokens=0))
        db.session.add(PlayerClassicState(player_id=player.id, session_id=game_session.id))
        db.session.commit()

        return {
            'session_id': game_session.id,
            'mc_problem_id': mc_problem.id,
            'admin_problem_id': admin_problem.id,
        }


def run_tests():
    ids = _setup_db()

    with flask_app.app_context():
        mc_problem = db.session.get(Problem, ids['mc_problem_id'])
        correct_option = next(option for option in mc_problem.choice_options if option.is_correct)
        wrong_option = next(option for option in mc_problem.choice_options if not option.is_correct)
        check(
            'PS3-01: check_answer validates multiple choice by option ID',
            check_answer(mc_problem, None, selected_option_id=correct_option.id) is True
            and check_answer(mc_problem, None, selected_option_id=wrong_option.id) is False,
        )

    with flask_app.test_client() as admin_client:
        _login(admin_client, '__ps3_admin__')

        r = admin_client.get(f'/admin/problems/{ids["admin_problem_id"]}/content')
        html = r.get_data(as_text=True)
        check(
            'PS3-02: admin content page exposes multiple-choice authoring controls',
            r.status_code == 200
            and 'Answer Type' in html
            and 'name="answer_type"' in html
            and 'value="multiple_choice"' in html,
        )

        admin_client.post(
            f'/admin/problems/{ids["admin_problem_id"]}/choices/add',
            data={},
            follow_redirects=True,
        )
        admin_client.post(
            f'/admin/problems/{ids["admin_problem_id"]}/choices/add',
            data={},
            follow_redirects=True,
        )

        with flask_app.app_context():
            admin_problem = db.session.get(Problem, ids['admin_problem_id'])
            option_ids = [option.id for option in sorted(admin_problem.choice_options, key=lambda row: row.position)]

        r = admin_client.post(
            f'/admin/problems/{ids["admin_problem_id"]}/content',
            data={
                'answer_type': 'multiple_choice',
                'accepted_answers_text': 'should be ignored',
                'correct_option_id': str(option_ids[1]),
                f'choice_{option_ids[0]}_option_text': 'Option A',
                f'choice_{option_ids[1]}_option_text': 'Option B $x$',
            },
            follow_redirects=True,
        )
        check(
            'PS3-03: admin can save multiple-choice options with one correct selection',
            r.status_code == 200 and 'Problem content for' in r.get_data(as_text=True),
        )

        with flask_app.app_context():
            admin_problem = db.session.get(Problem, ids['admin_problem_id'])
            ordered = sorted(admin_problem.choice_options, key=lambda row: row.position)
            check(
                'PS3-04: saved problem stores MC answer type and exactly one correct option',
                admin_problem.answer_type == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE
                and len(ordered) == 2
                and [row.option_text for row in ordered] == ['Option A', 'Option B $x$']
                and sum(1 for row in ordered if row.is_correct) == 1
                and ordered[1].is_correct,
            )

        r = admin_client.post(
            f'/admin/problems/{ids["admin_problem_id"]}/content',
            data={
                'answer_type': 'multiple_choice',
                f'choice_{option_ids[0]}_option_text': 'Option A',
                f'choice_{option_ids[1]}_option_text': 'Option B',
            },
            follow_redirects=True,
        )
        check(
            'PS3-05: admin save rejects MC content without a selected correct option',
            r.status_code == 200 and 'Select exactly one correct multiple-choice option.' in r.get_data(as_text=True),
        )

    with flask_app.test_client() as player_client:
        _login(player_client, '__ps3_player__')

        r = player_client.get(f'/classic/game/{ids["session_id"]}')
        game_html = r.get_data(as_text=True)
        check(
            'PS3-06: classic game page includes MC answer container',
            r.status_code == 200 and 'mc-answer-section' in game_html and 'selected_option_id' in game_html,
        )

        socket_client = socketio.test_client(flask_app, flask_test_client=player_client)
        check('PS3-07: socket test client connected', socket_client.is_connected())

        socket_client.emit('classic_join', {'session_id': ids['session_id']})
        received = socket_client.get_received()
        join_ack = next((event for event in received if event['name'] == 'join_ack'), None)
        check('PS3-08: classic_join returns join_ack for Slice 3 test session', join_ack is not None)

        payload = join_ack['args'][0]
        problem_map = {row['title']: row for row in payload['problem_list']}
        mc_payload = problem_map['MC Problem Slice3']
        text_payload = problem_map['Text Problem Slice3']

        check(
            'PS3-09: join payload includes MC answer type and option IDs',
            mc_payload['answer_type'] == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE
            and len(mc_payload['choice_options']) == 3
            and all(option['id'] for option in mc_payload['choice_options']),
        )
        check(
            'PS3-10: join payload preserves text-input problems unchanged',
            text_payload['answer_type'] == PROBLEM_ANSWER_TYPE_TEXT_INPUT and text_payload['choice_options'] == [],
        )

        wrong_mc_option = next(option for option in mc_payload['choice_options'] if option['position'] == 1)
        correct_mc_option = next(option for option in mc_payload['choice_options'] if option['position'] == 2)

        socket_client.emit(
            'classic_submit_answer',
            {
                'session_id': ids['session_id'],
                'problem_id': mc_payload['problem_id'],
                'selected_option_id': wrong_mc_option['id'],
            },
        )
        wrong_events = socket_client.get_received()
        wrong_result = next((event for event in wrong_events if event['name'] == 'answer_result'), None)
        check(
            'PS3-11: wrong MC submission returns answer_result',
            wrong_result is not None and wrong_result['args'][0]['correct'] is False,
        )

        socket_client.emit(
            'classic_submit_answer',
            {
                'session_id': ids['session_id'],
                'problem_id': mc_payload['problem_id'],
                'selected_option_id': correct_mc_option['id'],
            },
        )
        correct_events = socket_client.get_received()
        mc_prompt = next((event for event in correct_events if event['name'] == 'choose_action_prompt'), None)
        check(
            'PS3-12: correct MC submission returns choose_action_prompt',
            mc_prompt is not None and mc_prompt['args'][0]['problem_id'] == mc_payload['problem_id'],
        )

        socket_client.emit(
            'classic_submit_answer',
            {
                'session_id': ids['session_id'],
                'problem_id': text_payload['problem_id'],
                'answer_text': ' alpha ',
            },
        )
        text_events = socket_client.get_received()
        text_prompt = next((event for event in text_events if event['name'] == 'choose_action_prompt'), None)
        check(
            'PS3-13: existing text-input submission flow still works',
            text_prompt is not None and text_prompt['args'][0]['problem_id'] == text_payload['problem_id'],
        )

        socket_client.disconnect()


if __name__ == '__main__':
    print('\nProblem System V1 Slice 3 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL PROBLEM SYSTEM SLICE 3 TESTS PASSED.')
    else:
        print('SOME PROBLEM SYSTEM SLICE 3 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
