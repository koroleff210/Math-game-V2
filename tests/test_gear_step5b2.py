"""
test_gear_step5b2.py
====================

Targeted regression tests for Gear V1 Step 5B2:
  - selected gear images render when valid
  - slot placeholders render when image is blank/missing
  - Hub/Blacksmith/admin pages still render safely

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step5b2.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.game import GameSession
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.services.gear import (
    get_gear_placeholder_key,
    resolve_gear_image_static_path,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-5b2-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0
_TEST_IMAGE_PATHS = []


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        msg = f'  FAIL  {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)
        failed += 1


def _make_player(username, is_admin=False, password='pass1234'):
    p = Player(username=username, is_admin=is_admin)
    p.set_password(password)
    db.session.add(p)
    db.session.flush()
    return p


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def _gear_static_dir():
    return os.path.join(flask_app.static_folder, 'gear')


def _write_test_file(filename, content=b'test'):
    folder = _gear_static_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    with open(path, 'wb') as fh:
        fh.write(content)
    _TEST_IMAGE_PATHS.append(path)


def _cleanup_test_files():
    for path in _TEST_IMAGE_PATHS:
        if os.path.exists(path):
            os.remove(path)


def _make_item(item_id, slot_type, **kwargs):
    item = GearItemDefinition(
        id=item_id,
        slot_type=slot_type,
        name=kwargs.pop('name', item_id.replace('_', ' ').title()),
        description=kwargs.pop('description', 'Test item'),
        image_key=kwargs.pop('image_key', None),
        diamond_cost=kwargs.pop('diamond_cost', 5),
        mine_gold_delta=kwargs.pop('mine_gold_delta', 0),
        steal_gold_delta=kwargs.pop('steal_gold_delta', 0),
        shield_duration_delta=kwargs.pop('shield_duration_delta', 0),
        is_active=kwargs.pop('is_active', True),
        is_blacksmith_visible=kwargs.pop('is_blacksmith_visible', True),
        **kwargs,
    )
    db.session.add(item)
    db.session.flush()
    return item


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin = _make_player('__gear5b2_admin__', is_admin=True)
        player = _make_player('__gear5b2_player__')

        _make_item('valid_image_item', 'main_hand', name='Valid Image Item', image_key='alpha_blade.png')
        _make_item('blank_image_item', 'off_hand', name='Blank Image Item', image_key=None)
        _make_item('missing_image_item', 'head', name='Missing Image Item', image_key='missing_image.png')
        _make_item('shop_item', 'boots', name='Shop Item', image_key=None)

        db.session.add(PlayerGearOwnership(player_id=player.id, item_id='valid_image_item'))
        db.session.add(PlayerGearOwnership(player_id=player.id, item_id='blank_image_item'))
        db.session.add(PlayerGearOwnership(player_id=player.id, item_id='missing_image_item'))
        db.session.flush()
        db.session.add(
            PlayerGearLoadout(
                player_id=player.id,
                main_hand_item_id='valid_image_item',
                off_hand_item_id='blank_image_item',
                head_item_id='missing_image_item',
            )
        )
        db.session.commit()


def test_image_resolution_helper():
    with flask_app.app_context():
        valid_path = resolve_gear_image_static_path(slot_type='main_hand', image_key='alpha_blade.png')
        blank_path = resolve_gear_image_static_path(slot_type='off_hand', image_key=None)
        missing_path = resolve_gear_image_static_path(slot_type='head', image_key='missing_image.png')

        check('G5B2-01: gear item with valid image_key resolves to selected item image',
              valid_path.endswith('/static/gear/alpha_blade.png'),
              f'got {valid_path}')
        check('G5B2-02: blank image_key resolves to correct slot/type placeholder',
              blank_path.endswith('/static/gear/placeholder_off_hand.svg'),
              f'got {blank_path}')
        check('G5B2-03: missing file referenced by image_key resolves to correct placeholder',
              missing_path.endswith('/static/gear/placeholder_head.svg'),
              f'got {missing_path}')

        expected = {
            'main_hand': 'placeholder_main_hand.svg',
            'off_hand': 'placeholder_off_hand.svg',
            'chest': 'placeholder_chest.svg',
            'head': 'placeholder_head.svg',
            'boots': 'placeholder_boots.svg',
            'pocket': 'placeholder_pocket.svg',
        }
        actual = {slot: get_gear_placeholder_key(slot) for slot in expected}
        check('G5B2-04: each supported slot/type maps to the expected placeholder family',
              actual == expected,
              f'got {actual}')


def test_rendering_routes_and_runtime_guard():
    with flask_app.test_client() as client:
        _login(client, '__gear5b2_player__')

        hub = client.get('/player/dashboard')
        hub_html = hub.get_data(as_text=True)
        check('G5B2-05: Hub gear rendering still works when items have no image',
              'placeholder_off_hand.svg' in hub_html and 'placeholder_head.svg' in hub_html and 'alpha_blade.png' in hub_html)

        blacksmith = client.get('/player/blacksmith')
        blacksmith_html = blacksmith.get_data(as_text=True)
        check('G5B2-06: Blacksmith gear rendering still works when items have no image',
              'placeholder_boots.svg' in blacksmith_html)

    with flask_app.test_client() as client:
        _login(client, '__gear5b2_admin__')
        admin_index = client.get('/admin/gear/')
        admin_index_html = admin_index.get_data(as_text=True)
        admin_edit = client.get('/admin/gear/valid_image_item/edit')
        admin_edit_html = admin_edit.get_data(as_text=True)
        check('G5B2-07: admin gear list/create/edit behavior is not broken',
              admin_index.status_code == 200
              and admin_edit.status_code == 200
              and 'alpha_blade.png' in admin_index_html
              and '/static/gear/alpha_blade.png' in admin_edit_html)

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check('G5B2-10: gameplay/runtime code paths remain unchanged in this step',
          'image_key' not in src and 'placeholder_' not in src and 'app.services.gear' not in src)


if __name__ == '__main__':
    print('\nGear Step 5B2 - Tests')
    print('-' * 60)
    _write_test_file('alpha_blade.png')
    try:
        _setup_db()
        test_image_resolution_helper()
        test_rendering_routes_and_runtime_guard()
    finally:
        _cleanup_test_files()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 5B2 TESTS PASSED.')
    else:
        print('SOME GEAR STEP 5B2 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
