"""
Boss Rush Phase 6 live ability socket tests.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.boss_rush import BossRushBattleState, BossRushRoundConfig
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic
from app.modes.boss_rush.engine import initialize_player_state


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-phase6-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False


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


def _setup_battle(*, due=True):
    db.session.remove()
    db.drop_all()
    db.create_all()

    player = _make_player('__br6_player__')
    topic = Topic(name='__br6_topic__')
    db.session.add(topic)
    db.session.flush()
    attack = Problem(topic_id=topic.id, title='Attack', prompt_text='Attack', answer_text='1', difficulty=1)
    recovery = Problem(topic_id=topic.id, title='Recovery', prompt_text='Recovery', answer_text='r1', difficulty=1)
    db.session.add_all([attack, recovery])
    db.session.flush()
    attack_set = ProblemSet(name='__br6_attack__', usable_in_boss_rush=True)
    recovery_set = ProblemSet(name='__br6_recovery__', usable_as_recovery=True)
    db.session.add_all([attack_set, recovery_set])
    db.session.flush()
    attack_set.problems.append(attack)
    recovery_set.problems.append(recovery)

    session = GameSession(mode='boss_rush', status='active', problem_set_id=attack_set.id)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=1, started_at=datetime.now(timezone.utc))
    db.session.add(game_round)
    db.session.flush()
    config = BossRushRoundConfig(
        round_id=game_round.id,
        boss_type='fire_giant',
        boss_name='Fire Giant',
        boss_max_hp=30,
        player_max_hp=3,
        attack_problem_set_id=attack_set.id,
        recovery_problem_set_id=recovery_set.id,
        ability_enabled=True,
        ability_interval_seconds=60,
        fire_burn_damage=1,
        fire_shield_max_stacks=1,
    )
    battle = BossRushBattleState(
        round_id=game_round.id,
        current_boss_hp=30,
        status='active',
        next_ability_at=datetime.now(timezone.utc) + (timedelta(seconds=-1) if due else timedelta(seconds=45)),
    )
    db.session.add_all([config, battle])
    db.session.flush()
    state = initialize_player_state(game_round, player.id, config)
    state.submitted_since_last_ability = False
    db.session.add(RoundPlayer(session_id=session.id, player_id=player.id))
    db.session.commit()
    return session, game_round, config, battle, player


def _state_updates(received):
    return [item['args'][0] for item in received if item['name'] == 'boss_rush_state_update']


def run_tests():
    with flask_app.app_context():
        session, game_round, config, battle, player = _setup_battle(due=True)
        with flask_app.test_client() as client:
            _login(client, player.username)
            socket_client = socketio.test_client(flask_app, flask_test_client=client)
            socket_client.emit('boss_rush_join', {'session_id': session.id})
            socket_client.get_received()
            socket_client.emit('boss_rush_check_ability', {'session_id': session.id})
            updates = _state_updates(socket_client.get_received())
            battle = db.session.get(BossRushBattleState, battle.id)
            check('BR6-01: check event triggers due ability once', battle.ability_count == 1 and battle.last_ability_summary_json)
            check('BR6-02: due check emits boss_rush_state_update to room', bool(updates) and updates[-1]['ability']['ability_count'] == 1)
            check('BR6-03: payload has fresh timer and recent ability data', updates[-1]['ability']['next_ability_at'] and updates[-1]['ability']['recent_event']['message'])
            check('BR6-04: payload includes player-specific active bonus data', 'active_bonuses' in updates[-1]['leaderboard'][0] and updates[-1]['leaderboard'][0]['active_bonuses']['personal_message'])

            socket_client.emit('boss_rush_check_ability', {'session_id': session.id})
            socket_client.get_received()
            battle = db.session.get(BossRushBattleState, battle.id)
            check('BR6-05: duplicate check does not double-trigger ability', battle.ability_count == 1)
            socket_client.disconnect()

        session, game_round, config, battle, player = _setup_battle(due=False)
        with flask_app.test_client() as client:
            _login(client, player.username)
            socket_client = socketio.test_client(flask_app, flask_test_client=client)
            socket_client.emit('boss_rush_join', {'session_id': session.id})
            socket_client.get_received()
            socket_client.emit('boss_rush_check_ability', {'session_id': session.id})
            updates = _state_updates(socket_client.get_received())
            battle = db.session.get(BossRushBattleState, battle.id)
            socket_client.disconnect()
            check('BR6-06: no ability triggers when not due', battle.ability_count == 0)
            check('BR6-07: non-due check returns current timing to requester', bool(updates) and updates[-1]['ability']['seconds_remaining'] > 0)


if __name__ == '__main__':
    print('\nBoss Rush Phase 6 Live Ability - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH PHASE 6 LIVE ABILITY TESTS PASSED.')
    else:
        print('SOME BOSS RUSH PHASE 6 LIVE ABILITY TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
