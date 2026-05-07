"""
Boss Rush Phase 4 live-state payload tests.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.boss_rush import BossRushBattleState, BossRushPlayerState, BossRushRoundConfig
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import ProblemSet
from app.modes.boss_rush.engine import build_live_state_payload


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-phase4-secret'
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


def _make_player(username):
    player = Player(username=username)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    return client.post('/login', data={'username': username, 'password': 'pass1234'}, follow_redirects=True)


def _setup_live_state():
    db.session.remove()
    db.drop_all()
    db.create_all()

    players = [_make_player('__br4_a__'), _make_player('__br4_b__'), _make_player('__br4_c__')]
    attack_set = ProblemSet(name='__br4_attack__', usable_in_boss_rush=True)
    recovery_set = ProblemSet(name='__br4_recovery__', usable_as_recovery=True)
    db.session.add_all([attack_set, recovery_set])
    db.session.flush()
    session = GameSession(mode='boss_rush', status='active', problem_set_id=attack_set.id)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=1)
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
        combo_bonus_threshold=5,
        combo_bonus_damage=1,
    )
    battle = BossRushBattleState(
        round_id=game_round.id,
        current_boss_hp=12,
        status='active',
        is_defeated=False,
    )
    db.session.add_all([config, battle])
    db.session.flush()
    now = datetime.now(timezone.utc)
    states = [
        BossRushPlayerState(round_id=game_round.id, player_id=players[0].id, hp=3, damage_dealt=5, current_combo=6, max_combo=6, correct_count=6, incorrect_count=0, last_contribution_at=now + timedelta(seconds=20)),
        BossRushPlayerState(round_id=game_round.id, player_id=players[1].id, hp=0, damage_dealt=5, current_combo=0, max_combo=5, correct_count=5, incorrect_count=0, last_contribution_at=now + timedelta(seconds=10)),
        BossRushPlayerState(round_id=game_round.id, player_id=players[2].id, hp=2, damage_dealt=2, current_combo=1, max_combo=2, correct_count=2, incorrect_count=1, last_contribution_at=now + timedelta(seconds=30)),
    ]
    states[2].is_completed = True
    states[2].is_observer = True
    db.session.add_all(states)
    db.session.add(RoundPlayer(session_id=session.id, player_id=players[0].id))
    db.session.commit()
    return session, game_round, config, battle, players


def run_tests():
    with flask_app.app_context():
        session, game_round, config, battle, players = _setup_live_state()
        payload = build_live_state_payload(session, game_round, config, battle)
        leaderboard = payload['leaderboard']
        check('BR4-01: payload includes boss HP/status', payload['boss']['hp'] == 12 and payload['boss']['max_hp'] == 30 and payload['boss']['status'] == 'active')
        check('BR4-02: leaderboard ranks damage then max combo', leaderboard[0]['player_id'] == players[0].id and leaderboard[1]['player_id'] == players[1].id)
        check('BR4-03: combo bonus flag/label is exposed', leaderboard[0]['combo_bonus']['active'] and '+1 dmg' in leaderboard[0]['combo_bonus']['label'])
        check('BR4-04: HP hearts are exposed', len(leaderboard[1]['hp_hearts']) == 3 and not any(heart['filled'] for heart in leaderboard[1]['hp_hearts']))
        check('BR4-05: player status labels are exposed', leaderboard[1]['status'] == 'recovery' and leaderboard[2]['status'] == 'completed')
        check('BR4-06: active bonuses placeholder is present', payload['active_bonuses']['placeholder'] == 'No active bonuses' and payload['active_bonuses']['items'] == [])

        battle.is_defeated = True
        battle.current_boss_hp = 0
        battle.status = 'defeated'
        db.session.commit()
        payload = build_live_state_payload(session, game_round, config, battle)
        check('BR4-07: defeated state is included', payload['boss']['defeated'] and payload['leaderboard'][0]['status'] == 'defeated')

        with flask_app.test_client() as client:
            _login(client, players[0].username)
            socket_client = socketio.test_client(flask_app, flask_test_client=client)
            socket_client.emit('boss_rush_join', {'session_id': session.id})
            received = socket_client.get_received()
            socket_client.disconnect()
            check(
                'BR4-08: socket join receives Boss Rush state update',
                any(item['name'] == 'boss_rush_state_update' and item['args'][0]['session_id'] == session.id for item in received),
            )


if __name__ == '__main__':
    print('\nBoss Rush Phase 4 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH PHASE 4 TESTS PASSED.')
    else:
        print('SOME BOSS RUSH PHASE 4 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
