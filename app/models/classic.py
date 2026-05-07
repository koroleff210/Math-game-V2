# app/models/classic.py
#
# Database models specific to Classic Mode.
# These are separate from the mode-agnostic game session models in game.py.
#
#   ClassicRoundConfig  — per-round settings set by admin before starting
#   PlayerWallet        — session-scoped economy (gold, gems, steal_tokens)
#   PlayerClassicState  — [Step D] per-player gameplay state (shield timer, etc.)
#   PlayerProblemState  — per-player personal progress on each problem in a round
#   ProblemSolverCount  — tracks how many players have solved each problem (for first-solver bonus)
#   StoreItem           — [Step B] items available for purchase in a session
#   PlayerInventory     — [Step B] session consumables inventory (not persistent gear)
#   StealEvent          — [Step D] audit log of every steal attempt

from datetime import datetime, timezone
from app.extensions import db


# ── ClassicRoundConfig ────────────────────────────────────────────────────────

class ClassicRoundConfig(db.Model):
    __tablename__ = 'classic_round_config'

    id       = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('game_round.id'), unique=True, nullable=False)

    # Core economy
    mine_reward            = db.Column(db.Integer, nullable=False, default=20)
    treasure_search_reward = db.Column(db.Integer, nullable=False, default=5)
    attempts_per_problem   = db.Column(db.Integer, nullable=False, default=1)   # -1 = unlimited
    wrong_answer_penalty   = db.Column(db.Integer, nullable=False, default=0)

    # Timer bonus: any correct answer submitted within bonus_timer_duration seconds earns bonus_timer_gold
    bonus_timer_duration   = db.Column(db.Integer, nullable=False, default=120)  # 0 = disabled
    bonus_timer_gold       = db.Column(db.Integer, nullable=False, default=5)

    # First-solver bonus
    # Formula: max(0, (first_solver_count - (solver_rank - 1)) * first_solver_multiplier)
    first_solver_count      = db.Column(db.Integer, nullable=False, default=3)
    first_solver_multiplier = db.Column(db.Integer, nullable=False, default=2)

    # [Step C] Random Treasure Search gold and gem awards
    # treasure_search_max_reward: upper bound for TS gold roll; min = treasure_search_reward
    #   When max == min, the roll is deterministic (backward-compatible).
    # gem_milestone_count: solved problems per round needed per +1 gem (0 = disabled)
    # gem_streak_count: consecutive correct answers per +1 gem (0 = disabled)
    # gem_treasure_chance: probability (0.0–1.0) that a Treasure Search awards 1 gem (0.0 = disabled)
    treasure_search_max_reward = db.Column(db.Integer, nullable=False, default=5)
    gem_milestone_count        = db.Column(db.Integer, nullable=False, default=5)
    gem_streak_count           = db.Column(db.Integer, nullable=False, default=3)
    gem_treasure_chance        = db.Column(db.Float,   nullable=False, default=0.5)

    # [Step D] Steal system config
    steal_percent               = db.Column(db.Float,   nullable=False, default=0.10)
    steal_min_cap               = db.Column(db.Integer, nullable=False, default=10)
    steal_max_cap               = db.Column(db.Integer, nullable=False, default=50)   # -1 = no upper cap
    steal_fallback_gold         = db.Column(db.Integer, nullable=False, default=5)
    steal_chest_count           = db.Column(db.Integer, nullable=False, default=6)    # 0 = mini-game disabled
    steal_winning_chest_count   = db.Column(db.Integer, nullable=False, default=4)
    shield_duration              = db.Column(db.Integer, nullable=False, default=60)   # deprecated schema residue; runtime uses split fields below
    active_shield_duration       = db.Column(db.Integer, nullable=False, default=60)   # manual shield-token activation
    reactive_shield_duration     = db.Column(db.Integer, nullable=False, default=20)   # victim protection after steal
    # treasure_steal_token_chance: probability that a Treasure Search action awards a steal token.
    # Named under the treasure system because it is a treasure reward, not a steal mechanic.
    treasure_steal_token_chance = db.Column(db.Float,   nullable=False, default=0.6)

    # Treasure chest fill chances. Each currently eligible reward type becomes one chest.
    # Each shown chest rolls filled/empty independently.
    treasure_active_shield_chance = db.Column(db.Float, nullable=False, default=0.6)
    treasure_second_chance_chance = db.Column(db.Float, nullable=False, default=0.5)

    round = db.relationship('GameRound', backref=db.backref('classic_config', uselist=False))

    def __repr__(self):
        return f'<ClassicRoundConfig round={self.round_id} mine={self.mine_reward}>'


# ── PlayerWallet ──────────────────────────────────────────────────────────────

class PlayerWallet(db.Model):
    __tablename__ = 'player_wallet'

    id         = db.Column(db.Integer, primary_key=True)
    player_id  = db.Column(db.Integer, db.ForeignKey('player.id'),       nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False)

    # Gold and gems are both session-scoped: they accumulate across all rounds in the
    # same session. A new session always creates a fresh wallet (both reset to 0).
    # Diamonds are player-scoped meta-progression currency; deferred to Step E.
    gold = db.Column(db.Integer, nullable=False, default=0)
    gems = db.Column(db.Integer, nullable=False, default=0)  # [Step C]

    # [Step D] steal_tokens: starts at 1 per wallet creation (cap = 1 for Step D).
    # shield_expires_at (steal protection) lives in PlayerClassicState, not here. See AD-27.
    steal_tokens = db.Column(db.Integer, nullable=False, default=1)

    __table_args__ = (
        db.UniqueConstraint('player_id', 'session_id', name='uq_wallet_player_session'),
    )

    player  = db.relationship('Player',      backref='wallets',        lazy='select')
    session = db.relationship('GameSession', backref='player_wallets', lazy='select')

    def __repr__(self):
        return f'<PlayerWallet player={self.player_id} session={self.session_id} gold={self.gold} gems={self.gems}>'


# ── PlayerClassicState ────────────────────────────────────────────────────────

class PlayerClassicState(db.Model):
    """Per-player Classic Mode gameplay state for a session.

    Holds time-based state that is NOT economy data and therefore does not
    belong in PlayerWallet.

    shield_expires_at: time-based steal protection (AD-27).
      NULL = no shield active.
      Active when shield_expires_at is not None AND > utcnow().
      Separate from PlayerInventory bonus_type='shield' (wrong-answer absorber).
    """
    __tablename__ = 'player_classic_state'

    id         = db.Column(db.Integer, primary_key=True)
    player_id  = db.Column(db.Integer, db.ForeignKey('player.id'),       nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False)

    shield_expires_at = db.Column(db.DateTime, nullable=True)  # NULL = no steal shield active

    __table_args__ = (
        db.UniqueConstraint('player_id', 'session_id', name='uq_pcs_player_session'),
    )

    player  = db.relationship('Player',      backref='classic_states', lazy='select')
    session = db.relationship('GameSession',
                              backref=db.backref('player_classic_states', cascade='all, delete-orphan'),
                              lazy='select')

    def __repr__(self):
        return f'<PlayerClassicState player={self.player_id} session={self.session_id} shield={self.shield_expires_at}>'


# ── PlayerProblemState ────────────────────────────────────────────────────────

class PlayerProblemState(db.Model):
    __tablename__ = 'player_problem_state'

    id         = db.Column(db.Integer, primary_key=True)
    player_id  = db.Column(db.Integer, db.ForeignKey('player.id'),     nullable=False)
    round_id   = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'),    nullable=False)

    attempts_used = db.Column(db.Integer, nullable=False, default=0)
    is_solved     = db.Column(db.Boolean, nullable=False, default=False)

    # is_closed = True when problem is solved OR all attempts are exhausted.
    # A closed problem cannot be submitted again by this player.
    is_closed     = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        db.UniqueConstraint(
            'player_id', 'round_id', 'problem_id',
            name='uq_pps_player_round_problem'
        ),
    )

    player  = db.relationship('Player',  backref='problem_states', lazy='select')
    problem = db.relationship('Problem', backref='player_states',  lazy='select')

    def __repr__(self):
        return (
            f'<PlayerProblemState player={self.player_id} '
            f'round={self.round_id} problem={self.problem_id} '
            f'solved={self.is_solved} closed={self.is_closed}>'
        )


# ── ProblemSolverCount ────────────────────────────────────────────────────────

class ProblemSolverCount(db.Model):
    __tablename__ = 'problem_solver_count'

    id         = db.Column(db.Integer, primary_key=True)
    round_id   = db.Column(db.Integer, db.ForeignKey('game_round.id'), nullable=False)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'),    nullable=False)

    # solver_count: incremented each time any player correctly solves this problem.
    # Used to compute first-solver bonus rank (1st, 2nd, 3rd to solve = rank 1, 2, 3).
    solver_count = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('round_id', 'problem_id', name='uq_psc_round_problem'),
    )

    def __repr__(self):
        return f'<ProblemSolverCount round={self.round_id} problem={self.problem_id} count={self.solver_count}>'


# ── StoreItem ─────────────────────────────────────────────────────────────────

class StoreItem(db.Model):
    """An item that players can buy during a Classic session.

    currency ∈ ['gold', 'gems']: which wallet field the cost is deducted from.

    bonus_type ∈ ['x2_mine', 'shield', 'steal_token', 'steal_shield']
      x2_mine     — doubles the mine reward for the next Mine action (one-time use)
      shield      — Second Chance: wrong answer preserves attempt, no penalty (one-time use)
      steal_token — immediately credits 1 steal token
      steal_shield — manual theft-protection token

    session_stock    = -1 means unlimited session-wide stock.
    per_player_limit = -1 means unlimited per-player purchases.
    """
    __tablename__ = 'store_item'

    id         = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False)

    name        = db.Column(db.String(80),  nullable=False)
    description = db.Column(db.String(255), nullable=True)
    cost        = db.Column(db.Integer,     nullable=False)
    currency    = db.Column(db.String(10),  nullable=False, default='gold')  # 'gold' | 'gems'
    bonus_type       = db.Column(db.String(20),  nullable=False)           # 'x2_mine' | 'shield'
    session_stock    = db.Column(db.Integer,     nullable=False, default=-1)  # -1 = unlimited
    per_player_limit = db.Column(db.Integer,     nullable=False, default=-1)  # -1 = unlimited
    is_system        = db.Column(db.Boolean,     nullable=False, default=False)  # D4b: hidden system item

    session   = db.relationship('GameSession', backref='store_items', lazy='select')
    # Backref name kept for compatibility. This relationship points to
    # session consumables inventory rows, not persistent Hub gear ownership.
    inventory = db.relationship('PlayerInventory', backref='item', lazy='dynamic')

    def __repr__(self):
        return f'<StoreItem {self.name!r} cost={self.cost} session={self.session_id}>'


# ── PlayerInventory ───────────────────────────────────────────────────────────

class PlayerInventory(db.Model):
    """One purchased instance of a StoreItem in a player's session consumables inventory.

    used_at is NULL while the item is active; set when the item is consumed.
    Each row represents a single purchased copy of an item (one row = one use).
    This is session runtime state only. Persistent Hub gear ownership/loadout
    lives in PlayerGearOwnership / PlayerGearLoadout instead.
    """
    __tablename__ = 'player_inventory'

    id           = db.Column(db.Integer,  primary_key=True)
    player_id    = db.Column(db.Integer,  db.ForeignKey('player.id'),       nullable=False)
    session_id   = db.Column(db.Integer,  db.ForeignKey('game_session.id'), nullable=False)
    item_id      = db.Column(db.Integer,  db.ForeignKey('store_item.id'),   nullable=False)
    purchased_at = db.Column(db.DateTime, nullable=False)
    used_at      = db.Column(db.DateTime, nullable=True)  # NULL = item still active

    # Backref names kept for compatibility. Both refer to session consumables
    # inventory, not the player's persistent Hub gear collection.
    player  = db.relationship('Player',      backref='inventory',         lazy='select')
    session = db.relationship('GameSession', backref='player_inventory',  lazy='select')

    def __repr__(self):
        return (
            f'<PlayerInventory player={self.player_id} item={self.item_id} '
            f'used={"yes" if self.used_at else "no"}>'
        )


# ── StealEvent ────────────────────────────────────────────────────────────────

class StealEvent(db.Model):
    """Audit log for every steal attempt in a Classic session.

    outcome ∈ ['targeted_success', 'stranger_chest', 'stranger_no_targets', 'stranger_target_invalid']
      targeted_success      — gold transferred from target to actor
      stranger_chest        — non-winning chest picked; actor gets Stranger steal gold
      stranger_no_targets   — no valid targets existed; actor gets Stranger steal gold
      stranger_target_invalid — target became invalid, so the attempt converted to Stranger steal

    target_id is NULL when outcome='stranger_no_targets'.
    mini_game_pick is NULL when the mini-game is disabled.
    gold_exchanged stores the actor's gained gold for each outcome.
    """
    __tablename__ = 'steal_event'

    id             = db.Column(db.Integer,  primary_key=True)
    session_id     = db.Column(db.Integer,  db.ForeignKey('game_session.id'), nullable=False, index=True)
    round_id       = db.Column(db.Integer,  db.ForeignKey('game_round.id'),   nullable=False)
    actor_id       = db.Column(db.Integer,  db.ForeignKey('player.id'),       nullable=False)
    target_id      = db.Column(db.Integer,  db.ForeignKey('player.id'),       nullable=True)   # NULL for stranger_no_targets
    outcome        = db.Column(db.String(32), nullable=False)
    gold_exchanged = db.Column(db.Integer,  nullable=False)
    mini_game_pick = db.Column(db.Integer,  nullable=True)      # chest index chosen; NULL when mini-game disabled
    created_at     = db.Column(db.DateTime, nullable=False)

    session = db.relationship('GameSession', backref='steal_events',   lazy='select',
                              foreign_keys=[session_id])
    actor   = db.relationship('Player', backref='steal_events_as_actor',  lazy='select',
                              foreign_keys=[actor_id])
    target  = db.relationship('Player', backref='steal_events_as_target', lazy='select',
                              foreign_keys=[target_id])

    def __repr__(self):
        return (
            f'<StealEvent session={self.session_id} actor={self.actor_id} '
            f'target={self.target_id} outcome={self.outcome!r} gold={self.gold_exchanged}>'
        )
