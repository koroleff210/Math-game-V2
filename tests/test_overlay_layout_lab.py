"""
Focused overlay layout lab regression test.

Verifies that the admin-only layout lab can save to the shared instance JSON
source and that the player runtime page reads the saved overlay layouts back.
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.game import GameRound, GameSession
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic
from app.services.overlay_layouts import build_overlay_asset_payload, load_overlay_layouts


_DB_FILE = tempfile.NamedTemporaryFile(prefix='overlay_layout_lab_', suffix='.sqlite3', delete=False)
_DB_FILE.close()
_INSTANCE_DIR = tempfile.mkdtemp(prefix='overlay_layout_lab_instance_')


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_DB_FILE.name.replace(os.sep, '/')}"
    SECRET_KEY = 'overlay-layout-lab-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)
flask_app.instance_path = _INSTANCE_DIR

passed = 0
failed = 0


@atexit.register
def _cleanup_temp_artifacts():
    try:
        os.remove(_DB_FILE.name)
    except OSError:
        pass
    shutil.rmtree(_INSTANCE_DIR, ignore_errors=True)


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        message = f'  FAIL  {label}'
        if detail:
            message += f'  ({detail})'
        print(message)
        failed += 1


def _make_player(username, *, is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    return client.post(
        '/login',
        data={'username': username, 'password': 'pass1234'},
        follow_redirects=True,
    )


def _setup_world():
    db.create_all()

    admin = _make_player('__layout_lab_admin__', is_admin=True)
    player = _make_player('__layout_lab_player__', is_admin=False)

    topic = Topic(name='__layout_lab_topic__')
    db.session.add(topic)
    db.session.flush()

    problem = Problem(
        topic_id=topic.id,
        title='Layout Lab Problem',
        prompt_text='1 + 1',
        answer_text='2',
        difficulty=1,
    )
    db.session.add(problem)
    db.session.flush()

    problem_set = ProblemSet(name='__layout_lab_problem_set__')
    db.session.add(problem_set)
    db.session.flush()
    problem_set.problems.append(problem)

    session = GameSession(mode='classic', status='active', problem_set_id=problem_set.id)
    db.session.add(session)
    db.session.flush()

    round_row = GameRound(
        session_id=session.id,
        round_number=1,
        problem_id=None,
        started_at=datetime.now(timezone.utc),
    )
    db.session.add(round_row)
    db.session.commit()
    return admin, player, session


def run_tests():
    with flask_app.app_context():
        admin, player, session = _setup_world()
        admin_client = flask_app.test_client()
        player_client = flask_app.test_client()

        _login(admin_client, admin.username)
        _login(player_client, player.username)

        get_resp = admin_client.get('/admin/classic/layout-lab')
        get_html = get_resp.get_data(as_text=True)
        check('OLL-01: layout lab page renders for admin', get_resp.status_code == 200, f'status={get_resp.status_code}')
        check(
            'OLL-02: layout lab page includes save control and shared asset payload',
            'saveLayoutDraft' in get_html and 'Overlay Layout Lab' in get_html and 'OVERLAY_ASSETS' in get_html,
        )

        payload = {
            'treasure': {
                'slot_layouts': {
                    '1': [{'name': 'slot_1', 'x': 48.8, 'y': 41.8, 'scale': 1.0}],
                    '2': [
                        {'name': 'slot_1', 'x': 39.7, 'y': 43.4, 'scale': 0.8},
                        {'name': 'slot_2', 'x': 60.9, 'y': 43.6, 'scale': 0.8},
                    ],
                    '3': [
                        {'name': 'slot_1', 'x': 29.1, 'y': 41.2, 'scale': 0.5},
                        {'name': 'slot_2', 'x': 55.5, 'y': 44.4, 'scale': 0.7},
                        {'name': 'slot_3', 'x': 70.4, 'y': 41.6, 'scale': 0.5},
                    ],
                    '4': [
                        {'name': 'slot_1', 'x': 42.6, 'y': 38.4, 'scale': 0.4},
                        {'name': 'slot_2', 'x': 61.3, 'y': 38.5, 'scale': 0.4},
                        {'name': 'slot_3', 'x': 42.6, 'y': 53.6, 'scale': 0.4},
                        {'name': 'slot_4', 'x': 61.3, 'y': 53.5, 'scale': 0.4},
                    ],
                },
            },
            'steal': {
                'slot_layouts': {
                    'item1': {'name': 'item1', 'x': 14.5, 'y': 44.8, 'scale': 0.4},
                    'item2': {'name': 'item2', 'x': 27.4, 'y': 42.5, 'scale': 0.4},
                    'item3': {'name': 'item3', 'x': 30.8, 'y': 79.2, 'scale': 0.4},
                    'item4': {'name': 'item4', 'x': 39.5, 'y': 41.0, 'scale': 0.3},
                    'item5': {'name': 'item5', 'x': 90.7, 'y': 52.1, 'scale': 0.3},
                    'item6': {'name': 'item6', 'x': 88.2, 'y': 27.2, 'scale': 0.2},
                    'item7': {'name': 'item7', 'x': 82.0, 'y': 39.8, 'scale': 0.2},
                },
                'avatar': {
                    'name': 'avatar',
                    'x': 63.3,
                    'y': 57.7,
                    'width': 28.4,
                    'aspect_ratio': 11 / 12,
                },
            },
        }

        save_resp = admin_client.post('/admin/classic/layout-lab/save', json=payload)
        save_json = save_resp.get_json(silent=True) or {}
        check('OLL-03: layout lab save endpoint returns 200', save_resp.status_code == 200, f'status={save_resp.status_code}')
        check(
            'OLL-04: saved payload returns normalized shared layout data',
            save_json.get('ok') is True
            and save_json.get('overlay_layouts', {}).get('treasure', {}).get('slot_layouts', {}).get('3', [{}])[1].get('x') == 55.5
            and save_json.get('overlay_layouts', {}).get('steal', {}).get('avatar', {}).get('width') == 28.4,
        )

        overlay_json_path = os.path.join(flask_app.instance_path, 'overlay_layouts.json')
        check('OLL-05: save writes overlay_layouts.json to instance path', os.path.exists(overlay_json_path), overlay_json_path)
        with open(overlay_json_path, 'r', encoding='utf-8') as handle:
            saved_file = json.load(handle)
        check(
            'OLL-06: persisted JSON file stores updated treasure and steal values',
            saved_file['treasure']['slot_layouts']['3'][1]['x'] == 55.5
            and saved_file['steal']['avatar']['width'] == 28.4,
        )

        loaded = load_overlay_layouts()
        check(
            'OLL-07: layout service reloads saved values from shared source',
            loaded['treasure']['slot_layouts']['3'][1]['x'] == 55.5
            and loaded['steal']['avatar']['x'] == 63.3,
        )

        assets = build_overlay_asset_payload()
        check(
            'OLL-07b: shared asset payload uses canonical filenames without duplicate extensions',
            assets['treasure']['containers']['closed']['4'].endswith('chest_04_closed.png')
            and assets['steal']['containers']['closed']['4'].endswith('bag_04_closed.png')
            and '.png.png' not in assets['treasure']['containers']['closed']['4']
            and '.png.png' not in assets['steal']['containers']['closed']['4'],
        )

        runtime_resp = player_client.get(f'/classic/game/{session.id}')
        runtime_html = runtime_resp.get_data(as_text=True)
        check('OLL-08: runtime game shell still renders after layout save', runtime_resp.status_code == 200, f'status={runtime_resp.status_code}')
        check(
            'OLL-09: runtime game shell includes saved layouts and shared asset payload without duplicate extensions',
            ('"x": 55.5' in runtime_html or '"x":55.5' in runtime_html)
            and 'OVERLAY_ASSETS' in runtime_html
            and '.png.png' not in runtime_html,
        )

    print(f'\nOverlay layout lab checks: {passed} passed, {failed} failed')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    run_tests()
