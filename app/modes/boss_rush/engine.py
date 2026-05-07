# app/modes/boss_rush/engine.py
#
# Boss Rush battle helpers. These functions are deliberately mode-specific:
# Classic runtime state stays separate, and persistent rewards are deferred.

import random
from datetime import datetime, timedelta, timezone

from app.core.problem_engine import check_answer
from app.extensions import db
from app.models.boss_rush import (
    BOSS_RUSH_ATTEMPT_ATTACK,
    BOSS_RUSH_ATTEMPT_RECOVERY,
    BOSS_RUSH_STATUS_ACTIVE,
    BOSS_RUSH_STATUS_DEFEATED,
    BOSS_RUSH_STATUS_ENDED,
    BOSS_RUSH_STATUS_WAITING,
    BossRushBattleState,
    BossRushPlayerState,
    BossRushProblemAttempt,
)
from app.models.problems import Problem
from app.services.analytics import (
    boss_rush_battle_event_key,
    ensure_player_problem,
    ensure_player_round,
    latest_boss_rush_answer_attempt,
    record_answer_attempt,
    record_boss_rush_battle_event,
)
from app.services.progression import award_diamonds_to_player

BOSS_RUSH_MODE = 'boss_rush'

DEFAULT_BOSS_RUSH_SETTINGS = {
    'boss_max_hp': 30,
    'player_max_hp': 3,
    'first_place_diamonds': 5,
    'second_place_diamonds': 4,
    'third_place_diamonds': 3,
    'other_participant_diamonds': 1,
    'highest_combo_diamonds': 5,
    'combo_bonus_threshold': 5,
    'combo_bonus_damage': 1,
    'ability_enabled': True,
    'ability_interval_seconds': 60,
    'fire_burn_damage': 1,
    'fire_shield_max_stacks': 1,
    'swamp_regen_amount': 2,
    'stone_guard_combo_required': 3,
    'time_drain_damage': 1,
}

BOSS_TYPE_CATALOG = {
    'fire_giant': {
        'label': 'Fire Giant',
        'image_path': 'boss_rush/bosses/fire_boss.png',
    },
    'stone_golem': {
        'label': 'Stone Golem',
        'image_path': 'boss_rush/bosses/stone_boss.png',
    },
    'air_elemental': {
        'label': 'Air Elemental',
        'image_path': 'boss_rush/bosses/air_boss.png',
    },
    'swamp_monster': {
        'label': 'Swamp Monster',
        'image_path': 'boss_rush/bosses/swamp_boss.png',
    },
    'mirror_phantom': {
        'label': 'Mirror Phantom',
        'image_path': 'boss_rush/bosses/mirror_boss.png',
    },
    'time_wraith': {
        'label': 'Time Wraith',
        'image_path': 'boss_rush/bosses/time_boss.png',
    },
}

BOSS_ABILITY_CATALOG = {
    'fire_giant': {
        'name': 'Heat Wave',
        'hint': 'Solve at least one attack problem correctly before the timer ends. This gives you Fire Shield and protects you from the next Heat Wave.',
        'summary': 'Correct attack answers give you Fire Shield. When Heat Wave starts, players with Fire Shield are safe and lose the shield. Players without Fire Shield lose HP.',
    },
    'air_elemental': {
        'name': 'Wind Shuffle',
        'hint': 'Work steadily. Try to solve the problem before the timer ends, or you may have to start a new one.',
        'summary': 'When Wind Shuffle starts, active players lose their current attack problem and get a new one. HP and combo do not change. Recovery and completed players are not affected.',
    },
    'stone_golem': {
        'name': 'Stone Guard',
        'hint': 'Do not rush. Build your combo with correct answers. Once the guard breaks, everyone can damage the boss again.',
        'summary': 'When Stone Guard is active, correct answers with low combo still count as solved and increase combo, but they do not damage the boss. When a player reaches the required combo with a correct answer, Stone Guard breaks and that answer deals damage.',
    },
    'swamp_monster': {
        'name': 'Regenerate',
        'hint': 'Keep solving problems. The class needs steady damage, or the boss will heal back what you already did.',
        'summary': 'When Regenerate starts, the boss restores HP. It cannot heal above its maximum HP.',
    },
    'mirror_phantom': {
        'name': 'Reflection',
        'hint': 'Learn from mistakes. If a problem comes back, fix your method and turn the old mistake into damage.',
        'summary': 'When Reflection starts, players who have wrong attack problems may get one of those problems again. Players with no wrong problems are safe from this ability.',
    },
    'time_wraith': {
        'name': 'Time Drain',
        'hint': 'Stay active. Keep working and submit before the timer ends, or the Time Wraith will drain your HP.',
        'summary': 'Players who submit at least one answer before the timer ends are safe. Players who do not submit lose HP. Correct, incorrect, and recovery answers all count as activity.',
    },
}


def boss_type_choices():
    return [(key, entry['label']) for key, entry in BOSS_TYPE_CATALOG.items()]


def boss_catalog_entry(boss_type):
    return BOSS_TYPE_CATALOG.get(boss_type) or BOSS_TYPE_CATALOG['fire_giant']


def boss_ability_entry(boss_type):
    return BOSS_ABILITY_CATALOG.get(boss_type) or {
        'name': 'Boss Ability',
        'hint': 'Watch the timer.',
        'summary': 'A timed boss effect.',
    }


def _utcnow():
    return datetime.now(timezone.utc)


def _coerce_aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def ability_interval_enabled(config):
    return bool(getattr(config, 'ability_enabled', True)) and int(getattr(config, 'ability_interval_seconds', 60) or 0) > 0


def schedule_next_ability(battle_state, config, *, now=None):
    if not ability_interval_enabled(config):
        battle_state.next_ability_at = None
        return None
    now = now or _utcnow()
    battle_state.next_ability_at = now + timedelta(seconds=int(config.ability_interval_seconds))
    return battle_state.next_ability_at


def combo_damage_for_correct_answer(old_combo, *, threshold, bonus_damage):
    """Return Phase-2 damage for a correct attack answer.

    Kept as a pure helper so the locked combo rule has a home, without wiring
    live answer submission yet.
    """
    new_combo = old_combo + 1
    if threshold != -1 and new_combo > threshold:
        return 1 + bonus_damage
    return 1


def _problem_ids(problem_set):
    if not problem_set:
        return []
    ids = [problem.id for problem in problem_set.problems.order_by(Problem.id).all()]
    random.shuffle(ids)
    return ids


def _as_int_list(value):
    if not value:
        return []
    return [int(item) for item in value]


def _unique_append(items, value):
    value = int(value)
    normalized = _as_int_list(items)
    if value not in normalized:
        normalized.append(value)
    return normalized


def _without(items, value):
    value = int(value)
    return [item for item in _as_int_list(items) if item != value]


def _shuffle_copy(items):
    shuffled = _as_int_list(items)
    random.shuffle(shuffled)
    return shuffled


def initialize_battle_state(game_round, config):
    """Ensure a battle state exists for a Boss Rush round."""
    battle_state = game_round.boss_rush_battle_state
    if battle_state is None:
        battle_state = BossRushBattleState(
            round_id=game_round.id,
            current_boss_hp=config.boss_max_hp,
            status=BOSS_RUSH_STATUS_WAITING,
        )
        db.session.add(battle_state)
        db.session.flush()
    if battle_state.status == BOSS_RUSH_STATUS_ACTIVE and ability_interval_enabled(config) and battle_state.next_ability_at is None:
        schedule_next_ability(battle_state, config)
        db.session.flush()
    return battle_state


def initialize_player_state(game_round, player_id, config):
    """Ensure one player's Boss Rush runtime state and pools exist."""
    state = BossRushPlayerState.query.filter_by(
        round_id=game_round.id,
        player_id=player_id,
    ).first()
    if state is None:
        state = BossRushPlayerState(
            round_id=game_round.id,
            player_id=player_id,
            hp=config.player_max_hp,
        )
        db.session.add(state)
        db.session.flush()

    changed = False
    if state.hp is None:
        state.hp = config.player_max_hp
        changed = True
    if state.attack_never_ids is None:
        state.attack_never_ids = _problem_ids(config.attack_problem_set)
        state.attack_incorrect_ids = []
        state.attack_solved_ids = []
        changed = True
    if state.recovery_never_ids is None:
        state.recovery_never_ids = _problem_ids(config.recovery_problem_set)
        state.recovery_incorrect_ids = []
        state.recovery_solved_ids = []
        changed = True
    if changed:
        db.session.flush()
    if state.submitted_since_last_ability is None:
        state.submitted_since_last_ability = True
    if state.fire_shield_stacks is None:
        state.fire_shield_stacks = 0
    ensure_player_round(game_round, state.player, BOSS_RUSH_MODE, state=state)
    return state


def select_next_attack_problem(state, config):
    """Assign and return the next attack problem, or None when completed."""
    all_attack_ids = set(_problem_ids(config.attack_problem_set))
    solved_ids = set(_as_int_list(state.attack_solved_ids))
    if all_attack_ids and solved_ids >= all_attack_ids:
        state.is_completed = True
        state.is_observer = True
        state.current_problem_id = None
        state.current_problem_kind = None
        db.session.flush()
        return None

    never_ids = _as_int_list(state.attack_never_ids)
    if not never_ids:
        retry_ids = _as_int_list(state.attack_incorrect_ids)
        if retry_ids:
            never_ids = _shuffle_copy(retry_ids)
            state.attack_incorrect_ids = []

    if not never_ids:
        state.is_completed = True
        state.is_observer = True
        state.current_problem_id = None
        state.current_problem_kind = None
        db.session.flush()
        return None

    problem_id = never_ids.pop(0)
    state.attack_never_ids = never_ids
    state.current_problem_id = problem_id
    state.current_problem_kind = BOSS_RUSH_ATTEMPT_ATTACK
    db.session.flush()
    problem = db.session.get(Problem, problem_id)
    if problem:
        ensure_player_problem(
            state.round,
            state.player,
            problem,
            'boss_rush_attack',
            mark_seen=True,
        )
    return problem


def select_next_recovery_problem(state, config):
    """Assign and return the next recovery problem. Recovery can repeat forever."""
    never_ids = _as_int_list(state.recovery_never_ids)
    if not never_ids:
        retry_ids = _as_int_list(state.recovery_incorrect_ids)
        if retry_ids:
            never_ids = _shuffle_copy(retry_ids)
            state.recovery_incorrect_ids = []

    if not never_ids:
        reset_ids = _problem_ids(config.recovery_problem_set)
        never_ids = reset_ids
        state.recovery_solved_ids = []
        state.recovery_incorrect_ids = []

    if not never_ids:
        state.current_problem_id = None
        state.current_problem_kind = BOSS_RUSH_ATTEMPT_RECOVERY
        db.session.flush()
        return None

    problem_id = never_ids.pop(0)
    state.recovery_never_ids = never_ids
    state.current_problem_id = problem_id
    state.current_problem_kind = BOSS_RUSH_ATTEMPT_RECOVERY
    db.session.flush()
    problem = db.session.get(Problem, problem_id)
    if problem:
        ensure_player_problem(
            state.round,
            state.player,
            problem,
            'boss_rush_recovery',
            mark_seen=True,
        )
    return problem


def get_current_problem(state, config, battle_state=None):
    """Return the persisted current problem, assigning one if needed."""
    if battle_state and battle_state.is_defeated:
        return None
    if state.is_completed:
        return None
    if state.current_problem_id:
        problem = db.session.get(Problem, state.current_problem_id)
        if problem:
            return problem
        state.current_problem_id = None
        state.current_problem_kind = None

    if state.hp <= 0:
        return select_next_recovery_problem(state, config)
    return select_next_attack_problem(state, config)


def _mark_boss_defeated_if_needed(battle_state):
    if battle_state.current_boss_hp <= 0 and not battle_state.is_defeated:
        battle_state.current_boss_hp = 0
        battle_state.is_defeated = True
        battle_state.status = BOSS_RUSH_STATUS_DEFEATED
        battle_state.defeated_at = datetime.now(timezone.utc)


def apply_boss_damage(battle_state, intended_damage):
    """Apply capped damage and mark defeat. Returns actual applied damage."""
    if battle_state.is_defeated or battle_state.current_boss_hp <= 0:
        _mark_boss_defeated_if_needed(battle_state)
        return 0
    applied = min(max(intended_damage, 0), battle_state.current_boss_hp)
    battle_state.current_boss_hp -= applied
    _mark_boss_defeated_if_needed(battle_state)
    return applied


def _active_player_states(round_id):
    return BossRushPlayerState.query.filter_by(round_id=round_id).all()


def _ability_summary(config, message, *, affected=0, immune=0):
    return {
        'boss_type': config.boss_type,
        'ability_name': boss_ability_entry(config.boss_type)['name'],
        'message': message,
        'affected_count': affected,
        'immune_count': immune,
        'triggered_at': _utcnow().isoformat(),
    }


def _ability_damage_player(state, amount, message):
    if state.is_completed or state.is_observer:
        return False
    if state.hp <= 0:
        state.last_ability_personal_message = message
        return False
    state.hp = max(0, state.hp - max(int(amount or 0), 0))
    state.last_ability_personal_message = message
    if state.hp <= 0:
        state.current_problem_id = None
        state.current_problem_kind = None
    return amount > 0


def _state_effect_snapshot(state):
    return {
        'hp': int(state.hp or 0),
        'current_combo': int(state.current_combo or 0),
        'current_problem_id': state.current_problem_id,
        'current_problem_kind': state.current_problem_kind,
        'fire_shield_stacks': int(state.fire_shield_stacks or 0),
        'submitted_since_last_ability': bool(state.submitted_since_last_ability),
        'last_ability_personal_message': state.last_ability_personal_message,
        'is_completed': bool(state.is_completed),
        'is_observer': bool(state.is_observer),
    }


def _state_effect_changed(before, after):
    keys = (
        'hp',
        'current_problem_id',
        'current_problem_kind',
        'fire_shield_stacks',
        'submitted_since_last_ability',
        'last_ability_personal_message',
    )
    return any(before.get(key) != after.get(key) for key in keys)


def _return_current_attack_to_pool(state):
    if state.current_problem_id and state.current_problem_kind == BOSS_RUSH_ATTEMPT_ATTACK:
        if state.current_problem_id not in _as_int_list(state.attack_solved_ids):
            state.attack_never_ids = _unique_append(state.attack_never_ids, state.current_problem_id)
    state.current_problem_id = None
    state.current_problem_kind = None


def _apply_fire_giant_ability(config, battle_state, states):
    damaged = 0
    shielded = 0
    for state in states:
        if state.is_completed or state.is_observer:
            continue
        if state.fire_shield_stacks > 0:
            state.fire_shield_stacks = max(0, state.fire_shield_stacks - 1)
            state.last_ability_personal_message = 'Fire Shield absorbed Heat Wave.'
            shielded += 1
            continue
        if _ability_damage_player(state, config.fire_burn_damage, 'Heat Wave burned you.'):
            damaged += 1
    return _ability_summary(config, f'Heat Wave burned {damaged} unshielded players; {shielded} shields held.', affected=damaged, immune=shielded)


def _apply_air_elemental_ability(config, battle_state, states):
    shuffled = 0
    for state in states:
        if state.is_completed or state.is_observer or state.hp <= 0 or state.current_problem_kind != BOSS_RUSH_ATTEMPT_ATTACK:
            continue
        if state.current_problem_id:
            state.attack_incorrect_ids = _unique_append(state.attack_incorrect_ids, state.current_problem_id)
        state.current_problem_id = None
        state.current_problem_kind = None
        select_next_attack_problem(state, config)
        if state.current_problem_kind == BOSS_RUSH_ATTEMPT_ATTACK:
            shuffled += 1
            state.last_ability_personal_message = 'Wind Shuffle replaced your attack problem.'
    return _ability_summary(config, f'Wind Shuffle replaced problems for {shuffled} players.', affected=shuffled)


def _apply_stone_golem_ability(config, battle_state, states):
    battle_state.stone_guard_active = True
    for state in states:
        state.last_ability_personal_message = f'Stone Guard active: combo {config.stone_guard_combo_required} required.'
    return _ability_summary(config, f'Stone Guard is active. Combo {config.stone_guard_combo_required} required.', affected=len(states))


def _apply_swamp_monster_ability(config, battle_state, states):
    before = battle_state.current_boss_hp
    battle_state.current_boss_hp = min(config.boss_max_hp, battle_state.current_boss_hp + config.swamp_regen_amount)
    healed = battle_state.current_boss_hp - before
    return _ability_summary(config, f'Swamp Monster regenerated {healed} HP.', affected=1 if healed else 0)


def _apply_mirror_phantom_ability(config, battle_state, states):
    reflected = 0
    immune = 0
    for state in states:
        if state.is_completed or state.is_observer or state.hp <= 0 or state.current_problem_kind != BOSS_RUSH_ATTEMPT_ATTACK:
            continue
        incorrect_ids = _as_int_list(state.attack_incorrect_ids)
        if not incorrect_ids:
            state.last_ability_personal_message = 'Mirror Phantom has no power over you now.'
            immune += 1
            continue
        _return_current_attack_to_pool(state)
        reflected_problem_id = random.choice(incorrect_ids)
        state.attack_incorrect_ids = _without(state.attack_incorrect_ids, reflected_problem_id)
        state.current_problem_id = reflected_problem_id
        state.current_problem_kind = BOSS_RUSH_ATTEMPT_ATTACK
        state.last_ability_personal_message = 'Reflection returned one of your missed problems.'
        reflected += 1
    return _ability_summary(config, f'Reflection returned missed problems for {reflected} players; {immune} were clear.', affected=reflected, immune=immune)


def _apply_time_wraith_ability(config, battle_state, states):
    drained = 0
    safe = 0
    for state in states:
        if state.is_completed or state.is_observer:
            continue
        if state.submitted_since_last_ability:
            safe += 1
            state.last_ability_personal_message = 'You were active and avoided Time Drain.'
        elif _ability_damage_player(state, config.time_drain_damage, 'Time Drain hit because you were inactive.'):
            drained += 1
        state.submitted_since_last_ability = False
    return _ability_summary(config, f'Time Wraith drained {drained} inactive players; {safe} stayed active.', affected=drained, immune=safe)


def trigger_boss_ability(game_round, config, battle_state):
    """Apply the current boss type's timed ability once."""
    if not ability_interval_enabled(config):
        battle_state.last_ability_summary_json = _ability_summary(config, 'Boss abilities are inactive.')
        battle_state.next_ability_at = None
        return {'triggered': False, 'summary': battle_state.last_ability_summary_json}
    if battle_state.is_defeated or battle_state.status in (BOSS_RUSH_STATUS_DEFEATED, BOSS_RUSH_STATUS_ENDED):
        return {'triggered': False, 'summary': battle_state.last_ability_summary_json}

    states = _active_player_states(game_round.id)
    boss_hp_before = battle_state.current_boss_hp
    state_snapshots_before = {
        state.player_id: _state_effect_snapshot(state)
        for state in states
    }
    if config.boss_type == 'fire_giant':
        summary = _apply_fire_giant_ability(config, battle_state, states)
    elif config.boss_type == 'air_elemental':
        summary = _apply_air_elemental_ability(config, battle_state, states)
    elif config.boss_type == 'stone_golem':
        summary = _apply_stone_golem_ability(config, battle_state, states)
    elif config.boss_type == 'swamp_monster':
        summary = _apply_swamp_monster_ability(config, battle_state, states)
    elif config.boss_type == 'mirror_phantom':
        summary = _apply_mirror_phantom_ability(config, battle_state, states)
    elif config.boss_type == 'time_wraith':
        summary = _apply_time_wraith_ability(config, battle_state, states)
    else:
        summary = _ability_summary(config, 'This boss has no tactical ability yet.')

    now = _utcnow()
    battle_state.last_ability_at = now
    battle_state.ability_count = int(battle_state.ability_count or 0) + 1
    battle_state.last_ability_summary_json = summary
    schedule_next_ability(battle_state, config, now=now)
    ability_count = int(battle_state.ability_count or 0)
    ability_key = config.boss_type
    record_boss_rush_battle_event(
        game_round,
        event_type='boss_ability_trigger',
        boss_type=config.boss_type,
        boss_hp_before=boss_hp_before,
        boss_hp_after=battle_state.current_boss_hp,
        ability_key=ability_key,
        ability_count=ability_count,
        event_key=boss_rush_battle_event_key(game_round, 'boss_ability_trigger', ability_count),
        details_json={
            'summary': summary,
            'boss_name': config.boss_name,
            'ability_name': boss_ability_entry(config.boss_type)['name'],
            'state_count': len(states),
            'stone_guard_active_after': bool(battle_state.stone_guard_active),
        },
    )
    for state in states:
        before = state_snapshots_before.get(state.player_id) or {}
        after = _state_effect_snapshot(state)
        if not _state_effect_changed(before, after):
            continue
        hp_delta = int(after.get('hp') or 0) - int(before.get('hp') or 0)
        shield_absorbed = 0
        if config.boss_type == 'fire_giant' and int(before.get('fire_shield_stacks') or 0) > int(after.get('fire_shield_stacks') or 0):
            shield_absorbed = int(config.fire_burn_damage or 0)
        record_boss_rush_battle_event(
            game_round,
            event_type='boss_ability_player_effect',
            player=state.player,
            boss_type=config.boss_type,
            boss_hp_before=boss_hp_before,
            boss_hp_after=battle_state.current_boss_hp,
            player_hp_before=before.get('hp'),
            player_hp_after=after.get('hp'),
            combo_before=before.get('current_combo'),
            combo_after=after.get('current_combo'),
            shield_or_guard_absorbed=shield_absorbed,
            ability_key=ability_key,
            ability_count=ability_count,
            event_key=boss_rush_battle_event_key(game_round, 'boss_ability_player_effect', f'{ability_count}:{state.player_id}'),
            details_json={
                'before': before,
                'after': after,
                'hp_delta': hp_delta,
                'personal_message': state.last_ability_personal_message,
            },
        )
        if hp_delta < 0:
            record_boss_rush_battle_event(
                game_round,
                event_type='player_hp_loss',
                player=state.player,
                linked_problem_id=before.get('current_problem_id'),
                boss_type=config.boss_type,
                boss_hp_before=boss_hp_before,
                boss_hp_after=battle_state.current_boss_hp,
                player_hp_before=before.get('hp'),
                player_hp_after=after.get('hp'),
                combo_before=before.get('current_combo'),
                combo_after=after.get('current_combo'),
                ability_key=ability_key,
                ability_count=ability_count,
                event_key=boss_rush_battle_event_key(game_round, 'player_hp_loss', f'ability:{ability_count}:{state.player_id}'),
                details_json={
                    'reason': f'{config.boss_type}_ability',
                    'summary': summary,
                    'before': before,
                    'after': after,
                },
            )
    db.session.flush()
    return {'triggered': True, 'summary': summary}


def process_due_ability(game_round, config, battle_state, *, now=None):
    """Opportunistic persisted timer hook. No background worker is required."""
    now = now or _utcnow()
    if not ability_interval_enabled(config):
        battle_state.next_ability_at = None
        return {'triggered': False, 'summary': battle_state.last_ability_summary_json}
    if battle_state.status != BOSS_RUSH_STATUS_ACTIVE or battle_state.is_defeated:
        return {'triggered': False, 'summary': battle_state.last_ability_summary_json}
    if battle_state.next_ability_at is None:
        schedule_next_ability(battle_state, config, now=now)
        return {'triggered': False, 'summary': battle_state.last_ability_summary_json}
    due_at = _coerce_aware(battle_state.next_ability_at)
    if due_at and due_at <= now:
        return trigger_boss_ability(game_round, config, battle_state)
    return {'triggered': False, 'summary': battle_state.last_ability_summary_json}


def _record_attempt(state, problem, *, attempt_type, submitted_text, selected_option_id, is_correct, damage_dealt, combo_before, hp_before):
    attempt = BossRushProblemAttempt(
        round_id=state.round_id,
        player_id=state.player_id,
        problem_id=problem.id,
        attempt_type=attempt_type,
        submitted_answer=(submitted_text or '').strip() or None,
        selected_option_id=selected_option_id,
        is_correct=is_correct,
        damage_dealt=damage_dealt,
        combo_before=combo_before,
        combo_after=state.current_combo,
        hp_before=hp_before,
        hp_after=state.hp,
        submitted_at=datetime.now(timezone.utc),
    )
    db.session.add(attempt)
    db.session.flush()
    mode_context = 'boss_rush_attack' if attempt_type == BOSS_RUSH_ATTEMPT_ATTACK else 'boss_rush_recovery'
    action_context = 'boss_damage' if attempt_type == BOSS_RUSH_ATTEMPT_ATTACK else 'boss_recovery'
    analytics_attempt = record_answer_attempt(
        state.round,
        state.player,
        problem,
        is_correct=is_correct,
        submitted_answer_text=submitted_text,
        selected_option_id=selected_option_id,
        mode_context=mode_context,
        action_context=action_context,
        submitted_at=attempt.submitted_at,
        extra_json={
            'boss_rush_problem_attempt_id': attempt.id,
            'attempt_type': attempt_type,
            'damage_dealt': damage_dealt,
            'combo_before': combo_before,
            'combo_after': state.current_combo,
            'hp_before': hp_before,
            'hp_after': state.hp,
        },
    )
    attempt.analytics_answer_attempt = analytics_attempt
    return attempt


def submit_attack_answer(state, config, battle_state, *, submitted_text=None, selected_option_id=None):
    problem = get_current_problem(state, config, battle_state)
    if problem is None or state.current_problem_kind != BOSS_RUSH_ATTEMPT_ATTACK:
        return {'ok': False, 'message': 'No attack problem is available.', 'attempt': None, 'attempt_type': BOSS_RUSH_ATTEMPT_ATTACK}

    combo_before = state.current_combo
    hp_before = state.hp
    boss_hp_before = battle_state.current_boss_hp
    is_correct = check_answer(problem, submitted_text, selected_option_id=selected_option_id)
    applied_damage = 0
    intended_damage = 0
    no_damage_reason = None
    state.submitted_since_last_ability = True

    if is_correct:
        new_combo = combo_before + 1
        intended_damage = combo_damage_for_correct_answer(
            combo_before,
            threshold=config.combo_bonus_threshold,
            bonus_damage=config.combo_bonus_damage,
        )
        if config.boss_type == 'stone_golem' and battle_state.stone_guard_active:
            if new_combo >= config.stone_guard_combo_required:
                battle_state.stone_guard_active = False
                battle_state.last_ability_summary_json = _ability_summary(
                    config,
                    f'Stone Guard broke when combo reached {new_combo}.',
                    affected=1,
                )
                applied_damage = apply_boss_damage(battle_state, intended_damage)
            else:
                applied_damage = 0
                no_damage_reason = 'stone_guard'
                state.last_ability_personal_message = f'Stone Guard blocked your damage. Build combo {config.stone_guard_combo_required}.'
        else:
            applied_damage = apply_boss_damage(battle_state, intended_damage)
        state.damage_dealt += applied_damage
        state.correct_count += 1
        state.current_combo = new_combo
        state.max_combo = max(state.max_combo, new_combo)
        if config.boss_type == 'fire_giant':
            state.fire_shield_stacks = min(
                config.fire_shield_max_stacks,
                int(state.fire_shield_stacks or 0) + 1,
            )
        if applied_damage > 0:
            state.last_contribution_at = _utcnow()
        state.attack_solved_ids = _unique_append(state.attack_solved_ids, problem.id)
        state.attack_incorrect_ids = _without(state.attack_incorrect_ids, problem.id)
    else:
        state.hp = max(0, state.hp - 1)
        state.current_combo = 0
        state.incorrect_count += 1
        state.attack_incorrect_ids = _unique_append(state.attack_incorrect_ids, problem.id)

    state.current_problem_id = None
    state.current_problem_kind = None
    attempt = _record_attempt(
        state,
        problem,
        attempt_type=BOSS_RUSH_ATTEMPT_ATTACK,
        submitted_text=submitted_text,
        selected_option_id=selected_option_id,
        is_correct=is_correct,
        damage_dealt=applied_damage,
        combo_before=combo_before,
        hp_before=hp_before,
    )
    linked_analytics_attempt = getattr(attempt, 'analytics_answer_attempt', None) or latest_boss_rush_answer_attempt(state.round, state.player, attempt)
    if is_correct:
        event_type = 'boss_damage' if applied_damage > 0 else 'boss_damage_blocked'
        record_boss_rush_battle_event(
            state.round,
            event_type=event_type,
            player=state.player,
            linked_answer_attempt=linked_analytics_attempt,
            linked_boss_rush_attempt=attempt,
            linked_problem_id=problem.id,
            boss_type=config.boss_type,
            boss_hp_before=boss_hp_before,
            boss_hp_after=battle_state.current_boss_hp,
            player_hp_before=hp_before,
            player_hp_after=state.hp,
            combo_before=combo_before,
            combo_after=state.current_combo,
            damage_intended=intended_damage,
            damage_applied=applied_damage,
            shield_or_guard_absorbed=max(intended_damage - applied_damage, 0),
            ability_key='stone_guard' if no_damage_reason == 'stone_guard' else None,
            ability_count=battle_state.ability_count,
            event_key=boss_rush_battle_event_key(state.round, event_type, attempt.id),
            details_json={
                'reason': no_damage_reason,
                'combo_bonus_threshold': config.combo_bonus_threshold,
                'combo_bonus_damage': config.combo_bonus_damage,
                'stone_guard_active_after': bool(battle_state.stone_guard_active),
                'stone_guard_combo_required': config.stone_guard_combo_required,
                'fire_shield_stacks_after': int(state.fire_shield_stacks or 0),
            },
        )
        if battle_state.is_defeated and boss_hp_before > 0 and battle_state.current_boss_hp == 0:
            record_boss_rush_battle_event(
                state.round,
                event_type='boss_defeated',
                player=state.player,
                linked_answer_attempt=linked_analytics_attempt,
                linked_boss_rush_attempt=attempt,
                linked_problem_id=problem.id,
                boss_type=config.boss_type,
                boss_hp_before=boss_hp_before,
                boss_hp_after=battle_state.current_boss_hp,
                combo_before=combo_before,
                combo_after=state.current_combo,
                damage_intended=intended_damage,
                damage_applied=applied_damage,
                event_key=boss_rush_battle_event_key(state.round, 'boss_defeated', attempt.id),
                details_json={'defeated_at': battle_state.defeated_at.isoformat() if battle_state.defeated_at else None},
            )
    else:
        record_boss_rush_battle_event(
            state.round,
            event_type='player_hp_loss',
            player=state.player,
            linked_answer_attempt=linked_analytics_attempt,
            linked_boss_rush_attempt=attempt,
            linked_problem_id=problem.id,
            boss_type=config.boss_type,
            boss_hp_before=boss_hp_before,
            boss_hp_after=battle_state.current_boss_hp,
            player_hp_before=hp_before,
            player_hp_after=state.hp,
            combo_before=combo_before,
            combo_after=state.current_combo,
            event_key=boss_rush_battle_event_key(state.round, 'player_hp_loss', attempt.id),
            details_json={'reason': 'wrong_attack_answer'},
        )
    get_current_problem(state, config, battle_state)
    db.session.flush()
    return {
        'ok': True,
        'is_correct': is_correct,
        'damage_dealt': applied_damage,
        'attempt': attempt,
        'attempt_type': BOSS_RUSH_ATTEMPT_ATTACK,
        'boss_hp_before': boss_hp_before,
        'boss_defeated_after': bool(battle_state.is_defeated),
        'no_damage_reason': no_damage_reason,
    }


def submit_recovery_answer(state, config, battle_state, *, submitted_text=None, selected_option_id=None):
    problem = get_current_problem(state, config, battle_state)
    if problem is None or state.current_problem_kind != BOSS_RUSH_ATTEMPT_RECOVERY:
        return {'ok': False, 'message': 'No recovery problem is available.', 'attempt': None, 'attempt_type': BOSS_RUSH_ATTEMPT_RECOVERY}

    combo_before = state.current_combo
    hp_before = state.hp
    is_correct = check_answer(problem, submitted_text, selected_option_id=selected_option_id)
    state.submitted_since_last_ability = True

    if is_correct:
        state.hp = 1
        state.recovery_correct_count += 1
        state.recovery_solved_ids = _unique_append(state.recovery_solved_ids, problem.id)
        state.recovery_incorrect_ids = _without(state.recovery_incorrect_ids, problem.id)
    else:
        state.hp = 0
        state.current_combo = 0
        state.recovery_incorrect_count += 1
        state.recovery_incorrect_ids = _unique_append(state.recovery_incorrect_ids, problem.id)

    state.current_problem_id = None
    state.current_problem_kind = None
    attempt = _record_attempt(
        state,
        problem,
        attempt_type=BOSS_RUSH_ATTEMPT_RECOVERY,
        submitted_text=submitted_text,
        selected_option_id=selected_option_id,
        is_correct=is_correct,
        damage_dealt=0,
        combo_before=combo_before,
        hp_before=hp_before,
    )
    linked_analytics_attempt = getattr(attempt, 'analytics_answer_attempt', None) or latest_boss_rush_answer_attempt(state.round, state.player, attempt)
    record_boss_rush_battle_event(
        state.round,
        event_type='player_recovery_success' if is_correct else 'player_recovery_failed',
        player=state.player,
        linked_answer_attempt=linked_analytics_attempt,
        linked_boss_rush_attempt=attempt,
        linked_problem_id=problem.id,
        boss_type=config.boss_type,
        boss_hp_before=battle_state.current_boss_hp,
        boss_hp_after=battle_state.current_boss_hp,
        player_hp_before=hp_before,
        player_hp_after=state.hp,
        combo_before=combo_before,
        combo_after=state.current_combo,
        event_key=boss_rush_battle_event_key(
            state.round,
            'player_recovery_success' if is_correct else 'player_recovery_failed',
            attempt.id,
        ),
        details_json={'reason': 'recovery_answer'},
    )
    get_current_problem(state, config, battle_state)
    db.session.flush()
    return {
        'ok': True,
        'is_correct': is_correct,
        'damage_dealt': 0,
        'attempt': attempt,
        'attempt_type': BOSS_RUSH_ATTEMPT_RECOVERY,
        'boss_hp_before': battle_state.current_boss_hp,
        'boss_defeated_after': bool(battle_state.is_defeated),
        'no_damage_reason': 'recovery',
    }


def submit_current_answer(state, config, battle_state, *, submitted_text=None, selected_option_id=None):
    get_current_problem(state, config, battle_state)
    if battle_state.is_defeated:
        return {'ok': False, 'message': 'The boss has already been defeated.', 'attempt': None, 'attempt_type': None, 'boss_already_defeated': True}
    if state.current_problem_kind == BOSS_RUSH_ATTEMPT_RECOVERY:
        return submit_recovery_answer(
            state,
            config,
            battle_state,
            submitted_text=submitted_text,
            selected_option_id=selected_option_id,
        )
    return submit_attack_answer(
        state,
        config,
        battle_state,
        submitted_text=submitted_text,
        selected_option_id=selected_option_id,
    )


def build_player_state_payload(state, config, battle_state, current_problem=None):
    attack_total = len(_problem_ids(config.attack_problem_set))
    recovery_total = len(_problem_ids(config.recovery_problem_set))
    solved = len(_as_int_list(state.attack_solved_ids))
    mode = 'completed' if state.is_completed else state.current_problem_kind or BOSS_RUSH_ATTEMPT_ATTACK
    if battle_state.is_defeated:
        mode = 'defeated'
    return {
        'mode': mode,
        'boss_hp': battle_state.current_boss_hp,
        'boss_max_hp': config.boss_max_hp,
        'boss_defeated': battle_state.is_defeated,
        'player_hp': state.hp,
        'player_max_hp': config.player_max_hp,
        'damage_dealt': state.damage_dealt,
        'current_combo': state.current_combo,
        'max_combo': state.max_combo,
        'correct_count': state.correct_count,
        'incorrect_count': state.incorrect_count,
        'recovery_correct_count': state.recovery_correct_count,
        'recovery_incorrect_count': state.recovery_incorrect_count,
        'attack_solved_count': solved,
        'attack_total_count': attack_total,
        'recovery_total_count': recovery_total,
        'current_problem': current_problem,
        'active_bonuses': _active_bonuses_for_state(state, config),
        'ability': _ability_state_payload(config, battle_state),
    }


def _accuracy_for_state(state):
    attempts = state.correct_count + state.incorrect_count
    if attempts <= 0:
        return 0.0
    return state.correct_count / attempts


def _state_label(state, battle_state):
    if battle_state and battle_state.is_defeated:
        return 'defeated'
    if state.is_completed:
        return 'completed'
    if state.hp <= 0:
        return 'recovery'
    return 'attacking'


def _combo_bonus_payload(state, config):
    threshold = config.combo_bonus_threshold
    if threshold == -1:
        return {
            'enabled': False,
            'active': False,
            'label': f'Combo x{state.current_combo}',
            'next_threshold': None,
            'bonus_damage': 0,
        }
    active = state.current_combo > threshold
    next_threshold = None if active else max(threshold + 1 - state.current_combo, 0)
    return {
        'enabled': True,
        'active': active,
        'label': f'Combo x{state.current_combo}' + (f' (+{config.combo_bonus_damage} dmg)' if active else ''),
        'next_threshold': next_threshold,
        'bonus_damage': config.combo_bonus_damage if active else 0,
    }


def _hp_hearts(current_hp, max_hp):
    max_hp = max(int(max_hp or 0), 0)
    current_hp = max(min(int(current_hp or 0), max_hp), 0)
    return [
        {
            'index': index + 1,
            'filled': index < current_hp,
        }
        for index in range(max_hp)
    ]


def _active_bonuses_for_state(state, config):
    items = []
    if int(state.fire_shield_stacks or 0) > 0:
        items.append(f'Fire Shield x{state.fire_shield_stacks}')
    if config.boss_type == 'time_wraith':
        items.append('Safe this cycle' if state.submitted_since_last_ability else 'Submit before drain')
    return {
        'items': items,
        'placeholder': 'No active bonuses',
        'personal_message': state.last_ability_personal_message,
    }


def _ability_state_payload(config, battle_state):
    enabled = ability_interval_enabled(config)
    now = _utcnow()
    next_at = _coerce_aware(battle_state.next_ability_at)
    seconds_remaining = None
    if enabled and next_at:
        seconds_remaining = max(0, int((next_at - now).total_seconds()))
    entry = boss_ability_entry(config.boss_type)
    return {
        'enabled': enabled,
        'name': entry['name'],
        'hint': entry['hint'],
        'summary': entry['summary'],
        'interval_seconds': int(getattr(config, 'ability_interval_seconds', 0) or 0),
        'next_ability_at': next_at.isoformat() if next_at else None,
        'seconds_remaining': seconds_remaining,
        'ready': bool(enabled and seconds_remaining == 0),
        'last_ability_at': battle_state.last_ability_at.isoformat() if battle_state.last_ability_at else None,
        'ability_count': int(battle_state.ability_count or 0),
        'recent_event': battle_state.last_ability_summary_json,
        'stone_guard_active': bool(battle_state.stone_guard_active),
        'stone_guard_combo_required': config.stone_guard_combo_required,
    }


def _serialize_player_state_for_live(state, config, battle_state, rank):
    return {
        'rank': rank,
        'player_id': state.player_id,
        'username': state.player.username if state.player else f'Player {state.player_id}',
        'damage_dealt': state.damage_dealt,
        'current_combo': state.current_combo,
        'max_combo': state.max_combo,
        'combo_bonus': _combo_bonus_payload(state, config),
        'hp': state.hp,
        'max_hp': config.player_max_hp,
        'hp_hearts': _hp_hearts(state.hp, config.player_max_hp),
        'correct_count': state.correct_count,
        'incorrect_count': state.incorrect_count,
        'accuracy': _accuracy_for_state(state),
        'status': _state_label(state, battle_state),
        'is_completed': state.is_completed,
        'active_bonuses': _active_bonuses_for_state(state, config),
        'submitted_since_last_ability': bool(state.submitted_since_last_ability),
        'fire_shield_stacks': int(state.fire_shield_stacks or 0),
    }


def _rank_player_states(player_states):
    return sorted(
        player_states,
        key=lambda state: (
            -state.damage_dealt,
            -state.max_combo,
            -_accuracy_for_state(state),
            _last_contribution_sort_value(state),
            state.player_id,
        ),
    )


def build_admin_state_payload(game_round, config, battle_state):
    ranked_states = _rank_player_states(
        BossRushPlayerState.query
        .filter_by(round_id=game_round.id)
        .all()
    )
    return {
        'boss_hp': battle_state.current_boss_hp,
        'boss_max_hp': config.boss_max_hp,
        'boss_defeated': battle_state.is_defeated,
        'status': battle_state.status,
        'players': ranked_states,
        'leaderboard': [
            _serialize_player_state_for_live(state, config, battle_state, rank)
            for rank, state in enumerate(ranked_states, start=1)
        ],
    }


def build_live_state_payload(game_session, game_round, config, battle_state):
    admin_state = build_admin_state_payload(game_round, config, battle_state)
    session_status = game_session.status
    round_ended = bool(game_round.ended_at)
    if session_status == 'finished':
        redirect_target = 'session_over'
    elif session_status == 'waiting' or round_ended:
        redirect_target = 'lobby'
    else:
        redirect_target = 'game'
    return {
        'session_id': game_session.id,
        'round_id': game_round.id,
        'mode': BOSS_RUSH_MODE,
        'session': {
            'status': session_status,
            'round_number': game_round.round_number,
            'round_started': bool(game_round.started_at),
            'round_ended': round_ended,
            'redirect_target': redirect_target,
        },
        'boss': {
            'name': config.boss_name,
            'type': config.boss_type,
            'image_path': config.boss_image_path,
            'hp': battle_state.current_boss_hp,
            'max_hp': config.boss_max_hp,
            'hp_percent': round((battle_state.current_boss_hp / config.boss_max_hp) * 100, 2) if config.boss_max_hp else 0,
            'status': battle_state.status,
            'defeated': battle_state.is_defeated,
            'defeated_at': battle_state.defeated_at.isoformat() if battle_state.defeated_at else None,
            'rewards_finalized': bool(battle_state.rewards_finalized_at),
            'rewards_finalized_at': battle_state.rewards_finalized_at.isoformat() if battle_state.rewards_finalized_at else None,
        },
        'ability': _ability_state_payload(config, battle_state),
        'leaderboard': admin_state['leaderboard'],
        'active_bonuses': {
            'items': [],
            'placeholder': 'No active bonuses',
        },
    }


def _last_contribution_sort_value(state):
    if state.last_contribution_at is None:
        return datetime.max.replace(tzinfo=timezone.utc)
    value = state.last_contribution_at
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _reward_breakdown_dict(*, placement=0, other=0, highest_combo=0):
    return {
        'placement': int(placement),
        'other_participant': int(other),
        'highest_combo': int(highest_combo),
    }


def calculate_final_rewards(player_states, config):
    """Return a minimal deterministic reward snapshot for a defeated round."""
    ordered = sorted(
        player_states,
        key=lambda state: (
            -state.damage_dealt,
            -state.max_combo,
            -_accuracy_for_state(state),
            _last_contribution_sort_value(state),
            state.player_id,
        ),
    )
    damage_ranked = [state for state in ordered if state.damage_dealt > 0]
    placement_rewards = {
        1: config.first_place_diamonds,
        2: config.second_place_diamonds,
        3: config.third_place_diamonds,
    }

    rewards_by_player = {}
    for rank, state in enumerate(damage_ranked, start=1):
        placement = placement_rewards.get(rank, 0)
        other = 0
        if rank > 3:
            other = config.other_participant_diamonds
        rewards_by_player[state.player_id] = {
            'player_id': state.player_id,
            'username': state.player.username if state.player else f'Player {state.player_id}',
            'rank': rank,
            'damage_dealt': state.damage_dealt,
            'max_combo': state.max_combo,
            'accuracy': _accuracy_for_state(state),
            'correct_count': state.correct_count,
            'incorrect_count': state.incorrect_count,
            'last_contribution_at': state.last_contribution_at.isoformat() if state.last_contribution_at else None,
            'breakdown': _reward_breakdown_dict(placement=placement, other=other),
            'total_diamonds': placement + other,
        }

    combo_eligible_states = [state for state in player_states if state.damage_dealt > 0]
    highest_combo = max((state.max_combo for state in combo_eligible_states), default=0)
    if highest_combo > 0:
        for state in combo_eligible_states:
            if state.max_combo == highest_combo:
                entry = rewards_by_player.get(state.player_id)
                if entry is None:
                    entry = {
                        'player_id': state.player_id,
                        'username': state.player.username if state.player else f'Player {state.player_id}',
                        'rank': None,
                        'damage_dealt': state.damage_dealt,
                        'max_combo': state.max_combo,
                        'accuracy': _accuracy_for_state(state),
                        'correct_count': state.correct_count,
                        'incorrect_count': state.incorrect_count,
                        'last_contribution_at': state.last_contribution_at.isoformat() if state.last_contribution_at else None,
                        'breakdown': _reward_breakdown_dict(),
                        'total_diamonds': 0,
                    }
                    rewards_by_player[state.player_id] = entry
                entry['breakdown']['highest_combo'] = config.highest_combo_diamonds
                entry['total_diamonds'] += config.highest_combo_diamonds

    zero_reward_states = [
        state for state in ordered
        if state.player_id not in rewards_by_player
    ]
    for state in zero_reward_states:
        rewards_by_player[state.player_id] = {
            'player_id': state.player_id,
            'username': state.player.username if state.player else f'Player {state.player_id}',
            'rank': None,
            'damage_dealt': state.damage_dealt,
            'max_combo': state.max_combo,
            'accuracy': _accuracy_for_state(state),
            'correct_count': state.correct_count,
            'incorrect_count': state.incorrect_count,
            'last_contribution_at': state.last_contribution_at.isoformat() if state.last_contribution_at else None,
            'breakdown': _reward_breakdown_dict(),
            'total_diamonds': 0,
        }

    entries = sorted(
        rewards_by_player.values(),
        key=lambda row: (
            row['rank'] is None,
            row['rank'] or 999999,
            -row['damage_dealt'],
            row['player_id'],
        ),
    )
    return {
        'entries': entries,
        'highest_combo': highest_combo,
        'participant_count': len(player_states),
        'damage_participant_count': len(damage_ranked),
    }


def get_final_reward_snapshot(game_round, config):
    player_states = (
        BossRushPlayerState.query
        .filter_by(round_id=game_round.id)
        .all()
    )
    return calculate_final_rewards(player_states, config)


def get_reward_entry_for_player(battle_state, player_id):
    snapshot = battle_state.final_rewards_json or {}
    for entry in snapshot.get('entries', []):
        if int(entry.get('player_id')) == int(player_id):
            return entry
    return None


def finalize_boss_rush_rewards(game_session, game_round, config, battle_state, *, admin_player_id=None):
    """Finalize a defeated Boss Rush once and award diamonds through the ledger."""
    if not battle_state.is_defeated or battle_state.current_boss_hp > 0:
        raise ValueError('Boss Rush rewards can only be finalized after the boss is defeated.')
    if battle_state.rewards_finalized_at:
        return {
            'finalized': False,
            'already_finalized': True,
            'snapshot': battle_state.final_rewards_json or get_final_reward_snapshot(game_round, config),
        }

    snapshot = get_final_reward_snapshot(game_round, config)
    reason = f'boss_rush_reward:{game_round.id}'
    for entry in snapshot['entries']:
        amount = int(entry.get('total_diamonds') or 0)
        if amount > 0:
            award_diamonds_to_player(
                player_id=int(entry['player_id']),
                amount=amount,
                reason=reason,
                admin_player_id=admin_player_id,
                session_id=game_session.id,
            )

    battle_state.final_rewards_json = snapshot
    battle_state.rewards_finalized_at = datetime.now(timezone.utc)
    record_boss_rush_battle_event(
        game_round,
        event_type='boss_rewards_finalized',
        boss_type=config.boss_type,
        boss_hp_before=battle_state.current_boss_hp,
        boss_hp_after=battle_state.current_boss_hp,
        details_json={
            'snapshot': snapshot,
            'admin_player_id': admin_player_id,
            'rewards_finalized_at': battle_state.rewards_finalized_at.isoformat(),
        },
        event_key=boss_rush_battle_event_key(game_round, 'boss_rewards_finalized', game_round.id),
    )
    db.session.flush()
    return {
        'finalized': True,
        'already_finalized': False,
        'snapshot': snapshot,
    }
