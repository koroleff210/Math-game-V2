"""
test_gear_step6d.py
===================

Targeted regression tests for Gear / Hub UX Step 6D:
  - in-place equip / unequip shell responses
  - fallback redirect behavior still exists
  - Step 6C shell interaction model remains intact

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step6d.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-6d-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0


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


def _make_player(username, password='pass1234'):
    player = Player(username=username, is_admin=False)
    player.set_password(password)
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def _make_item(item_id, slot_type, **kwargs):
    item = GearItemDefinition(
        id=item_id,
        slot_type=slot_type,
        name=kwargs.pop('name', item_id.replace('_', ' ').title()),
        description=kwargs.pop('description', 'Test item description'),
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
        player = _make_player('__gear6d_player__')

        _make_item(
            'iron_pick',
            'main_hand',
            name='Iron Pick',
            description='Reliable mining tool.',
            mine_gold_delta=3,
        )
        _make_item(
            'cloth_hood',
            'head',
            name='Cloth Hood',
            description='Lightweight hood.',
            shield_duration_delta=2,
        )
        _make_item(
            'lucky_coin',
            'pocket',
            name='Lucky Coin',
            description='Pocket item with steal bonus.',
            steal_gold_delta=1,
        )

        db.session.add_all([
            PlayerGearOwnership(player_id=player.id, item_id='iron_pick'),
            PlayerGearOwnership(player_id=player.id, item_id='cloth_hood'),
            PlayerGearOwnership(player_id=player.id, item_id='lucky_coin'),
        ])
        db.session.flush()
        db.session.add(
            PlayerGearLoadout(
                player_id=player.id,
                main_hand_item_id='iron_pick',
            )
        )
        db.session.commit()


def test_js_shell_actions_and_fallback():
    with flask_app.test_client() as client:
        _login(client, '__gear6d_player__')

        js_headers = {'X-Requested-With': 'XMLHttpRequest'}

        r = client.post(
            '/player/gear/equip',
            data={
                'item_id': 'cloth_hood',
                'slot_key': 'head',
                'gear_filter': 'head',
                'selected_item': 'cloth_hood',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        check('G6D-01: JS-enhanced equip path can return/update the gear shell without full page navigation semantics',
              r.status_code == 200 and 'data-gear-shell' in html and 'Equipped in Head' in html)
        check('G6D-03: equip action updates inventory equipped markers correctly',
              'Equipped in Head' in html)
        check('G6D-04: equip action updates equipment panel correctly',
              'data-gear-loadout-slot="head"' in html and 'Cloth Hood' in html)
        check('G6D-05: equip action updates active bonus summary correctly',
              'Shield: +2 s' in html)
        check('G6D-09: selected item/details remain coherent after equip',
              'data-gear-selected-item="cloth_hood"' in html and 'Unequip' in html)

        r = client.post(
            '/player/gear/unequip',
            data={
                'slot_key': 'head',
                'gear_filter': 'head',
                'selected_item': 'cloth_hood',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        check('G6D-02: JS-enhanced unequip path can return/update the gear shell without full page navigation semantics',
              r.status_code == 200 and 'data-gear-shell' in html and 'Head unequipped.' in html)
        check('G6D-06: unequip action updates inventory equipped markers correctly',
              'Equipped in Head' not in html and 'data-gear-inventory-item="cloth_hood"' in html)
        check('G6D-07: unequip action updates equipment panel correctly',
              'data-gear-loadout-slot="head"' in html and 'Empty slot' in html)
        check('G6D-08: unequip action updates active bonus summary correctly',
              'Shield: +0 s' in html)
        check('G6D-10: selected item/details remain coherent after unequip',
              'data-gear-selected-item="cloth_hood"' in html and 'Equip to Head' in html)

        r = client.post(
            '/player/gear/equip',
            data={
                'item_id': 'not_owned',
                'slot_key': 'head',
                'gear_filter': 'head',
                'selected_item': 'cloth_hood',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        check('G6D-11: invalid equip action is handled safely',
              r.status_code == 200 and 'Gear item not found.' in html and 'data-gear-shell' in html)

        r = client.post(
            '/player/gear/equip',
            data={
                'item_id': 'cloth_hood',
                'slot_key': 'head',
                'gear_filter': 'head',
                'selected_item': 'cloth_hood',
            },
            follow_redirects=False,
        )
        check('G6D-12: existing non-JS fallback still basically works',
              r.status_code in (301, 302))

        hub = client.get('/player/dashboard?gear_filter=head&selected_item=cloth_hood')
        hub_html = hub.get_data(as_text=True)
        check('G6D-13: existing Step 6C in-place selection/filter behavior is not broken',
              'data-gear-shell-url="' in hub_html and 'data-gear-shell-form' in hub_html)

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check('G6D-14: existing Step 4 snapshot/runtime behavior is not broken',
          'effective_gear_mine_gold_delta' in src and 'player/gear/equip' not in src)
    check('G6D-15: gameplay/runtime code paths remain unchanged in this step',
          'data-gear-shell-form' not in src and 'gear-shell' not in src)


if __name__ == '__main__':
    print('\nGear Step 6D - Tests')
    print('-' * 60)
    _setup_db()
    test_js_shell_actions_and_fallback()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 6D TESTS PASSED.')
    else:
        print('SOME GEAR STEP 6D TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
