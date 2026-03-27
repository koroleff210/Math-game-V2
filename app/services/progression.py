# app/services/progression.py
#
# Progression service helpers.
#
# Provides atomic helpers for reading/writing Diamonds (persistent currency),
# purchasing permanent upgrade levels, and managing session-scoped participant
# snapshots (frozen upgrade effects).
#
# Public API:
#   get_or_create_player_progression(player_id) -> PlayerProgression
#   award_diamonds_to_player(player_id, amount, reason, admin_player_id, session_id) -> int
#   get_player_upgrade_map(player_id) -> dict[str, PlayerUpgrade]
#   purchase_upgrade(player_id, upgrade_type) -> dict
#   ensure_session_participant_snapshot(session_id, player_id) -> SessionParticipantSnapshot
#   ensure_all_session_participant_snapshots(session_id) -> list[SessionParticipantSnapshot]
#   get_session_player_modifiers(session_id, player_id) -> SessionParticipantSnapshot | _DefaultModifiers

from datetime import datetime, timezone

from app.extensions import db
from app.models.progression import PlayerProgression, DiamondTransaction, PlayerUpgrade, SessionParticipantSnapshot
from app.services.gear import build_frozen_gear_modifiers_for_player


def get_or_create_player_progression(player_id: int) -> PlayerProgression:
    """Return the PlayerProgression row for *player_id*, creating it if absent.

    Safe to call multiple times — uses a get-or-create pattern within the
    current session.  Does NOT commit; the caller owns the transaction.
    """
    prog = PlayerProgression.query.filter_by(player_id=player_id).first()
    if prog is None:
        prog = PlayerProgression(
            player_id=player_id,
            diamonds_balance=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(prog)
        db.session.flush()   # assigns prog.id without outer commit
    return prog


def award_diamonds_to_player(
    *,
    player_id: int,
    amount: int,
    reason: str,
    admin_player_id: int | None = None,
    session_id: int | None = None,
) -> int:
    """Award *amount* Diamonds to *player_id* atomically.

    Rules:
    - amount must be a positive integer (raises ValueError otherwise)
    - reason must be a non-empty string after stripping (raises ValueError otherwise)
    - increments PlayerProgression.diamonds_balance
    - writes exactly one DiamondTransaction row
    - caller is responsible for db.session.commit() after this call
      (all writes are flushed but not committed, so failures roll back cleanly)

    Returns the new diamonds_balance after the award.
    """
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError(f'amount must be a positive integer, got {amount!r}')
    reason_clean = (reason or '').strip()
    if not reason_clean:
        raise ValueError('reason must be a non-empty string')

    prog = get_or_create_player_progression(player_id)
    prog.diamonds_balance += amount
    prog.updated_at = datetime.now(timezone.utc)

    tx = DiamondTransaction(
        player_id=player_id,
        amount_delta=amount,
        balance_after=prog.diamonds_balance,
        reason=reason_clean,
        admin_player_id=admin_player_id,
        session_id=session_id,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(tx)
    db.session.flush()

    return prog.diamonds_balance


# ── D2: Upgrade helpers ───────────────────────────────────────────────────────

def get_player_upgrade_map(player_id: int) -> dict:
    """Return a dict mapping upgrade_type → PlayerUpgrade for *player_id*.

    Only rows that already exist in the DB are included; missing upgrades
    are at their implicit level-0 baseline (not stored until first purchase).
    """
    rows = PlayerUpgrade.query.filter_by(player_id=player_id).all()
    return {row.upgrade_type: row for row in rows}


def _get_or_create_player_upgrade(player_id: int, upgrade_type: str) -> PlayerUpgrade:
    """Return (or create) a PlayerUpgrade row for (player_id, upgrade_type).

    Does NOT commit; flushes so the row has an id.
    """
    row = PlayerUpgrade.query.filter_by(
        player_id=player_id, upgrade_type=upgrade_type
    ).first()
    if row is None:
        row = PlayerUpgrade(
            player_id=player_id,
            upgrade_type=upgrade_type,
            level=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(row)
        db.session.flush()
    return row


def purchase_upgrade(*, player_id: int, upgrade_type: str) -> dict:
    """Spend Diamonds to purchase the next level of *upgrade_type* for *player_id*.

    Validation:
    - upgrade_type must exist in UPGRADE_CATALOG  (ValueError if not)
    - player must not already be at max level      (ValueError if maxed)
    - player must have enough Diamonds             (ValueError if insufficient)

    On success:
    - PlayerProgression.diamonds_balance is decremented by the cost
    - PlayerUpgrade.level is incremented by 1
    - One DiamondTransaction row with negative amount_delta is created
    - All writes are flushed but NOT committed; caller owns the commit

    Returns a summary dict:
      {
        'upgrade_type': str,
        'new_level': int,
        'cost': int,
        'new_balance': int,
      }
    """
    # Import here to avoid circular imports at module load time.
    from app.services.upgrade_catalog import get_upgrade

    upgrade_def = get_upgrade(upgrade_type)   # raises ValueError if unknown

    upgrade_row = _get_or_create_player_upgrade(player_id, upgrade_type)
    current_level = upgrade_row.level

    cost = upgrade_def.cost_for_next_level(current_level)
    if cost is None:
        raise ValueError(
            f'Upgrade "{upgrade_type}" is already at max level ({upgrade_def.max_level}).'
        )

    prog = get_or_create_player_progression(player_id)
    if prog.diamonds_balance < cost:
        raise ValueError(
            f'Not enough Diamonds. Need {cost}, have {prog.diamonds_balance}.'
        )

    # Deduct and record
    prog.diamonds_balance -= cost
    prog.updated_at = datetime.now(timezone.utc)

    upgrade_row.level += 1
    upgrade_row.updated_at = datetime.now(timezone.utc)

    tx = DiamondTransaction(
        player_id=player_id,
        amount_delta=-cost,
        balance_after=prog.diamonds_balance,
        reason=f'upgrade_purchase:{upgrade_type}',
        admin_player_id=None,
        session_id=None,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(tx)
    db.session.flush()

    return {
        'upgrade_type': upgrade_type,
        'new_level': upgrade_row.level,
        'cost': cost,
        'new_balance': prog.diamonds_balance,
    }


# ── Gameplay modifier access ──────────────────────────────────────────────────

class _DefaultModifiers:
    """Attribute-compatible stand-in returned when a snapshot row is
    unexpectedly absent.  Represents baseline (level-0) values so gameplay
    degrades gracefully.
    """
    effective_steal_token_cap  = 1
    effective_mine_bonus       = 0
    effective_treasure_bonus   = 0
    effective_shield_bonus_pct = 0.0
    effective_gear_mine_gold_delta = 0
    effective_gear_steal_gold_delta = 0
    effective_gear_shield_duration_delta = 0


# ── Session-scoped participant snapshot ───────────────────────────────────────

def ensure_session_participant_snapshot(session_id: int, player_id: int):
    """Create (or return existing) session-scoped frozen runtime snapshot for one player.

    Idempotent — if the row already exists it is returned unchanged.
    Resolves current PlayerUpgrade levels and normalized equipped gear into
    concrete effective values.

    Does NOT commit; flushes so the row receives its id.
    Returns the SessionParticipantSnapshot row.
    """
    from app.services.upgrade_catalog import UPGRADE_CATALOG

    existing = SessionParticipantSnapshot.query.filter_by(
        session_id=session_id,
        player_id=player_id,
    ).first()
    if existing:
        return existing

    upgrade_map = get_player_upgrade_map(player_id)

    def _effect(upgrade_type: str):
        row = upgrade_map.get(upgrade_type)
        level = row.level if row else 0
        return UPGRADE_CATALOG[upgrade_type].effect_at_level(level)

    gear_mods = build_frozen_gear_modifiers_for_player(player_id)

    snapshot = SessionParticipantSnapshot(
        session_id=session_id,
        player_id=player_id,
        effective_steal_token_cap=_effect('steal_token_cap'),
        effective_mine_bonus=_effect('mine_bonus'),
        effective_treasure_bonus=_effect('treasure_bonus'),
        effective_shield_bonus_pct=_effect('shield_bonus_pct'),
        effective_gear_mine_gold_delta=gear_mods['effective_gear_mine_gold_delta'],
        effective_gear_steal_gold_delta=gear_mods['effective_gear_steal_gold_delta'],
        effective_gear_shield_duration_delta=gear_mods['effective_gear_shield_duration_delta'],
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(snapshot)
    db.session.flush()
    return snapshot


def ensure_all_session_participant_snapshots(session_id: int) -> list:
    """Ensure session snapshot rows exist for all enrolled players in a session.

    Called at round start (start_round / next_round) as a safety net for
    players who joined during 'waiting'.  Idempotent — existing rows are
    skipped without re-freezing.

    Does NOT commit; flushes new rows so they receive their IDs.
    Returns list of newly-created SessionParticipantSnapshot rows.
    """
    from app.models.game import RoundPlayer

    enrolled = RoundPlayer.query.filter_by(session_id=session_id).all()
    created = []
    for rp in enrolled:
        existing = SessionParticipantSnapshot.query.filter_by(
            session_id=session_id, player_id=rp.player_id,
        ).first()
        if not existing:
            snap = ensure_session_participant_snapshot(session_id, rp.player_id)
            created.append(snap)
    return created


def get_session_player_modifiers(session_id: int, player_id: int):
    """Return the frozen SessionParticipantSnapshot for (session_id, player_id).

    Reads the session-scoped frozen snapshot created at explicit Join time.

    If the row is unexpectedly absent, returns _DefaultModifiers with baseline
    values so gameplay is not broken.  Absence should not normally occur
    (join creates the snapshot; round-start is a safety net).
    """
    row = SessionParticipantSnapshot.query.filter_by(
        session_id=session_id,
        player_id=player_id,
    ).first()
    return row if row is not None else _DefaultModifiers()
