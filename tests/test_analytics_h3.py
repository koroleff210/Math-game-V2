"""
Phase H3 Boss Rush battle analytics tests.

Run:
    .venv\\Scripts\\python.exe tests\\test_analytics_h3.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.analytics import AnalyticsAnswerAttempt, AnalyticsBossRushBattleEvent
from app.models.boss_rush import BossRushBattleState, BossRushPlayerState, BossRushRoundConfig
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic
from app.modes.boss_rush.engine import (
    finalize_boss_rush_rewards,
    initialize_player_state,
    submit_current_answer,
    trigger_boss_ability,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'analytics-h3-secret'
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
            msg += f' ({detail})'
        print(msg)
        failed += 1


def _make_player(username, *, is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _make_problem_set(prefix, answer):
    topic = Topic(name=f'{prefix}_topic')
    db.session.add(topic)
    db.session.flush()
    problem = Problem(
        topic_id=topic.id,
        title=f'{prefix} Problem',
        prompt_text=f'{prefix} prompt',
        answer_text=answer,
        difficulty=1,
    )
    db.session.add(problem)
    db.session.flush()
    pset = ProblemSet(
        name=f'{prefix} Set',
        usable_in_boss_rush=True,
        usable_as_recovery=True,
    )
    db.session.add(pset)
    db.session.flush()
    pset.problems.append(problem)
    db.session.flush()
    return problem, pset


def _setup_round(prefix, *, boss_type='fire_giant', boss_hp=5, player_hp=3):
    db.session.remove()
    db.drop_all()
    db.create_all()

    player = _make_player(f'{prefix}_player')
    attack_problem, attack_set = _make_problem_set(f'{prefix}_attack', 'a')
    recovery_problem, recovery_set = _make_problem_set(f'{prefix}_recovery', 'r')
    session = GameSession(mode='boss_rush', status='active', problem_set_id=attack_set.id)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=1, started_at=datetime.now(timezone.utc))
    db.session.add(game_round)
    db.session.flush()
    config = BossRushRoundConfig(
        round_id=game_round.id,
        boss_type=boss_type,
        boss_name=boss_type.replace('_', ' ').title(),
        boss_max_hp=boss_hp,
        player_max_hp=player_hp,
        attack_problem_set_id=attack_set.id,
        recovery_problem_set_id=recovery_set.id,
        combo_bonus_threshold=5,
        combo_bonus_damage=1,
        ability_enabled=True,
        ability_interval_seconds=60,
        fire_burn_damage=1,
        fire_shield_max_stacks=1,
        stone_guard_combo_required=3,
        time_drain_damage=1,
    )
    battle = BossRushBattleState(
        round_id=game_round.id,
        current_boss_hp=boss_hp,
        status='active',
        next_ability_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    db.session.add_all([config, battle, RoundPlayer(session_id=session.id, player_id=player.id)])
    db.session.flush()
    state = initialize_player_state(game_round, player.id, config)
    state.current_problem_id = attack_problem.id
    state.current_problem_kind = 'attack'
    db.session.flush()
    return {
        'player': player,
        'session': session,
        'round': game_round,
        'config': config,
        'battle': battle,
        'state': state,
        'attack_problem': attack_problem,
        'recovery_problem': recovery_problem,
    }


def test_damage_defeat_and_rewards_events():
    ctx = _setup_round('__h3_damage', boss_hp=1)
    result = submit_current_answer(ctx['state'], ctx['config'], ctx['battle'], submitted_text='a')
    reward_result = finalize_boss_rush_rewards(ctx['session'], ctx['round'], ctx['config'], ctx['battle'])
    db.session.commit()

    damage = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='boss_damage').first()
    defeated = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='boss_defeated').first()
    rewards = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='boss_rewards_finalized').all()
    attempt_count = AnalyticsAnswerAttempt.query.filter_by(round_id=ctx['round'].id).count()
    check('H3-01 boss damage event records applied damage', damage is not None and damage.damage_applied == result['damage_dealt'] and damage.boss_hp_after == 0)
    check('H3-02 boss defeated event recorded', defeated is not None and defeated.linked_boss_rush_attempt_id == damage.linked_boss_rush_attempt_id)
    check('H3-03 reward finalized event is idempotent', len(rewards) == 1 and reward_result['finalized'])
    finalize_boss_rush_rewards(ctx['session'], ctx['round'], ctx['config'], ctx['battle'])
    db.session.commit()
    check('H3-04 repeated reward finalize does not duplicate event', AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='boss_rewards_finalized').count() == 1)
    check('H3-05 H1 answer attempt still captured', attempt_count == 1)


def test_blocked_wrong_and_recovery_events():
    ctx = _setup_round('__h3_blocked', boss_type='stone_golem', boss_hp=10, player_hp=1)
    ctx['battle'].stone_guard_active = True
    submit_current_answer(ctx['state'], ctx['config'], ctx['battle'], submitted_text='a')
    blocked = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='boss_damage_blocked').first()
    check('H3-06 stone guard blocked damage event recorded', blocked is not None and blocked.damage_applied == 0 and blocked.shield_or_guard_absorbed >= 1)

    ctx['state'].is_completed = False
    ctx['state'].is_observer = False
    ctx['state'].attack_solved_ids = []
    ctx['state'].current_problem_id = ctx['attack_problem'].id
    ctx['state'].current_problem_kind = 'attack'
    ctx['state'].hp = 1
    db.session.flush()
    submit_current_answer(ctx['state'], ctx['config'], ctx['battle'], submitted_text='wrong')
    hp_loss = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='player_hp_loss').order_by(AnalyticsBossRushBattleEvent.id.desc()).first()
    check('H3-07 wrong attack records player HP loss', hp_loss is not None and hp_loss.player_hp_before == 1 and hp_loss.player_hp_after == 0 and hp_loss.details_json.get('reason') == 'wrong_attack_answer')

    ctx['state'].current_problem_id = ctx['recovery_problem'].id
    ctx['state'].current_problem_kind = 'recovery'
    submit_current_answer(ctx['state'], ctx['config'], ctx['battle'], submitted_text='r')
    recovery = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='player_recovery_success').first()
    db.session.commit()
    check('H3-08 recovery success event recorded', recovery is not None and recovery.player_hp_before == 0 and recovery.player_hp_after == 1)


def test_ability_trigger_and_player_effect_events():
    ctx = _setup_round('__h3_ability', boss_type='fire_giant', boss_hp=10, player_hp=3)
    shielded = _make_player('__h3_ability_shielded')
    db.session.add(RoundPlayer(session_id=ctx['session'].id, player_id=shielded.id))
    db.session.flush()
    shielded_state = BossRushPlayerState(
        round_id=ctx['round'].id,
        player_id=shielded.id,
        hp=3,
        fire_shield_stacks=1,
        submitted_since_last_ability=False,
    )
    db.session.add(shielded_state)
    ctx['state'].submitted_since_last_ability = False
    db.session.flush()

    result = trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
    db.session.commit()
    trigger = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='boss_ability_trigger').first()
    effects = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='boss_ability_player_effect').all()
    hp_loss = AnalyticsBossRushBattleEvent.query.filter_by(round_id=ctx['round'].id, event_type='player_hp_loss', ability_key='fire_giant').first()
    shield_effect = [event for event in effects if event.player_id == shielded.id][0]
    check('H3-09 ability trigger event recorded', result['triggered'] and trigger is not None and trigger.ability_count == 1)
    check('H3-10 ability player effects recorded', len(effects) >= 2)
    check('H3-11 ability HP loss recorded separately', hp_loss is not None and hp_loss.player_hp_before == 3 and hp_loss.player_hp_after == 2)
    check('H3-12 shield absorption captured', shield_effect.shield_or_guard_absorbed == 1 and shield_effect.player_hp_after == 3)


def run_tests():
    with flask_app.app_context():
        test_damage_defeat_and_rewards_events()
        test_blocked_wrong_and_recovery_events()
        test_ability_trigger_and_player_effect_events()


if __name__ == '__main__':
    print('\nPhase H3 Boss Rush Battle Analytics Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL H3 BOSS RUSH BATTLE TESTS PASSED.')
    else:
        print('SOME H3 BOSS RUSH BATTLE TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
