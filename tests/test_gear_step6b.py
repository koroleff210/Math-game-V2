"""
test_gear_step6b.py
===================

Targeted regression tests for Gear / Hub UX Step 6B:
  - equipment panel / slot selection
  - active equipped bonus summary
  - Step 6A inventory/details flow remains intact

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step6b.py
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
    SECRET_KEY = 'gear-step-6b-secret'
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
        player = _make_player('__gear6b_player__')

        _make_item(
            'iron_pick',
            'main_hand',
            name='Iron Pick',
            description='Reliable mining tool.',
            mine_gold_delta=3,
        )
        _make_item(
            'storm_shield',
            'off_hand',
            name='Storm Shield',
            description='Off-hand with a penalty to steal.',
            steal_gold_delta=-2,
            shield_duration_delta=5,
        )
        _make_item(
            'lucky_coin',
            'pocket',
            name='Lucky Coin',
            description='Pocket item with steal bonus.',
            steal_gold_delta=1,
        )
        _make_item(
            'cloth_hood',
            'head',
            name='Cloth Hood',
            description='Lightweight hood.',
            shield_duration_delta=2,
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
            PlayerGearOwnership(player_id=player.id, item_id='storm_shield'),
            PlayerGearOwnership(player_id=player.id, item_id='lucky_coin'),
            PlayerGearOwnership(player_id=player.id, item_id='cloth_hood'),
        ])
        db.session.flush()
        db.session.add(
            PlayerGearLoadout(
                player_id=player.id,
                main_hand_item_id='iron_pick',
                off_hand_item_id='storm_shield',
                pocket1_item_id='lucky_coin',
            )
        )
        db.session.commit()


def test_equipment_panel_and_summary():
    with flask_app.test_client() as client:
        _login(client, '__gear6b_player__')

        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        check('G6B-01: Hub renders all 7 equipment slots',
              all(slot_key in html for slot_key in (
                  'data-gear-loadout-slot="main_hand"',
                  'data-gear-loadout-slot="off_hand"',
                  'data-gear-loadout-slot="head"',
                  'data-gear-loadout-slot="chest"',
                  'data-gear-loadout-slot="boots"',
                  'data-gear-loadout-slot="pocket1"',
                  'data-gear-loadout-slot="pocket2"',
              )))
        check('G6B-02: occupied slots display the equipped item safely',
              'Iron Pick' in html and 'Storm Shield' in html and 'Lucky Coin' in html)
        check('G6B-03: empty slots display safe empty-state',
              html.count('Empty slot') >= 3 and 'Nothing equipped' in html)
        check('G6B-06: active bonus summary renders equipped totals correctly',
              'Mine: +3' in html and 'Steal: -1' in html and 'Shield: +5 s' in html)
        check('G6B-08: positive and negative equipped totals render correctly',
              'Steal: -1' in html)
        check('G6B-09: inventory + details behavior from Step 6A is not broken',
              'All (4)' in html and 'data-gear-selected-item="iron_pick"' in html)

        r = client.get('/player/dashboard?gear_filter=off_hand&selected_item=storm_shield')
        html = r.get_data(as_text=True)
        check('G6B-04: clicking/selecting an occupied slot drives the shared details panel correctly',
              'data-gear-selected-item="storm_shield"' in html and 'Off-hand with a penalty to steal.' in html)
        check('G6B-05: selected equipped slot/item still shows correct Unequip action in details panel',
              'Equipped in Off Hand' in html and 'action="/player/gear/unequip"' in html)

        with flask_app.app_context():
            loadout = PlayerGearLoadout.query.first()
            loadout.main_hand_item_id = None
            loadout.off_hand_item_id = None
            loadout.pocket1_item_id = None
            db.session.commit()

        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        check('G6B-07: active bonus summary handles zero/empty loadout safely',
              'Mine: +0' in html and 'Steal: +0' in html and 'Shield: +0 s' in html)


def test_routes_and_runtime_guard():
    with flask_app.test_client() as client:
        _login(client, '__gear6b_player__')

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
        check('G6B-10: existing equip/unequip backend flow still works through the updated UI',
              r.status_code == 200 and 'Equipped in Head' in html and 'Shield: +2 s' in html)

        blacksmith = client.get('/player/blacksmith')
        blacksmith_html = blacksmith.get_data(as_text=True)
        check('G6B-11: existing Blacksmith behavior is not broken',
              blacksmith.status_code == 200 and 'Boots Shop' in blacksmith_html)

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check('G6B-12: existing Step 4 snapshot/runtime behavior is not broken',
          'effective_gear_mine_gold_delta' in src and 'build_player_gear_hub_view' not in src)
    check('G6B-13: gameplay/runtime code paths remain unchanged in this step',
          'data-gear-loadout-slot' not in src and 'Active Gear Bonuses' not in src)


if __name__ == '__main__':
    print('\nGear Step 6B - Tests')
    print('-' * 60)
    _setup_db()
    test_equipment_panel_and_summary()
    test_routes_and_runtime_guard()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 6B TESTS PASSED.')
    else:
        print('SOME GEAR STEP 6B TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
