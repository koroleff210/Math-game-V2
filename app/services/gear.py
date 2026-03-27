from datetime import datetime, timezone
import os

from flask import current_app

from app.extensions import db
from app.models.gear import (
    GEAR_SLOT_BOOTS,
    GEAR_SLOT_CHEST,
    GEAR_SLOT_HEAD,
    GEAR_SLOT_MAIN_HAND,
    GEAR_SLOT_OFF_HAND,
    GEAR_SLOT_POCKET,
    GEAR_SLOT_TYPES,
    GearItemDefinition,
    PlayerGearLoadout,
    PlayerGearOwnership,
)


SLOT_KEY_TO_ATTR = {
    'main_hand': 'main_hand_item_id',
    'off_hand': 'off_hand_item_id',
    'chest': 'chest_item_id',
    'head': 'head_item_id',
    'boots': 'boots_item_id',
    'pocket1': 'pocket1_item_id',
    'pocket2': 'pocket2_item_id',
}

ATTR_TO_SLOT_KEY = {v: k for k, v in SLOT_KEY_TO_ATTR.items()}

LOADOUT_SLOTS = (
    ('main_hand_item_id', 'Main Hand', GEAR_SLOT_MAIN_HAND),
    ('off_hand_item_id', 'Off Hand', GEAR_SLOT_OFF_HAND),
    ('chest_item_id', 'Chest', GEAR_SLOT_CHEST),
    ('head_item_id', 'Headgear', GEAR_SLOT_HEAD),
    ('boots_item_id', 'Boots', GEAR_SLOT_BOOTS),
    ('pocket1_item_id', 'Pocket 1', GEAR_SLOT_POCKET),
    ('pocket2_item_id', 'Pocket 2', GEAR_SLOT_POCKET),
)

GEAR_SLOT_LABELS = {
    GEAR_SLOT_MAIN_HAND: 'Main Hand',
    GEAR_SLOT_OFF_HAND: 'Off Hand',
    GEAR_SLOT_CHEST: 'Chest',
    # Keep the slot key "head" for compatibility, but use "Headgear" in
    # player-facing persistent gear surfaces so it does not conflict with the
    # cosmetic avatar face/head identity.
    GEAR_SLOT_HEAD: 'Headgear',
    GEAR_SLOT_BOOTS: 'Boots',
    GEAR_SLOT_POCKET: 'Pocket Items',
}

GEAR_SLOT_ORDER = (
    GEAR_SLOT_MAIN_HAND,
    GEAR_SLOT_OFF_HAND,
    GEAR_SLOT_CHEST,
    GEAR_SLOT_HEAD,
    GEAR_SLOT_BOOTS,
    GEAR_SLOT_POCKET,
)

HUB_FILTER_TABS = (
    ('all', 'All', None),
    (GEAR_SLOT_MAIN_HAND, 'Main hand', GEAR_SLOT_MAIN_HAND),
    (GEAR_SLOT_OFF_HAND, 'Off hand', GEAR_SLOT_OFF_HAND),
    (GEAR_SLOT_HEAD, 'Headgear', GEAR_SLOT_HEAD),
    (GEAR_SLOT_CHEST, 'Chest', GEAR_SLOT_CHEST),
    (GEAR_SLOT_BOOTS, 'Boots', GEAR_SLOT_BOOTS),
    (GEAR_SLOT_POCKET, 'Pocket', GEAR_SLOT_POCKET),
)

SAMPLE_GEAR_ITEMS = (
    {
        'id': 'bronze_pickaxe',
        'slot_type': GEAR_SLOT_MAIN_HAND,
        'name': 'Bronze Pickaxe',
        'description': 'A starter mining tool with a small flat mine bonus.',
        'avatar_asset_key': '001',
        'diamond_cost': 8,
        'mine_gold_delta': 2,
    },
    {
        'id': 'oak_buckler',
        'slot_type': GEAR_SLOT_OFF_HAND,
        'name': 'Oak Buckler',
        'description': 'A basic shield that slightly extends shield duration.',
        'avatar_asset_key': '001',
        'diamond_cost': 8,
        'shield_duration_delta': 5,
    },
    {
        'id': 'linen_hood',
        'slot_type': GEAR_SLOT_HEAD,
        'name': 'Linen Hood',
        'description': 'Simple headwear with no gameplay bonus.',
        'avatar_asset_key': '001',
        'diamond_cost': 4,
    },
    {
        'id': 'padded_vest',
        'slot_type': GEAR_SLOT_CHEST,
        'name': 'Padded Vest',
        'description': 'A light chest piece with no gameplay bonus.',
        'avatar_asset_key': '001',
        'diamond_cost': 5,
    },
    {
        'id': 'trail_boots',
        'slot_type': GEAR_SLOT_BOOTS,
        'name': 'Trail Boots',
        'description': 'Reliable boots with no gameplay bonus.',
        'avatar_asset_key': '001',
        'diamond_cost': 5,
    },
    {
        'id': 'test_helmet_001',
        'slot_type': GEAR_SLOT_HEAD,
        'name': 'Test Helmet 001',
        'description': 'Simple test helmet for avatar preview checks.',
        'avatar_asset_key': '001',
        'diamond_cost': 1,
    },
    {
        'id': 'test_chest_001',
        'slot_type': GEAR_SLOT_CHEST,
        'name': 'Test Chest 001',
        'description': 'Simple test chest item for avatar preview checks.',
        'avatar_asset_key': '001',
        'diamond_cost': 1,
    },
    {
        'id': 'test_boots_001',
        'slot_type': GEAR_SLOT_BOOTS,
        'name': 'Test Boots 001',
        'description': 'Simple test boots item for avatar preview checks.',
        'avatar_asset_key': '001',
        'diamond_cost': 1,
    },
    {
        'id': 'test_main_hand_001',
        'slot_type': GEAR_SLOT_MAIN_HAND,
        'name': 'Test Main Hand 001',
        'description': 'Simple test main-hand item for avatar preview checks.',
        'avatar_asset_key': '001',
        'diamond_cost': 1,
    },
    {
        'id': 'test_off_hand_001',
        'slot_type': GEAR_SLOT_OFF_HAND,
        'name': 'Test Off Hand 001',
        'description': 'Simple test off-hand item for avatar preview checks.',
        'avatar_asset_key': '001',
        'diamond_cost': 1,
    },
    {
        'id': 'lucky_coin',
        'slot_type': GEAR_SLOT_POCKET,
        'name': 'Lucky Coin',
        'description': 'A pocket item that adds a small flat steal bonus.',
        'diamond_cost': 6,
        'steal_gold_delta': 1,
    },
    {
        'id': 'time_charm',
        'slot_type': GEAR_SLOT_POCKET,
        'name': 'Time Charm',
        'description': 'A pocket item that slightly extends shield duration.',
        'diamond_cost': 6,
        'shield_duration_delta': 3,
    },
)

GEAR_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')
GEAR_PLACEHOLDER_BY_SLOT = {
    GEAR_SLOT_MAIN_HAND: 'placeholder_main_hand.svg',
    GEAR_SLOT_OFF_HAND: 'placeholder_off_hand.svg',
    GEAR_SLOT_CHEST: 'placeholder_chest.svg',
    GEAR_SLOT_HEAD: 'placeholder_head.svg',
    GEAR_SLOT_BOOTS: 'placeholder_boots.svg',
    GEAR_SLOT_POCKET: 'placeholder_pocket.svg',
}
GEAR_ICON_FOLDERS = {
    GEAR_SLOT_MAIN_HAND: 'main_hand',
    GEAR_SLOT_OFF_HAND: 'off_hand',
    GEAR_SLOT_CHEST: 'chest',
    GEAR_SLOT_HEAD: 'head',
    GEAR_SLOT_BOOTS: 'boots',
    GEAR_SLOT_POCKET: 'pocket',
}

_AVATAR_ASSET_KEY_PATTERNS = {
    GEAR_SLOT_MAIN_HAND: 'main_hand_',
    GEAR_SLOT_OFF_HAND: 'off_hand_',
    GEAR_SLOT_CHEST: 'chest_',
    GEAR_SLOT_BOOTS: 'boots_',
    GEAR_SLOT_HEAD: 'head_',
}


def get_or_create_player_gear_loadout(player_id: int):
    """Return the persistent loadout row for a player, creating it if absent."""
    row = PlayerGearLoadout.query.filter_by(player_id=player_id).first()
    created = False
    if row is None:
        row = PlayerGearLoadout(
            player_id=player_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(row)
        db.session.flush()
        created = True
    return row, created


def ensure_sample_gear_items() -> list:
    """Create the built-in sample gear catalog if items are missing.

    Safe to call repeatedly. Caller owns commit/rollback.
    """
    created = []
    for item_data in SAMPLE_GEAR_ITEMS:
        existing = db.session.get(GearItemDefinition, item_data['id'])
        if existing is not None:
            continue
        item = GearItemDefinition(**item_data)
        db.session.add(item)
        created.append(item)
    if created:
        db.session.flush()
    return created


def _loadout_slot_map():
    return {
        attr_name: {
            'label': label,
            'expected_slot': expected_slot,
            'slot_key': ATTR_TO_SLOT_KEY[attr_name],
        }
        for attr_name, label, expected_slot in LOADOUT_SLOTS
    }


def normalize_player_gear_loadout(player_id: int) -> dict:
    """Ensure the player's loadout row exists and clear inactive/missing refs.

    Returns a dict describing whether a row was created and whether stale slot
    refs were cleared. Caller owns commit/rollback.
    """
    loadout, created = get_or_create_player_gear_loadout(player_id)
    changed = False

    for attr_name, _label, _expected_slot in LOADOUT_SLOTS:
        item_id = getattr(loadout, attr_name)
        if not item_id:
            continue
        item = db.session.get(GearItemDefinition, item_id)
        if item is None or not item.is_active:
            setattr(loadout, attr_name, None)
            changed = True

    if changed:
        loadout.updated_at = datetime.now(timezone.utc)
        db.session.flush()

    return {
        'loadout': loadout,
        'created': created,
        'changed': changed,
    }


def build_frozen_gear_modifiers_for_player(player_id: int) -> dict:
    """Resolve the player's normalized loadout into frozen scalar gear totals.

    Caller owns commit/rollback. Any inactive or missing equipped refs are
    normalized out through normalize_player_gear_loadout() before aggregation.
    """
    state = normalize_player_gear_loadout(player_id)
    loadout = state['loadout']

    totals = {
        'effective_gear_mine_gold_delta': 0,
        'effective_gear_steal_gold_delta': 0,
        'effective_gear_shield_duration_delta': 0,
    }

    for attr_name, _label, _expected_slot in LOADOUT_SLOTS:
        item_id = getattr(loadout, attr_name)
        if not item_id:
            continue
        item = db.session.get(GearItemDefinition, item_id)
        if item is None or not item.is_active:
            continue
        totals['effective_gear_mine_gold_delta'] += item.mine_gold_delta
        totals['effective_gear_steal_gold_delta'] += item.steal_gold_delta
        totals['effective_gear_shield_duration_delta'] += item.shield_duration_delta

    totals['loadout_created'] = state['created']
    totals['loadout_normalized'] = state['changed']
    return totals


def _owned_item_ids(player_id: int) -> set:
    return {
        row.item_id
        for row in PlayerGearOwnership.query.filter_by(player_id=player_id).all()
    }


def _find_equipped_slot(loadout, item_id: str):
    for attr_name, _label, _expected_slot in LOADOUT_SLOTS:
        if getattr(loadout, attr_name) == item_id:
            return ATTR_TO_SLOT_KEY[attr_name]
    return None


def _get_equipped_slot_lookup(loadout) -> dict:
    lookup = {}
    for attr_name, label, _expected_slot in LOADOUT_SLOTS:
        item_id = getattr(loadout, attr_name)
        if not item_id:
            continue
        lookup[item_id] = {
            'slot_key': ATTR_TO_SLOT_KEY[attr_name],
            'slot_label': label,
        }
    return lookup


def _normalize_hub_filter(selected_filter: str | None) -> str:
    selected = (selected_filter or 'all').strip().lower()
    allowed = {key for key, _label, _slot_type in HUB_FILTER_TABS}
    return selected if selected in allowed else 'all'


def get_gear_image_directory() -> str:
    """Return the fixed static directory used for manually managed gear images."""
    return os.path.join(current_app.static_folder, 'gear')


def get_gear_image_slot_directory(slot_type: str) -> str:
    """Return the slot-scoped static directory used for gear preview images."""
    return os.path.join(get_gear_image_directory(), slot_type)


def get_gear_icon_directory(slot_type: str) -> str:
    """Return the fixed static directory used for small hub gear icons."""
    folder_name = GEAR_ICON_FOLDERS.get(slot_type, slot_type)
    return os.path.join(current_app.static_folder, 'gear_icons', folder_name)


def _derive_avatar_asset_key_from_image(*, slot_type: str, image_key: str | None) -> str | None:
    """Derive the legacy avatar asset key from the selected wearable filename."""
    if not image_key or slot_type == GEAR_SLOT_POCKET:
        return None

    lowered = image_key.lower()
    prefix = _AVATAR_ASSET_KEY_PATTERNS.get(slot_type)
    if not prefix or not lowered.startswith(prefix) or not lowered.endswith('.png'):
        return None

    suffix = lowered[len(prefix):-4]
    if slot_type == GEAR_SLOT_HEAD:
        if not suffix or suffix[-1] not in ('a', 'b'):
            return None
        return suffix[:-1] or None

    return suffix or None


def list_available_gear_image_keys(slot_type: str | None = None) -> list[str]:
    """Return sorted image filenames from the slot folder, or the legacy root folder."""
    folder = get_gear_image_slot_directory(slot_type) if slot_type else get_gear_image_directory()
    if not os.path.isdir(folder):
        return []

    filenames = []
    for name in os.listdir(folder):
        full_path = os.path.join(folder, name)
        if not os.path.isfile(full_path):
            continue
        if os.path.splitext(name)[1].lower() not in GEAR_IMAGE_EXTENSIONS:
            continue
        lowered = name.lower()
        if slot_type == GEAR_SLOT_CHEST:
            if lowered == 'body_upper.png' or lowered.endswith('a.png'):
                continue
        elif slot_type == GEAR_SLOT_HEAD:
            if not lowered.endswith('a.png'):
                continue
        elif slot_type == GEAR_SLOT_BOOTS:
            if lowered == 'body_lower.png':
                continue
        elif slot_type == GEAR_SLOT_OFF_HAND:
            if lowered == 'off_hand_base.png':
                continue
        filenames.append(name)
    return sorted(filenames, key=str.lower)


def build_gear_image_select_choices(slot_type: str | None = None) -> list[tuple[str, str]]:
    """Return SelectField choices for gear image selection."""
    return [('', '-- None --')] + [(name, name) for name in list_available_gear_image_keys(slot_type)]


def build_gear_image_select_choices_by_slot() -> dict[str, list[tuple[str, str]]]:
    """Return slot-scoped SelectField choices for all gear slot types."""
    return {
        slot_type: build_gear_image_select_choices(slot_type)
        for slot_type in GEAR_SLOT_TYPES
    }


def get_gear_placeholder_key(slot_type: str) -> str:
    """Return the placeholder filename for a gear slot family."""
    return GEAR_PLACEHOLDER_BY_SLOT.get(slot_type, GEAR_PLACEHOLDER_BY_SLOT[GEAR_SLOT_POCKET])


def _build_static_gear_path(filename: str, slot_type: str | None = None) -> str:
    if slot_type:
        return f'{current_app.static_url_path}/gear/{slot_type}/{filename}'
    return f'{current_app.static_url_path}/gear/{filename}'


def _build_static_gear_icon_path(slot_type: str, filename: str) -> str:
    folder_name = GEAR_ICON_FOLDERS.get(slot_type, slot_type)
    return f'{current_app.static_url_path}/gear_icons/{folder_name}/{filename}'


def resolve_gear_image_static_path(*, slot_type: str, image_key: str | None = None) -> str:
    """Return selected gear image path, or the slot placeholder path."""
    if image_key:
        slot_image_path = os.path.join(get_gear_image_slot_directory(slot_type), image_key)
        if os.path.isfile(slot_image_path):
            return _build_static_gear_path(image_key, slot_type)

        legacy_image_path = os.path.join(get_gear_image_directory(), image_key)
        if os.path.isfile(legacy_image_path):
            return _build_static_gear_path(image_key)

    return _build_static_gear_path(get_gear_placeholder_key(slot_type))


def resolve_gear_icon_static_path(*, slot_type: str, image_key: str | None = None) -> str:
    """Return the slot-scoped hub icon path matching the selected asset filename."""
    if image_key:
        icon_path = os.path.join(get_gear_icon_directory(slot_type), image_key)
        if os.path.isfile(icon_path):
            return _build_static_gear_icon_path(slot_type, image_key)
    return resolve_gear_image_static_path(slot_type=slot_type, image_key=image_key)


def list_admin_gear_catalog() -> list:
    """Return all persistent gear items for admin catalog listing."""
    items = (
        GearItemDefinition.query
        .order_by(GearItemDefinition.slot_type, GearItemDefinition.name, GearItemDefinition.id)
        .all()
    )
    return [build_admin_gear_item_view(item) for item in items]


def build_admin_gear_item_view(item: GearItemDefinition) -> dict:
    """Return one admin-facing dict for a catalog item."""
    return {
        'id': item.id,
        'slot_type': item.slot_type,
        'name': item.name,
        'description': item.description,
        'image_key': item.image_key,
        'avatar_asset_key': item.avatar_asset_key,
        'icon_static_path': resolve_gear_icon_static_path(
            slot_type=item.slot_type,
            image_key=item.image_key,
        ),
        'image_static_path': resolve_gear_image_static_path(
            slot_type=item.slot_type,
            image_key=item.image_key,
        ),
        'diamond_cost': item.diamond_cost,
        'mine_gold_delta': item.mine_gold_delta,
        'steal_gold_delta': item.steal_gold_delta,
        'shield_duration_delta': item.shield_duration_delta,
        'is_active': item.is_active,
        'is_blacksmith_visible': item.is_blacksmith_visible,
        'created_at': item.created_at,
        'updated_at': item.updated_at,
    }


def _clean_gear_catalog_payload(payload: dict) -> dict:
    item_id = (payload.get('item_id') or payload.get('id') or '').strip()
    name = (payload.get('name') or '').strip()
    description = (payload.get('description') or '').strip()
    slot_type = (payload.get('slot_type') or '').strip()
    image_key = (payload.get('image_key') or '').strip() or None
    avatar_asset_key = (payload.get('avatar_asset_key') or '').strip() or None
    derived_avatar_asset_key = _derive_avatar_asset_key_from_image(
        slot_type=slot_type,
        image_key=image_key,
    )

    cleaned = {
        'id': item_id,
        'name': name,
        'description': description,
        'slot_type': slot_type,
        'image_key': image_key,
        'avatar_asset_key': derived_avatar_asset_key or avatar_asset_key,
        'diamond_cost': payload.get('diamond_cost'),
        'mine_gold_delta': payload.get('mine_gold_delta'),
        'steal_gold_delta': payload.get('steal_gold_delta'),
        'shield_duration_delta': payload.get('shield_duration_delta'),
        'is_active': bool(payload.get('is_active')),
        'is_blacksmith_visible': bool(payload.get('is_blacksmith_visible')),
    }
    return cleaned


def _validate_gear_catalog_payload(cleaned: dict, *, existing_item_id: str | None = None) -> None:
    from app.services.avatar import list_available_avatar_asset_keys

    if not cleaned['id']:
        raise ValueError('Item ID is required.')
    if len(cleaned['id']) > 64:
        raise ValueError('Item ID must be 64 characters or fewer.')
    if not cleaned['name']:
        raise ValueError('Display name is required.')
    if not cleaned['description']:
        raise ValueError('Description is required.')
    if cleaned['slot_type'] not in GEAR_SLOT_TYPES:
        raise ValueError('Invalid gear slot type.')
    if cleaned['image_key'] is not None and cleaned['image_key'] not in list_available_gear_image_keys(cleaned['slot_type']):
        raise ValueError('Invalid gear image selection.')
    if cleaned['avatar_asset_key'] is not None:
        if len(cleaned['avatar_asset_key']) > 16:
            raise ValueError('Avatar asset key must be 16 characters or fewer.')
        if cleaned['slot_type'] == GEAR_SLOT_POCKET:
            raise ValueError('Pocket items do not support avatar asset keys.')
        allowed_avatar_keys = list_available_avatar_asset_keys(cleaned['slot_type'])
        if allowed_avatar_keys and cleaned['avatar_asset_key'] not in allowed_avatar_keys:
            raise ValueError('Invalid avatar asset key for that slot type.')

    for key in ('diamond_cost', 'mine_gold_delta', 'steal_gold_delta', 'shield_duration_delta'):
        value = cleaned[key]
        if not isinstance(value, int):
            raise ValueError(f'{key} must be an integer.')

    if cleaned['diamond_cost'] < 0:
        raise ValueError('Diamond cost must be 0 or higher.')

    existing = db.session.get(GearItemDefinition, cleaned['id'])
    if existing is not None and cleaned['id'] != existing_item_id:
        raise ValueError('A gear item with that Item ID already exists.')


def create_admin_gear_item(payload: dict) -> GearItemDefinition:
    """Create one gear item definition from admin-authored catalog data."""
    cleaned = _clean_gear_catalog_payload(payload)
    _validate_gear_catalog_payload(cleaned)

    item = GearItemDefinition(
        id=cleaned['id'],
        slot_type=cleaned['slot_type'],
        name=cleaned['name'],
        description=cleaned['description'],
        image_key=cleaned['image_key'],
        avatar_asset_key=cleaned['avatar_asset_key'],
        diamond_cost=cleaned['diamond_cost'],
        mine_gold_delta=cleaned['mine_gold_delta'],
        steal_gold_delta=cleaned['steal_gold_delta'],
        shield_duration_delta=cleaned['shield_duration_delta'],
        is_active=cleaned['is_active'],
        is_blacksmith_visible=cleaned['is_blacksmith_visible'],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add(item)
    db.session.flush()
    return item


def update_admin_gear_item(item_id: str, payload: dict) -> GearItemDefinition:
    """Update one existing gear item definition from admin-authored data."""
    item = db.session.get(GearItemDefinition, item_id)
    if item is None:
        raise ValueError('Gear item not found.')

    cleaned = _clean_gear_catalog_payload(payload)
    cleaned['id'] = item.id
    _validate_gear_catalog_payload(cleaned, existing_item_id=item.id)

    item.slot_type = cleaned['slot_type']
    item.name = cleaned['name']
    item.description = cleaned['description']
    item.image_key = cleaned['image_key']
    item.avatar_asset_key = cleaned['avatar_asset_key']
    item.diamond_cost = cleaned['diamond_cost']
    item.mine_gold_delta = cleaned['mine_gold_delta']
    item.steal_gold_delta = cleaned['steal_gold_delta']
    item.shield_duration_delta = cleaned['shield_duration_delta']
    item.is_active = cleaned['is_active']
    item.is_blacksmith_visible = cleaned['is_blacksmith_visible']
    item.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    return item


def delete_admin_gear_item(item_id: str) -> dict:
    """Delete one gear item definition and remove all persistent references."""
    item = db.session.get(GearItemDefinition, item_id)
    if item is None:
        raise ValueError('Gear item not found.')

    now = datetime.now(timezone.utc)
    cleared_loadout_slots = 0

    for attr_name, _label, _expected_slot in LOADOUT_SLOTS:
        cleared = (
            PlayerGearLoadout.query
            .filter(getattr(PlayerGearLoadout, attr_name) == item.id)
            .update(
                {
                    attr_name: None,
                    PlayerGearLoadout.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        cleared_loadout_slots += cleared

    removed_ownerships = (
        PlayerGearOwnership.query
        .filter_by(item_id=item.id)
        .delete(synchronize_session=False)
    )

    item_name = item.name
    db.session.delete(item)
    db.session.flush()

    return {
        'item_id': item.id,
        'item_name': item_name,
        'removed_ownerships': removed_ownerships,
        'cleared_loadout_slots': cleared_loadout_slots,
    }


def list_blacksmith_gear_for_player(player_id: int) -> list:
    """Return active, visible, not-owned gear stock for the player."""
    owned_item_ids = _owned_item_ids(player_id)
    query = (
        GearItemDefinition.query
        .filter(
            GearItemDefinition.is_active.is_(True),
            GearItemDefinition.is_blacksmith_visible.is_(True),
        )
        .order_by(GearItemDefinition.slot_type, GearItemDefinition.name)
    )
    if owned_item_ids:
        query = query.filter(~GearItemDefinition.id.in_(owned_item_ids))

    items = query.all()
    return [{
        'id': item.id,
        'slot_type': item.slot_type,
        'name': item.name,
        'description': item.description,
        'image_key': item.image_key,
        'avatar_asset_key': item.avatar_asset_key,
        'icon_static_path': resolve_gear_icon_static_path(
            slot_type=item.slot_type,
            image_key=item.image_key,
        ),
        'image_static_path': resolve_gear_image_static_path(
            slot_type=item.slot_type,
            image_key=item.image_key,
        ),
        'diamond_cost': item.diamond_cost,
        'mine_gold_delta': item.mine_gold_delta,
        'steal_gold_delta': item.steal_gold_delta,
        'shield_duration_delta': item.shield_duration_delta,
    } for item in items]


def purchase_blacksmith_gear(*, player_id: int, item_id: str) -> dict:
    """Spend Diamonds to buy one persistent gear item for a player."""
    from app.services.progression import get_or_create_player_progression

    item = db.session.get(GearItemDefinition, item_id)
    if item is None:
        raise ValueError('Gear item not found.')
    if not item.is_active:
        raise ValueError('That gear item is not currently available.')
    if not item.is_blacksmith_visible:
        raise ValueError('That gear item is not currently for sale.')

    existing = PlayerGearOwnership.query.filter_by(
        player_id=player_id,
        item_id=item_id,
    ).first()
    if existing is not None:
        raise ValueError('You already own that gear item.')

    if not isinstance(item.diamond_cost, int) or item.diamond_cost < 0:
        raise ValueError('That gear item has an invalid Diamond cost.')

    prog = get_or_create_player_progression(player_id)
    if prog.diamonds_balance < item.diamond_cost:
        raise ValueError(
            f'Not enough Diamonds. Need {item.diamond_cost}, have {prog.diamonds_balance}.'
        )

    prog.diamonds_balance -= item.diamond_cost
    prog.updated_at = datetime.now(timezone.utc)
    ownership = PlayerGearOwnership(
        player_id=player_id,
        item_id=item_id,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(ownership)

    from app.models.progression import DiamondTransaction
    tx = DiamondTransaction(
        player_id=player_id,
        amount_delta=-item.diamond_cost,
        balance_after=prog.diamonds_balance,
        reason=f'gear_purchase:{item_id}',
        admin_player_id=None,
        session_id=None,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(tx)
    db.session.flush()

    return {
        'item_id': item.id,
        'item_name': item.name,
        'cost': item.diamond_cost,
        'new_balance': prog.diamonds_balance,
    }


def _validate_slot_key(slot_key: str) -> dict:
    attr_name = SLOT_KEY_TO_ATTR.get(slot_key)
    if attr_name is None:
        raise ValueError('Invalid gear slot.')
    return _loadout_slot_map()[attr_name]


def equip_player_gear_item(*, player_id: int, item_id: str, slot_key: str) -> dict:
    """Equip one owned active item into a validated loadout slot."""
    slot_meta = _validate_slot_key(slot_key)
    state = normalize_player_gear_loadout(player_id)
    loadout = state['loadout']

    item = db.session.get(GearItemDefinition, item_id)
    if item is None:
        raise ValueError('Gear item not found.')
    if not item.is_active:
        raise ValueError('That gear item is not currently available.')
    if item_id not in _owned_item_ids(player_id):
        raise ValueError('You do not own that gear item.')
    if item.slot_type != slot_meta['expected_slot']:
        raise ValueError('That gear item cannot be equipped in that slot.')

    existing_slot = _find_equipped_slot(loadout, item_id)
    if existing_slot and existing_slot != slot_key:
        raise ValueError('That gear item is already equipped in another slot.')

    current_attr = SLOT_KEY_TO_ATTR[slot_key]
    current_item_id = getattr(loadout, current_attr)
    changed = current_item_id != item_id
    setattr(loadout, current_attr, item_id)
    if changed:
        loadout.updated_at = datetime.now(timezone.utc)
        db.session.flush()

    return {
        'loadout': loadout,
        'slot_key': slot_key,
        'item': item,
        'changed': changed,
        'normalized_changed': state['changed'],
        'loadout_created': state['created'],
    }


def unequip_player_gear_slot(*, player_id: int, slot_key: str) -> dict:
    """Clear one loadout slot. Idempotent."""
    _validate_slot_key(slot_key)
    state = normalize_player_gear_loadout(player_id)
    loadout = state['loadout']
    current_attr = SLOT_KEY_TO_ATTR[slot_key]
    had_item = getattr(loadout, current_attr) is not None
    if had_item:
        setattr(loadout, current_attr, None)
        loadout.updated_at = datetime.now(timezone.utc)
        db.session.flush()

    return {
        'loadout': loadout,
        'slot_key': slot_key,
        'changed': had_item,
        'normalized_changed': state['changed'],
        'loadout_created': state['created'],
    }


def build_player_gear_hub_view(
    player_id: int,
    *,
    selected_filter: str = 'all',
    selected_item_id: str | None = None,
) -> dict:
    """Return read-only Hub data for persistent owned gear and persistent loadout.

    This view model is intentionally Hub-facing. Session consumables inventory
    and frozen runtime snapshot data are separate concepts and are not exposed
    through this helper.
    """
    state = normalize_player_gear_loadout(player_id)
    loadout = state['loadout']
    slot_map = _loadout_slot_map()
    current_filter = _normalize_hub_filter(selected_filter)
    equipped_lookup = _get_equipped_slot_lookup(loadout)

    owned_rows = (
        db.session.query(GearItemDefinition)
        .join(PlayerGearOwnership, PlayerGearOwnership.item_id == GearItemDefinition.id)
        .filter(
            PlayerGearOwnership.player_id == player_id,
            GearItemDefinition.is_active.is_(True),
        )
        .order_by(GearItemDefinition.slot_type, GearItemDefinition.name)
        .all()
    )

    owned_by_slot = {slot: [] for slot in GEAR_SLOT_ORDER}
    for item in owned_rows:
        equipped_meta = equipped_lookup.get(item.id)
        item_view = {
            'id': item.id,
            'slot_type': item.slot_type,
            'slot_label': GEAR_SLOT_LABELS.get(item.slot_type, item.slot_type.replace('_', ' ').title()),
            'name': item.name,
            'description': item.description,
            'image_key': item.image_key,
            'avatar_asset_key': item.avatar_asset_key,
            'icon_static_path': resolve_gear_icon_static_path(
                slot_type=item.slot_type,
                image_key=item.image_key,
            ),
            'image_static_path': resolve_gear_image_static_path(
                slot_type=item.slot_type,
                image_key=item.image_key,
            ),
            'mine_gold_delta': item.mine_gold_delta,
            'steal_gold_delta': item.steal_gold_delta,
            'shield_duration_delta': item.shield_duration_delta,
            'is_equipped': equipped_meta is not None,
            'equipped_slot_key': equipped_meta['slot_key'] if equipped_meta else None,
            'equipped_slot_label': equipped_meta['slot_label'] if equipped_meta else None,
        }
        owned_by_slot.setdefault(item.slot_type, []).append(item_view)

    inventory_groups = []
    inventory_items = []
    for slot_type in GEAR_SLOT_ORDER:
        items = owned_by_slot.get(slot_type) or []
        if not items:
            continue
        inventory_items.extend(items)
        inventory_groups.append({
            'slot_type': slot_type,
            'label': GEAR_SLOT_LABELS[slot_type],
            'gear_items': items,
        })

    visible_items = [
        item for item in inventory_items
        if current_filter == 'all' or item['slot_type'] == current_filter
    ]

    inventory_by_id = {item['id']: item for item in inventory_items}
    selected_item = inventory_by_id.get(selected_item_id)
    if selected_item is None and visible_items:
        selected_item = visible_items[0]

    filter_tabs = []
    for filter_key, label, slot_type in HUB_FILTER_TABS:
        tab_items = [
            item for item in inventory_items
            if slot_type is None or item['slot_type'] == slot_type
        ]
        filter_tabs.append({
            'key': filter_key,
            'label': label,
            'is_active': filter_key == current_filter,
            'item_count': len(tab_items),
            'default_selected_item_id': tab_items[0]['id'] if tab_items else None,
        })

    selected_item_detail = None
    if selected_item is not None:
        equip_targets = []
        if not selected_item['is_equipped']:
            if selected_item['slot_type'] == GEAR_SLOT_POCKET:
                equip_targets = [
                    {'slot_key': 'pocket1', 'label': 'Pocket 1'},
                    {'slot_key': 'pocket2', 'label': 'Pocket 2'},
                ]
            else:
                equip_targets = [{
                    'slot_key': selected_item['slot_type'],
                    'label': selected_item['slot_label'],
                }]

        selected_item_detail = {
            **selected_item,
            'equip_targets': equip_targets,
            'effects': (
                {'label': 'Mine gold', 'value': selected_item['mine_gold_delta']},
                {'label': 'Steal gold', 'value': selected_item['steal_gold_delta']},
                {'label': 'Shield duration', 'value': f'{selected_item["shield_duration_delta"]:+d}s'},
            ),
        }

    slot_rows = []
    active_bonus_summary = {
        'mine_gold_delta': 0,
        'steal_gold_delta': 0,
        'shield_duration_delta': 0,
    }
    for attr_name, label, expected_slot in LOADOUT_SLOTS:
        item_id = getattr(loadout, attr_name)
        item = db.session.get(GearItemDefinition, item_id) if item_id else None
        item_view = None if item is None else {
            'id': item.id,
            'slot_type': item.slot_type,
            'name': item.name,
            'description': item.description,
            'image_key': item.image_key,
            'avatar_asset_key': item.avatar_asset_key,
            'icon_static_path': resolve_gear_icon_static_path(
                slot_type=item.slot_type,
                image_key=item.image_key,
            ),
            'image_static_path': resolve_gear_image_static_path(
                slot_type=item.slot_type,
                image_key=item.image_key,
            ),
            'mine_gold_delta': item.mine_gold_delta,
            'steal_gold_delta': item.steal_gold_delta,
            'shield_duration_delta': item.shield_duration_delta,
        }
        if item_view is not None:
            active_bonus_summary['mine_gold_delta'] += item.mine_gold_delta
            active_bonus_summary['steal_gold_delta'] += item.steal_gold_delta
            active_bonus_summary['shield_duration_delta'] += item.shield_duration_delta
        slot_rows.append({
            'slot_key': slot_map[attr_name]['slot_key'],
            'label': label,
            'expected_slot': expected_slot,
            'item': item_view,
            'is_selected': bool(item_view and selected_item_detail and item_view['id'] == selected_item_detail['id']),
        })

    return {
        'loadout': loadout,
        'loadout_created': state['created'],
        'loadout_normalized': state['changed'],
        'selected_filter': current_filter,
        'filter_tabs': filter_tabs,
        'inventory_items': inventory_items,
        'visible_items': visible_items,
        'selected_item': selected_item_detail,
        'inventory_groups': inventory_groups,
        'slot_rows': slot_rows,
        'active_bonus_summary': active_bonus_summary,
    }
