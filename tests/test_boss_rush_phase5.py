"""
Boss Rush Phase 5 tactical ability tests.
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
from app.models.problems import Problem, ProblemSet, Topic
from app.modes.boss_rush.engine import (
    build_live_state_payload,
    get_current_problem,
    is_ability_frozen,
    initialize_player_state,
    process_due_ability,
    schedule_next_ability,
    submit_current_answer,
    trigger_boss_ability,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-phase5-secret'
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


def _make_player(username):
    player = Player(username=username)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _make_problem(topic, title, answer):
    problem = Problem(topic_id=topic.id, title=title, prompt_text=title, answer_text=answer, difficulty=1)
    db.session.add(problem)
    db.session.flush()
    return problem


def _setup_battle(*, boss_type='fire_giant', attack_count=4, recovery_count=2, boss_hp=30, player_count=2):
    db.session.remove()
    db.drop_all()
    db.create_all()

    topic = Topic(name=f'__br5_topic_{boss_type}__')
    db.session.add(topic)
    db.session.flush()
    attack_problems = [_make_problem(topic, f'Attack {idx}', str(idx)) for idx in range(1, attack_count + 1)]
    recovery_problems = [_make_problem(topic, f'Recovery {idx}', f'r{idx}') for idx in range(1, recovery_count + 1)]
    attack_set = ProblemSet(name=f'__br5_attack_{boss_type}__', usable_in_boss_rush=True)
    recovery_set = ProblemSet(name=f'__br5_recovery_{boss_type}__', usable_as_recovery=True)
    db.session.add_all([attack_set, recovery_set])
    db.session.flush()
    for problem in attack_problems:
        attack_set.problems.append(problem)
    for problem in recovery_problems:
        recovery_set.problems.append(problem)
    players = [_make_player(f'__br5_{boss_type}_{idx}__') for idx in range(player_count)]
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
        player_max_hp=3,
        attack_problem_set_id=attack_set.id,
        recovery_problem_set_id=recovery_set.id,
        combo_bonus_threshold=5,
        combo_bonus_damage=1,
        ability_enabled=True,
        ability_interval_seconds=60,
        fire_burn_damage=1,
        fire_shield_max_stacks=1,
        swamp_regen_amount=2,
        stone_guard_combo_required=3,
        time_drain_damage=1,
    )
    battle = BossRushBattleState(
        round_id=game_round.id,
        current_boss_hp=boss_hp,
        status='active',
        next_ability_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    db.session.add_all([config, battle])
    db.session.flush()
    states = [initialize_player_state(game_round, player.id, config) for player in players]
    db.session.commit()
    return {
        'session': session,
        'round': game_round,
        'config': config,
        'battle': battle,
        'players': players,
        'states': states,
        'attack_answers': {problem.id: problem.answer_text for problem in attack_problems},
        'recovery_answers': {problem.id: problem.answer_text for problem in recovery_problems},
    }


def _answer_current(state, config, battle, answer_map, *, correct=True):
    problem = get_current_problem(state, config, battle)
    answer = answer_map[problem.id] if correct else '__wrong__'
    return submit_current_answer(state, config, battle, submitted_text=answer)


def run_tests():
    with flask_app.app_context():
        ctx = _setup_battle()
        ctx['battle'].next_ability_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        result = process_due_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-01: ability schedule triggers when due', result['triggered'] and ctx['battle'].ability_count == 1 and ctx['battle'].next_ability_at is not None)

        ctx = _setup_battle()
        ctx['battle'].ability_frozen = True
        ctx['battle'].next_ability_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        result = process_due_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-01b: frozen ability prevents due trigger', not result['triggered'] and ctx['battle'].ability_count == 0 and ctx['battle'].next_ability_at is None and is_ability_frozen(ctx['battle']))

        ctx['battle'].ability_frozen = False
        schedule_next_ability(ctx['battle'], ctx['config'], now=datetime.now(timezone.utc))
        check('BR5-01c: resume ability resets next timer from now', ctx['battle'].next_ability_at is not None and ctx['battle'].next_ability_at > datetime.now(timezone.utc))

        ctx = _setup_battle()
        ctx['config'].ability_enabled = False
        ctx['battle'].next_ability_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        result = process_due_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-02: ability does not trigger when disabled', not result['triggered'] and ctx['battle'].next_ability_at is None)

        ctx = _setup_battle(boss_type='fire_giant')
        state = ctx['states'][0]
        _answer_current(state, ctx['config'], ctx['battle'], ctx['attack_answers'], correct=True)
        check('BR5-03: Fire correct attack grants Fire Shield', state.fire_shield_stacks == 1)
        hp_before = state.hp
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-04: Heat Wave consumes shield instead of HP', state.hp == hp_before and state.fire_shield_stacks == 0)
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-05: Heat Wave damages unshielded player', state.hp == hp_before - 1)
        state.hp = 1
        state.current_combo = 4
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        recovery_problem = get_current_problem(state, ctx['config'], ctx['battle'])
        wrong_recovery = submit_current_answer(state, ctx['config'], ctx['battle'], submitted_text='__wrong__')
        check('BR5-06: ability HP loss enters recovery and recovery wrong resets combo', state.hp == 0 and recovery_problem and not wrong_recovery['is_correct'] and state.current_combo == 0)

        ctx = _setup_battle(boss_type='swamp_monster', boss_hp=30)
        ctx['battle'].current_boss_hp = 20
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        healed_once = ctx['battle'].current_boss_hp
        ctx['battle'].current_boss_hp = 29
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-07: Swamp regen heals but caps at max HP', healed_once == 22 and ctx['battle'].current_boss_hp == 30)

        ctx = _setup_battle(boss_type='stone_golem', attack_count=4)
        state = ctx['states'][0]
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        first = _answer_current(state, ctx['config'], ctx['battle'], ctx['attack_answers'], correct=True)
        second = _answer_current(state, ctx['config'], ctx['battle'], ctx['attack_answers'], correct=True)
        third = _answer_current(state, ctx['config'], ctx['battle'], ctx['attack_answers'], correct=True)
        check('BR5-08: Stone Guard blocks below combo requirement', first['damage_dealt'] == 0 and second['damage_dealt'] == 0 and state.current_combo == 3)
        check('BR5-09: Stone Guard breaks at required combo and same answer damages', third['damage_dealt'] == 1 and not ctx['battle'].stone_guard_active)

        ctx = _setup_battle(boss_type='air_elemental')
        state = ctx['states'][0]
        original = get_current_problem(state, ctx['config'], ctx['battle'])
        state.current_combo = 2
        hp_before = state.hp
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-10: Air shuffle replaces attack problem and preserves HP/combo', state.current_problem_id != original.id and state.hp == hp_before and state.current_combo == 2)
        recovery_state = ctx['states'][1]
        recovery_state.hp = 0
        get_current_problem(recovery_state, ctx['config'], ctx['battle'])
        recovery_problem_id = recovery_state.current_problem_id
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-11: Air shuffle skips recovery players', recovery_state.current_problem_id == recovery_problem_id)
        payload = build_live_state_payload(ctx['session'], ctx['round'], ctx['config'], ctx['battle'])
        rows = {row['player_id']: row for row in payload['leaderboard']}
        check('BR5-11b: Wind Shuffle marks only affected attack players for refresh', rows[state.player_id]['problem_refresh_required'] and not rows[recovery_state.player_id]['problem_refresh_required'])

        ctx = _setup_battle(boss_type='mirror_phantom')
        state = ctx['states'][0]
        missed = get_current_problem(state, ctx['config'], ctx['battle'])
        submit_current_answer(state, ctx['config'], ctx['battle'], submitted_text='__wrong__')
        get_current_problem(state, ctx['config'], ctx['battle'])
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        reflected_id = state.current_problem_id
        result = submit_current_answer(state, ctx['config'], ctx['battle'], submitted_text=ctx['attack_answers'][reflected_id])
        check('BR5-12: Mirror reflects incorrect problem and solving it damages normally', reflected_id == missed.id and result['is_correct'] and result['damage_dealt'] == 1)
        clean_state = ctx['states'][1]
        get_current_problem(clean_state, ctx['config'], ctx['battle'])
        clean_problem = clean_state.current_problem_id
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-13: Mirror has no effect on players with no incorrect pool', clean_state.current_problem_id == clean_problem)

        ctx = _setup_battle(boss_type='time_wraith')
        active_state, idle_state = ctx['states']
        idle_state.submitted_since_last_ability = False
        _answer_current(active_state, ctx['config'], ctx['battle'], ctx['attack_answers'], correct=False)
        active_hp = active_state.hp
        idle_hp = idle_state.hp
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-14: Time Wraith marks submitting player safe and damages inactive', active_state.hp == active_hp and idle_state.hp == idle_hp - 1)
        check('BR5-15: Time Wraith resets activity flags after trigger', not active_state.submitted_since_last_ability and not idle_state.submitted_since_last_ability)

        ctx = _setup_battle(boss_type='time_wraith')
        ctx['states'][0].is_completed = True
        ctx['states'][0].is_observer = True
        ctx['states'][0].submitted_since_last_ability = False
        hp_before = ctx['states'][0].hp
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-16: completed observers are unaffected by abilities', ctx['states'][0].hp == hp_before)

        payload = build_live_state_payload(ctx['session'], ctx['round'], ctx['config'], ctx['battle'])
        check('BR5-17: ability state and active bonuses appear in payload', 'ability' in payload and 'active_bonuses' in payload['leaderboard'][0])
        check('BR5-18: ability payload exposes frozen status', 'frozen' in payload['ability'])


if __name__ == '__main__':
    print('\nBoss Rush Phase 5 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH PHASE 5 TESTS PASSED.')
    else:
        print('SOME BOSS RUSH PHASE 5 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
