"""Bounded Boss Rush rewards and exact, contribution-based team payouts."""
from datetime import datetime, timezone
from fractions import Fraction
import random
from app.extensions import db
from app.models.gear import GearItemDefinition, PlayerGearOwnership
from app.models.player import Player
from app.services.economy import gold_account


def uses_shared_bank(config, session):
    return session.economy_version >= 2 and config.shared_bank_enabled


def attack_rewards(config, combo):
    tier = 'high' if combo >= config.reward_combo_high else 'low' if combo >= config.reward_combo_start else None
    personal = config.attack_gold + (getattr(config, 'combo_gold_' + tier) if tier else 0)
    bank = config.bank_gold + (getattr(config, 'bank_combo_' + tier) if tier else 0)
    return personal, bank


def bank_shares(total, contributions, equal_percent=50):
    """Only correct attack contributors qualify. Largest remainders conserve gold."""
    eligible = {pid: count for pid, count in contributions.items() if count > 0}
    if not eligible:
        return {}
    total = max(0, int(total))
    equal_percent = max(0, min(100, equal_percent))
    correct_total = sum(eligible.values())
    exact = {pid: Fraction(total * equal_percent, 100 * len(eligible)) +
        Fraction(total * (100 - equal_percent) * count, 100 * correct_total)
        for pid, count in eligible.items()}
    result = {pid: int(value) for pid, value in exact.items()}
    remaining = total - sum(result.values())
    order = sorted(eligible, key=lambda pid: (-(exact[pid] - result[pid]), pid))
    for pid in order[:remaining]:result[pid] += 1
    return result


def reward_snapshot(config, battle, player_states):
    shares = bank_shares(battle.team_bank_gold, {p.player_id:p.correct_count for p in player_states}, config.bank_equal_percent)
    return {p.player_id:dict(bank_share=shares.get(p.player_id,0),
        defeat_gold=config.defeat_gold if p.player_id in shares else 0,
        total_gold=shares.get(p.player_id,0) + (config.defeat_gold if p.player_id in shares else 0),
        total_diamonds=config.defeat_diamonds if p.player_id in shares else 0,
        eligible=p.player_id in shares,
        loot_gear_id=config.defeat_gear_id if p.player_id in shares else None)
        for p in player_states}


def grant_gear_loot(entry, config, player_id):
    """Called only under the locked, one-time battle finalization transaction."""
    entry.update(loot_received=False, loot_name=None, loot_fallback_gold=0)
    if not entry.get('eligible') or not config.defeat_gear_id or random.random() >= config.defeat_gear_chance:
        return
    # Use the same account lock as Blacksmith purchases to protect ownership.
    gold_account(player_id)
    item = db.session.get(GearItemDefinition, config.defeat_gear_id)
    player = db.session.get(Player, player_id)
    owned = PlayerGearOwnership.query.filter_by(player_id=player_id, item_id=config.defeat_gear_id).first()
    from app.services.gear import is_item_variant_compatible_for_player
    if item is None or not item.is_active or owned or not is_item_variant_compatible_for_player(item, player.avatar_body_variant):
        entry['loot_fallback_gold'] = config.loot_duplicate_gold
        entry['total_gold'] += config.loot_duplicate_gold
        entry['loot_name'] = item.name if item else 'Unavailable gear'
        return
    db.session.add(PlayerGearOwnership(player_id=player_id, item_id=item.id, created_at=datetime.now(timezone.utc)))
    entry.update(loot_received=True, loot_name=item.name)


def expire_bank(config, battle, session):
    if uses_shared_bank(config, session) and not battle.is_defeated and not battle.bank_expired_at:
        battle.bank_expired_at = datetime.now(timezone.utc)


def bank_payload(config, battle, session):
    enabled = uses_shared_bank(config, session)
    return dict(enabled=enabled, total=battle.team_bank_gold if enabled else 0,
        status='expired' if battle.bank_expired_at else 'unlocked' if battle.rewards_finalized_at else 'locked',
        equal_percent=config.bank_equal_percent,
        eligibility='At least one correct attack answer')
