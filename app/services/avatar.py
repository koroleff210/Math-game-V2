import os
import re

from flask import current_app

from app.extensions import db
from app.models.gear import (
    GEAR_SLOT_BOOTS,
    GEAR_SLOT_CHEST,
    GEAR_SLOT_HEAD,
    GEAR_SLOT_MAIN_HAND,
    GEAR_SLOT_OFF_HAND,
    GearItemDefinition,
)


DEFAULT_FACE_KEY = '001'
AVATAR_IMAGE_EXTENSION = '.png'
AVATAR_ROOT = 'gear'

AVATAR_FOLDERS = {
    GEAR_SLOT_MAIN_HAND: 'main_hand',
    GEAR_SLOT_OFF_HAND: 'off_hand',
    GEAR_SLOT_CHEST: 'chest',
    GEAR_SLOT_HEAD: 'head',
    GEAR_SLOT_BOOTS: 'boots',
    'face': 'face',
}

_SINGLE_LAYER_FILENAMES = {
    GEAR_SLOT_MAIN_HAND: 'main_hand_{key}.png',
    GEAR_SLOT_OFF_HAND: 'off_hand_{key}.png',
    GEAR_SLOT_CHEST: 'chest_{key}.png',
    GEAR_SLOT_BOOTS: 'boots_{key}.png',
    'face': 'face_{key}.png',
}

_HEAD_BACK_FILENAME = 'head_{key}b.png'
_HEAD_FRONT_FILENAME = 'head_{key}a.png'
_CHEST_UNDERLAY_FILENAME = 'chest_{key}a.png'
_BODY_UPPER_FILENAME = 'body_upper.png'
_BODY_LOWER_FILENAME = 'body_lower.png'
_OFF_HAND_BASE_FILENAME = 'off_hand_base.png'

_KEY_PATTERNS = {
    GEAR_SLOT_MAIN_HAND: re.compile(r'^main_hand_(?P<key>.+)\.png$', re.IGNORECASE),
    GEAR_SLOT_OFF_HAND: re.compile(r'^off_hand_(?P<key>.+)\.png$', re.IGNORECASE),
    GEAR_SLOT_CHEST: re.compile(r'^chest_(?P<key>.+)\.png$', re.IGNORECASE),
    GEAR_SLOT_BOOTS: re.compile(r'^boots_(?P<key>.+)\.png$', re.IGNORECASE),
    'face': re.compile(r'^face_(?P<key>.+)\.png$', re.IGNORECASE),
}
_HEAD_PATTERN = re.compile(r'^head_(?P<key>.+)(?P<part>[ab])\.png$', re.IGNORECASE)


def _sort_asset_keys(keys):
    def _sort_value(value: str):
        return (0, int(value)) if value.isdigit() else (1, value.lower())

    return sorted(keys, key=_sort_value)


def _avatar_directory(folder_name: str) -> str:
    return os.path.join(current_app.static_folder, AVATAR_ROOT, folder_name)


def _avatar_static_path(folder_name: str, filename: str) -> str:
    return f'{current_app.static_url_path}/{AVATAR_ROOT}/{folder_name}/{filename}'


def _list_png_files(folder_name: str) -> list[str]:
    folder = _avatar_directory(folder_name)
    if not os.path.isdir(folder):
        return []

    return sorted(
        [
            name for name in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, name))
            and name.lower().endswith(AVATAR_IMAGE_EXTENSION)
        ],
        key=str.lower,
    )


def _file_exists(folder_name: str, filename: str) -> bool:
    return os.path.isfile(os.path.join(_avatar_directory(folder_name), filename))


def list_available_face_keys() -> list[str]:
    keys = []
    for name in _list_png_files(AVATAR_FOLDERS['face']):
        match = _KEY_PATTERNS['face'].match(name)
        if match:
            keys.append(match.group('key'))
    return _sort_asset_keys(keys)


def list_available_avatar_asset_keys(slot_type: str) -> list[str]:
    if slot_type == GEAR_SLOT_HEAD:
        keys_a = set()
        keys_b = set()
        for name in _list_png_files(AVATAR_FOLDERS[GEAR_SLOT_HEAD]):
            match = _HEAD_PATTERN.match(name)
            if not match:
                continue
            if match.group('part').lower() == 'a':
                keys_a.add(match.group('key'))
            else:
                keys_b.add(match.group('key'))
        return _sort_asset_keys(keys_a & keys_b)

    if slot_type == GEAR_SLOT_CHEST:
        keys = []
        for name in _list_png_files(AVATAR_FOLDERS[GEAR_SLOT_CHEST]):
            lowered = name.lower()
            if lowered == _BODY_UPPER_FILENAME:
                continue
            if lowered.endswith('a.png'):
                continue
            match = _KEY_PATTERNS[GEAR_SLOT_CHEST].match(name)
            if match:
                keys.append(match.group('key'))
        return _sort_asset_keys(keys)

    pattern = _KEY_PATTERNS.get(slot_type)
    folder_name = AVATAR_FOLDERS.get(slot_type)
    if pattern is None or folder_name is None:
        return []

    keys = []
    for name in _list_png_files(folder_name):
        if name.lower() == _OFF_HAND_BASE_FILENAME:
            continue
        match = pattern.match(name)
        if match:
            keys.append(match.group('key'))
    return _sort_asset_keys(keys)


def get_valid_selected_face_key(face_key: str | None) -> str:
    available = list_available_face_keys()
    if face_key and face_key in available:
        return face_key
    if DEFAULT_FACE_KEY in available:
        return DEFAULT_FACE_KEY
    if available:
        return available[0]
    return DEFAULT_FACE_KEY


def cycle_player_face_selection(player, direction: str) -> str:
    available = list_available_face_keys()
    if not available:
        player.selected_face_key = DEFAULT_FACE_KEY
        db.session.flush()
        return player.selected_face_key

    current = get_valid_selected_face_key(getattr(player, 'selected_face_key', None))
    if current not in available:
        current = available[0]

    current_index = available.index(current)
    if direction == 'prev':
        next_index = (current_index - 1) % len(available)
    elif direction == 'next':
        next_index = (current_index + 1) % len(available)
    else:
        raise ValueError('Invalid face selection action.')

    player.selected_face_key = available[next_index]
    db.session.flush()
    return player.selected_face_key


def _item_avatar_asset_key(item: GearItemDefinition | None, slot_type: str) -> str | None:
    if item is None or not item.is_active or not item.avatar_asset_key:
        return None
    key = item.avatar_asset_key.strip()
    if not key:
        return None
    return key if key in list_available_avatar_asset_keys(slot_type) else None


def _item_avatar_asset_filename(item: GearItemDefinition | None, slot_type: str) -> str | None:
    if item is None or not item.is_active:
        return None
    image_key = (getattr(item, 'image_key', None) or '').strip()
    if image_key and _file_exists(AVATAR_FOLDERS[slot_type], image_key):
        return image_key
    return None


def _get_equipped_item(loadout, attr_name: str) -> GearItemDefinition | None:
    item_id = getattr(loadout, attr_name, None)
    if not item_id:
        return None
    return db.session.get(GearItemDefinition, item_id)


def _build_layer(label: str, folder_name: str, filename: str) -> dict:
    return {
        'label': label,
        'static_path': _avatar_static_path(folder_name, filename),
    }


def build_player_avatar_view(player, loadout) -> dict:
    """Build the Hub avatar preview from persistent cosmetic face + gear loadout.

    The selected face is cosmetic identity. The legacy gear slot key "head"
    still refers to equipped headgear/helmet art for compatibility with the
    current persistent gear schema. Wearable/base avatar layers now resolve
    from static/gear so runtime no longer depends on the legacy static/avatars
    tree.
    """
    selected_face_key = get_valid_selected_face_key(getattr(player, 'selected_face_key', None))

    head_item = _get_equipped_item(loadout, 'head_item_id')
    chest_item = _get_equipped_item(loadout, 'chest_item_id')
    boots_item = _get_equipped_item(loadout, 'boots_item_id')
    main_hand_item = _get_equipped_item(loadout, 'main_hand_item_id')
    off_hand_item = _get_equipped_item(loadout, 'off_hand_item_id')

    head_filename = _item_avatar_asset_filename(head_item, GEAR_SLOT_HEAD)
    chest_filename = _item_avatar_asset_filename(chest_item, GEAR_SLOT_CHEST)
    boots_filename = _item_avatar_asset_filename(boots_item, GEAR_SLOT_BOOTS)
    main_hand_filename = _item_avatar_asset_filename(main_hand_item, GEAR_SLOT_MAIN_HAND)
    off_hand_filename = _item_avatar_asset_filename(off_hand_item, GEAR_SLOT_OFF_HAND)

    head_key = _item_avatar_asset_key(head_item, GEAR_SLOT_HEAD)
    chest_key = _item_avatar_asset_key(chest_item, GEAR_SLOT_CHEST)
    boots_key = _item_avatar_asset_key(boots_item, GEAR_SLOT_BOOTS)
    main_hand_key = _item_avatar_asset_key(main_hand_item, GEAR_SLOT_MAIN_HAND)
    off_hand_key = _item_avatar_asset_key(off_hand_item, GEAR_SLOT_OFF_HAND)

    if head_filename:
        head_match = _HEAD_PATTERN.match(head_filename)
        if head_match:
            head_key = head_match.group('key')
    if chest_filename:
        chest_match = _KEY_PATTERNS[GEAR_SLOT_CHEST].match(chest_filename)
        if chest_match:
            chest_key = chest_match.group('key')
    if boots_filename:
        boots_match = _KEY_PATTERNS[GEAR_SLOT_BOOTS].match(boots_filename)
        if boots_match:
            boots_key = boots_match.group('key')
    if main_hand_filename:
        main_hand_match = _KEY_PATTERNS[GEAR_SLOT_MAIN_HAND].match(main_hand_filename)
        if main_hand_match:
            main_hand_key = main_hand_match.group('key')
    if off_hand_filename:
        off_hand_match = _KEY_PATTERNS[GEAR_SLOT_OFF_HAND].match(off_hand_filename)
        if off_hand_match:
            off_hand_key = off_hand_match.group('key')

    layers = []
    if head_key:
        layers.append(
            _build_layer(
                'head-back',
                AVATAR_FOLDERS[GEAR_SLOT_HEAD],
                _HEAD_BACK_FILENAME.format(key=head_key),
            )
        )

    if chest_key:
        chest_underlay_filename = _CHEST_UNDERLAY_FILENAME.format(key=chest_key)
        if _file_exists(AVATAR_FOLDERS[GEAR_SLOT_CHEST], chest_underlay_filename):
            layers.append(
                _build_layer(
                    'chest-underlay',
                    AVATAR_FOLDERS[GEAR_SLOT_CHEST],
                    chest_underlay_filename,
                )
            )

    layers.append(
        _build_layer(
            'body-upper',
            AVATAR_FOLDERS[GEAR_SLOT_CHEST],
            _BODY_UPPER_FILENAME,
        )
    )

    if boots_key:
        layers.append(
            _build_layer(
                'boots',
                AVATAR_FOLDERS[GEAR_SLOT_BOOTS],
                _SINGLE_LAYER_FILENAMES[GEAR_SLOT_BOOTS].format(key=boots_key),
            )
        )
    else:
        layers.append(
            _build_layer(
                'body-lower',
                AVATAR_FOLDERS[GEAR_SLOT_BOOTS],
                _BODY_LOWER_FILENAME,
            )
        )

    if main_hand_key:
        layers.append(
            _build_layer(
                'main-hand',
                AVATAR_FOLDERS[GEAR_SLOT_MAIN_HAND],
                _SINGLE_LAYER_FILENAMES[GEAR_SLOT_MAIN_HAND].format(key=main_hand_key),
            )
        )

    if chest_key:
        layers.append(
            _build_layer(
                'chest',
                AVATAR_FOLDERS[GEAR_SLOT_CHEST],
                _SINGLE_LAYER_FILENAMES[GEAR_SLOT_CHEST].format(key=chest_key),
            )
        )

    face_filename = _SINGLE_LAYER_FILENAMES['face'].format(key=selected_face_key)
    if _file_exists(AVATAR_FOLDERS['face'], face_filename):
        layers.append(
            _build_layer(
                'face',
                AVATAR_FOLDERS['face'],
                face_filename,
            )
        )

    if head_key:
        layers.append(
            _build_layer(
                'head-front',
                AVATAR_FOLDERS[GEAR_SLOT_HEAD],
                _HEAD_FRONT_FILENAME.format(key=head_key),
            )
        )

    if off_hand_key:
        layers.append(
            _build_layer(
                'off-hand',
                AVATAR_FOLDERS[GEAR_SLOT_OFF_HAND],
                _SINGLE_LAYER_FILENAMES[GEAR_SLOT_OFF_HAND].format(key=off_hand_key),
            )
        )
    else:
        layers.append(
            _build_layer(
                'off-hand-base',
                AVATAR_FOLDERS[GEAR_SLOT_OFF_HAND],
                _OFF_HAND_BASE_FILENAME,
            )
        )

    layer_map = {layer['label']: layer for layer in layers}

    return {
        'selected_face_key': selected_face_key,
        'face_label': f'Face {selected_face_key}',
        'available_face_keys': list_available_face_keys(),
        'layers': layers,
        'layer_map': layer_map,
        'equipped_visual_keys': {
            'head': head_key,
            'chest': chest_key,
            'boots': boots_key,
            'main_hand': main_hand_key,
            'off_hand': off_hand_key,
        },
    }
