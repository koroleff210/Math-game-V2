"""
Boss Rush Phase 2 battle-loop tests.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.boss_rush import (
    BOSS_RUSH_ATTEMPT_ATTACK,
    BOSS_RUSH_ATTEMPT_RECOVERY,
    BossRushBattleState,
    BossRushPlayerState,
    BossRushRoundConfig,
)
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic
from app.modes.boss_rush.engine import (
    apply_boss_damage,
    get_current_problem,
    initialize_player_state,
    submit_current_answer,
    trigger_boss_ability,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-phase2-secret'
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


def _make_problem(topic, title, answer):
    problem = Problem(
        topic_id=topic.id,
        title=title,
        prompt_text=title,
        answer_text=answer,
        difficulty=1,
    )
    db.session.add(problem)
    db.session.flush()
    return problem


def _setup_battle(*, boss_hp=30, player_hp=3, threshold=5, bonus_damage=1, attack_count=2, recovery_count=1):
    db.session.remove()
    db.drop_all()
    db.create_all()

    player = _make_player(f'__boss_phase2_player_{attack_count}_{boss_hp}__')
    topic = Topic(name=f'__boss_phase2_topic_{attack_count}_{boss_hp}__')
    db.session.add(topic)
    db.session.flush()

    attack_problems = [
        _make_problem(topic, f'Attack {idx}', str(idx))
        for idx in range(1, attack_count + 1)
    ]
    recovery_problems = [
        _make_problem(topic, f'Recovery {idx}', f'r{idx}')
        for idx in range(1, recovery_count + 1)
    ]

    attack_set = ProblemSet(name=f'Attack Set {attack_count} {boss_hp}', usable_in_boss_rush=True)
    recovery_set = ProblemSet(name=f'Recovery Set {recovery_count} {boss_hp}', usable_as_recovery=True)
    db.session.add_all([attack_set, recovery_set])
    db.session.flush()
    for problem in attack_problems:
        attack_set.problems.append(problem)
    for problem in recovery_problems:
        recovery_set.problems.append(problem)
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
        boss_max_hp=boss_hp,
        player_max_hp=player_hp,
        attack_problem_set_id=attack_set.id,
        recovery_problem_set_id=recovery_set.id,
        combo_bonus_threshold=threshold,
        combo_bonus_damage=bonus_damage,
    )
    battle_state = BossRushBattleState(
        round_id=game_round.id,
        current_boss_hp=boss_hp,
        status='active',
    )
    db.session.add_all([config, battle_state])
    db.session.flush()
    state = initialize_player_state(game_round, player.id, config)
    db.session.commit()
    return {
        'player': player,
        'round': game_round,
        'config': config,
        'battle': battle_state,
        'state': state,
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
        state = ctx['state']
        config = ctx['config']
        battle = ctx['battle']
        problem = get_current_problem(state, config, battle)
        check('BR2-01: player initializes with full HP and attack pool', state.hp == 3 and problem and state.current_problem_kind == BOSS_RUSH_ATTEMPT_ATTACK)

        result = _answer_current(state, config, battle, ctx['attack_answers'], correct=True)
        check('BR2-02: correct attack deals damage and increases combo', result['is_correct'] and result['damage_dealt'] == 1 and state.damage_dealt == 1 and state.current_combo == 1 and battle.current_boss_hp == 29)

        result = _answer_current(state, config, battle, ctx['attack_answers'], correct=False)
        check('BR2-03: wrong attack reduces HP and resets combo', not result['is_correct'] and state.hp == 2 and state.current_combo == 0)

        ctx = _setup_battle(threshold=1, bonus_damage=2, attack_count=3)
        state = ctx['state']
        config = ctx['config']
        battle = ctx['battle']
        _answer_current(state, config, battle, ctx['attack_answers'], correct=True)
        result = _answer_current(state, config, battle, ctx['attack_answers'], correct=True)
        check('BR2-04: combo bonus applies when new combo exceeds threshold', result['damage_dealt'] == 3 and state.current_combo == 2 and state.damage_dealt == 4)

        ctx = _setup_battle(boss_hp=2, threshold=0, bonus_damage=5, attack_count=2)
        state = ctx['state']
        config = ctx['config']
        battle = ctx['battle']
        result = _answer_current(state, config, battle, ctx['attack_answers'], correct=True)
        later_damage = apply_boss_damage(battle, 5)
        check('BR2-05: boss HP never goes below zero and no later overkill applies', result['damage_dealt'] == 2 and battle.current_boss_hp == 0 and battle.is_defeated and later_damage == 0)

        ctx = _setup_battle(player_hp=1)
        state = ctx['state']
        config = ctx['config']
        battle = ctx['battle']
        _answer_current(state, config, battle, ctx['attack_answers'], correct=False)
        recovery_problem = get_current_problem(state, config, battle)
        result = submit_current_answer(state, config, battle, submitted_text=ctx['recovery_answers'][recovery_problem.id])
        check('BR2-06: recovery correct restores HP to 1 without damage', result['is_correct'] and state.hp == 1 and result['damage_dealt'] == 0 and state.damage_dealt == 0)

        ctx = _setup_battle(player_hp=1)
        state = ctx['state']
        config = ctx['config']
        battle = ctx['battle']
        _answer_current(state, config, battle, ctx['attack_answers'], correct=False)
        result = submit_current_answer(state, config, battle, submitted_text='__wrong__')
        check('BR2-07: recovery wrong keeps HP at 0 and resets combo', not result['is_correct'] and state.hp == 0 and state.current_combo == 0 and state.current_problem_kind == BOSS_RUSH_ATTEMPT_RECOVERY)

        ctx = _setup_battle(player_hp=5, attack_count=1)
        state = ctx['state']
        config = ctx['config']
        battle = ctx['battle']
        first_problem = get_current_problem(state, config, battle)
        _answer_current(state, config, battle, ctx['attack_answers'], correct=False)
        retry_problem = get_current_problem(state, config, battle)
        check('BR2-08: incorrect attack problems re-enter when never pool is empty', retry_problem and retry_problem.id == first_problem.id)

        ctx = _setup_battle(attack_count=1)
        state = ctx['state']
        config = ctx['config']
        battle = ctx['battle']
        _answer_current(state, config, battle, ctx['attack_answers'], correct=True)
        check('BR2-09: player becomes completed after solving all attacks', state.is_completed and state.is_observer and state.damage_dealt == 1)

        ctx = _setup_battle()
        battle = ctx['battle']
        config = ctx['config']
        first_state = ctx['state']
        _answer_current(first_state, config, battle, ctx['attack_answers'], correct=True)
        second_player = _make_player('__boss_phase2_mid_join__')
        second_state = initialize_player_state(ctx['round'], second_player.id, config)
        check('BR2-10: mid-game join initializes fresh state without resetting boss', second_state.hp == 3 and second_state.damage_dealt == 0 and battle.current_boss_hp == 29)

        ctx = _setup_battle(boss_hp=5, attack_count=1)
        player = ctx['player']
        db.session.add(RoundPlayer(session_id=ctx['round'].session_id, player_id=player.id))
        db.session.commit()
        with flask_app.test_client() as client:
            _login(client, player.username)
            r = client.get(f'/boss-rush/game/{ctx["round"].session_id}')
            state = BossRushPlayerState.query.filter_by(round_id=ctx['round'].id, player_id=player.id).first()
            answer = ctx['attack_answers'][state.current_problem_id]
            r = client.post(
                f'/boss-rush/game/{ctx["round"].session_id}/answer',
                data={'answer_text': answer},
                follow_redirects=True,
            )
            battle = db.session.get(BossRushBattleState, ctx['battle'].id)
            check('BR2-11: player route renders and accepts an attack answer', r.status_code == 200 and battle.current_boss_hp == 4 and 'You dealt 1 damage' in r.get_data(as_text=True))

        ctx = _setup_battle(player_hp=1)
        player = ctx['player']
        db.session.add(RoundPlayer(session_id=ctx['round'].session_id, player_id=player.id))
        db.session.commit()
        _answer_current(ctx['state'], ctx['config'], ctx['battle'], ctx['attack_answers'], correct=False)
        recovery_problem = get_current_problem(ctx['state'], ctx['config'], ctx['battle'])
        with flask_app.test_client() as client:
            _login(client, player.username)
            r = client.post(
                f'/boss-rush/game/{ctx["round"].session_id}/answer',
                data={'answer_text': ctx['recovery_answers'][recovery_problem.id]},
                follow_redirects=True,
            )
            html = r.get_data(as_text=True)
            check('BR2-12: recovery correct shows recovered feedback, not boss-defeated feedback', 'Recovered! HP restored to 1.' in html and 'boss is already defeated' not in html)

        ctx = _setup_battle(player_hp=1)
        player = ctx['player']
        db.session.add(RoundPlayer(session_id=ctx['round'].session_id, player_id=player.id))
        db.session.commit()
        _answer_current(ctx['state'], ctx['config'], ctx['battle'], ctx['attack_answers'], correct=False)
        with flask_app.test_client() as client:
            _login(client, player.username)
            r = client.post(
                f'/boss-rush/game/{ctx["round"].session_id}/answer',
                data={'answer_text': '__wrong__'},
                follow_redirects=True,
            )
            html = r.get_data(as_text=True)
            check('BR2-13: recovery wrong shows combo reset feedback', 'Not quite. Your combo reset.' in html)

        ctx = _setup_battle(attack_count=4)
        ctx['config'].boss_type = 'stone_golem'
        ctx['config'].stone_guard_combo_required = 3
        player = ctx['player']
        db.session.add(RoundPlayer(session_id=ctx['round'].session_id, player_id=player.id))
        trigger_boss_ability(ctx['round'], ctx['config'], ctx['battle'])
        db.session.commit()
        first_problem = get_current_problem(ctx['state'], ctx['config'], ctx['battle'])
        with flask_app.test_client() as client:
            _login(client, player.username)
            r = client.post(
                f'/boss-rush/game/{ctx["round"].session_id}/answer',
                data={'answer_text': ctx['attack_answers'][first_problem.id]},
                follow_redirects=True,
            )
            html = r.get_data(as_text=True)
            check('BR2-14: Stone Guard no-damage correct uses guard feedback', 'Stone Guard blocked the damage' in html and 'boss is already defeated' not in html)

        ctx = _setup_battle(boss_hp=0, attack_count=1)
        ctx['battle'].is_defeated = True
        player = ctx['player']
        db.session.add(RoundPlayer(session_id=ctx['round'].session_id, player_id=player.id))
        db.session.commit()
        with flask_app.test_client() as client:
            _login(client, player.username)
            r = client.post(
                f'/boss-rush/game/{ctx["round"].session_id}/answer',
                data={'answer_text': '1'},
                follow_redirects=True,
            )
            html = r.get_data(as_text=True)
            check('BR2-15: already defeated feedback only appears for defeated boss', 'The boss has already been defeated.' in html)


if __name__ == '__main__':
    print('\nBoss Rush Phase 2 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH PHASE 2 TESTS PASSED.')
    else:
        print('SOME BOSS RUSH PHASE 2 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
