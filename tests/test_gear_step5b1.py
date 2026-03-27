"""
test_gear_step5b1.py
====================

Targeted regression tests for Gear V1 Step 5B1:
  - optional image_key support
  - admin dropdown populated from app/static/gear
  - service validation of selected filenames

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step5b1.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition
from app.models.player import Player
from app.services.gear import create_admin_gear_item, list_available_gear_image_keys


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-5b1-secret'
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


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        _make_player('__gear5b1_admin__', is_admin=True)
        _make_player('__gear5b1_player__')
        db.session.commit()


def _seed_images():
    _write_test_file('zzz_ignore.txt')
    _write_test_file('alpha_blade.png')
    _write_test_file('beta_shield.webp')
    _write_test_file('gamma_hood.jpg')


def test_admin_image_dropdown_and_persistence():
    with flask_app.test_client() as client:
        _login(client, '__gear5b1_admin__')

        r = client.get('/admin/gear/new')
        html = r.get_data(as_text=True)
        check('G5B1-01: admin create form renders with image dropdown options from fixed folder',
              'alpha_blade.png' in html and 'beta_shield.webp' in html and 'zzz_ignore.txt' not in html)

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'blank_image_item',
                'name': 'Blank Image Item',
                'slot_type': 'main_hand',
                'description': 'No image selected.',
                'image_key': '',
                'diamond_cost': '5',
                'mine_gold_delta': '1',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'blank_image_item')
            check('G5B1-03: admin can create item with blank image selection',
                  item is not None and item.image_key is None)

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'image_item',
                'name': 'Image Item',
                'slot_type': 'off_hand',
                'description': 'Selected image.',
                'image_key': 'beta_shield.webp',
                'diamond_cost': '7',
                'mine_gold_delta': '0',
                'steal_gold_delta': '2',
                'shield_duration_delta': '3',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'image_item')
            check('G5B1-04: admin can create item with valid selected image filename',
                  item is not None and item.image_key == 'beta_shield.webp')

        r = client.get('/admin/gear/image_item/edit')
        html = r.get_data(as_text=True)
        check('G5B1-02: admin edit form renders current selected image correctly',
              'option selected value="beta_shield.webp"' in html or 'value="beta_shield.webp" selected' in html)

        r = client.post(
            '/admin/gear/image_item/edit',
            data={
                'item_id': 'image_item',
                'name': 'Image Item Updated',
                'slot_type': 'off_hand',
                'description': 'Updated image.',
                'image_key': 'gamma_hood.jpg',
                'diamond_cost': '8',
                'mine_gold_delta': '4',
                'steal_gold_delta': '-1',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'image_item')
            check('G5B1-05: admin can edit item image selection',
                  item is not None and item.image_key == 'gamma_hood.jpg')
            check('G5B1-07: existing admin gear create/edit behavior for non-image fields is not broken',
                  item.name == 'Image Item Updated' and item.diamond_cost == 8 and item.mine_gold_delta == 4 and item.steal_gold_delta == -1)


def test_service_image_validation_and_runtime_guard():
    with flask_app.app_context():
        available = list_available_gear_image_keys()
        check('G5B1-01: discovered image keys are sorted and filtered',
              available == ['alpha_blade.png', 'beta_shield.webp', 'gamma_hood.jpg'],
              f'got {available}')

        try:
            create_admin_gear_item({
                'item_id': 'invalid_image_item',
                'name': 'Invalid Image Item',
                'slot_type': 'head',
                'description': 'Bad image selection.',
                'image_key': 'not_allowed.png',
                'diamond_cost': 3,
                'mine_gold_delta': 0,
                'steal_gold_delta': 0,
                'shield_duration_delta': 0,
                'is_active': True,
                'is_blacksmith_visible': True,
            })
        except ValueError as exc:
            check('G5B1-06: invalid image selection outside allowed discovered files is rejected',
                  'Invalid gear image selection' in str(exc),
                  f'got {exc!r}')
        else:
            check('G5B1-06: invalid image selection outside allowed discovered files is rejected', False, 'ValueError not raised')

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check('G5B1-10: gameplay/runtime code paths remain unchanged in this step',
          'image_key' not in src and 'app.services.gear' not in src and 'app.models.gear' not in src)


if __name__ == '__main__':
    print('\nGear Step 5B1 - Tests')
    print('-' * 60)
    _seed_images()
    try:
        _setup_db()
        test_admin_image_dropdown_and_persistence()
        test_service_image_validation_and_runtime_guard()
    finally:
        _cleanup_test_files()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 5B1 TESTS PASSED.')
    else:
        print('SOME GEAR STEP 5B1 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
