"""
test_gear_step6a.py
===================

Targeted regression tests for Gear / Hub UX Step 6A:
  - Hub filter tabs and same-screen selection/details shell
  - equipped-state inventory markers
  - existing equip / unequip routes working through the new shell

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step6a.py
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
    SECRET_KEY = 'gear-step-6a-secret'
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
        player = _make_player('__gear6a_player__')

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
        _make_item(
            'boots_shop',
            'boots',
            name='Boots Shop',
            description='Visible shop item.',
            is_blacksmith_visible=True,
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


def test_hub_inventory_shell():
    with flask_app.test_client() as client:
        _login(client, '__gear6a_player__')

        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        check('G6A-01: Hub renders filter controls',
              all(label in html for label in ('All (3)', 'Main hand (1)', 'Pocket (1)')))
        check('G6A-02: All filter shows owned items across types',
              'Iron Pick' in html and 'Cloth Hood' in html and 'Lucky Coin' in html)
        check('G6A-03: selected item details render on the same page',
              'Reliable mining tool.' in html and 'Mine gold: +3' in html)
        check('G6A-04: selected item shows description/effects/image',
              'src="/static/gear/' in html and 'Shield duration' in html)
        check('G6A-05: equipped item is visibly marked in inventory rendering',
              'Equipped in Main Hand' in html)
        check('G6A-06: selected equipped item shows Unequip action',
              'action="/player/gear/unequip"' in html and 'Unequip' in html)

        r = client.get('/player/dashboard?gear_filter=head&selected_item=cloth_hood')
        html = r.get_data(as_text=True)
        check('G6A-07: slot-specific filter limits visible items appropriately',
              'data-gear-inventory-item="cloth_hood"' in html
              and 'data-gear-inventory-item="lucky_coin"' not in html
              and 'data-gear-inventory-item="iron_pick"' not in html)
        check('G6A-08: selected unequipped item shows Equip action',
              'Equip to Head' in html and 'action="/player/gear/equip"' in html)

        r = client.get('/player/dashboard?gear_filter=pocket&selected_item=lucky_coin')
        html = r.get_data(as_text=True)
        check('G6A-09: pocket item details show both Pocket 1 and Pocket 2 equip targets',
              'Equip to Pocket 1' in html and 'Equip to Pocket 2' in html)

        r = client.get('/player/dashboard?gear_filter=head&selected_item=does_not_exist')
        html = r.get_data(as_text=True)
        check('G6A-10: selecting an invalid/non-owned item id is handled safely',
              r.status_code == 200 and 'Cloth Hood' in html and 'Select an item' not in html)

        r = client.get('/player/dashboard?gear_filter=boots')
        html = r.get_data(as_text=True)
        check('G6A-11: empty filtered result shows safe empty state',
              'No owned items match this filter yet.' in html)


def test_routes_and_runtime_guard():
    with flask_app.test_client() as client:
        _login(client, '__gear6a_player__')

        r = client.post(
            '/player/gear/equip',
            data={
                'item_id': 'cloth_hood',
                'slot_key': 'head',
                'gear_filter': 'head',
                'selected_item': 'cloth_hood',
            },
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        check('G6A-12: existing equip backend flow still works through the new UI',
              r.status_code == 200 and 'Equipped in Head' in html and 'Unequip' in html)

        r = client.post(
            '/player/gear/unequip',
            data={
                'slot_key': 'head',
                'gear_filter': 'head',
                'selected_item': 'cloth_hood',
            },
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        check('G6A-12: existing unequip backend flow still works through the new UI',
              r.status_code == 200 and 'Equip to Head' in html)

        blacksmith = client.get('/player/blacksmith')
        blacksmith_html = blacksmith.get_data(as_text=True)
        check('G6A-13: existing Blacksmith behavior is not broken',
              blacksmith.status_code == 200 and 'Boots Shop' in blacksmith_html)

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check('G6A-14: gameplay/runtime code paths remain unchanged in this step',
          'gear_filter' not in src and 'selected_item' not in src and 'inventory-shell' not in src)


if __name__ == '__main__':
    print('\nGear Step 6A - Tests')
    print('-' * 60)
    _setup_db()
    test_hub_inventory_shell()
    test_routes_and_runtime_guard()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 6A TESTS PASSED.')
    else:
        print('SOME GEAR STEP 6A TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
