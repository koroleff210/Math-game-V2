"""
test_avatar_preview_step1.py
============================

Targeted tests for avatar preview implementation attempt 1:
  - ordered avatar layer composition
  - player face persistence
  - Hub shell avatar updates through existing equip / unequip flow
  - minimal admin avatar_asset_key support
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.services.avatar import build_player_avatar_view
from datetime import datetime, timezone


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'avatar-preview-step1-secret'
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


def _make_player(username, *, is_admin=False, password='pass1234'):
    player = Player(username=username, is_admin=is_admin)
    player.set_password(password)
    db.session.add(player)
    db.session.flush()
    return player


def _make_item(item_id, slot_type, avatar_asset_key=None, **kwargs):
    item = GearItemDefinition(
        id=item_id,
        slot_type=slot_type,
        name=kwargs.pop('name', item_id.replace('_', ' ').title()),
        description=kwargs.pop('description', 'Avatar test item'),
        image_key=kwargs.pop('image_key', None),
        avatar_asset_key=avatar_asset_key,
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

        admin = _make_player('__avatar_admin__', is_admin=True)
        player = _make_player('__avatar_player__')

        _make_item('steel_blade', 'main_hand', avatar_asset_key='005', mine_gold_delta=2)
        _make_item('tower_guard', 'off_hand', avatar_asset_key='006', shield_duration_delta=3)
        _make_item('field_vest', 'chest', avatar_asset_key='002')
        _make_item('horned_helm', 'head', avatar_asset_key='003')
        _make_item('ranger_boots', 'boots', avatar_asset_key='004', steal_gold_delta=1)
        _make_item('coin_pouch', 'pocket', steal_gold_delta=1)

        db.session.add_all([
            PlayerGearOwnership(player_id=player.id, item_id='steel_blade'),
            PlayerGearOwnership(player_id=player.id, item_id='tower_guard'),
            PlayerGearOwnership(player_id=player.id, item_id='field_vest'),
            PlayerGearOwnership(player_id=player.id, item_id='horned_helm'),
            PlayerGearOwnership(player_id=player.id, item_id='ranger_boots'),
            PlayerGearOwnership(player_id=player.id, item_id='coin_pouch'),
        ])
        db.session.flush()

        loadout = PlayerGearLoadout(
            player_id=player.id,
            main_hand_item_id='steel_blade',
            off_hand_item_id='tower_guard',
            chest_item_id='field_vest',
            head_item_id='horned_helm',
        )
        db.session.add(loadout)
        db.session.commit()

        _IDS['admin_id'] = admin.id
        _IDS['player_id'] = player.id


def test_avatar_service_layer_order():
    with flask_app.app_context():
        player = db.session.get(Player, _IDS['player_id'])
        loadout = PlayerGearLoadout.query.filter_by(player_id=player.id).first()

        avatar = build_player_avatar_view(player, loadout)
        labels = [layer['label'] for layer in avatar['layers']]
        paths = [layer['static_path'] for layer in avatar['layers']]
        check(
            'AV-01: avatar layer stack order matches current paper-doll order when boots are not equipped',
            labels == [
                'head-back',
                'chest-underlay',
                'body-upper',
                'body-lower',
                'main-hand',
                'chest',
                'face',
                'head-front',
                'off-hand',
            ],
            detail=str(labels),
        )
        check(
            'AV-02: avatar uses resolved static/gear filenames for equipped gear and default face',
            paths[0].endswith('/gear/head/head_003b.png')
            and paths[1].endswith('/gear/chest/chest_002a.png')
            and paths[3].endswith('/gear/boots/body_lower.png')
            and paths[4].endswith('/gear/main_hand/main_hand_005.png')
            and paths[5].endswith('/gear/chest/chest_002.png')
            and paths[6].endswith('/gear/face/face_001.png')
            and paths[7].endswith('/gear/head/head_003a.png')
            and paths[8].endswith('/gear/off_hand/off_hand_006.png'),
        )

        loadout.boots_item_id = 'ranger_boots'
        db.session.commit()
        avatar = build_player_avatar_view(player, loadout)
        labels = [layer['label'] for layer in avatar['layers']]
        paths = [layer['static_path'] for layer in avatar['layers']]
        check(
            'AV-03: body lower hides when boots gear is equipped',
            'body-lower' not in labels and 'boots' in labels and any(path.endswith('/gear/boots/boots_004.png') for path in paths),
        )

        loadout.off_hand_item_id = None
        db.session.commit()
        avatar = build_player_avatar_view(player, loadout)
        paths = [layer['static_path'] for layer in avatar['layers']]
        check(
            'AV-04: off-hand base renders when no off-hand gear is equipped',
            paths[-1].endswith('/gear/off_hand/off_hand_base.png'),
        )


def test_hub_shell_avatar_and_face_actions():
    with flask_app.test_client() as client:
        _login(client, '__avatar_player__')

        r = client.get('/player/dashboard?gear_filter=all&selected_item=steel_blade')
        html = r.get_data(as_text=True)
        check(
            'AV-05: Hub renders avatar preview in the existing gear shell',
            r.status_code == 200 and 'data-avatar-preview' in html and 'data-avatar-layer-label="face"' in html,
        )

        js_headers = {'X-Requested-With': 'XMLHttpRequest'}
        r = client.post(
            '/player/avatar/face',
            data={
                'direction': 'next',
                'gear_filter': 'all',
                'selected_item': 'steel_blade',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        with flask_app.app_context():
            player = db.session.get(Player, _IDS['player_id'])
            check(
                'AV-06: previous/next face controls persist selected face',
                player.selected_face_key == '002',
            )
        check(
            'AV-07: JS-enhanced face change updates the character-selection shell in place',
            r.status_code == 200
            and 'data-avatar-face-key="002"' in html
            and '/gear/face/face_002.png' in html
            and 'data-avatar-layer-region="face"' in html
        )

        r = client.post(
            '/player/avatar/face',
            data={
                'direction': 'next',
                'gear_filter': 'all',
                'selected_item': 'steel_blade',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        with flask_app.app_context():
            player = db.session.get(Player, _IDS['player_id'])
            check(
                'AV-07B: repeated async next face remains reliable after replacement',
                player.selected_face_key == '003',
            )
        check(
            'AV-07C: repeated async next response updates face-only markers',
            r.status_code == 200
            and 'data-avatar-face-key="003"' in html
            and '/gear/face/face_003.png' in html
            and 'data-avatar-layer-region="face"' in html,
        )

        with flask_app.app_context():
            player = db.session.get(Player, _IDS['player_id'])
            player.character_locked_at = datetime.now(timezone.utc)
            loadout = PlayerGearLoadout.query.filter_by(player_id=player.id).first()
            loadout.boots_item_id = None
            loadout.off_hand_item_id = 'tower_guard'
            db.session.commit()

        r = client.post(
            '/player/avatar/face',
            data={
                'direction': 'next',
                'gear_filter': 'all',
                'selected_item': 'steel_blade',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        with flask_app.app_context():
            player = db.session.get(Player, _IDS['player_id'])
            check(
                'AV-07D: locked players cannot cycle face but still render the face layer',
                player.selected_face_key == '003'
                and r.status_code == 200
                and 'Your character face is locked' in html
                and 'data-avatar-layer-region="face"' in html
                and 'data-avatar-face-key="003"' in html,
            )

        r = client.post(
            '/player/gear/equip',
            data={
                'item_id': 'ranger_boots',
                'slot_key': 'boots',
                'gear_filter': 'boots',
                'selected_item': 'ranger_boots',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        check(
            'AV-08: equipping an item updates the avatar preview visually',
            r.status_code == 200 and '/gear/boots/boots_004.png' in html and '/gear/boots/body_lower.png' not in html,
        )
        check(
            'AV-09: selected-item panel still works after equip',
            'data-gear-selected-item="ranger_boots"' in html and 'Unequip' in html,
        )

        r = client.post(
            '/player/gear/unequip',
            data={
                'slot_key': 'off_hand',
                'gear_filter': 'off_hand',
                'selected_item': 'tower_guard',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        check(
            'AV-10: unequipping updates the avatar preview visually',
            r.status_code == 200 and '/gear/off_hand/off_hand_base.png' in html and '/gear/off_hand/off_hand_006.png' not in html,
        )
        check(
            'AV-11: equipped inventory markers remain coherent after avatar-driven shell updates',
            'Equipped in Off Hand' not in html and 'data-gear-loadout-slot="main_hand"' in html and 'Steel Blade' in html,
        )


def test_admin_avatar_asset_key_support():
    with flask_app.test_client() as client:
        _login(client, '__avatar_admin__')
        r = client.post(
            '/admin/gear/new',
            data={
                'item_id': 'admin_avatar_item',
                'name': 'Admin Avatar Item',
                'slot_type': 'chest',
                'description': 'Admin-created item with avatar art.',
                'image_key': '',
                'avatar_asset_key': '004',
                'diamond_cost': '9',
                'mine_gold_delta': '0',
                'steal_gold_delta': '0',
                'shield_duration_delta': '0',
                'is_active': 'y',
                'is_blacksmith_visible': 'y',
            },
            follow_redirects=True,
        )
        html = r.get_data(as_text=True)
        with flask_app.app_context():
            item = db.session.get(GearItemDefinition, 'admin_avatar_item')
            check(
                'AV-12: minimal admin-side avatar asset key support exists for gear items',
                item is not None and item.avatar_asset_key == '004' and 'admin_avatar_item' in html,
            )

    events_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app', 'modes', 'classic', 'events.py',
    )
    with open(events_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    check(
        'AV-13: Classic runtime only consumes avatar service payloads, not editable cosmetic fields directly',
        'selected_face_key' not in src and 'avatar_asset_key' not in src and 'build_player_avatar_view' in src,
    )


if __name__ == '__main__':
    print('\nAvatar Preview Attempt 1 - Tests')
    print('-' * 60)
    _setup_db()
    test_avatar_service_layer_order()
    test_hub_shell_avatar_and_face_actions()
    test_admin_avatar_asset_key_support()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL AVATAR PREVIEW ATTEMPT 1 TESTS PASSED.')
    else:
        print('SOME AVATAR PREVIEW ATTEMPT 1 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
