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
DEFAULT_BODY_VARIANT = 'm'
SUPPORTED_BODY_VARIANTS = ('m', 'f')
AVATAR_IMAGE_EXTENSION = '.png'
AVATAR_ROOT = 'gear'
BODY_ROOT = os.path.join('avatars', 'bodies')

AVATAR_FOLDERS = {
    GEAR_SLOT_MAIN_HAND: 'main_hand',
    GEAR_SLOT_OFF_HAND: 'off_hand',
    GEAR_SLOT_CHEST: 'chest',
    GEAR_SLOT_HEAD: 'head',
    GEAR_SLOT_BOOTS: 'boots',
    'face': 'face',
}

_LEGACY_SINGLE_LAYER_FILENAMES = {
    GEAR_SLOT_MAIN_HAND: 'main_hand_{key}.png',
    GEAR_SLOT_OFF_HAND: 'off_hand_{key}.png',
    GEAR_SLOT_CHEST: 'chest_{key}.png',
    GEAR_SLOT_BOOTS: 'boots_{key}.png',
    'face': 'face_{key}.png',
}

_LEGACY_HEAD_BACK_FILENAME = 'head_{key}b.png'
_LEGACY_HEAD_FRONT_FILENAME = 'head_{key}a.png'
_LEGACY_CHEST_UNDERLAY_FILENAME = 'chest_{key}a.png'
_LEGACY_BODY_UPPER_FILENAME = 'body_upper.png'
_LEGACY_BODY_LOWER_FILENAME = 'body_lower.png'
_LEGACY_OFF_HAND_BASE_FILENAME = 'off_hand_base.png'

_KEY_PATTERNS = {
    GEAR_SLOT_MAIN_HAND: re.compile(r'^main_hand_(?P<key>.+)\.png$', re.IGNORECASE),
    GEAR_SLOT_OFF_HAND: re.compile(r'^off_hand_(?P<key>.+)\.png$', re.IGNORECASE),
    GEAR_SLOT_CHEST: re.compile(r'^chest_(?P<key>.+)\.png$', re.IGNORECASE),
    GEAR_SLOT_BOOTS: re.compile(r'^boots_(?P<key>.+)\.png$', re.IGNORECASE),
    'face': re.compile(r'^face_(?P<key>.+)\.png$', re.IGNORECASE),
}
_HEAD_PATTERN = re.compile(r'^head_(?P<key>.+)(?P<part>[ab])\.png$', re.IGNORECASE)
_FACE_PATTERN = re.compile(r'^face_(?:(?P<variant>[mf])_)?(?P<key>.+)\.png$', re.IGNORECASE)


def _sort_asset_keys(keys):
    def _sort_value(value: str):
        return (0, int(value)) if value.isdigit() else (1, value.lower())

    return sorted(keys, key=_sort_value)


def normalize_avatar_body_variant(value: str | None) -> str:
    cleaned = (value or '').strip().lower()
    if cleaned in SUPPORTED_BODY_VARIANTS:
        return cleaned
    return DEFAULT_BODY_VARIANT


def _avatar_directory(folder_name: str) -> str:
    return os.path.join(current_app.static_folder, AVATAR_ROOT, folder_name)


def _avatar_static_path(folder_name: str, filename: str) -> str:
    return f'{current_app.static_url_path}/{AVATAR_ROOT}/{folder_name}/{filename}'


def _body_directory(variant: str) -> str:
    return os.path.join(current_app.static_folder, BODY_ROOT, variant)


def _body_static_path(variant: str, filename: str) -> str:
    body_root = BODY_ROOT.replace('\\', '/')
    return f'{current_app.static_url_path}/{body_root}/{variant}/{filename}'


def _file_exists(path: str) -> bool:
    return os.path.isfile(path)


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


def _slot_file_exists(slot_type: str, filename: str) -> bool:
    return _file_exists(os.path.join(_avatar_directory(AVATAR_FOLDERS[slot_type]), filename))


def _parse_face_filename(filename: str) -> tuple[str, str] | None:
    match = _FACE_PATTERN.match(filename)
    if not match:
        return None
    variant = (match.group('variant') or 'm').lower()
    return variant, match.group('key')


def list_available_face_keys(body_variant: str | None = None) -> list[str]:
    target_variant = normalize_avatar_body_variant(body_variant)
    keys = []
    for name in _list_png_files(AVATAR_FOLDERS['face']):
        parsed = _parse_face_filename(name)
        if not parsed:
            continue
        variant, key = parsed
        if target_variant == 'f':
            if variant == 'f':
                keys.append(key)
        else:
            if variant == 'm':
                keys.append(key)
    from app.models.media import UploadedAsset
    category = 'face_f' if target_variant == 'f' else 'face_m'
    keys.extend(row.asset_key for row in UploadedAsset.query.filter_by(category=category).all() if row.asset_key)
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
            if lowered == _LEGACY_BODY_UPPER_FILENAME:
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
        if name.lower() == _LEGACY_OFF_HAND_BASE_FILENAME:
            continue
        match = pattern.match(name)
        if match:
            keys.append(match.group('key'))
    return _sort_asset_keys(keys)


def get_valid_selected_face_key(face_key: str | None, body_variant: str | None = None) -> str:
    available = list_available_face_keys(body_variant)
    if face_key and face_key in available:
        return face_key
    if DEFAULT_FACE_KEY in available:
        return DEFAULT_FACE_KEY
    if available:
        return available[0]
    return DEFAULT_FACE_KEY


def cycle_player_face_selection(player, direction: str) -> str:
    body_variant = normalize_avatar_body_variant(getattr(player, 'avatar_body_variant', None))
    available = list_available_face_keys(body_variant)
    if not available:
        player.selected_face_key = DEFAULT_FACE_KEY
        db.session.flush()
        return player.selected_face_key

    current = get_valid_selected_face_key(getattr(player, 'selected_face_key', None), body_variant)
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


def set_player_body_variant(player, variant: str) -> str:
    normalized = normalize_avatar_body_variant(variant)
    player.avatar_body_variant = normalized
    player.selected_face_key = get_valid_selected_face_key(
        getattr(player, 'selected_face_key', None),
        normalized,
    )
    db.session.flush()
    return normalized


def _get_equipped_item(loadout, attr_name: str) -> GearItemDefinition | None:
    item_id = getattr(loadout, attr_name, None)
    if not item_id:
        return None
    return db.session.get(GearItemDefinition, item_id)


def _build_layer(label: str, static_path: str) -> dict:
    return {
        'label': label,
        'static_path': static_path,
    }


def _build_legacy_slot_path(slot_type: str, filename: str) -> str:
    return _avatar_static_path(AVATAR_FOLDERS[slot_type], filename)


def _new_package_layer_path(slot_type: str, package_key: str, variant: str, layer_filename: str) -> str | None:
    path = os.path.join(
        _avatar_directory(AVATAR_FOLDERS[slot_type]),
        package_key,
        variant,
        layer_filename,
    )
    if _file_exists(path):
        return f'{current_app.static_url_path}/{AVATAR_ROOT}/{AVATAR_FOLDERS[slot_type]}/{package_key}/{variant}/{layer_filename}'
    return None


def _package_key_candidates(item: GearItemDefinition | None) -> list[str]:
    if item is None:
        return []
    candidates = []
    raw_avatar_key = (getattr(item, 'avatar_asset_key', None) or '').strip()
    raw_image_key = (getattr(item, 'image_key', None) or '').strip()
    if raw_avatar_key:
        candidates.append(raw_avatar_key)
    if raw_image_key:
        stem, _ext = os.path.splitext(raw_image_key)
        if stem:
            candidates.append(stem)
        candidates.append(raw_image_key)
    dedup = []
    seen = set()
    for candidate in candidates:
        lowered = candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        dedup.append(candidate)
    return dedup


def _resolve_package_layer(slot_type: str, item: GearItemDefinition | None, body_variant: str, layer_filename: str) -> str | None:
    if item is not None:
        from app.services.uploaded_media import asset_url, find_gear_asset
        uploaded = find_gear_asset(item.id, body_variant, layer_filename.removesuffix('.png'))
        if uploaded:
            return asset_url(uploaded)
    for package_key in _package_key_candidates(item):
        variant_path = _new_package_layer_path(slot_type, package_key, body_variant, layer_filename)
        if variant_path:
            return variant_path
        shared_path = _new_package_layer_path(slot_type, package_key, 'shared', layer_filename)
        if shared_path:
            return shared_path
    return None


def _resolve_body_layer(body_variant: str, filename: str, legacy_slot: str) -> str:
    variant = normalize_avatar_body_variant(body_variant)
    for candidate in (variant, DEFAULT_BODY_VARIANT):
        body_path = os.path.join(_body_directory(candidate), filename)
        if _file_exists(body_path):
            return _body_static_path(candidate, filename)
    return _build_legacy_slot_path(legacy_slot, filename)


def _resolve_off_hand_base_layer(body_variant: str) -> str:
    return _resolve_body_layer(body_variant, _LEGACY_OFF_HAND_BASE_FILENAME, GEAR_SLOT_OFF_HAND)


def _legacy_visual_key_from_item(item: GearItemDefinition | None, slot_type: str) -> str | None:
    if item is None or not item.is_active:
        return None
    image_key = (getattr(item, 'image_key', None) or '').strip()
    if image_key:
        if slot_type == GEAR_SLOT_HEAD:
            match = _HEAD_PATTERN.match(image_key)
            if match:
                return match.group('key')
        else:
            pattern = _KEY_PATTERNS.get(slot_type)
            if pattern:
                match = pattern.match(image_key)
                if match:
                    return match.group('key')
    asset_key = (getattr(item, 'avatar_asset_key', None) or '').strip()
    return asset_key or None


def _resolve_head_layers(item: GearItemDefinition | None, body_variant: str) -> tuple[str | None, str | None, str | None]:
    back = _resolve_package_layer(GEAR_SLOT_HEAD, item, body_variant, 'back.png')
    front = _resolve_package_layer(GEAR_SLOT_HEAD, item, body_variant, 'front.png')
    if front:
        return back, front, None
    if normalize_avatar_body_variant(body_variant) == 'f':
        return None, None, None

    key = _legacy_visual_key_from_item(item, GEAR_SLOT_HEAD)
    if not key:
        return None, None, None
    back_name = _LEGACY_HEAD_BACK_FILENAME.format(key=key)
    front_name = _LEGACY_HEAD_FRONT_FILENAME.format(key=key)
    if _slot_file_exists(GEAR_SLOT_HEAD, back_name) and _slot_file_exists(GEAR_SLOT_HEAD, front_name):
        return (
            _build_legacy_slot_path(GEAR_SLOT_HEAD, back_name),
            _build_legacy_slot_path(GEAR_SLOT_HEAD, front_name),
            key,
        )
    return None, None, None


def _resolve_chest_layers(item: GearItemDefinition | None, body_variant: str) -> tuple[str | None, str | None, str | None]:
    underlay = _resolve_package_layer(GEAR_SLOT_CHEST, item, body_variant, 'underlay.png')
    front = _resolve_package_layer(GEAR_SLOT_CHEST, item, body_variant, 'front.png')
    if front:
        return underlay, front, None
    if normalize_avatar_body_variant(body_variant) == 'f':
        return None, None, None

    key = _legacy_visual_key_from_item(item, GEAR_SLOT_CHEST)
    if not key:
        return None, None, None
    front_name = _LEGACY_SINGLE_LAYER_FILENAMES[GEAR_SLOT_CHEST].format(key=key)
    underlay_name = _LEGACY_CHEST_UNDERLAY_FILENAME.format(key=key)
    if _slot_file_exists(GEAR_SLOT_CHEST, front_name):
        underlay_path = (
            _build_legacy_slot_path(GEAR_SLOT_CHEST, underlay_name)
            if _slot_file_exists(GEAR_SLOT_CHEST, underlay_name) else None
        )
        return underlay_path, _build_legacy_slot_path(GEAR_SLOT_CHEST, front_name), key
    return None, None, None


def _resolve_single_layer(slot_type: str, item: GearItemDefinition | None, body_variant: str, layer_filename: str = 'front.png') -> tuple[str | None, str | None]:
    package_path = _resolve_package_layer(slot_type, item, body_variant, layer_filename)
    if package_path:
        return package_path, None
    if normalize_avatar_body_variant(body_variant) == 'f':
        return None, None
    key = _legacy_visual_key_from_item(item, slot_type)
    if not key:
        return None, None
    legacy_name = _LEGACY_SINGLE_LAYER_FILENAMES[slot_type].format(key=key)
    if _slot_file_exists(slot_type, legacy_name):
        return _build_legacy_slot_path(slot_type, legacy_name), key
    return None, None


def build_player_avatar_view(player, loadout) -> dict:
    body_variant = normalize_avatar_body_variant(getattr(player, 'avatar_body_variant', None))
    selected_face_key = get_valid_selected_face_key(getattr(player, 'selected_face_key', None), body_variant)

    head_item = _get_equipped_item(loadout, 'head_item_id')
    chest_item = _get_equipped_item(loadout, 'chest_item_id')
    boots_item = _get_equipped_item(loadout, 'boots_item_id')
    main_hand_item = _get_equipped_item(loadout, 'main_hand_item_id')
    off_hand_item = _get_equipped_item(loadout, 'off_hand_item_id')

    head_back, head_front, head_key = _resolve_head_layers(head_item, body_variant)
    chest_underlay, chest_front, chest_key = _resolve_chest_layers(chest_item, body_variant)
    boots_front, boots_key = _resolve_single_layer(GEAR_SLOT_BOOTS, boots_item, body_variant)
    main_hand_front, main_hand_key = _resolve_single_layer(GEAR_SLOT_MAIN_HAND, main_hand_item, body_variant)
    off_hand_front, off_hand_key = _resolve_single_layer(GEAR_SLOT_OFF_HAND, off_hand_item, body_variant)

    layers = []
    if head_back:
        layers.append(_build_layer('head-back', head_back))
    if chest_underlay:
        layers.append(_build_layer('chest-underlay', chest_underlay))

    layers.append(_build_layer('body-upper', _resolve_body_layer(body_variant, 'body_upper.png', GEAR_SLOT_CHEST)))

    if boots_front:
        layers.append(_build_layer('boots', boots_front))
    else:
        layers.append(_build_layer('body-lower', _resolve_body_layer(body_variant, 'body_lower.png', GEAR_SLOT_BOOTS)))

    if main_hand_front:
        layers.append(_build_layer('main-hand', main_hand_front))
    if chest_front:
        layers.append(_build_layer('chest', chest_front))

    face_filenames = (
        [f'face_f_{selected_face_key}.png']
        if body_variant == 'f'
        else [
            _LEGACY_SINGLE_LAYER_FILENAMES['face'].format(key=selected_face_key),
            f'face_m_{selected_face_key}.png',
        ]
    )
    from app.models.media import UploadedAsset
    from app.services.uploaded_media import asset_url
    face_category = 'face_f' if body_variant == 'f' else 'face_m'
    uploaded_face = UploadedAsset.query.filter_by(category=face_category, asset_key=selected_face_key).first()
    if uploaded_face:
        layers.append(_build_layer('face', asset_url(uploaded_face)))
    for face_filename in ([] if uploaded_face else face_filenames):
        face_path = os.path.join(_avatar_directory(AVATAR_FOLDERS['face']), face_filename)
        if _file_exists(face_path):
            layers.append(_build_layer('face', _avatar_static_path(AVATAR_FOLDERS['face'], face_filename)))
            break

    if head_front:
        layers.append(_build_layer('head-front', head_front))
    if off_hand_front:
        layers.append(_build_layer('off-hand', off_hand_front))
    else:
        layers.append(_build_layer('off-hand-base', _resolve_off_hand_base_layer(body_variant)))

    layer_map = {layer['label']: layer for layer in layers}
    return {
        'selected_face_key': selected_face_key,
        'avatar_body_variant': body_variant,
        'face_label': f'Face {selected_face_key}',
        'available_face_keys': list_available_face_keys(body_variant),
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
