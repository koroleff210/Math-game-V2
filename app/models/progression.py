# app/models/progression.py
#
# Persistent meta-progression models — Diamonds/Upgrades Phase D0–D4.
#
# These tables form the data-model foundation for Diamonds and permanent
# upgrade mechanics.  No gameplay, shop UI, or admin award UI is wired here.
#
#   PlayerProgression        — one persistent row per player; holds diamond balance
#   DiamondTransaction       — immutable ledger of every diamond balance change
#   PlayerUpgrade            — one row per player per upgrade type; holds level
#   SessionParticipantSnapshot — session-scoped frozen effective values (one per player per session)
#
# Boundaries (enforced by design):
#   - Diamonds must never live in PlayerWallet (session-scoped) or Player (identity)
#   - Upgrade levels are persistent; their *effects* are frozen at join time (session scope)
#   - SessionParticipantSnapshot is the runtime source of truth for upgrade effects
#   - History models (RoundHistory, RoundPlayerResult) are never touched here

from datetime import datetime, timezone

from app.extensions import db


# ── PlayerProgression ─────────────────────────────────────────────────────────

class PlayerProgression(db.Model):
    """Persistent diamond balance for a player.

    One row per player (unique FK).  Created on first award or on demand.
    Balance changes must always be accompanied by a DiamondTransaction entry.
    """
    __tablename__ = 'player_progression'

    id        = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(
        db.Integer, db.ForeignKey('player.id'), unique=True, nullable=False
    )

    diamonds_balance = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    player = db.relationship('Player', backref=db.backref('progression', uselist=False))

    def __repr__(self):
        return f'<PlayerProgression player={self.player_id} diamonds={self.diamonds_balance}>'


# ── DiamondTransaction ────────────────────────────────────────────────────────

class DiamondTransaction(db.Model):
    """Immutable audit ledger for every diamond balance change.

    Never mutated after creation.  Every award or spend must write a row here
    alongside updating PlayerProgression.diamonds_balance.

    Fields:
      amount_delta   positive = award, negative = spend
      balance_after  snapshot of PlayerProgression.diamonds_balance after this tx
      reason         short machine-readable string (e.g. 'admin_award', 'upgrade_purchase')
      admin_player_id  the admin who triggered the change (nullable; NULL for system events)
      session_id       the session context if relevant (nullable)
    """
    __tablename__ = 'diamond_transaction'

    id              = db.Column(db.Integer, primary_key=True)
    player_id       = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    amount_delta    = db.Column(db.Integer, nullable=False)
    balance_after   = db.Column(db.Integer, nullable=False)
    reason          = db.Column(db.String(64), nullable=False)
    admin_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    session_id      = db.Column(
        db.Integer, db.ForeignKey('game_session.id'), nullable=True
    )
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    player       = db.relationship('Player', foreign_keys=[player_id],       backref='diamond_transactions')
    admin_player = db.relationship('Player', foreign_keys=[admin_player_id])
    session      = db.relationship('GameSession', backref='diamond_transactions')

    def __repr__(self):
        return (
            f'<DiamondTransaction player={self.player_id} delta={self.amount_delta:+d} '
            f'after={self.balance_after} reason={self.reason!r}>'
        )


# ── PlayerUpgrade ─────────────────────────────────────────────────────────────

class PlayerUpgrade(db.Model):
    """Persistent upgrade level for a specific upgrade type owned by a player.

    One row per (player_id, upgrade_type) pair — enforced by UNIQUE constraint.
    level starts at 0 (not yet purchased / not applicable) and increments with
    each purchase.  Max level per upgrade type is defined in the Python-side
    upgrade catalog (added in a later phase).

    upgrade_type examples: 'steal_token_cap', 'mine_bonus',
                            'treasure_bonus', 'shield_bonus_pct'
    """
    __tablename__ = 'player_upgrade'

    id           = db.Column(db.Integer, primary_key=True)
    player_id    = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    upgrade_type = db.Column(db.String(64), nullable=False)
    level        = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint('player_id', 'upgrade_type', name='uq_player_upgrade_type'),
    )

    player = db.relationship('Player', backref='upgrades')

    def __repr__(self):
        return (
            f'<PlayerUpgrade player={self.player_id} type={self.upgrade_type!r} '
            f'level={self.level}>'
        )


# ── SessionParticipantSnapshot ────────────────────────────────────────────────

class SessionParticipantSnapshot(db.Model):
    """Session-scoped frozen snapshot of a player's effective runtime values.

    Created once at explicit Join time and never updated.  Values represent
    the player's upgrade-derived and gear-derived gameplay effects for the
    entire session.

    Keyed by (session_id, player_id) — one row per player per session.
    Runtime source of truth for upgrade-derived gameplay effects.

    Fields:
      effective_steal_token_cap  max steal tokens the player may hold this session
      effective_mine_bonus       extra gold added to each mine action reward
      effective_treasure_bonus   extra gold added to each treasure search reward
      effective_shield_bonus_pct percentage bonus applied to shield duration
                                  (0.0 = no bonus, 0.10 = +10%)
      effective_gear_mine_gold_delta
                                 flat gold delta added to each mine action
      effective_gear_steal_gold_delta
                                 flat gold delta added to the steal amount
      effective_gear_shield_duration_delta
                                 flat seconds delta added before shield pct scaling
    """
    __tablename__ = 'session_participant_snapshot'

    id         = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('game_session.id'), nullable=False)
    player_id  = db.Column(db.Integer, db.ForeignKey('player.id'),       nullable=False)

    effective_steal_token_cap  = db.Column(db.Integer, nullable=False, default=1)
    effective_mine_bonus       = db.Column(db.Integer, nullable=False, default=0)
    effective_treasure_bonus   = db.Column(db.Integer, nullable=False, default=0)
    effective_shield_bonus_pct = db.Column(db.Float,   nullable=False, default=0.0)
    effective_gear_mine_gold_delta = db.Column(db.Integer, nullable=False, default=0)
    effective_gear_steal_gold_delta = db.Column(db.Integer, nullable=False, default=0)
    effective_gear_shield_duration_delta = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint('session_id', 'player_id', name='uq_session_participant_snapshot'),
    )

    session = db.relationship(
        'GameSession',
        backref=db.backref('participant_snapshots', cascade='all, delete-orphan'),
    )
    player  = db.relationship('Player',      backref='session_snapshots')

    def __repr__(self):
        return (
            f'<SessionParticipantSnapshot session={self.session_id} player={self.player_id} '
            f'steal_cap={self.effective_steal_token_cap}>'
        )
