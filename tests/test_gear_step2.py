"""
test_gear_step2.py
==================

Targeted regression tests for Gear V1 Step 2:
  - service-layer equip / unequip validation
  - inactive loadout normalization
  - Hub POST equip / unequip routes

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step2.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.game import GameSession, RoundPlayer
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.services.gear import (
    build_player_gear_hub_view,
    equip_player_gear_item,
    unequip_player_gear_slot,
)


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-2-secret'
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
        _make_player('__gear2_admin__', is_admin=True)
        player = _make_player('__gear2_player__')
        db.session.commit()
        _IDS['player_id'] = player.id

        db.session.add_all([
            GearItemDefinition(
                id='mh_a',
                slot_type='main_hand',
                name='Main A',
                description='Main hand item A.',
            ),
            GearItemDefinition(
                id='mh_b',
                slot_type='main_hand',
                name='Main B',
                description='Main hand item B.',
            ),
            GearItemDefinition(
                id='off_a',
                slot_type='off_hand',
                name='Off A',
                description='Off hand item.',
            ),
            GearItemDefinition(
                id='pocket_a',
                slot_type='pocket',
                name='Pocket A',
                description='Pocket item A.',
            ),
            GearItemDefinition(
                id='pocket_b',
                slot_type='pocket',
                name='Pocket B',
                description='Pocket item B.',
            ),
            GearItemDefinition(
                id='retired_item',
                slot_type='boots',
                name='Retired Item',
                description='Inactive item.',
                is_active=False,
            ),
        ])
        db.session.flush()

        db.session.add_all([
            PlayerGearOwnership(player_id=player.id, item_id='mh_a'),
            PlayerGearOwnership(player_id=player.id, item_id='mh_b'),
            PlayerGearOwnership(player_id=player.id, item_id='off_a'),
            PlayerGearOwnership(player_id=player.id, item_id='pocket_a'),
            PlayerGearOwnership(player_id=player.id, item_id='pocket_b'),
            PlayerGearOwnership(player_id=player.id, item_id='retired_item'),
        ])
        db.session.commit()


def _expect_value_error(label, fn, expected_text):
    try:
        fn()
    except ValueError as exc:
        check(label, expected_text in str(exc), f'got {exc!r}')
    else:
        check(label, False, 'ValueError not raised')


def test_service_logic():
    with flask_app.app_context():
        pid = _IDS['player_id']

        res = equip_player_gear_item(player_id=pid, item_id='mh_a', slot_key='main_hand')
        db.session.commit()
        loadout = PlayerGearLoadout.query.filter_by(player_id=pid).first()
        check('G2-01: equip owned compatible item into empty slot', loadout.main_hand_item_id == 'mh_a')

        equip_player_gear_item(player_id=pid, item_id='mh_b', slot_key='main_hand')
        db.session.commit()
        db.session.refresh(loadout)
        check('G2-02: equip into occupied slot replaces previous content', loadout.main_hand_item_id == 'mh_b')

        owned_before = PlayerGearOwnership.query.filter_by(player_id=pid, item_id='mh_b').count()
        unequip_player_gear_slot(player_id=pid, slot_key='main_hand')
        db.session.commit()
        db.session.refresh(loadout)
        owned_after = PlayerGearOwnership.query.filter_by(player_id=pid, item_id='mh_b').count()
        check('G2-03: unequip clears slot', loadout.main_hand_item_id is None)
        check('G2-03: unequip does not affect ownership', owned_before == owned_after == 1)

        _expect_value_error(
            'G2-04: cannot equip unowned item',
            lambda: equip_player_gear_item(player_id=pid, item_id='missing_item', slot_key='main_hand'),
            'not found',
        )

        _expect_value_error(
            'G2-05: cannot equip inactive item',
            lambda: equip_player_gear_item(player_id=pid, item_id='retired_item', slot_key='boots'),
            'not currently available',
        )

        _expect_value_error(
            'G2-06: cannot equip incompatible slot',
            lambda: equip_player_gear_item(player_id=pid, item_id='off_a', slot_key='main_hand'),
            'cannot be equipped',
        )

        equip_player_gear_item(player_id=pid, item_id='pocket_a', slot_key='pocket1')
        db.session.commit()
        _expect_value_error(
            'G2-07: cannot equip same item into both pocket slots',
            lambda: equip_player_gear_item(player_id=pid, item_id='pocket_a', slot_key='pocket2'),
            'already equipped',
        )

        _expect_value_error(
            'G2-08: duplicate protection rejects same item in another slot',
            lambda: equip_player_gear_item(player_id=pid, item_id='pocket_a', slot_key='pocket2'),
            'already equipped',
        )

        equip_player_gear_item(player_id=pid, item_id='pocket_b', slot_key='pocket2')
        db.session.commit()
        db.session.refresh(loadout)
        check('G2-09: pocket item can equip into pocket1', loadout.pocket1_item_id == 'pocket_a')
        check('G2-10: pocket item can equip into pocket2', loadout.pocket2_item_id == 'pocket_b')

        loadout.boots_item_id = 'retired_item'
        db.session.commit()
        view = build_player_gear_hub_view(pid)
        db.session.commit()
        db.session.refresh(loadout)
        effective_boots = next(s for s in view['slot_rows'] if s['slot_key'] == 'boots')
        check('G2-11: inactive equipped refs normalized out of effective loadout', effective_boots['item'] is None)
        check('G2-11: inactive equipped refs cleared from persisted loadout', loadout.boots_item_id is None)


def test_hub_routes():
    with flask_app.test_client() as client:
        _login(client, '__gear2_player__')

        r = client.post(
            '/player/gear/equip',
            data={'item_id': 'mh_a', 'slot_key': 'main_hand'},
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        check('G2-12: equip route renders safely after redirect', r.status_code == 200)
        check('G2-12: equip route preserves existing Hub sections', 'Diamonds' in html and 'Upgrades' in html)
        check('G2-12: equip route shows Gear Loadout section', 'Gear Loadout' in html)
        check('G2-12: equipped item appears in Hub after route action', 'Main A' in html)

        r = client.post(
            '/player/gear/unequip',
            data={'slot_key': 'main_hand'},
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        check('G2-13: unequip route renders safely after redirect', r.status_code == 200)
        check('G2-13: unequip route keeps Owned Gear section intact', 'Owned Gear' in html)
        check('G2-13: unequipped slot shows empty state', 'Nothing equipped' in html)

        with flask_app.app_context():
            session = GameSession(mode='classic', status='waiting')
            db.session.add(session)
            db.session.flush()
            db.session.add(RoundPlayer(session_id=session.id, player_id=_IDS['player_id']))
            db.session.commit()

        r = client.post(
            '/player/gear/equip',
            data={'item_id': 'mh_a', 'slot_key': 'main_hand'},
            follow_redirects=False,
        )
        check('G2-12: route blocks gear changes during unfinished session', r.status_code in (301, 302))


if __name__ == '__main__':
    print('\nGear Step 2 - Tests')
    print('-' * 60)
    _setup_db()
    test_service_logic()
    test_hub_routes()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 2 TESTS PASSED.')
    else:
        print('SOME GEAR STEP 2 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
