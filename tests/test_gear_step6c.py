"""
test_gear_step6c.py
===================

Targeted regression tests for Gear / Hub UX Step 6C:
  - partial gear-shell endpoint for in-place selection
  - shared selection path for filters, inventory, and equipment panel
  - fallback-safe Hub rendering remains intact

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step6c.py
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
    SECRET_KEY = 'gear-step-6c-secret'
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
        player = _make_player('__gear6c_player__')
        # Step 6C assertions target the normal Hub gear shell, not first-time
        # character setup; lock character to bypass setup gating.
        player.character_locked_at = player.created_at

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
            PlayerGearOwnership(player_id=player.id, item_id='storm_shield'),
            PlayerGearOwnership(player_id=player.id, item_id='cloth_hood'),
            PlayerGearOwnership(player_id=player.id, item_id='lucky_coin'),
        ])
        db.session.flush()
        db.session.add(
            PlayerGearLoadout(
                player_id=player.id,
                main_hand_item_id='iron_pick',
                off_hand_item_id='storm_shield',
            )
        )
        db.session.commit()


def test_partial_shell_endpoint_and_hub_markup():
    with flask_app.test_client() as client:
        _login(client, '__gear6c_player__')

        r = client.get('/player/gear/shell?gear_filter=head&selected_item=cloth_hood')
        html = r.get_data(as_text=True)
        check('G6C-01: shell partial endpoint returns correct selected item fragment for owned item',
              r.status_code == 200 and 'data-gear-selected-item="cloth_hood"' in html and 'Lightweight hood.' in html)
        check('G6C-07: selected item details still show correct image/description/effects/actions',
              'Shield duration: +2s' in html and 'action="/player/gear/equip"' in html and 'src="/static/gear/' in html)
        check('G6C-06: filter context remains stable while using partial selection',
              'class="filter-tab active"' in html and 'Headgear (1)' in html)

        r = client.get('/player/gear/shell?gear_filter=head&selected_item=storm_shield')
        html = r.get_data(as_text=True)
        check('G6C-02: shell partial endpoint handles equipped slot selection correctly',
              'data-gear-selected-item="storm_shield"' in html and 'Equipped in Off Hand' in html and 'Unequip' in html)
        check('G6C-05: selecting from equipment panel uses the same shared details rendering path',
              'action="/player/gear/unequip"' in html and 'data-gear-loadout-slot="off_hand"' in html)

        r = client.get('/player/gear/shell?gear_filter=head&selected_item=not_owned')
        html = r.get_data(as_text=True)
        check('G6C-03: invalid/non-owned item selection is handled safely',
              r.status_code == 200 and 'data-gear-selected-item="cloth_hood"' in html)

        hub = client.get('/player/dashboard?gear_filter=all&selected_item=cloth_hood')
        hub_html = hub.get_data(as_text=True)
        check('G6C-04: selecting from inventory no longer depends on full page navigation logic',
              'data-gear-shell-url="' in hub_html and 'data-gear-shell-link' in hub_html and 'gear-shell-container' in hub_html)
        check('G6C-04: filter click no longer depends on full page navigation logic',
              'data-gear-shell-url="/player/gear/shell?gear_filter=head&amp;selected_item=cloth_hood"' in hub_html)
        check('G6C-08: equipped markers remain correct after partial selection changes',
              'data-gear-loadout-slot="main_hand"' in hub_html
              and 'data-gear-loadout-slot="off_hand"' in hub_html
              and 'Equipped in' in hub_html)


def test_routes_and_runtime_guard():
    with flask_app.test_client() as client:
        _login(client, '__gear6c_player__')

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
        check('G6C-09: existing equip/unequip backend flow still works with the updated UI',
              r.status_code == 200 and 'Equipped in Head' in html and 'data-gear-shell-url="' in html)

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check('G6C-12: existing Step 4 snapshot/runtime behavior is not broken',
          'effective_gear_mine_gold_delta' in src and 'player/gear/shell' not in src)
    check('G6C-13: gameplay/runtime code paths remain unchanged in this step',
          'data-gear-shell-url' not in src and 'gear-shell-container' not in src)


if __name__ == '__main__':
    print('\nGear Step 6C - Tests')
    print('-' * 60)
    _setup_db()
    test_partial_shell_endpoint_and_hub_markup()
    test_routes_and_runtime_guard()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 6C TESTS PASSED.')
    else:
        print('SOME GEAR STEP 6C TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
