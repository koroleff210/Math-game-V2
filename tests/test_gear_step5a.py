"""
test_gear_step5a.py
===================

Targeted regression tests for Gear V1 Step 5A:
  - admin gear catalog list/create/edit
  - Blacksmith visibility after admin edits
  - Hub continuity after catalog edits
  - runtime source guard (no direct persistent gear reads in gameplay events)

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step5a.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.game import GameSession
from app.models.gear import GearItemDefinition, PlayerGearOwnership
from app.models.player import Player
from app.models.progression import SessionParticipantSnapshot
from app.services.progression import ensure_session_participant_snapshot


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-5a-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0
_IDS = {}


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


def _make_item(item_id, slot_type='main_hand', **kwargs):
    item = GearItemDefinition(
        id=item_id,
        slot_type=slot_type,
        name=kwargs.pop('name', item_id.replace('_', ' ').title()),
        description=kwargs.pop('description', 'Test item'),
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


def _make_session(status='waiting'):
    gs = GameSession(mode='classic', status=status)
    db.session.add(gs)
    db.session.flush()
    return gs


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin = _make_player('__gear5a_admin__', is_admin=True)
        player = _make_player('__gear5a_player__')
        _make_item(
            'existing_gear',
            slot_type='main_hand',
            name='Existing Gear',
            description='Already in catalog.',
            diamond_cost=9,
            mine_gold_delta=2,
        )
        _make_item(
            'owned_visible_gear',
            slot_type='off_hand',
            name='Owned Visible Gear',
            description='Owned by player.',
            diamond_cost=7,
            shield_duration_delta=4,
        )
        db.session.flush()
        db.session.add(PlayerGearOwnership(player_id=player.id, item_id='owned_visible_gear'))
        db.session.commit()
        _IDS['admin_id'] = admin.id
        _IDS['player_id'] = player.id


def test_admin_catalog_routes():
    with flask_app.test_client() as client:
        _login(client, '__gear5a_admin__')

        r = client.get('/admin/gear/')
        html = r.get_data(as_text=True)
        check('G5A-01: admin gear list page renders existing items', r.status_code == 200 and 'Existing Gear' in html)

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'new_test_gear',
                'name': 'New Test Gear',
                'slot_type': 'head',
                'description': 'Created from admin UI.',
                'diamond_cost': '11',
                'mine_gold_delta': '3',
                'steal_gold_delta': '-2',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'new_test_gear')
            check('G5A-02: admin can create a valid gear item', item is not None and item.name == 'New Test Gear')

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'existing_gear',
                'name': 'Duplicate Gear',
                'slot_type': 'head',
                'description': 'Duplicate id.',
                'diamond_cost': '1',
                'mine_gold_delta': '0',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        dup_html = r.get_data(as_text=True)
        check('G5A-03: create rejects duplicate item identifier/key', 'already exists' in dup_html)

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'invalid_slot_item',
                'name': 'Invalid Slot Item',
                'slot_type': 'ring',
                'description': 'Bad slot.',
                'diamond_cost': '1',
                'mine_gold_delta': '0',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        invalid_slot_html = r.get_data(as_text=True)
        check('G5A-04: create rejects invalid slot/type', 'Not a valid choice' in invalid_slot_html)

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'invalid_numeric_item',
                'name': 'Invalid Numeric Item',
                'slot_type': 'head',
                'description': 'Bad numeric.',
                'diamond_cost': 'abc',
                'mine_gold_delta': '0',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        invalid_numeric_html = r.get_data(as_text=True)
        check('G5A-05: create rejects invalid numeric input where appropriate', 'Not a valid integer value' in invalid_numeric_html)

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'delta_values_item',
                'name': 'Delta Values Item',
                'slot_type': 'pocket',
                'description': 'Mixed delta signs.',
                'diamond_cost': '0',
                'mine_gold_delta': '-5',
                'steal_gold_delta': '0',
                'shield_duration_delta': '6',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'delta_values_item')
            check('G5A-06: create accepts negative/zero/positive flat effect values',
                  item is not None and item.mine_gold_delta == -5 and item.steal_gold_delta == 0 and item.shield_duration_delta == 6)
            check('G5A-07: create accepts non-negative Diamond cost',
                  item is not None and item.diamond_cost == 0)

        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'negative_cost_item',
                'name': 'Negative Cost Item',
                'slot_type': 'boots',
                'description': 'Bad cost.',
                'diamond_cost': '-1',
                'mine_gold_delta': '0',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        negative_cost_html = r.get_data(as_text=True)
        check('G5A-07: create rejects invalid negative Diamond cost', '0 or higher' in negative_cost_html)

        r = client.post(
            '/admin/gear/existing_gear/edit',
            data={
                'item_id': 'existing_gear',
                'name': 'Existing Gear Updated',
                'slot_type': 'boots',
                'description': 'Updated description.',
                'diamond_cost': '12',
                'mine_gold_delta': '4',
                'steal_gold_delta': '5',
                'shield_duration_delta': '-3',
            },
            follow_redirects=True,
        )
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'existing_gear')
            check('G5A-08: admin can edit display fields',
                  item.name == 'Existing Gear Updated' and item.description == 'Updated description.')
            check('G5A-09: admin can edit flat effect values',
                  item.mine_gold_delta == 4 and item.steal_gold_delta == 5 and item.shield_duration_delta == -3)

        r = client.post(
            '/admin/gear/existing_gear/edit',
            data={
                'item_id': 'existing_gear',
                'name': 'Existing Gear Updated',
                'slot_type': 'boots',
                'description': 'Updated description.',
                'diamond_cost': '12',
                'mine_gold_delta': '4',
                'steal_gold_delta': '5',
                'shield_duration_delta': '-3',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'existing_gear')
            check('G5A-10: admin can edit active flag', item.is_active is False)
            check('G5A-11: admin can edit Blacksmith visible flag', item.is_blacksmith_visible is True)

        r = client.get('/admin/gear/')
        html = r.get_data(as_text=True)
        check('G5A-12: edited item appears updated in admin list/view',
              'Existing Gear Updated' in html and 'data-item-id="existing_gear"' in html)


def test_player_surfaces_after_admin_edits():
    with flask_app.test_client() as client:
        _login(client, '__gear5a_admin__')
        client.post(
            '/admin/gear/owned_visible_gear/edit',
            data={
                'item_id': 'owned_visible_gear',
                'name': 'Owned Visible Gear',
                'slot_type': 'off_hand',
                'description': 'Owned by player.',
                'diamond_cost': '7',
                'mine_gold_delta': '0',
                'steal_gold_delta': '0',
                'shield_duration_delta': '4',
                'is_active': 'y',
            },
            follow_redirects=True,
        )
        client.post(
            '/admin/gear/new',
            data={
                'item_id': 'stock_item_for_player',
                'name': 'Stock Item For Player',
                'slot_type': 'head',
                'description': 'Visible in Blacksmith.',
                'diamond_cost': '10',
                'mine_gold_delta': '1',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        client.post(
            '/admin/gear/stock_item_for_player/edit',
            data={
                'item_id': 'stock_item_for_player',
                'name': 'Stock Item For Player',
                'slot_type': 'head',
                'description': 'Visible in Blacksmith.',
                'diamond_cost': '10',
                'mine_gold_delta': '1',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
            },
            follow_redirects=True,
        )

    with flask_app.test_client() as client:
        _login(client, '__gear5a_player__')

        r = client.get('/player/blacksmith')
        html = r.get_data(as_text=True)
        check('G5A-13: hidden-from-Blacksmith item no longer appears in Blacksmith stock',
              'Stock Item For Player' not in html)
        check('G5A-14: inactive item no longer appears as valid Blacksmith stock',
              'Existing Gear Updated' not in html)
        check('G5A-15: existing Step 3 Blacksmith upgrade behavior is not broken',
              'steal_token_cap' in html)

        hub = client.get('/player/dashboard')
        hub_html = hub.get_data(as_text=True)
        check('G5A-16: existing Step 2 Hub equip behavior is not broken',
              'Owned Gear' in hub_html and 'Gear Loadout' in hub_html and 'Owned Visible Gear' in hub_html)


def test_snapshot_behavior_and_runtime_source_guard():
    with flask_app.app_context():
        pid = _IDS['player_id']
        item = db.session.get(GearItemDefinition, 'owned_visible_gear')
        item.mine_gold_delta = 9
        gs = _make_session(status='waiting')
        ensure_session_participant_snapshot(gs.id, pid)
        db.session.commit()
        snap = SessionParticipantSnapshot.query.filter_by(session_id=gs.id, player_id=pid).first()
        check('G5A-17: existing Step 4 snapshot/runtime behavior is not broken',
              snap is not None and snap.effective_gear_mine_gold_delta == 0,
              f'got {None if snap is None else snap.effective_gear_mine_gold_delta}')

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check('G5A-18: no gameplay code path was modified to re-read persistent gear during runtime',
          'app.services.gear' not in src and 'app.models.gear' not in src and 'GearItemDefinition' not in src)


if __name__ == '__main__':
    print('\nGear Step 5A - Tests')
    print('-' * 60)
    _setup_db()
    test_admin_catalog_routes()
    test_player_surfaces_after_admin_edits()
    test_snapshot_behavior_and_runtime_source_guard()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 5A TESTS PASSED.')
    else:
        print('SOME GEAR STEP 5A TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
