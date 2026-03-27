from datetime import datetime, timezone

from app.extensions import db


GEAR_SLOT_MAIN_HAND = 'main_hand'
GEAR_SLOT_OFF_HAND = 'off_hand'
GEAR_SLOT_CHEST = 'chest'
# Current schema keeps the persistent headgear slot under the legacy key
# "head". Cosmetic face/head identity is separate from this gameplay slot.
GEAR_SLOT_HEAD = 'head'
GEAR_SLOT_BOOTS = 'boots'
GEAR_SLOT_POCKET = 'pocket'

GEAR_SLOT_TYPES = (
    GEAR_SLOT_MAIN_HAND,
    GEAR_SLOT_OFF_HAND,
    GEAR_SLOT_CHEST,
    GEAR_SLOT_HEAD,
    GEAR_SLOT_BOOTS,
    GEAR_SLOT_POCKET,
)


class GearItemDefinition(db.Model):
    """Persistent definition of one gear item.

    `id` is the canonical item identifier used everywhere else in the gear
    system. The table stores only static definition data; ownership and equip
    state live in separate persistent tables.
    """
    __tablename__ = 'gear_item_definition'

    id = db.Column(db.String(64), primary_key=True)
    slot_type = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(255), nullable=False, default='')
    image_key = db.Column(db.String(255), nullable=True)
    avatar_asset_key = db.Column(db.String(16), nullable=True)
    diamond_cost = db.Column(db.Integer, nullable=False, default=0)

    mine_gold_delta = db.Column(db.Integer, nullable=False, default=0)
    steal_gold_delta = db.Column(db.Integer, nullable=False, default=0)
    shield_duration_delta = db.Column(db.Integer, nullable=False, default=0)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_blacksmith_visible = db.Column(db.Boolean, nullable=False, default=True)

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

    def __repr__(self):
        return f'<GearItemDefinition id={self.id!r} slot={self.slot_type!r}>'


class PlayerGearOwnership(db.Model):
    """Persistent ownership row for one player and one gear item."""
    __tablename__ = 'player_gear_ownership'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=False
    )
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint('player_id', 'item_id', name='uq_player_gear_ownership'),
    )

    player = db.relationship('Player', backref='gear_ownerships', lazy='select')
    item = db.relationship('GearItemDefinition', backref='owners', lazy='select')

    def __repr__(self):
        return f'<PlayerGearOwnership player={self.player_id} item={self.item_id!r}>'


class PlayerGearLoadout(db.Model):
    """Persistent equipped gear loadout for one player.

    This table belongs to the Hub / persistent preparation layer. Runtime
    gameplay must read frozen session participant snapshots instead of this
    live loadout row after the player joins a session.
    """
    __tablename__ = 'player_gear_loadout'

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(
        db.Integer, db.ForeignKey('player.id'), unique=True, nullable=False
    )

    main_hand_item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True
    )
    off_hand_item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True
    )
    chest_item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True
    )
    head_item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True
    )
    boots_item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True
    )
    pocket1_item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True
    )
    pocket2_item_id = db.Column(
        db.String(64), db.ForeignKey('gear_item_definition.id'), nullable=True
    )

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

    player = db.relationship('Player', backref=db.backref('gear_loadout', uselist=False))
    main_hand_item = db.relationship('GearItemDefinition', foreign_keys=[main_hand_item_id])
    off_hand_item = db.relationship('GearItemDefinition', foreign_keys=[off_hand_item_id])
    chest_item = db.relationship('GearItemDefinition', foreign_keys=[chest_item_id])
    head_item = db.relationship('GearItemDefinition', foreign_keys=[head_item_id])
    boots_item = db.relationship('GearItemDefinition', foreign_keys=[boots_item_id])
    pocket1_item = db.relationship('GearItemDefinition', foreign_keys=[pocket1_item_id])
    pocket2_item = db.relationship('GearItemDefinition', foreign_keys=[pocket2_item_id])

    def __repr__(self):
        return f'<PlayerGearLoadout player={self.player_id}>'
