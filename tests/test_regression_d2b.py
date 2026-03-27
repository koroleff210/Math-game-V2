"""
test_regression_d2b.py
======================

Regression tests for D2b — Catalog value corrections + Blacksmith session gating.

Coverage:
  D2b-01: steal_token_cap has max_level=2 and effects=[1, 2, 3]
  D2b-02: shield_bonus_pct has effects=[0.0, 0.10, 0.15, 0.20]
  D2b-03: treasure_bonus has effects=[0, 5, 10, 15]
  D2b-04: GET /player/blacksmith blocked when player is in an active session
  D2b-05: GET /player/blacksmith blocked when player is in a waiting session
  D2b-06: POST /player/blacksmith/buy blocked when player is in an active session
  D2b-07: GET /player/blacksmith allowed when player has no session enrollment
  D2b-08: GET /player/blacksmith allowed when player's only session is finished

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_d2b.py

Expected: all tests pass, final line "ALL D2b TESTS PASSED."
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.game import GameSession, RoundPlayer
from app.services.upgrade_catalog import UPGRADE_CATALOG


# ── App config ─────────────────────────────────────────────────────────────────

class _TestConfig:
    TESTING                        = True
    SQLALCHEMY_DATABASE_URI        = 'sqlite:///:memory:'
    SECRET_KEY                     = 'd2b-test-secret'
    WTF_CSRF_ENABLED               = False
    SOCKETIO_ASYNC_MODE            = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED                 = False


flask_app = create_app(_TestConfig)

# ── Test runner ────────────────────────────────────────────────────────────────

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


# ── Fixture helpers ────────────────────────────────────────────────────────────

_PLAYER_USER = '__d2b_player__'
_IDS = {}


def _make_player(username, is_admin=False, password='pass1234'):
    p = Player(username=username, is_admin=is_admin)
    p.set_password(password)
    db.session.add(p)
    db.session.flush()
    return p


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        player = _make_player(_PLAYER_USER, is_admin=False)
        db.session.commit()
        _IDS['player_id'] = player.id


def _login(client, username, password='pass1234'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


# ── Catalog value tests (D2b-01 … D2b-03) ─────────────────────────────────────

def test_catalog_values():
    # D2b-01: steal_token_cap — max_level=2, effects=[1, 2, 3]
    defn = UPGRADE_CATALOG['steal_token_cap']
    check('D2b-01: steal_token_cap max_level == 2',
          defn.max_level == 2,
          f'got {defn.max_level}')
    check('D2b-01: steal_token_cap effects == [1, 2, 3]',
          list(defn.effects) == [1, 2, 3],
          f'got {list(defn.effects)}')
    check('D2b-01: steal_token_cap costs == [5, 10]',
          list(defn.costs) == [5, 10],
          f'got {list(defn.costs)}')

    # D2b-02: shield_bonus_pct effects=[0.0, 0.10, 0.15, 0.20]
    defn = UPGRADE_CATALOG['shield_bonus_pct']
    check('D2b-02: shield_bonus_pct effects == [0.0, 0.10, 0.15, 0.20]',
          list(defn.effects) == [0.0, 0.10, 0.15, 0.20],
          f'got {list(defn.effects)}')

    # D2b-03: treasure_bonus effects=[0, 5, 10, 15]
    defn = UPGRADE_CATALOG['treasure_bonus']
    check('D2b-03: treasure_bonus effects == [0, 5, 10, 15]',
          list(defn.effects) == [0, 5, 10, 15],
          f'got {list(defn.effects)}')


# ── Session gating tests (D2b-04 … D2b-08) ────────────────────────────────────

def test_session_gating():
    with flask_app.test_client() as client:
        _login(client, _PLAYER_USER)

        # D2b-04: blocked when enrolled in an active session
        with flask_app.app_context():
            session_active = GameSession(mode='classic', status='active')
            db.session.add(session_active)
            db.session.flush()
            rp = RoundPlayer(session_id=session_active.id, player_id=_IDS['player_id'])
            db.session.add(rp)
            db.session.commit()
            active_session_id = session_active.id

        r = client.get('/player/blacksmith', follow_redirects=False)
        check('D2b-04: GET blacksmith redirects when in active session',
              r.status_code in (301, 302),
              f'got {r.status_code}')

        # D2b-05: blocked when enrolled in a waiting session (not started)
        with flask_app.app_context():
            # Change the existing session to waiting status
            s = db.session.get(GameSession, active_session_id)
            s.status = 'waiting'
            db.session.commit()

        r = client.get('/player/blacksmith', follow_redirects=False)
        check('D2b-05: GET blacksmith redirects when in waiting session',
              r.status_code in (301, 302),
              f'got {r.status_code}')

        # D2b-06: POST blacksmith/buy blocked during active session
        with flask_app.app_context():
            s = db.session.get(GameSession, active_session_id)
            s.status = 'active'
            db.session.commit()

        r = client.post('/player/blacksmith/buy',
                        data={'upgrade_type': 'mine_bonus'},
                        follow_redirects=False)
        check('D2b-06: POST blacksmith/buy redirects when in active session',
              r.status_code in (301, 302),
              f'got {r.status_code}')

        # D2b-07: allowed when player has no session enrollment at all
        with flask_app.app_context():
            # Remove all RoundPlayer rows for this player
            RoundPlayer.query.filter_by(player_id=_IDS['player_id']).delete()
            db.session.commit()

        r = client.get('/player/blacksmith')
        check('D2b-07: GET blacksmith returns 200 when no session enrollment',
              r.status_code == 200,
              f'got {r.status_code}')

        # D2b-08: allowed when player's only session is finished
        with flask_app.app_context():
            session_finished = GameSession(mode='classic', status='finished')
            db.session.add(session_finished)
            db.session.flush()
            rp = RoundPlayer(session_id=session_finished.id, player_id=_IDS['player_id'])
            db.session.add(rp)
            db.session.commit()

        r = client.get('/player/blacksmith')
        check('D2b-08: GET blacksmith returns 200 when only session is finished',
              r.status_code == 200,
              f'got {r.status_code}')


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('\nD2b Catalog Corrections + Session Gating — Tests')
    print('─' * 60)

    _setup_db()
    test_catalog_values()
    test_session_gating()

    print('─' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL D2b TESTS PASSED.')
    else:
        print('SOME D2b TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
