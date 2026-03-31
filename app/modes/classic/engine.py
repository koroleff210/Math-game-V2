# app/modes/classic/engine.py
#
# Pure calculation functions for Classic Mode rewards and penalties.
#
# Rules:
#   - No DB access.
#   - No Socket.IO calls.
#   - All inputs are scalar values (not ORM objects), except the steal helpers
#     which accept ORM rows read-only to inspect field values.
#   - Config fields are read from a ClassicRoundConfig instance passed as `config`,
#     which is fine because it is used read-only and contains only plain integers.
#
# First-solver bonus formula (confirmed design decision):
#   bonus = max(0, (first_solver_count - (solver_rank - 1)) * first_solver_multiplier)
#   solver_rank is 1-indexed: first solver = rank 1, second = rank 2, etc.
#
# Gold never goes below zero (apply_penalty enforces this).

import random


def _first_solver_bonus(config, solver_rank: int) -> int:
    """Compute the first-solver bonus gold for this solver_rank."""
    return max(0, (config.first_solver_count - (solver_rank - 1)) * config.first_solver_multiplier)


def calc_mine_reward(config, solver_rank: int, timer_active: bool) -> dict:
    """
    Calculate the total gold awarded when a player chooses Mine.

    Args:
        config      (ClassicRoundConfig): Round settings (used read-only).
        solver_rank (int): 1-indexed position in which this player solved the problem.
        timer_active (bool): Whether the timer bonus window is still open.

    Returns:
        dict with keys:
            "gold"      → total gold awarded (int)
            "breakdown" → list of human-readable component strings
    """
    breakdown = []
    gold = config.mine_reward
    breakdown.append(f"base mine: {config.mine_reward}")

    fsb = _first_solver_bonus(config, solver_rank)
    if fsb > 0:
        gold += fsb
        breakdown.append(f"first-solver bonus: {fsb}")

    if timer_active and config.bonus_timer_duration > 0:
        gold += config.bonus_timer_gold
        breakdown.append(f"timer bonus: {config.bonus_timer_gold}")

    return {"gold": gold, "breakdown": breakdown}


def calc_treasure_search_reward(config, solver_rank: int, timer_active: bool) -> dict:
    """
    Calculate the total gold awarded when a player chooses Treasure Search.

    [Step C-2] The base reward is now a random roll in the range
    [treasure_search_reward, treasure_search_max_reward].  When min == max the
    roll is deterministic, preserving pre-Step-C behaviour exactly.

    Args:
        config      (ClassicRoundConfig): Round settings (used read-only).
        solver_rank (int): 1-indexed position in which this player solved the problem.
        timer_active (bool): Whether the timer bonus window is still open.

    Returns:
        dict with keys:
            "gold"          → total gold awarded (int)
            "breakdown"     → list of human-readable component strings
            "treasure_roll" → the raw random roll, before bonuses (int)
    """
    ts_min = config.treasure_search_reward
    ts_max = getattr(config, 'treasure_search_max_reward', ts_min)  # safe for old configs
    # Clamp: if admin set max < min somehow, floor the max at min
    if ts_max < ts_min:
        ts_max = ts_min
    roll = random.randint(ts_min, ts_max)

    breakdown = []
    gold = roll
    if ts_min == ts_max:
        breakdown.append(f"base treasure search: {roll}")
    else:
        breakdown.append(f"treasure roll: {roll} (range {ts_min}–{ts_max})")

    fsb = _first_solver_bonus(config, solver_rank)
    if fsb > 0:
        gold += fsb
        breakdown.append(f"first-solver bonus: {fsb}")

    if timer_active and config.bonus_timer_duration > 0:
        gold += config.bonus_timer_gold
        breakdown.append(f"timer bonus: {config.bonus_timer_gold}")

    return {"gold": gold, "breakdown": breakdown, "treasure_roll": roll}


def apply_penalty(current_gold: int, penalty: int) -> int:
    """
    Apply a wrong-answer gold penalty, flooring at zero.

    Args:
        current_gold (int): Player's current gold balance.
        penalty      (int): Penalty to deduct.

    Returns:
        int: New gold balance (never negative).
    """
    return max(0, current_gold - penalty)


def apply_x2_mine(reward_dict: dict) -> dict:
    """
    Double the gold in a mine reward dict (x2 Mine item effect).

    The original breakdown entries are preserved and a note is appended.
    Called after calc_mine_reward() when the player has an active x2_mine item.

    Args:
        reward_dict (dict): Return value of calc_mine_reward().

    Returns:
        dict: New reward dict with doubled gold and updated breakdown.
    """
    gold = reward_dict['gold'] * 2
    breakdown = list(reward_dict['breakdown']) + [f'x2 mine bonus: ×2 → {gold}']
    return {'gold': gold, 'breakdown': breakdown}


def calc_gem_award(solved_count: int, cfg_milestone: int,
                   streak_count: int, cfg_streak: int) -> dict:
    """
    Determine how many gems to award and why.  Pure function — no DB access.

    Milestone rule: if cfg_milestone > 0 and solved_count > 0
                    and solved_count % cfg_milestone == 0  → +1 gem
    Streak rule:    if cfg_streak > 0 and streak_count > 0
                    and streak_count % cfg_streak == 0     → +1 gem
    Both rules can fire simultaneously (gems_gained = 2, reason = 'both').
    Passing cfg_milestone=0 or cfg_streak=0 disables that feature entirely
    (guards against division-by-zero, per AD-23).

    Args:
        solved_count  (int): Problems solved by this player in the current round.
        cfg_milestone (int): Milestone threshold from ClassicRoundConfig.
        streak_count  (int): Current consecutive-correct-answer streak from state.
        cfg_streak    (int): Streak threshold from ClassicRoundConfig.

    Returns:
        dict with keys:
            "gems"   → total gems to award (int, 0–2)
            "reason" → 'milestone' | 'streak' | 'both' | None
    """
    milestone_gem = (
        1 if (cfg_milestone > 0
              and solved_count > 0
              and solved_count % cfg_milestone == 0)
        else 0
    )
    streak_gem = (
        1 if (cfg_streak > 0
              and streak_count > 0
              and streak_count % cfg_streak == 0)
        else 0
    )

    gems = milestone_gem + streak_gem
    if milestone_gem and streak_gem:
        reason = 'both'
    elif milestone_gem:
        reason = 'milestone'
    elif streak_gem:
        reason = 'streak'
    else:
        reason = None

    return {'gems': gems, 'reason': reason}


def calc_treasure_gem_award(config) -> dict:
    """
    Determine whether a Treasure Search action awards a bonus gem.

    Rolls a random float in [0, 1).  If the roll is less than
    config.gem_treasure_chance, 1 gem is awarded.  Setting the chance to 0.0
    disables the feature entirely.

    NOTE: As of Step D4, this function is no longer called from Treasure Search
    event handling — side rewards now use pick_treasure_side_reward() instead.
    Kept for backward compatibility and direct-call usage.

    Args:
        config (ClassicRoundConfig): Round settings (used read-only).

    Returns:
        dict with keys:
            "gems"  → 0 or 1
            "won"   → True if gem was awarded, False otherwise
    """
    chance = getattr(config, 'gem_treasure_chance', 0.0)
    if chance > 0.0 and random.random() < chance:
        return {'gems': 1, 'won': True}
    return {'gems': 0, 'won': False}


def build_treasure_chest_candidates(config, eligibility: dict | None = None) -> list[dict]:
    """Return the currently visible Treasure chest candidates.

    Each configured reward type becomes at most one chest candidate.
    A candidate is shown only when:
      - its configured fill chance is > 0
      - the reward is currently grantable for this player/session
    """
    eligibility = eligibility or {}
    reward_specs = [
        ('gem', getattr(config, 'gem_treasure_chance', 0.0)),
        ('steal_token', getattr(config, 'treasure_steal_token_chance', 0.0)),
        ('shield_token', getattr(config, 'treasure_active_shield_chance', 0.0)),
        ('second_chance', getattr(config, 'treasure_second_chance_chance', 0.0)),
    ]
    candidates = []
    for reward_type, fill_chance in reward_specs:
        if fill_chance <= 0:
            continue
        if eligibility.get(reward_type, True) is not True:
            continue
        candidates.append({
            'reward_type': reward_type,
            'fill_chance': fill_chance,
        })
    return candidates


def roll_treasure_chests(candidates: list[dict]) -> list[dict]:
    """Roll filled/empty state independently for each treasure chest and shuffle order."""
    chests = []
    for idx, candidate in enumerate(candidates, start=1):
        chests.append({
            'index': idx,
            'reward_type': candidate['reward_type'],
            'fill_chance': candidate['fill_chance'],
            'filled': random.random() < candidate['fill_chance'],
        })
    random.shuffle(chests)
    for idx, chest in enumerate(chests, start=1):
        chest['index'] = idx
    return chests


# ── [Step D] Steal system helpers ─────────────────────────────────────────────
#
# Shield state lives in PlayerClassicState.shield_expires_at (AD-27).
# PlayerWallet holds only economy data (gold, gems, steal_tokens).

import random as _random
from datetime import datetime, timezone, timedelta


def calc_steal_amount(target_gold: int, steal_percent: float,
                      min_cap: int, max_cap: int) -> int:
    """
    Calculate how much gold is stolen from a target.

    Formula:
        amount = clamp(round(target_gold * steal_percent), min_cap, max_cap)
        amount = min(amount, target_gold)   # never steal more than target has

    max_cap == -1 means no upper clamp (AD-25).
    """
    raw = round(target_gold * steal_percent)
    result = max(min_cap, raw)
    if max_cap != -1:
        result = min(result, max_cap)
    return min(result, target_gold)


def calc_effective_steal_amount(target_gold: int, steal_percent: float,
                                min_cap: int, max_cap: int,
                                flat_gold_delta: int = 0) -> int:
    """Return the final steal amount after applying the frozen flat gear delta.

    The existing percent/cap flow is preserved by first computing the base
    steal amount via calc_steal_amount(). The frozen flat gear delta is then
    added, and the result is still bounded by target_gold.
    """
    base_amount = calc_steal_amount(target_gold, steal_percent, min_cap, max_cap)
    return min(base_amount + flat_gold_delta, target_gold)


def calc_effective_shield_duration(base_duration_s: int,
                                   shield_bonus_pct: float = 0.0,
                                   flat_duration_delta_s: int = 0) -> int:
    """Return the final shield duration after frozen flat and pct modifiers."""
    return round((base_duration_s + flat_duration_delta_s) * (1 + shield_bonus_pct))


def is_steal_shield_active(player_classic_state) -> bool:
    """
    Return True when the player's steal shield is currently active.

    Args:
        player_classic_state: PlayerClassicState ORM row (read-only).
    """
    expires = player_classic_state.shield_expires_at
    if expires is None:
        return False
    # Normalise: if stored without tzinfo, treat as UTC
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def grant_steal_shield(player_classic_state, duration_s: int) -> datetime:
    """
    Grant (or extend) a steal shield on the given PlayerClassicState row.

    Stacking rule:
      - If no shield or already expired: new expiry = now + duration
      - If already active:               new expiry = existing expiry + duration

    Mutates player_classic_state.shield_expires_at in place.
    Caller is responsible for db.session.commit().

    Returns the new shield_expires_at value.
    """
    now = datetime.now(timezone.utc)
    current = player_classic_state.shield_expires_at
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    # Use existing expiry as base only when the shield is still active
    base = current if (current is not None and current > now) else now
    new_expiry = base + timedelta(seconds=duration_s)
    player_classic_state.shield_expires_at = new_expiry
    return new_expiry


def build_steal_targets(wallets, states, acting_player_id: int) -> list:
    """
    Return a list of valid steal targets for the acting player.

    A player is excluded when any of the following apply:
      - they are the acting player
      - their wallet.gold <= 0
      - their PlayerClassicState has an active steal shield

    Args:
        wallets (iterable): All PlayerWallet rows for the session.
        states  (dict):     Mapping of player_id → PlayerClassicState for the session.
                            Players absent from the dict are treated as having no shield.
        acting_player_id (int): The player performing the steal.

    Returns:
        list of dicts: [{player_id, username, gold}, ...]
    """
    targets = []
    for w in wallets:
        if w.player_id == acting_player_id:
            continue
        if w.gold <= 0:
            continue
        pcs = states.get(w.player_id)
        if pcs is not None and is_steal_shield_active(pcs):
            continue
        targets.append({
            'player_id': w.player_id,
            'username':  w.player.username,
            'gold':      w.gold,
        })
    return targets


def generate_winning_chests(chest_count: int, winning_count: int) -> frozenset:
    """
    Randomly select which chest indices are winners.

    Chest indices are 1-based: range [1, chest_count].
    Returns a frozenset of winning_count distinct integers.
    """
    return frozenset(_random.sample(range(1, chest_count + 1), winning_count))


def try_award_steal_token(wallet, max_cap: int = 1) -> bool:
    """
    Credit one steal token to the wallet if under the cap.

    Returns True if the token was actually credited; False if already at cap.
    Caller is responsible for db.session.commit().
    """
    if wallet.steal_tokens < max_cap:
        wallet.steal_tokens += 1
        return True
    return False
