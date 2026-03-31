import copy
import json
import os

from flask import current_app


DEFAULT_OVERLAY_LAYOUTS = {
    'treasure': {
        'slot_layouts': {
            '1': [
                {'name': 'slot_1', 'x': 48.8, 'y': 41.8, 'scale': 1.0},
            ],
            '2': [
                {'name': 'slot_1', 'x': 39.7, 'y': 43.4, 'scale': 0.8},
                {'name': 'slot_2', 'x': 60.9, 'y': 43.6, 'scale': 0.8},
            ],
            '3': [
                {'name': 'slot_1', 'x': 29.1, 'y': 41.2, 'scale': 0.5},
                {'name': 'slot_2', 'x': 50.4, 'y': 41.9, 'scale': 0.5},
                {'name': 'slot_3', 'x': 70.4, 'y': 41.6, 'scale': 0.5},
            ],
            '4': [
                {'name': 'slot_1', 'x': 42.6, 'y': 38.4, 'scale': 0.4},
                {'name': 'slot_2', 'x': 61.3, 'y': 38.5, 'scale': 0.4},
                {'name': 'slot_3', 'x': 42.6, 'y': 53.6, 'scale': 0.4},
                {'name': 'slot_4', 'x': 61.3, 'y': 53.5, 'scale': 0.4},
            ],
        },
    },
    'steal': {
        'slot_layouts': {
            'item1': {'name': 'item1', 'x': 14.5, 'y': 44.8, 'scale': 0.4},
            'item2': {'name': 'item2', 'x': 27.4, 'y': 42.5, 'scale': 0.4},
            'item3': {'name': 'item3', 'x': 30.8, 'y': 79.2, 'scale': 0.4},
            'item4': {'name': 'item4', 'x': 39.5, 'y': 41.0, 'scale': 0.3},
            'item5': {'name': 'item5', 'x': 90.7, 'y': 52.1, 'scale': 0.3},
            'item6': {'name': 'item6', 'x': 88.2, 'y': 27.2, 'scale': 0.2},
            'item7': {'name': 'item7', 'x': 82.0, 'y': 39.8, 'scale': 0.2},
        },
        'avatar': {
            'name': 'avatar',
            'x': 58.3,
            'y': 54.2,
            'width': 36.3,
            'aspect_ratio': 11 / 12,
        },
    },
}

_TREASURE_SLOT_NAMES = {
    '1': ['slot_1'],
    '2': ['slot_1', 'slot_2'],
    '3': ['slot_1', 'slot_2', 'slot_3'],
    '4': ['slot_1', 'slot_2', 'slot_3', 'slot_4'],
}
_STEAL_SLOT_KEYS = ['item1', 'item2', 'item3', 'item4', 'item5', 'item6', 'item7']


def _static_overlay_url(filename: str) -> str:
    return f'{current_app.static_url_path}/{filename}'


def build_overlay_asset_payload() -> dict:
    return {
        'treasure': {
            'backgrounds': {
                '1': _static_overlay_url('classic_ui/treasure/backgrounds/treasure_bg_cave_1.png'),
                '2': _static_overlay_url('classic_ui/treasure/backgrounds/treasure_bg_cave_2.png'),
                '3': _static_overlay_url('classic_ui/treasure/backgrounds/treasure_bg_cave_3.png'),
                '4': _static_overlay_url('classic_ui/treasure/backgrounds/treasure_bg_cave_4.png'),
            },
            'containers': {
                'closed': {
                    str(index): _static_overlay_url(f'classic_ui/treasure/containers/chest_{index:02d}_closed.png')
                    for index in range(1, 7)
                },
                'open': {
                    str(index): _static_overlay_url(f'classic_ui/treasure/containers/chest_{index:02d}_open.png')
                    for index in range(1, 7)
                },
            },
            'reward_icons': {
                'gem': _static_overlay_url('classic_ui/icons/gem.png'),
                'shield_token': _static_overlay_url('classic_ui/icons/shield.png'),
                'steal_token': _static_overlay_url('classic_ui/icons/steal_token.png'),
                'second_chance': _static_overlay_url('classic_ui/icons/second_chance.png'),
                'empty': _static_overlay_url('classic_ui/icons/junk_01.png'),
            },
        },
        'steal': {
            'background': _static_overlay_url('classic_ui/steal/backgrounds/steal_bg_main.png'),
            'containers': {
                'closed': {
                    str(index): _static_overlay_url(f'classic_ui/steal/containers/bag_{index:02d}_closed.png')
                    for index in range(1, 9)
                },
                'open': {
                    str(index): _static_overlay_url(f'classic_ui/steal/containers/bag_{index:02d}_open.png')
                    for index in range(1, 9)
                },
            },
            'fillers': {
                'item1': _static_overlay_url('classic_ui/steal/backgrounds/item1.png'),
                'item2': _static_overlay_url('classic_ui/steal/backgrounds/item2.png'),
                'item6': _static_overlay_url('classic_ui/steal/backgrounds/item6.png'),
                'item7': _static_overlay_url('classic_ui/steal/backgrounds/item7.png'),
            },
            'reveal_icons': {
                'gold': _static_overlay_url('classic_ui/icons/gold.png'),
                'junk': _static_overlay_url('classic_ui/icons/junk_01.png'),
            },
        },
    }


def _overlay_layouts_path() -> str:
    os.makedirs(current_app.instance_path, exist_ok=True)
    return os.path.join(current_app.instance_path, 'overlay_layouts.json')


def _to_float(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _round_value(value: float) -> float:
    return round(float(value), 1)


def _normalize_position(value: float, fallback: float) -> float:
    return _round_value(max(0.0, min(100.0, _to_float(value, fallback))))


def _normalize_scale(value: float, fallback: float, minimum: float, maximum: float) -> float:
    return _round_value(max(minimum, min(maximum, _to_float(value, fallback))))


def _normalize_treasure_slot(slot: dict | None, *, fallback: dict) -> dict:
    source = slot or {}
    return {
        'name': fallback['name'],
        'x': _normalize_position(source.get('x'), fallback['x']),
        'y': _normalize_position(source.get('y'), fallback['y']),
        'scale': _normalize_scale(source.get('scale'), fallback['scale'], 0.1, 1.4),
    }


def _normalize_steal_slot(slot: dict | None, *, key: str, fallback: dict) -> dict:
    source = slot or {}
    return {
        'name': key,
        'x': _normalize_position(source.get('x'), fallback['x']),
        'y': _normalize_position(source.get('y'), fallback['y']),
        'scale': _normalize_scale(source.get('scale'), fallback['scale'], 0.1, 0.8),
    }


def _normalize_avatar_layout(layout: dict | None) -> dict:
    source = layout or {}
    fallback = DEFAULT_OVERLAY_LAYOUTS['steal']['avatar']
    return {
        'name': 'avatar',
        'x': _normalize_position(source.get('x'), fallback['x']),
        'y': _normalize_position(source.get('y'), fallback['y']),
        'width': _normalize_scale(source.get('width'), fallback['width'], 8.0, 40.0),
        'aspect_ratio': _to_float(source.get('aspect_ratio'), fallback['aspect_ratio']),
    }


def normalize_overlay_layouts(raw_layouts: dict | None) -> dict:
    normalized = copy.deepcopy(DEFAULT_OVERLAY_LAYOUTS)
    source = raw_layouts if isinstance(raw_layouts, dict) else {}

    treasure_source = source.get('treasure') if isinstance(source.get('treasure'), dict) else {}
    treasure_layouts = treasure_source.get('slot_layouts') if isinstance(treasure_source.get('slot_layouts'), dict) else {}
    for layout_key, slot_names in _TREASURE_SLOT_NAMES.items():
        source_slots = treasure_layouts.get(layout_key)
        source_map = {
            (entry.get('name') if isinstance(entry, dict) else None): entry
            for entry in source_slots
        } if isinstance(source_slots, list) else {}
        fallback_slots = DEFAULT_OVERLAY_LAYOUTS['treasure']['slot_layouts'][layout_key]
        normalized['treasure']['slot_layouts'][layout_key] = [
            _normalize_treasure_slot(source_map.get(slot_name), fallback=fallback_slot)
            for slot_name, fallback_slot in zip(slot_names, fallback_slots)
        ]

    steal_source = source.get('steal') if isinstance(source.get('steal'), dict) else {}
    steal_slots_source = steal_source.get('slot_layouts') if isinstance(steal_source.get('slot_layouts'), dict) else {}
    for slot_key in _STEAL_SLOT_KEYS:
        normalized['steal']['slot_layouts'][slot_key] = _normalize_steal_slot(
            steal_slots_source.get(slot_key),
            key=slot_key,
            fallback=DEFAULT_OVERLAY_LAYOUTS['steal']['slot_layouts'][slot_key],
        )
    normalized['steal']['avatar'] = _normalize_avatar_layout(steal_source.get('avatar'))

    return normalized


def load_overlay_layouts() -> dict:
    path = _overlay_layouts_path()
    if not os.path.exists(path):
        return copy.deepcopy(DEFAULT_OVERLAY_LAYOUTS)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_OVERLAY_LAYOUTS)
    return normalize_overlay_layouts(loaded)


def save_overlay_layouts(raw_layouts: dict) -> dict:
    normalized = normalize_overlay_layouts(raw_layouts)
    path = _overlay_layouts_path()
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(normalized, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return normalized
