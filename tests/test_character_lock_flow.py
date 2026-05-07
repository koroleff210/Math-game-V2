"""
Focused regression tests for first-login character selection and face locking.

Run:
    .venv\\Scripts\\python.exe tests\\test_character_lock_flow.py
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
    SECRET_KEY = 'character-lock-flow-secret'
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


def _make_player(username, password='pass1234'):
    player = Player(username=username, is_admin=False)
    player.set_password(password)
    db.session.add(player)
    db.session.flush()
    return player


def _make_item(item_id, slot_type, **kwargs):
    item = GearItemDefinition(
        id=item_id,
        slot_type=slot_type,
        name=kwargs.pop('name', item_id.replace('_', ' ').title()),
        description=kwargs.pop('description', 'Character lock test item'),
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


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        player = _make_player('__character_lock_player__')
        _make_item('iron_pick', 'main_hand', name='Iron Pick', mine_gold_delta=3)
        _make_item('cloth_hood', 'head', name='Cloth Hood', shield_duration_delta=2)
        db.session.add_all([
            PlayerGearOwnership(player_id=player.id, item_id='iron_pick'),
            PlayerGearOwnership(player_id=player.id, item_id='cloth_hood'),
            PlayerGearLoadout(player_id=player.id),
        ])
        db.session.commit()
        _IDS['player_id'] = player.id


def test_first_login_selection_and_lock_flow():
    with flask_app.test_client() as client:
        _login(client, '__character_lock_player__')

        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        check(
            'CLF-01: unlocked player sees character selection before normal Hub',
            r.status_code == 200
            and 'Choose your character.' in html
            and 'Confirm Character' in html
            and 'Owned Gear' not in html
            and 'Blacksmith' not in html,
        )
        check(
            'CLF-02: unlocked player can cycle face while selecting',
            'Previous' in html and 'Next' in html and 'data-avatar-face-key="001"' in html,
        )

        js_headers = {'X-Requested-With': 'XMLHttpRequest'}
        r = client.post(
            '/player/avatar/face',
            data={'direction': 'next', 'gear_filter': 'all'},
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        with flask_app.app_context():
            player = db.session.get(Player, _IDS['player_id'])
            check(
                'CLF-03: unlocked face cycle persists selected preview face',
                player.selected_face_key == '002' and player.character_locked_at is None,
            )
        check(
            'CLF-04: unlocked face cycle keeps the selection shell fragment shape',
            r.status_code == 200
            and 'Confirm Character' in html
            and 'data-avatar-face-key="002"' in html
            and 'Owned Gear' not in html,
        )

        r = client.post('/player/avatar/confirm', follow_redirects=True)
        html = r.get_data(as_text=True)
        with flask_app.app_context():
            player = db.session.get(Player, _IDS['player_id'])
            check(
                'CLF-05: confirm locks the selected face with a nullable timestamp field',
                player.selected_face_key == '002' and player.character_locked_at is not None,
            )
        check(
            'CLF-06: locked player enters normal Hub with face controls hidden',
            r.status_code == 200
            and 'Owned Gear' in html
            and 'Blacksmith' in html
            and 'Confirm Character' not in html
            and 'action="/player/avatar/face"' not in html
            and 'Face locked. Gear can still be changed.' in html,
        )

        r = client.post(
            '/player/avatar/face',
            data={'direction': 'next', 'gear_filter': 'all'},
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        with flask_app.app_context():
            player = db.session.get(Player, _IDS['player_id'])
            check(
                'CLF-07: direct face route cannot mutate a locked character',
                player.selected_face_key == '002',
            )
        check(
            'CLF-08: locked face route explains that only face identity is locked',
            r.status_code == 200
            and 'Your character face is locked. Gear can still be changed normally.' in html,
        )

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
        check(
            'CLF-09: gear remains editable after character face lock',
            r.status_code == 200
            and 'Equipped in Head' in html
            and 'Face locked. Gear can still be changed.' in html,
        )


if __name__ == '__main__':
    print('\nCharacter Lock Flow - Tests')
    print('-' * 60)
    _setup_db()
    test_first_login_selection_and_lock_flow()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL CHARACTER LOCK FLOW TESTS PASSED.')
    else:
        print('SOME CHARACTER LOCK FLOW TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
