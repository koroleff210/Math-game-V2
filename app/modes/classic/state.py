# app/modes/classic/state.py
#
# In-memory live state for active Classic Mode sessions.
#
# What lives here:
#   - round start times: needed to evaluate timer bonus without a DB read per answer
#   - per-session threading locks: protect solver count increments from race conditions
#   - pending action tracking: ensure a player can only call classic_choose_action
#     after a confirmed correct answer, and only once per problem per round
#   - [Step D] steal intents: player has chosen Steal and is picking a target
#   - [Step D] steal mini-games: player is in an active chest mini-game
#   - [Step D] action logs: per-(player, session) rolling log of recent events
#
# What does NOT live here:
#   - solver counts: stored in DB (ProblemSolverCount) and incremented under the lock
#   - wallet balances: always read/written via DB
#   - shield state: stored in DB (PlayerClassicState.shield_expires_at)
#
# Rebuild behaviour on server restart:
#   - round_start_times: lost; server will fall back to GameRound.started_at from DB
#   - pending_actions: lost safely — pending choose_action opportunities are discarded
#   - session locks: recreated on next get_lock() call
#   - steal_intents / steal_minigames: lost safely — in-flight steal attempts discarded
#   - action_logs: lost — cosmetic only (AD-29)
#
# Thread safety:
#   All writes to _round_start_times and _pending_actions that matter for
#   correctness are done inside the per-session lock obtained via get_lock().

import threading
from collections import deque
from datetime import datetime, timezone

# round_start_times[session_id] = datetime when the round was started
_round_start_times: dict = {}

# session_locks[session_id] = threading.Lock()
_session_locks: dict = {}

# pending_actions[(player_id, round_id, problem_id)] = {
#     session_id, round_id, problem_id, solver_rank, timer_active, steal_available
# }
# Set after a correct answer; cleared after choose_action is processed.
_pending_actions: dict = {}

# player_streaks[(player_id, round_id)] = consecutive correct answer count
# Incremented on correct submission, reset to 0 on wrong submission.
# Lost on server restart (same accepted fallback as _round_start_times — AD-20).
_player_streaks: dict = {}

# ── [Step D] Steal in-flight state ────────────────────────────────────────────

# _pending_steal_intents[player_id] = {session_id, round_id, problem_id}
# Set when a player picks the Steal action; cleared when they pick a target
# (or cancel, or the session ends).  problem_id is stored so that cancel can
# restore the choose_action_prompt for the same solved problem.
_pending_steal_intents: dict = {}

# _pending_steal_minigames[player_id] = {
#     target_id, winning_chests (frozenset), steal_amount, session_id, round_id,
#     phase, selected_chest, reveal_result, containers
# }
# Set when a target is picked and the mini-game is enabled.
_pending_steal_minigames: dict = {}

# _pending_treasure_chests[player_id] = {
#     session_id, round_id, problem_id, chests, base_gold, breakdown, new_balance,
#     new_gems, gems_gained, gem_reason, active_bonuses, phase, selected_chest,
#     reveal_result
# }
# Set after Treasure Search base gold resolves and the optional chest phase awaits
# a player pick.
_pending_treasure_chests: dict = {}

# _action_logs[(player_id, session_id)] = deque(maxlen=10)
# Rolling display log — cosmetic only; not persisted (AD-29).
_action_logs: dict = {}


# ── Session lifecycle ─────────────────────────────────────────────────────────

def init_session(session_id: int, round_started_at: datetime) -> None:
    """Record that a round started.  Called by the admin start route."""
    _round_start_times[session_id] = round_started_at
    # Ensure the lock exists before any players connect
    get_lock(session_id)


def clear_session(session_id: int) -> None:
    """Remove all in-memory state for a session.  Called when the round ends."""
    _round_start_times.pop(session_id, None)
    _session_locks.pop(session_id, None)
    # Pending actions are keyed by (player_id, round_id, problem_id); remove those for
    # this session explicitly now that the payload stores session_id.
    for key, payload in list(_pending_actions.items()):
        if isinstance(payload, dict) and payload.get('session_id') == session_id:
            _pending_actions.pop(key, None)
    # Streaks are keyed by (player_id, round_id), not session_id.
    # They stay harmlessly in the dict; no validation can succeed once the round is gone.
    # Steal intents / mini-games are keyed by player_id; clear those whose session matches.
    for pid in [k for k, v in _pending_steal_intents.items() if v.get('session_id') == session_id]:
        _pending_steal_intents.pop(pid, None)
    for pid in [k for k, v in _pending_steal_minigames.items() if v.get('session_id') == session_id]:
        _pending_steal_minigames.pop(pid, None)
    for pid in [k for k, v in _pending_treasure_chests.items() if v.get('session_id') == session_id]:
        _pending_treasure_chests.pop(pid, None)
    # Action logs are keyed by (player_id, session_id); remove entries for this session.
    for key in [k for k in _action_logs if k[1] == session_id]:
        _action_logs.pop(key, None)


# ── Locking ───────────────────────────────────────────────────────────────────

def get_lock(session_id: int) -> threading.Lock:
    """Return the per-session lock, creating it if it does not exist."""
    if session_id not in _session_locks:
        _session_locks[session_id] = threading.Lock()
    return _session_locks[session_id]


# ── Timer bonus ───────────────────────────────────────────────────────────────

def is_timer_active(session_id: int, bonus_timer_duration: int) -> bool:
    """
    Return True if the timer bonus window is still open.

    Falls back to False if:
    - bonus_timer_duration is 0 (timer bonus disabled)
    - session_id is not in memory (e.g. after a server restart)
    """
    if bonus_timer_duration <= 0:
        return False

    started_at = _round_start_times.get(session_id)
    if started_at is None:
        return False

    # Handle naive datetimes stored without timezone info
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    return elapsed < bonus_timer_duration


# ── Pending action management ─────────────────────────────────────────────────

def set_pending_action(player_id: int, round_id: int, problem_id: int, **payload) -> None:
    """Mark that this player has a pending choose_action for this problem."""
    action_payload = {
        'round_id': round_id,
        'problem_id': problem_id,
    }
    action_payload.update(payload)
    _pending_actions[(player_id, round_id, problem_id)] = action_payload


def get_pending_action(player_id: int, round_id: int, problem_id: int) -> dict | None:
    """Return the pending choose_action payload for this player+round+problem."""
    return _pending_actions.get((player_id, round_id, problem_id))


def get_pending_action_for_round(player_id: int, round_id: int) -> dict | None:
    """Return any pending choose_action payload for this player+round."""
    for (pid, rid, _problem_id), payload in _pending_actions.items():
        if pid == player_id and rid == round_id:
            return payload
    return None


def has_pending_action(player_id: int, round_id: int, problem_id: int) -> bool:
    """Return True if a pending choose_action exists for this player+round+problem."""
    return (player_id, round_id, problem_id) in _pending_actions


def clear_pending_action(player_id: int, round_id: int, problem_id: int) -> None:
    """Remove the pending choose_action after it has been processed."""
    _pending_actions.pop((player_id, round_id, problem_id), None)


# ── Streak tracking ───────────────────────────────────────────────────────────

def increment_streak(player_id: int, round_id: int) -> int:
    """Increment the consecutive-correct-answer streak counter and return the new value."""
    key = (player_id, round_id)
    _player_streaks[key] = _player_streaks.get(key, 0) + 1
    return _player_streaks[key]


def reset_streak(player_id: int, round_id: int) -> None:
    """Reset the streak to 0 after a wrong answer."""
    _player_streaks.pop((player_id, round_id), None)


def get_streak(player_id: int, round_id: int) -> int:
    """Return the current consecutive-correct-answer streak (0 if not set)."""
    return _player_streaks.get((player_id, round_id), 0)


# ── [Step D] Steal intent API ────────────────────────────────────────────────

def set_steal_intent(player_id: int, session_id: int, round_id: int,
                     problem_id: int) -> None:
    """Record that a player has chosen the Steal action and is selecting a target.

    problem_id is stored so that classic_steal_cancel can restore
    choose_action_prompt for the same solved problem without forfeiting the
    action slot.
    """
    _pending_steal_intents[player_id] = {
        'session_id': session_id,
        'round_id':   round_id,
        'problem_id': problem_id,
    }


def get_steal_intent(player_id: int) -> dict | None:
    """Return the steal intent dict for the player, or None if not set."""
    return _pending_steal_intents.get(player_id)


def clear_steal_intent(player_id: int) -> None:
    """Remove the steal intent (target picked, cancelled, or session ended)."""
    _pending_steal_intents.pop(player_id, None)


# ── [Step D] Steal mini-game API ─────────────────────────────────────────────

def set_steal_minigame(
    player_id: int,
    target_id: int,
    winning_chests: frozenset,
    steal_amount: int,
    session_id: int,
    round_id: int,
    **extra,
) -> None:
    """Record the server-side mini-game state while the player picks a chest."""
    payload = {
        'target_id':      target_id,
        'winning_chests': winning_chests,
        'steal_amount':   steal_amount,
        'session_id':     session_id,
        'round_id':       round_id,
    }
    payload.update(extra)
    _pending_steal_minigames[player_id] = payload


def get_steal_minigame(player_id: int) -> dict | None:
    """Return the mini-game state dict for the player, or None if not set."""
    return _pending_steal_minigames.get(player_id)


def clear_steal_minigame(player_id: int) -> None:
    """Remove the mini-game state after the player picks a chest."""
    _pending_steal_minigames.pop(player_id, None)


def set_treasure_chests(player_id: int, **payload) -> None:
    """Record the pending Treasure chest phase for a player."""
    _pending_treasure_chests[player_id] = payload


def get_treasure_chests(player_id: int) -> dict | None:
    """Return the pending Treasure chest state dict for the player."""
    return _pending_treasure_chests.get(player_id)


def clear_treasure_chests(player_id: int) -> None:
    """Remove the pending Treasure chest state after resolution."""
    _pending_treasure_chests.pop(player_id, None)


def update_steal_minigame(player_id: int, **updates) -> dict | None:
    """Merge updates into the pending steal mini-game payload and return it."""
    payload = _pending_steal_minigames.get(player_id)
    if not payload:
        return None
    payload.update(updates)
    return payload


def update_treasure_chests(player_id: int, **updates) -> dict | None:
    """Merge updates into the pending Treasure payload and return it."""
    payload = _pending_treasure_chests.get(player_id)
    if not payload:
        return None
    payload.update(updates)
    return payload


# ── [Step D] Action log API ───────────────────────────────────────────────────

def append_action_log(player_id: int, session_id: int, entry: str) -> None:
    """Append an entry to the rolling action log for this player+session (max 10)."""
    key = (player_id, session_id)
    if key not in _action_logs:
        _action_logs[key] = deque(maxlen=10)
    _action_logs[key].append(entry)


def get_action_log(player_id: int, session_id: int) -> list:
    """Return the action log entries as a list (oldest first), or [] if none."""
    key = (player_id, session_id)
    return list(_action_logs.get(key, []))
