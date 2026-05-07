"""
Phase H2 Classic economy analytics tests.

Run:
    .venv\\Scripts\\python.exe tests\\test_analytics_h2.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.analytics import AnalyticsClassicEconomyEvent, AnalyticsPlayerRound
from app.models.classic import ClassicRoundConfig, PlayerProblemState, PlayerWallet, StealEvent, StoreItem
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic
from app.services.analytics import finalize_classic_round


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'analytics-h2-secret'
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


def _make_player(username, *, is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    return client.post('/login', data={'username': username, 'password': 'pass1234'}, follow_redirects=True)


def _event(received, name):
    for row in received:
        if row.get('name') == name:
            args = row.get('args') or [{}]
            return args[0] if args else {}
    return None


def _make_world(prefix, *, treasure=False, store=False, steal=False):
    topic = Topic(name=f'{prefix}_topic')
    db.session.add(topic)
    db.session.flush()
    problem = Problem(topic_id=topic.id, title=f'{prefix} Problem', prompt_text='2+2', answer_text='4', difficulty=1)
    db.session.add(problem)
    db.session.flush()
    pset = ProblemSet(name=f'{prefix} Set')
    db.session.add(pset)
    db.session.flush()
    pset.problems.append(problem)

    actor = _make_player(f'{prefix}_actor')
    target = _make_player(f'{prefix}_target') if steal else None
    session = GameSession(mode='classic', status='active', problem_set_id=pset.id)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=1, started_at=datetime.now(timezone.utc))
    db.session.add(game_round)
    db.session.flush()
    config = ClassicRoundConfig(
        round_id=game_round.id,
        mine_reward=20,
        treasure_search_reward=7,
        treasure_search_max_reward=7,
        attempts_per_problem=1,
        wrong_answer_penalty=0,
        bonus_timer_duration=0,
        bonus_timer_gold=0,
        first_solver_count=0,
        first_solver_multiplier=0,
        gem_milestone_count=0,
        gem_streak_count=0,
        gem_treasure_chance=1.0 if treasure else 0.0,
        steal_percent=0.5,
        steal_min_cap=1,
        steal_max_cap=50,
        steal_fallback_gold=3,
        steal_chest_count=0,
        steal_winning_chest_count=1,
        treasure_steal_token_chance=0.0,
        treasure_active_shield_chance=0.0,
        treasure_second_chance_chance=0.0,
    )
    db.session.add(config)
    db.session.add(RoundPlayer(session_id=session.id, player_id=actor.id))
    db.session.add(PlayerWallet(player_id=actor.id, session_id=session.id, gold=100 if store else 0, gems=0, steal_tokens=1))
    db.session.add(PlayerProblemState(player_id=actor.id, round_id=game_round.id, problem_id=problem.id))
    if target:
        db.session.add(RoundPlayer(session_id=session.id, player_id=target.id))
        db.session.add(PlayerWallet(player_id=target.id, session_id=session.id, gold=40, gems=0, steal_tokens=1))
    item = None
    if store:
        item = StoreItem(
            session_id=session.id,
            name=f'{prefix} Pickaxe',
            description='H2 store test',
            cost=15,
            currency='gold',
            bonus_type='x2_mine',
            session_stock=-1,
            per_player_limit=-1,
            is_system=False,
        )
        db.session.add(item)
    db.session.commit()
    return {
        'session_id': session.id,
        'round_id': game_round.id,
        'problem_id': problem.id,
        'actor_username': actor.username,
        'actor_id': actor.id,
        'target_id': target.id if target else None,
        'item_id': item.id if item else None,
    }


def _solve_and_choose(ids, action):
    with flask_app.test_client() as client:
        _login(client, ids['actor_username'])
        sock = socketio.test_client(flask_app, flask_test_client=client)
        sock.emit('classic_submit_answer', {
            'session_id': ids['session_id'],
            'problem_id': ids['problem_id'],
            'answer_text': '4',
        })
        sock.get_received()
        sock.emit('classic_choose_action', {
            'session_id': ids['session_id'],
            'problem_id': ids['problem_id'],
            'action': action,
        })
        received = sock.get_received()
        return sock, received


def test_mine_event_and_summary():
    with flask_app.app_context():
        ids = _make_world('__h2_mine')
    sock, _ = _solve_and_choose(ids, 'mine')
    sock.disconnect()
    with flask_app.app_context():
        row = AnalyticsClassicEconomyEvent.query.filter_by(round_id=ids['round_id'], event_type='mine_success').first()
        check('H2-01 mine event recorded', row is not None)
        check('H2-02 mine event has positive gold delta', row and row.gold_delta_actor == 20)
        check('H2-03 mine links answer/problem', row and row.linked_answer_attempt_id is not None and row.problem_id == ids['problem_id'])
        game_round = db.session.get(GameRound, ids['round_id'])
        game_round.ended_at = datetime.now(timezone.utc)
        finalize_classic_round(game_round)
        finalize_classic_round(game_round)
        db.session.commit()
        pr = AnalyticsPlayerRound.query.filter_by(round_id=ids['round_id'], player_id=ids['actor_id']).first()
        summary = (pr.summary_json or {}).get('classic_economy', {}) if pr else {}
        check('H2-04 summary counts mined gold without duplicate end-round events', summary.get('gold_mined') == 20)


def test_steal_success_event_keeps_existing_steal_event():
    with flask_app.app_context():
        ids = _make_world('__h2_steal', steal=True)
    sock, received = _solve_and_choose(ids, 'steal')
    check('H2-05 steal target prompt emitted', _event(received, 'steal_targets') is not None)
    sock.emit('classic_steal_pick_target', {'session_id': ids['session_id'], 'target_player_id': ids['target_id']})
    sock.get_received()
    sock.disconnect()
    with flask_app.app_context():
        row = AnalyticsClassicEconomyEvent.query.filter_by(round_id=ids['round_id'], event_type='steal_success').first()
        check('H2-06 steal success event recorded', row is not None)
        check('H2-07 steal event records actor gain and target loss', row and row.gold_delta_actor == 20 and row.gold_delta_target == -20)
        check('H2-08 existing StealEvent still written', StealEvent.query.filter_by(round_id=ids['round_id'], outcome='targeted_success').count() == 1)


def test_treasure_and_store_events():
    with flask_app.app_context():
        treasure_ids = _make_world('__h2_treasure', treasure=True)
    sock, received = _solve_and_choose(treasure_ids, 'treasure_search')
    offer = _event(received, 'treasure_chest_offer')
    chest = (offer or {}).get('chests', [{}])[0].get('index', 1)
    sock.emit('classic_treasure_pick_chest', {'session_id': treasure_ids['session_id'], 'chest_index': chest})
    sock.get_received()
    sock.disconnect()
    with flask_app.app_context():
        gold = AnalyticsClassicEconomyEvent.query.filter_by(round_id=treasure_ids['round_id'], event_type='treasure_gold').first()
        pick = AnalyticsClassicEconomyEvent.query.filter_by(round_id=treasure_ids['round_id'], event_type='treasure_pick').first()
        bonus = AnalyticsClassicEconomyEvent.query.filter_by(round_id=treasure_ids['round_id'], event_type='treasure_bonus').first()
        check('H2-09 treasure gold event recorded', gold is not None and gold.gold_delta_actor == 7)
        check('H2-10 treasure pick event recorded', pick is not None)
        check('H2-11 treasure bonus event recorded for filled gem chest', bonus is not None and bonus.gems_delta_actor == 1)

        store_ids = _make_world('__h2_store', store=True)
    with flask_app.test_client() as client:
        _login(client, store_ids['actor_username'])
        sock = socketio.test_client(flask_app, flask_test_client=client)
        sock.emit('classic_buy_item', {'session_id': store_ids['session_id'], 'item_id': store_ids['item_id']})
        sock.get_received()
        sock.disconnect()
    with flask_app.app_context():
        store_row = AnalyticsClassicEconomyEvent.query.filter_by(round_id=store_ids['round_id'], event_type='store_purchase').first()
        check('H2-12 store purchase event recorded', store_row is not None)
        check('H2-13 store purchase records negative gold delta', store_row and store_row.gold_delta_actor == -15)


def run_tests():
    with flask_app.app_context():
        db.create_all()
    test_mine_event_and_summary()
    test_steal_success_event_keeps_existing_steal_event()
    test_treasure_and_store_events()


if __name__ == '__main__':
    print('\nPhase H2 Classic Economy Analytics Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL H2 CLASSIC ECONOMY TESTS PASSED.')
    else:
        print('SOME H2 CLASSIC ECONOMY TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
