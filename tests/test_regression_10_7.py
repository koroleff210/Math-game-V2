"""
test_regression_10_7.py
========================

Regression test for issue 10.7 — restricted HTTP routing.

Confirms that an unauthorized user (not a member of the restricted group) is
denied at the HTTP route level (before any rendering or Socket.IO interaction)
when accessing a session restricted to a specific group.

Tests:
  R10_7_01: Non-member GET /classic/lobby/<id> (status=waiting) -> 302 to dashboard
  R10_7_02: Non-member GET /classic/game/<id>  (status=active)  -> 302 to dashboard
  R10_7_03: Authorized member GET /classic/lobby/<id> (status=waiting) -> 200
  R10_7_04: Authorized member GET /classic/game/<id>  (status=active)  -> 200
  R10_7_05: Non-member GET /classic/lobby/<id> (status=active)  -> 302 to dashboard
             (lobby must deny before it would normally redirect to game)
  R10_7_06: Open session (no group) - any logged-in player can access lobby

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_10_7.py

Expected: all tests pass, final line "ALL R10_7 TESTS PASSED."
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import ClassicRoundConfig, PlayerWallet
from app.models.groups import PlayerGroup, player_group_members

# Use in-memory SQLite for isolation
class TestConfig:
    TESTING = True
    SECRET_KEY = 'test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    LOGIN_DISABLED = False

flask_app = create_app(TestConfig)

# ─────────────────────────────────────────────────────────────────────────────
# Test runner
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Fixture setup
# ─────────────────────────────────────────────────────────────────────────────

_MEMBER_NAME    = '__r107_member__'
_NONMEMBER_NAME = '__r107_nonmember__'
_GROUP_NAME     = '__r107_group__'


def _setup():
    """Create two players, a group (member is in it, non-member is not),
    a restricted waiting session, and an active session."""
    with flask_app.app_context():
        db.create_all()

        # Clean any leftover fixture rows
        for name in (_MEMBER_NAME, _NONMEMBER_NAME):
            p = Player.query.filter_by(username=name).first()
            if p:
                db.session.delete(p)
        g = PlayerGroup.query.filter_by(name=_GROUP_NAME).first()
        if g:
            db.session.delete(g)
        db.session.flush()

        # Players
        member = Player(username=_MEMBER_NAME)
        member.set_password('pw')
        non_member = Player(username=_NONMEMBER_NAME)
        non_member.set_password('pw')
        db.session.add_all([member, non_member])
        db.session.flush()

        # Group — only member is in it
        group = PlayerGroup(name=_GROUP_NAME)
        db.session.add(group)
        db.session.flush()
        group.members.append(member)

        # Restricted waiting session
        sess_waiting = GameSession(mode='classic', status='waiting', group_id=group.id)
        db.session.add(sess_waiting)
        db.session.flush()
        rnd_waiting = GameRound(session_id=sess_waiting.id, round_number=1)
        db.session.add(rnd_waiting)
        db.session.flush()
        cfg_waiting = _default_config(rnd_waiting.id)
        db.session.add(cfg_waiting)

        # Restricted active session
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        sess_active = GameSession(mode='classic', status='active',
                                  group_id=group.id, started_at=now)
        db.session.add(sess_active)
        db.session.flush()
        rnd_active = GameRound(session_id=sess_active.id, round_number=1,
                               started_at=now)
        db.session.add(rnd_active)
        db.session.flush()
        cfg_active = _default_config(rnd_active.id)
        db.session.add(cfg_active)

        # Open session (no group restriction)
        sess_open = GameSession(mode='classic', status='waiting', group_id=None)
        db.session.add(sess_open)
        db.session.flush()
        rnd_open = GameRound(session_id=sess_open.id, round_number=1)
        db.session.add(rnd_open)
        db.session.flush()
        cfg_open = _default_config(rnd_open.id)
        db.session.add(cfg_open)

        db.session.commit()

        return {
            'member_id':    member.id,
            'nonmember_id': non_member.id,
            'group_id':     group.id,
            'waiting_id':   sess_waiting.id,
            'active_id':    sess_active.id,
            'open_id':      sess_open.id,
        }


def _default_config(round_id):
    return ClassicRoundConfig(
        round_id=round_id,
        mine_reward=20,
        treasure_search_reward=5,
        attempts_per_problem=1,
        wrong_answer_penalty=0,
        bonus_timer_duration=0,
        bonus_timer_gold=0,
        first_solver_count=0,
        first_solver_multiplier=1,
        treasure_search_max_reward=5,
        gem_milestone_count=0,
        gem_streak_count=0,
        gem_treasure_chance=0.0,
        steal_percent=0.1,
        steal_min_cap=10,
        steal_max_cap=50,
        steal_fallback_gold=5,
        steal_chest_count=2,
        steal_winning_chest_count=1,
        shield_duration=60,
        treasure_steal_token_chance=0.0,
    )


def _login(client, player_id):
    """Log in as the player with the given id using Flask-Login's test utilities."""
    with flask_app.app_context():
        player = db.session.get(Player, player_id)
        username = player.username

    resp = client.post('/login', data={
        'username': username,
        'password': 'pw',
    }, follow_redirects=False)
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def run_tests():
    print('\n=== R10_7: Restricted HTTP routing ===\n')

    ids = _setup()

    client = flask_app.test_client()

    # ── Non-member tests ──────────────────────────────────────────────────────

    # Login as non-member
    _login(client, ids['nonmember_id'])

    r = client.get(f'/classic/lobby/{ids["waiting_id"]}', follow_redirects=False)
    check(
        'R10_7_01: non-member lobby (waiting) -> redirect (not 200)',
        r.status_code == 302,
        detail=f'status={r.status_code}',
    )
    check(
        'R10_7_01b: non-member lobby redirect target is dashboard (not game)',
        '/player/dashboard' in (r.headers.get('Location') or ''),
        detail=f'Location={r.headers.get("Location")}',
    )

    r = client.get(f'/classic/game/{ids["active_id"]}', follow_redirects=False)
    check(
        'R10_7_02: non-member game (active) -> redirect (not 200)',
        r.status_code == 302,
        detail=f'status={r.status_code}',
    )
    check(
        'R10_7_02b: non-member game redirect target is dashboard (not lobby/game)',
        '/player/dashboard' in (r.headers.get('Location') or ''),
        detail=f'Location={r.headers.get("Location")}',
    )

    r = client.get(f'/classic/lobby/{ids["active_id"]}', follow_redirects=False)
    check(
        'R10_7_05: non-member lobby (active) -> redirect (denied before game redirect)',
        r.status_code == 302,
        detail=f'status={r.status_code}',
    )
    check(
        'R10_7_05b: lobby (active) redirect target is dashboard, not /classic/game',
        '/player/dashboard' in (r.headers.get('Location') or ''),
        detail=f'Location={r.headers.get("Location")}',
    )

    # ── Authorized member tests ───────────────────────────────────────────────

    # Re-login as member (new client to start clean session)
    client2 = flask_app.test_client()
    _login(client2, ids['member_id'])

    r = client2.get(f'/classic/lobby/{ids["waiting_id"]}', follow_redirects=False)
    check(
        'R10_7_03: authorized member lobby (waiting) -> 200',
        r.status_code == 200,
        detail=f'status={r.status_code}',
    )

    r = client2.get(f'/classic/game/{ids["active_id"]}', follow_redirects=False)
    check(
        'R10_7_04: authorized member game (active) -> 200',
        r.status_code == 200,
        detail=f'status={r.status_code}',
    )

    # ── Open session tests ────────────────────────────────────────────────────

    r = client.get(f'/classic/lobby/{ids["open_id"]}', follow_redirects=False)
    check(
        'R10_7_06: open session (no group) - non-member can access lobby -> 200',
        r.status_code == 200,
        detail=f'status={r.status_code}',
    )

    print(f'\n  Passed: {passed}  Failed: {failed}')
    if failed == 0:
        print('\nALL R10_7 TESTS PASSED.\n')
        return True
    else:
        print(f'\n{failed} R10_7 TEST(S) FAILED.\n')
        return False


if __name__ == '__main__':
    ok = run_tests()
    sys.exit(0 if ok else 1)
