# app/modes/classic/store.py
#
# Store purchase and item-consumption logic for Classic Mode.
#
# All functions require an active Flask application context (they perform DB I/O).
# They are called from Socket.IO event handlers, which run inside app context.
#
# Public API:
#   purchase_item(player_id, session_id, item_id) → (ok: bool, msg: str, new_gold: int)
#   consume_item(player_id, session_id, bonus_type) → PlayerInventory | None
#   get_active_counts(player_id, session_id) → dict[str, int]
#   store_items_for(session_id) → list[dict]

from datetime import datetime, timezone

from app.extensions import db
from app.models.classic import StoreItem, PlayerInventory, PlayerWallet


def get_or_create_system_sc(session_id: int) -> StoreItem:
    """Return the hidden system StoreItem used for Treasure-granted Second Chance.

    Creates one (once per session) if it does not already exist.
    """
    item = StoreItem.query.filter_by(
        session_id=session_id, bonus_type='shield', is_system=True,
    ).first()
    if not item:
        item = StoreItem(
            session_id=session_id,
            name='Treasure Second Chance',
            description='Granted by Treasure Search',
            cost=0,
            currency='gold',
            bonus_type='shield',
            session_stock=-1,
            per_player_limit=-1,
            is_system=True,
        )
        db.session.add(item)
        db.session.flush()
    return item


def get_or_create_system_shield_token(session_id: int) -> StoreItem:
    """Return the hidden system StoreItem used for Treasure-granted shield tokens."""
    item = StoreItem.query.filter_by(
        session_id=session_id, bonus_type='steal_shield', is_system=True,
    ).first()
    if not item:
        item = StoreItem(
            session_id=session_id,
            name='Treasure Shield Token',
            description='Granted by Treasure Search',
            cost=0,
            currency='gold',
            bonus_type='steal_shield',
            session_stock=-1,
            per_player_limit=-1,
            is_system=True,
        )
        db.session.add(item)
        db.session.flush()
    return item


def purchase_item(player_id: int, session_id: int, item_id: int,
                  steal_token_max_cap: int = 1):
    """
    Attempt to purchase a store item.

    Checks:
      - Item exists and belongs to the session.
      - Player wallet has enough of the item's currency (gold or gems).
      - Session-wide stock is not exhausted (session_stock).
      - Per-player purchase limit is not reached (per_player_limit).
      - steal_token items: player is not already at steal_token_max_cap.

    On success: deducts the correct currency, inserts a PlayerInventory row, commits.

    Returns:
        (True,  'ok',              new_gold: int)  on success
        (False, reason_string,     current_gold: int)  on failure
    """
    item = db.session.get(StoreItem, item_id)
    if not item or item.session_id != session_id:
        wallet = PlayerWallet.query.filter_by(
            player_id=player_id, session_id=session_id
        ).first()
        return False, 'item not found', wallet.gold if wallet else 0

    wallet = PlayerWallet.query.filter_by(
        player_id=player_id, session_id=session_id
    ).first()
    current_gold = wallet.gold if wallet else 0

    # Currency-aware affordability check
    currency = getattr(item, 'currency', 'gold') or 'gold'
    if currency == 'gems':
        current_amount = wallet.gems if wallet else 0
        if current_amount < item.cost:
            return False, 'not enough gems', current_gold
    else:
        if current_gold < item.cost:
            return False, 'not enough gold', current_gold

    # D5: Check session-wide stock
    if item.session_stock != -1:
        sold = PlayerInventory.query.filter_by(item_id=item_id).count()
        if sold >= item.session_stock:
            return False, 'out of stock', current_gold

    # D5: Check per-player purchase limit
    if item.per_player_limit != -1:
        player_bought = PlayerInventory.query.filter_by(
            item_id=item_id, player_id=player_id,
        ).count()
        if player_bought >= item.per_player_limit:
            return False, f'purchase limit reached ({item.per_player_limit} per player)', current_gold

    # A1-6: block steal_token purchase when player is already at the round cap.
    # Gold must NOT be deducted when this check fires.
    if item.bonus_type == 'steal_token' and wallet and wallet.steal_tokens >= steal_token_max_cap:
        return False, f'already at maximum steal tokens ({steal_token_max_cap})', current_gold

    # D2: Second Chance (bonus_type='shield') — max capacity 1.
    if item.bonus_type == 'shield':
        active = (
            PlayerInventory.query
            .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
            .filter(
                PlayerInventory.player_id  == player_id,
                PlayerInventory.session_id == session_id,
                StoreItem.bonus_type       == 'shield',
                PlayerInventory.used_at    == None,  # noqa: E711
            )
            .count()
        )
        if active >= 1:
            return False, 'you already have a Second Chance', current_gold

    # Deduct the correct currency
    if currency == 'gems':
        wallet.gems -= item.cost
    else:
        wallet.gold -= item.cost
    new_gold = wallet.gold

    # Record purchase
    inv = PlayerInventory(
        player_id=player_id,
        session_id=session_id,
        item_id=item_id,
        purchased_at=datetime.now(timezone.utc),
        used_at=None,
    )
    db.session.add(inv)
    db.session.commit()

    # ── Bonus-type-specific immediate effects ─────────────────────────────────
    if item.bonus_type == 'steal_token':
        # Cap already enforced above; credit one token unconditionally here.
        # Mark the inventory row used at purchase time (AD-26).
        wallet.steal_tokens += 1
        inv.used_at = inv.purchased_at
        db.session.commit()
    # steal_shield items are intentionally NOT auto-activated.
    # inv.used_at remains None; the item sits in active inventory until the
    # player explicitly activates the shield (separate event, D-4+).
    # get_active_counts() will report steal_shield: N for the UI to display.

    return True, 'ok', new_gold


def consume_item(player_id: int, session_id: int, bonus_type: str):
    """
    Mark the oldest active (unused) item of the given bonus_type as used.

    Returns the updated PlayerInventory row, or None if the player has no
    unused item of that type.
    """
    inv = (
        PlayerInventory.query
        .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
        .filter(
            PlayerInventory.player_id  == player_id,
            PlayerInventory.session_id == session_id,
            StoreItem.bonus_type       == bonus_type,
            PlayerInventory.used_at    == None,  # noqa: E711
        )
        .order_by(PlayerInventory.purchased_at.asc())
        .first()
    )
    if inv:
        inv.used_at = datetime.now(timezone.utc)
        db.session.commit()
    return inv


def get_active_counts(player_id: int, session_id: int) -> dict:
    """
    Return a dict mapping bonus_type → count of unused items for this player.

    Example: {'x2_mine': 2, 'shield': 1}
    """
    rows = (
        db.session.query(StoreItem.bonus_type, db.func.count(PlayerInventory.id))
        .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
        .filter(
            PlayerInventory.player_id  == player_id,
            PlayerInventory.session_id == session_id,
            PlayerInventory.used_at    == None,  # noqa: E711
        )
        .group_by(StoreItem.bonus_type)
        .all()
    )
    return {bonus_type: cnt for bonus_type, cnt in rows}


def store_items_for(session_id: int) -> list:
    """
    Return a list of dicts describing available store items for a session,
    with quantity_left computed (None = unlimited).
    """
    items = StoreItem.query.filter_by(session_id=session_id, is_system=False).order_by(StoreItem.cost).all()
    result = []
    for item in items:
        if item.session_stock == -1:
            qty_left = -1  # unlimited
        else:
            sold = PlayerInventory.query.filter_by(item_id=item.id).count()
            qty_left = max(0, item.session_stock - sold)
        result.append({
            'id':               item.id,
            'name':             item.name,
            'description':      item.description or '',
            'cost':             item.cost,
            'currency':         getattr(item, 'currency', 'gold') or 'gold',
            'bonus_type':       item.bonus_type,
            'quantity_left':    qty_left,
            'per_player_limit': item.per_player_limit,
        })
    return result
