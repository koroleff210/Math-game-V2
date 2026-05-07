"""
Boss Rush Phase 3 reward finalization tests.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.boss_rush import BossRushBattleState, BossRushPlayerState, BossRushRoundConfig
from app.models.game import GameRound, GameSession
from app.models.player import Player
from app.models.problems import ProblemSet
from app.models.progression import DiamondTransaction, PlayerProgression
from app.modes.boss_rush.engine import calculate_final_rewards, finalize_boss_rush_rewards


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-phase3-secret'
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


def _setup_defeated_round():
    db.session.remove()
    db.drop_all()
    db.create_all()

    admin = _make_player('__br3_admin__', is_admin=True)
    players = [
        _make_player('__br3_p1__'),
        _make_player('__br3_p2__'),
        _make_player('__br3_p3__'),
        _make_player('__br3_p4__'),
        _make_player('__br3_p5__'),
    ]
    attack_set = ProblemSet(name='__br3_attack__', usable_in_boss_rush=True)
    recovery_set = ProblemSet(name='__br3_recovery__', usable_as_recovery=True)
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
        first_place_diamonds=5,
        second_place_diamonds=4,
        third_place_diamonds=3,
        other_participant_diamonds=1,
        highest_combo_diamonds=5,
    )
    battle = BossRushBattleState(
        round_id=game_round.id,
        current_boss_hp=0,
        status='defeated',
        is_defeated=True,
        defeated_at=datetime.now(timezone.utc),
    )
    db.session.add_all([config, battle])
    db.session.flush()

    now = datetime.now(timezone.utc)
    rows = [
        BossRushPlayerState(round_id=game_round.id, player_id=players[0].id, hp=3, damage_dealt=10, max_combo=5, correct_count=5, incorrect_count=5, last_contribution_at=now + timedelta(seconds=10)),
        BossRushPlayerState(round_id=game_round.id, player_id=players[1].id, hp=3, damage_dealt=10, max_combo=5, correct_count=4, incorrect_count=0, last_contribution_at=now + timedelta(seconds=20)),
        BossRushPlayerState(round_id=game_round.id, player_id=players[2].id, hp=3, damage_dealt=7, max_combo=2, correct_count=7, incorrect_count=0, last_contribution_at=now + timedelta(seconds=30)),
        BossRushPlayerState(round_id=game_round.id, player_id=players[3].id, hp=3, damage_dealt=3, max_combo=1, correct_count=3, incorrect_count=0, last_contribution_at=now + timedelta(seconds=40)),
        BossRushPlayerState(round_id=game_round.id, player_id=players[4].id, hp=3, damage_dealt=0, max_combo=5, correct_count=0, incorrect_count=0, last_contribution_at=None),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return {
        'admin': admin,
        'players': players,
        'session': session,
        'round': game_round,
        'config': config,
        'battle': battle,
        'states': rows,
    }


def _entry(snapshot, player):
    for entry in snapshot['entries']:
        if entry['player_id'] == player.id:
            return entry
    return None


def run_tests():
    with flask_app.app_context():
        ctx = _setup_defeated_round()
        snapshot = calculate_final_rewards(ctx['states'], ctx['config'])
        p1, p2, p3, p4, p5 = ctx['players']
        e1 = _entry(snapshot, p1)
        e2 = _entry(snapshot, p2)
        e3 = _entry(snapshot, p3)
        e4 = _entry(snapshot, p4)
        e5 = _entry(snapshot, p5)

        check('BR3-01: placement ranking uses damage then max combo then accuracy', e2['rank'] == 1 and e1['rank'] == 2 and e3['rank'] == 3)
        check('BR3-02: highest combo reward is shared by all tied damage players', e1['breakdown']['highest_combo'] == 5 and e2['breakdown']['highest_combo'] == 5)
        check('BR3-03: other participant requires damage and excludes top three', e4['breakdown']['other_participant'] == 1 and e3['breakdown']['other_participant'] == 0 and e5['breakdown']['other_participant'] == 0)
        check('BR3-04: placement and highest combo rewards combine', e2['total_diamonds'] == 10 and e1['total_diamonds'] == 9)

        unbeaten = _setup_defeated_round()
        unbeaten['battle'].is_defeated = False
        unbeaten['battle'].current_boss_hp = 1
        db.session.commit()
        raised = False
        try:
            finalize_boss_rush_rewards(unbeaten['session'], unbeaten['round'], unbeaten['config'], unbeaten['battle'], admin_player_id=unbeaten['admin'].id)
        except ValueError:
            raised = True
            db.session.rollback()
        check('BR3-05: finalization requires boss defeat', raised)

        ctx = _setup_defeated_round()
        result = finalize_boss_rush_rewards(ctx['session'], ctx['round'], ctx['config'], ctx['battle'], admin_player_id=ctx['admin'].id)
        db.session.commit()
        txs = DiamondTransaction.query.filter_by(session_id=ctx['session'].id, reason=f'boss_rush_reward:{ctx["round"].id}').all()
        balances = {}
        for player in ctx['players']:
            progression = PlayerProgression.query.filter_by(player_id=player.id).first()
            balances[player.username] = progression.diamonds_balance if progression else 0
        check('BR3-06: finalization writes diamond transactions', result['finalized'] and len(txs) == 4)
        check('BR3-07: finalized balances match reward totals', balances['__br3_p2__'] == 10 and balances['__br3_p1__'] == 9 and balances['__br3_p5__'] == 0)
        check('BR3-08: finalized marker and minimal snapshot persist', ctx['battle'].rewards_finalized_at is not None and bool(ctx['battle'].final_rewards_json.get('entries')))

        result2 = finalize_boss_rush_rewards(ctx['session'], ctx['round'], ctx['config'], ctx['battle'], admin_player_id=ctx['admin'].id)
        db.session.commit()
        tx_count_after = DiamondTransaction.query.filter_by(session_id=ctx['session'].id, reason=f'boss_rush_reward:{ctx["round"].id}').count()
        check('BR3-09: finalization is idempotent', result2['already_finalized'] and tx_count_after == len(txs))

        ctx = _setup_defeated_round()
        with flask_app.test_client() as client:
            _login(client, ctx['admin'].username)
            r = client.get(f'/admin/boss-rush/{ctx["session"].id}/manage')
            html = r.get_data(as_text=True)
            check('BR3-10: defeated manage page offers finalize before finalization', r.status_code == 200 and 'Finalize Rewards' in html and 'Pending Reward Preview' in html)
            client.post(f'/admin/boss-rush/{ctx["session"].id}/finalize', follow_redirects=True)
            r = client.get(f'/admin/boss-rush/{ctx["session"].id}/manage')
            html = r.get_data(as_text=True)
            check('BR3-11: finalized manage page hides duplicate button and shows summary', 'Finalize Rewards' not in html and 'Final Rewards' in html)


if __name__ == '__main__':
    print('\nBoss Rush Phase 3 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH PHASE 3 TESTS PASSED.')
    else:
        print('SOME BOSS RUSH PHASE 3 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
