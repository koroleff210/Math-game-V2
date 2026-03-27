"""
test_gear_step1.py
==================

Targeted regression tests for Gear V1 Step 1:
  - persistent gear definition / ownership / loadout model families
  - read-only Hub rendering for owned gear + equipped loadout
  - hidden/removed items excluded from Hub inventory rendering

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step1.py
"""

import os
import sys

from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-1-secret'
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


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin = _make_player('__gear_admin__', is_admin=True)
        player_a = _make_player('__gear_player_a__')
        player_b = _make_player('__gear_player_b__')
        db.session.commit()
        _IDS['admin_id'] = admin.id
        _IDS['player_a_id'] = player_a.id
        _IDS['player_b_id'] = player_b.id


def test_model_persistence():
    with flask_app.app_context():
        item = GearItemDefinition(
            id='copper_pick',
            slot_type='main_hand',
            name='Copper Pick',
            description='Starter pick.',
            mine_gold_delta=2,
        )
        db.session.add(item)
        db.session.commit()

        fresh = db.session.get(GearItemDefinition, 'copper_pick')
        check('G1-01: gear item definition persists by string item id', fresh is not None)
        check('G1-01: flat stat fields persist', fresh.mine_gold_delta == 2)

        own = PlayerGearOwnership(player_id=_IDS['player_a_id'], item_id='copper_pick')
        db.session.add(own)
        db.session.commit()
        check(
            'G1-02: ownership row persists',
            PlayerGearOwnership.query.filter_by(
                player_id=_IDS['player_a_id'], item_id='copper_pick'
            ).count() == 1,
        )

        dup = PlayerGearOwnership(player_id=_IDS['player_a_id'], item_id='copper_pick')
        db.session.add(dup)
        try:
            db.session.commit()
            unique_ok = False
        except IntegrityError:
            db.session.rollback()
            unique_ok = True
        check('G1-03: ownership uniqueness blocks duplicate same item id', unique_ok)


def test_loadout_persistence():
    with flask_app.app_context():
        db.session.add_all([
            GearItemDefinition(
                id='tower_shield',
                slot_type='off_hand',
                name='Tower Shield',
                description='Big shield.',
                shield_duration_delta=8,
            ),
            GearItemDefinition(
                id='coin_a',
                slot_type='pocket',
                name='Coin A',
                description='Pocket item A.',
            ),
            GearItemDefinition(
                id='coin_b',
                slot_type='pocket',
                name='Coin B',
                description='Pocket item B.',
            ),
        ])
        db.session.commit()

        row = PlayerGearLoadout(
            player_id=_IDS['player_a_id'],
            main_hand_item_id='copper_pick',
            off_hand_item_id='tower_shield',
            pocket1_item_id='coin_a',
            pocket2_item_id='coin_b',
        )
        db.session.add(row)
        db.session.commit()

        fresh = PlayerGearLoadout.query.filter_by(player_id=_IDS['player_a_id']).first()
        check('G1-04: fixed-slot loadout persists one row per player', fresh is not None)
        check('G1-04: fixed non-pocket slots persist', fresh.off_hand_item_id == 'tower_shield')
        check(
            'G1-05: pocket slot structure persists separate pocket1/pocket2 refs',
            fresh.pocket1_item_id == 'coin_a' and fresh.pocket2_item_id == 'coin_b',
        )


def test_hub_rendering():
    with flask_app.test_client() as client:
        _login(client, '__gear_player_b__')

        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        check('G1-06: hub renders 200 for player with no owned gear', r.status_code == 200)
        check('G1-06: hub includes Gear Loadout section', 'Gear Loadout' in html)
        check('G1-06: hub includes Owned Gear section', 'Owned Gear' in html)
        check('G1-06: hub safely shows empty loadout state', 'Nothing equipped' in html)
        check('G1-06: hub safely shows empty inventory state', 'You do not own any gear yet.' in html)

        with flask_app.app_context():
            count = PlayerGearLoadout.query.filter_by(player_id=_IDS['player_b_id']).count()
            check('G1-06: dashboard bootstrap creates missing loadout row safely', count == 1)

    with flask_app.app_context():
        db.session.add_all([
            GearItemDefinition(
                id='active_boots',
                slot_type='boots',
                name='Active Boots',
                description='Visible owned item.',
            ),
            GearItemDefinition(
                id='removed_relic',
                slot_type='pocket',
                name='Removed Relic',
                description='Should be hidden.',
                is_active=False,
            ),
        ])
        db.session.commit()

        db.session.add_all([
            PlayerGearOwnership(player_id=_IDS['player_b_id'], item_id='active_boots'),
            PlayerGearOwnership(player_id=_IDS['player_b_id'], item_id='removed_relic'),
        ])
        loadout = PlayerGearLoadout.query.filter_by(player_id=_IDS['player_b_id']).first()
        loadout.boots_item_id = 'active_boots'
        loadout.pocket1_item_id = 'removed_relic'
        db.session.commit()

    with flask_app.test_client() as client:
        _login(client, '__gear_player_b__')
        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        check('G1-07: hub retains existing Diamonds section', 'Diamonds' in html)
        check('G1-07: hub retains existing Upgrades section', 'Upgrades' in html)
        check('G1-07: visible owned gear renders', 'Active Boots' in html)
        check('G1-07: removed item hidden from owned gear inventory', 'Removed Relic' not in html)


if __name__ == '__main__':
    print('\nGear Step 1 - Tests')
    print('-' * 60)
    _setup_db()
    test_model_persistence()
    test_loadout_persistence()
    test_hub_rendering()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 1 TESTS PASSED.')
    else:
        print('SOME GEAR STEP 1 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
