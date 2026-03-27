"""
test_gear_step3.py
==================

Targeted regression tests for Gear V1 Step 3:
  - Blacksmith gear availability filtering
  - Diamond-backed gear purchase
  - Blacksmith/Hub route integration

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step3.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.models.progression import DiamondTransaction, PlayerProgression
from app.services.gear import list_blacksmith_gear_for_player, purchase_blacksmith_gear
from app.services.progression import award_diamonds_to_player


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-3-secret'
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
        admin = _make_player('__gear3_admin__', is_admin=True)
        player = _make_player('__gear3_player__')
        db.session.commit()
        _IDS['admin_id'] = admin.id
        _IDS['player_id'] = player.id

        db.session.add_all([
            GearItemDefinition(
                id='gear_for_sale',
                slot_type='head',
                name='Gear For Sale',
                description='Visible and purchasable.',
                diamond_cost=9,
            ),
            GearItemDefinition(
                id='gear_owned',
                slot_type='boots',
                name='Owned Gear',
                description='Already owned.',
                diamond_cost=7,
            ),
            GearItemDefinition(
                id='gear_inactive',
                slot_type='chest',
                name='Inactive Gear',
                description='Not for sale.',
                diamond_cost=6,
                is_active=False,
            ),
            GearItemDefinition(
                id='gear_hidden',
                slot_type='off_hand',
                name='Hidden Gear',
                description='Hidden from Blacksmith.',
                diamond_cost=5,
                is_blacksmith_visible=False,
            ),
            GearItemDefinition(
                id='gear_pocket',
                slot_type='pocket',
                name='Pocket Gear',
                description='Pocket option.',
                diamond_cost=4,
            ),
            GearItemDefinition(
                id='gear_route_sale',
                slot_type='main_hand',
                name='Route Sale Gear',
                description='Dedicated route-purchase test item.',
                diamond_cost=3,
            ),
        ])
        db.session.flush()
        db.session.add(PlayerGearOwnership(player_id=player.id, item_id='gear_owned'))
        db.session.commit()


def _expect_value_error(label, fn, expected_text):
    try:
        fn()
    except ValueError as exc:
        check(label, expected_text in str(exc), f'got {exc!r}')
    else:
        check(label, False, 'ValueError not raised')


def test_blacksmith_service():
    with flask_app.app_context():
        pid = _IDS['player_id']
        admin_id = _IDS['admin_id']

        stock = list_blacksmith_gear_for_player(pid)
        stock_ids = {row['id'] for row in stock}
        check('G3-01: available gear excludes owned items', 'gear_owned' not in stock_ids)
        check('G3-02: available gear excludes inactive items', 'gear_inactive' not in stock_ids)
        check('G3-03: available gear excludes non-Blacksmith-visible items', 'gear_hidden' not in stock_ids)
        check('G3-03: active visible unowned gear remains listed', {'gear_for_sale', 'gear_pocket'} <= stock_ids)

        award_diamonds_to_player(
            player_id=pid,
            amount=20,
            reason='gear_step3_seed',
            admin_player_id=admin_id,
        )
        db.session.commit()

        bal_before = PlayerProgression.query.filter_by(player_id=pid).first().diamonds_balance
        purchase_blacksmith_gear(player_id=pid, item_id='gear_for_sale')
        db.session.commit()
        bal_after = PlayerProgression.query.filter_by(player_id=pid).first().diamonds_balance
        tx = (
            DiamondTransaction.query
            .filter_by(player_id=pid)
            .order_by(DiamondTransaction.id.desc())
            .first()
        )
        owned = PlayerGearOwnership.query.filter_by(player_id=pid, item_id='gear_for_sale').first()
        loadout = PlayerGearLoadout.query.filter_by(player_id=pid).first()
        check('G3-04: successful purchase deducts Diamonds', bal_after == bal_before - 9)
        check('G3-05: successful purchase creates ownership', owned is not None)
        check('G3-06: successful purchase does not auto-equip', loadout is None)
        check('G3-04: purchase writes DiamondTransaction reason', tx is not None and tx.reason == 'gear_purchase:gear_for_sale')

        stock_after = {row['id'] for row in list_blacksmith_gear_for_player(pid)}
        check('G3-07: purchased item disappears from Blacksmith availability', 'gear_for_sale' not in stock_after)

        _expect_value_error(
            'G3-09: cannot purchase already owned item',
            lambda: purchase_blacksmith_gear(player_id=pid, item_id='gear_owned'),
            'already own',
        )
        _expect_value_error(
            'G3-10: cannot purchase inactive item',
            lambda: purchase_blacksmith_gear(player_id=pid, item_id='gear_inactive'),
            'not currently available',
        )
        _expect_value_error(
            'G3-11: cannot purchase hidden/non-Blacksmith-visible item',
            lambda: purchase_blacksmith_gear(player_id=pid, item_id='gear_hidden'),
            'not currently for sale',
        )

        prog = PlayerProgression.query.filter_by(player_id=pid).first()
        prog.diamonds_balance = 0
        db.session.commit()
        _expect_value_error(
            'G3-12: cannot purchase with insufficient Diamonds',
            lambda: purchase_blacksmith_gear(player_id=pid, item_id='gear_pocket'),
            'Not enough Diamonds',
        )

        _expect_value_error(
            'G3-13: duplicate purchase attempts are safely rejected',
            lambda: purchase_blacksmith_gear(player_id=pid, item_id='gear_for_sale'),
            'already own',
        )


def test_blacksmith_and_hub_routes():
    with flask_app.test_client() as client:
        _login(client, '__gear3_player__')

        r = client.get('/player/blacksmith')
        html = r.get_data(as_text=True)
        check('G3-14: existing upgrade-related Blacksmith behavior still renders upgrades', 'steal_token_cap' in html)
        check('G3-01: Blacksmith page excludes owned gear', 'Owned Gear' not in html)
        check('G3-02: Blacksmith page excludes inactive gear', 'Inactive Gear' not in html)
        check('G3-03: Blacksmith page excludes hidden gear', 'Hidden Gear' not in html)
        check('G3-03: Blacksmith page shows available gear', 'data-item-id="gear_route_sale"' in html)

        with flask_app.app_context():
            award_diamonds_to_player(
                player_id=_IDS['player_id'],
                amount=20,
                reason='gear_route_seed',
                admin_player_id=_IDS['admin_id'],
            )
            db.session.commit()

        r = client.post(
            '/player/blacksmith/buy_gear',
            data={'item_id': 'gear_route_sale'},
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        check('G3-04: successful route purchase returns 200', r.status_code == 200)
        check('G3-07: purchased item disappears from Blacksmith page', 'data-item-id="gear_route_sale"' not in html)

        hub = client.get('/player/dashboard')
        hub_html = hub.get_data(as_text=True)
        check('G3-08: purchased item appears in Hub owned inventory', 'Route Sale Gear' in hub_html)
        check('G3-15: existing Hub gear Step 2 behavior still renders loadout section', 'Gear Loadout' in hub_html)
        check('G3-15: existing Hub gear Step 2 behavior still renders owned gear section', 'Owned Gear' in hub_html)


if __name__ == '__main__':
    print('\nGear Step 3 - Tests')
    print('-' * 60)
    _setup_db()
    test_blacksmith_service()
    test_blacksmith_and_hub_routes()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 3 TESTS PASSED.')
    else:
        print('SOME GEAR STEP 3 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
