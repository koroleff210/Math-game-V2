"""
Focused regression tests for the Hub polish pass.

Verifies:
  - Join Game control lives inside Active Gear Bonuses instead of a separate session-status card
  - no-session state renders a disabled join button
  - eligible-session state renders the existing join flow inside the bonuses card
  - gear/avatar async responses expose the named regions used for targeted Hub updates
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.game import GameSession
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.models.problems import ProblemSet


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'hub-polish-pass-secret'
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
    player = Player(
        username=username,
        is_admin=False,
        character_locked_at=datetime.now(timezone.utc),
    )
    player.set_password(password)
    db.session.add(player)
    db.session.flush()
    return player


def _make_item(item_id, slot_type, **kwargs):
    item = GearItemDefinition(
        id=item_id,
        slot_type=slot_type,
        name=kwargs.pop('name', item_id.replace('_', ' ').title()),
        description=kwargs.pop('description', 'Hub polish test item'),
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
        player = _make_player('__hub_polish_player__')

        _make_item('cloth_hood', 'head', name='Cloth Hood', shield_duration_delta=2)
        _make_item('iron_pick', 'main_hand', name='Iron Pick', mine_gold_delta=3)

        db.session.add_all([
            PlayerGearOwnership(player_id=player.id, item_id='cloth_hood'),
            PlayerGearOwnership(player_id=player.id, item_id='iron_pick'),
        ])
        db.session.flush()
        db.session.add(PlayerGearLoadout(player_id=player.id, main_hand_item_id='iron_pick'))
        db.session.commit()
        _IDS['player_id'] = player.id


def test_hub_session_control_layout():
    with flask_app.test_client() as client:
        _login(client, '__hub_polish_player__')

        r = client.get('/player/dashboard?gear_filter=head&selected_item=cloth_hood')
        html = r.get_data(as_text=True)
        check(
            'HPP-01: no-session Hub shows disabled Join Game inside bonuses card',
            r.status_code == 200
            and 'Active Gear Bonuses' in html
            and 'data-hub-session-control' in html
            and 'Join Game' in html
            and 'disabled' in html
            and 'Session Status' not in html
            and 'session-banner' not in html,
        )

        with flask_app.app_context():
            pset = ProblemSet(name='__hub_polish_set__')
            db.session.add(pset)
            db.session.flush()
            session = GameSession(
                mode='classic',
                status='waiting',
                problem_set_id=pset.id,
                started_at=datetime.now(timezone.utc),
            )
            db.session.add(session)
            db.session.commit()
            _IDS['session_id'] = session.id

        r = client.get('/player/dashboard?gear_filter=head&selected_item=cloth_hood')
        html = r.get_data(as_text=True)
        check(
            'HPP-02: eligible-session Hub renders join flow inside bonuses card without top banner',
            r.status_code == 200
            and 'data-hub-session-control' in html
            and 'action="/classic/join"' in html
            and f'name="session_id" value="{_IDS["session_id"]}"' in html
            and 'Session Status' not in html
            and 'session-banner' not in html,
        )


def test_hub_async_fragment_shape():
    with flask_app.test_client() as client:
        _login(client, '__hub_polish_player__')
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
        check(
            'HPP-03: equip async response contains split Hub regions for partial refresh',
            r.status_code == 200
            and 'data-gear-avatar-preview-region' in html
            and 'data-gear-avatar-composite-region' in html
            and 'data-avatar-layer-region="head-back"' in html
            and 'data-avatar-layer-region="face"' in html
            and 'data-gear-face-controls-region' in html
            and 'data-gear-slot-region="head"' in html
            and 'data-gear-slots-region' in html
            and 'data-gear-details-header-region' in html
            and 'data-gear-details-dynamic-region' in html
            and 'data-gear-bonus-region' in html
            and 'data-gear-inventory-region' in html
            and 'Equipped in Head' in html,
        )

        r = client.post(
            '/player/avatar/face',
            data={
                'direction': 'next',
                'gear_filter': 'head',
                'selected_item': 'cloth_hood',
            },
            headers=js_headers,
            follow_redirects=False,
        )
        html = r.get_data(as_text=True)
        check(
            'HPP-04: face async response exposes inner avatar preview regions',
            r.status_code == 200
            and 'data-avatar-preview' in html
            and 'data-gear-avatar-preview-region' in html
            and 'data-gear-avatar-composite-region' in html
            and 'data-avatar-layer-region="face"' in html
            and 'data-avatar-face-label-region' in html
            and 'data-gear-face-controls-region' in html
            and 'data-gear-slots-region' in html
            and 'data-gear-bonus-region' in html
            and 'data-gear-inventory-region' in html,
        )


def test_hub_selection_link_scope():
    hub_template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'app',
        'templates',
        'player',
        'hub.html',
    )
    with open(hub_template_path, encoding='utf-8') as f:
        html = f.read()

    inventory_branch_start = html.index("link.hasAttribute('data-gear-inventory-item')")
    inventory_branch_end = html.index("if (link.hasAttribute('data-gear-loadout-slot'))")
    inventory_branch = html[inventory_branch_start:inventory_branch_end]
    loadout_branch_start = inventory_branch_end
    loadout_branch_return = html.index('return [', loadout_branch_start)
    loadout_branch_end = html.index('return [', loadout_branch_return + 1)
    loadout_branch = html[loadout_branch_start:loadout_branch_end]

    check(
        'HPP-05: inventory/filter selection skips loadout and avatar refresh regions',
        '[data-gear-details-region]' in inventory_branch
        and '[data-gear-inventory-region]' in inventory_branch
        and '[data-gear-slots-region]' not in inventory_branch
        and '[data-gear-avatar-composite-region]' not in inventory_branch,
    )
    check(
        'HPP-06: loadout-slot selection can still refresh slot selection state',
        '[data-gear-slots-region]' in loadout_branch
        and '[data-gear-details-region]' in loadout_branch
        and '[data-gear-inventory-region]' in loadout_branch
        and '[data-gear-avatar-composite-region]' not in loadout_branch,
    )


if __name__ == '__main__':
    print('\nHub Polish Pass - Tests')
    print('-' * 60)
    _setup_db()
    test_hub_session_control_layout()
    test_hub_async_fragment_shape()
    test_hub_selection_link_scope()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL HUB POLISH PASS TESTS PASSED.')
    else:
        print('SOME HUB POLISH PASS TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
