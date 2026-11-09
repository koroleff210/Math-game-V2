"""Session economy and atomic permanent-wallet settlement.

Callers own the transaction. Never commit a balance without its ledger entry.
"""
from datetime import datetime, timezone
from functools import wraps
from threading import RLock
from app.extensions import db
from app.models.game import GameSession
from app.models.player import Player
from app.models.classic import PlayerWallet, ClassicRoundConfig
from app.models.progression import PlayerProgression
from app.models.economy import GoldTransaction

_locks = {}
_lock_guard = RLock()
STARTING_GOLD = 700
STARTING_GOLD_REASON = 'starter_grant'


def session_lock(session_id):
    with _lock_guard:
        return _locks.setdefault(session_id, RLock())


def serialized_session(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        session_id = kwargs.get('session_id', args[0] if args else 0)
        with session_lock(int(session_id)):
            return fn(*args, **kwargs)
    return wrapped


def is_new_economy(session):
    return bool(session and session.economy_version >= 2)


def saved_gold_balance(player_id):
    row = PlayerProgression.query.filter_by(player_id=player_id).first()
    return row.saved_gold if row else 0


def gold_account(player_id):
    # Lock identity first so account creation and concurrent session settlements
    # for the same player cannot race (also used by permanent purchases).
    Player.query.filter_by(id=player_id).with_for_update().one()
    row = PlayerProgression.query.filter_by(player_id=player_id).with_for_update().populate_existing().first()
    if row is None:
        row = PlayerProgression(player_id=player_id, diamonds_balance=0, saved_gold=0)
        db.session.add(row)
        db.session.flush()
    return row


def grant_starting_gold(player_id):
    """Credit the one-time new-player grant in the caller's transaction."""
    account = gold_account(player_id)
    event_key = f'{STARTING_GOLD_REASON}:{player_id}'
    if GoldTransaction.query.filter_by(event_key=event_key).first() is not None:
        return False
    account.saved_gold += STARTING_GOLD
    account.updated_at = datetime.now(timezone.utc)
    db.session.add(GoldTransaction(
        player_id=player_id, event_key=event_key, amount_delta=STARTING_GOLD,
        balance_after=account.saved_gold, reason=STARTING_GOLD_REASON,
    ))
    return True


def session_wallet(session_id, player_id):
    row = PlayerWallet.query.filter_by(session_id=session_id, player_id=player_id).with_for_update().first()
    if row is None:
        row = PlayerWallet(session_id=session_id, player_id=player_id, gold=0, gems=0)
        db.session.add(row)
        db.session.flush()
    return row


def settle_session(game_session):
    """Bank remaining gold once; expire gems; retain gold as the final score.

    The session lock, account updates, unique ledger keys and settlement marker
    are committed together by the caller. A crash rolls all of them back.
    Historical version-1 sessions never receive retroactive credit.
    """
    session = GameSession.query.filter_by(id=game_session.id).with_for_update().populate_existing().one()
    if not is_new_economy(session) or session.economy_settled_at:
        return False
    if session.status != 'finished':
        raise ValueError('Only finished sessions can be settled.')
    wallets = PlayerWallet.query.filter_by(session_id=session.id).order_by(PlayerWallet.player_id).with_for_update().all()
    for wallet in wallets:
        account = gold_account(wallet.player_id)
        amount = max(0, wallet.gold)
        account.saved_gold += amount
        wallet.gems = 0
        db.session.add(GoldTransaction(
            player_id=wallet.player_id, session_id=session.id,
            event_key=f'session:{session.id}:player:{wallet.player_id}',
            amount_delta=amount, balance_after=account.saved_gold, reason='session_settlement'))
    session.economy_settled_at = datetime.now(timezone.utc)
    db.session.flush()
    return True


def current_config(session_id):
    from app.models.game import GameRound
    return (ClassicRoundConfig.query.join(GameRound)
            .filter(GameRound.session_id == session_id)
            .order_by(GameRound.round_number.desc()).first())


def bonus_capacity(player_id, session_id, bonus_type):
    from app.modes.classic.store import get_active_counts
    config = current_config(session_id)
    counts = get_active_counts(player_id, session_id)
    # Each effect has one held charge; Double Mine consumes only one action.
    if counts.get(bonus_type, 0) >= 1:
        return False
    return sum(counts.values()) < config.active_bonus_limit


def capped_permanent_bonus(wallet, config, requested, base_gold):
    """Additive bonus with fractional carry, never exceeding the earning cap."""
    if config.standardized_competition or requested <= 0:
        return 0
    allowed = min(float(requested), max(0, base_gold) * config.permanent_bonus_cap)
    total = allowed + wallet.gear_bonus_remainder
    granted = int(total + 1e-9)
    wallet.gear_bonus_remainder = total - granted
    return granted


DEFAULT_STORE = (
    ('Shield Token', 'steal_shield', 1),
    ('Second Chance', 'shield', 1),
    ('Steal Token', 'steal_token', 1),
    ('Double Mine', 'x2_mine', 2),
)


def seed_session_store(session_id, config=None):
    from app.models.classic import StoreItem
    if config is not None and not any((config.gem_milestone_count, config.gem_streak_count,
                                       config.gem_treasure_chance)):
        return
    for name, effect, price in DEFAULT_STORE:
        if config is not None:
            if effect == 'steal_shield' and not config.active_shield_duration:
                continue
            if effect == 'steal_token' and not config.steal_attempt_limit:
                continue
        db.session.add(StoreItem(session_id=session_id, name=name,
            description='Temporary session item', cost=price, currency='gems',
            bonus_type=effect, session_stock=-1, per_player_limit=2))
