"""
test_regression_d3.py
=====================

Regression tests for session-scoped participant snapshot (formerly D3 --
round-start RoundPlayerModifiers snapshot, now retired).

Coverage:
  D3-01: ensure_all_session_participant_snapshots creates rows for all enrolled players
  D3-02: only enrolled players receive snapshot rows (non-enrolled player excluded)
  D3-03: effective values match current upgrade catalog levels
  D3-04: players with no purchased upgrades receive baseline defaults
  D3-05: calling ensure_all twice for the same session is idempotent (no duplicates)
  D3-06: buying an upgrade after session snapshot does NOT mutate existing snapshot row
  D3-07: a new session's snapshot picks up the upgrade purchased between sessions
  D3-08: smoke -- start_round HTTP route creates SessionParticipantSnapshot rows in DB
  D3-09: smoke -- next_round HTTP route preserves SessionParticipantSnapshot rows

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_d3.py

Expected: all tests pass, final line "ALL D3 TESTS PASSED."
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import ClassicRoundConfig, PlayerWallet
from app.models.progression import (
    PlayerProgression, PlayerUpgrade, SessionParticipantSnapshot,
)
from app.services.progression import (
    get_or_create_player_progression,
    award_diamonds_to_player,
    purchase_upgrade,
    ensure_session_participant_snapshot,
    ensure_all_session_participant_snapshots,
    get_session_player_modifiers,
)
from app.services.upgrade_catalog import UPGRADE_CATALOG


# -- App config ----------------------------------------------------------------

class _TestConfig:
    TESTING                        = True
    SQLALCHEMY_DATABASE_URI        = 'sqlite:///:memory:'
    SECRET_KEY                     = 'd3-test-secret'
    WTF_CSRF_ENABLED               = False
    SOCKETIO_ASYNC_MODE            = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED                 = False


flask_app = create_app(_TestConfig)

# -- Test runner ---------------------------------------------------------------

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


# -- Fixture helpers -----------------------------------------------------------

_ADMIN_USER   = '__d3_admin__'
_PLAYER_A     = '__d3_player_a__'
_PLAYER_B     = '__d3_player_b__'
_PLAYER_C     = '__d3_player_c__'     # never enrolled -- excluded from snapshots
_IDS = {}


def _make_player(username, is_admin=False, password='pass1234'):
    p = Player(username=username, is_admin=is_admin)
    p.set_password(password)
    db.session.add(p)
    db.session.flush()
    return p


def _make_session_with_round(session_id_hint=None):
    """Create a GameSession, a GameRound, and return (game_session, game_round)."""
    gs = GameSession(mode='classic', status='waiting')
    db.session.add(gs)
    db.session.flush()
    gr = GameRound(session_id=gs.id, round_number=1, started_at=None)
    db.session.add(gr)
    db.session.flush()
    return gs, gr


def _make_classic_config(round_id):
    """Add a minimal ClassicRoundConfig so next_round can copy it."""
    cfg = ClassicRoundConfig(
        round_id=round_id,
        mine_reward=10,
        treasure_search_reward=20,
        attempts_per_problem=3,
        wrong_answer_penalty=0,
        bonus_timer_duration=30,
        bonus_timer_gold=5,
        first_solver_count=3,
        first_solver_multiplier=2.0,
        treasure_search_max_reward=40,
        gem_milestone_count=5,
        gem_streak_count=3,
        gem_treasure_chance=0.1,
        steal_percent=0.1,
        steal_min_cap=5,
        steal_max_cap=20,
        steal_fallback_gold=5,
        steal_chest_count=3,
        steal_winning_chest_count=1,
        shield_duration=30,
        treasure_steal_token_chance=0.1,
    )
    db.session.add(cfg)
    db.session.flush()
    return cfg


def _enroll(session_id, player_id):
    rp = RoundPlayer(session_id=session_id, player_id=player_id)
    db.session.add(rp)
    db.session.flush()
    return rp


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin   = _make_player(_ADMIN_USER,  is_admin=True)
        p_a     = _make_player(_PLAYER_A,    is_admin=False)
        p_b     = _make_player(_PLAYER_B,    is_admin=False)
        p_c     = _make_player(_PLAYER_C,    is_admin=False)
        db.session.commit()
        _IDS['admin_id']    = admin.id
        _IDS['player_a_id'] = p_a.id
        _IDS['player_b_id'] = p_b.id
        _IDS['player_c_id'] = p_c.id


# -- Service-layer tests (D3-01 ... D3-07) ------------------------------------

def test_service():
    with flask_app.app_context():
        pid_a   = _IDS['player_a_id']
        pid_b   = _IDS['player_b_id']
        pid_c   = _IDS['player_c_id']
        admin_id = _IDS['admin_id']

        # -- Create session with two enrolled players --------------------------
        gs, gr = _make_session_with_round()
        _enroll(gs.id, pid_a)
        _enroll(gs.id, pid_b)
        # player_c is NOT enrolled
        db.session.commit()

        # -- D3-01: ensure_all creates rows for all enrolled players -----------
        created = ensure_all_session_participant_snapshots(gs.id)
        db.session.commit()

        rows = SessionParticipantSnapshot.query.filter_by(session_id=gs.id).all()
        check('D3-01: snapshot creates one row per enrolled player',
              len(rows) == 2,
              f'got {len(rows)} rows')

        # -- D3-02: only enrolled players receive snapshot rows ----------------
        player_ids_in_snapshot = {r.player_id for r in rows}
        check('D3-02: non-enrolled player excluded from snapshot',
              pid_c not in player_ids_in_snapshot,
              f'found player_c in {player_ids_in_snapshot}')
        check('D3-02: both enrolled players have snapshot rows',
              {pid_a, pid_b} == player_ids_in_snapshot)

        # -- D3-04: baseline defaults for players with no upgrades -------------
        row_a = SessionParticipantSnapshot.query.filter_by(
            session_id=gs.id, player_id=pid_a
        ).first()
        check('D3-04: effective_steal_token_cap baseline = 1',
              row_a.effective_steal_token_cap == UPGRADE_CATALOG['steal_token_cap'].effects[0],
              f'got {row_a.effective_steal_token_cap}')
        check('D3-04: effective_mine_bonus baseline = 0',
              row_a.effective_mine_bonus == UPGRADE_CATALOG['mine_bonus'].effects[0],
              f'got {row_a.effective_mine_bonus}')
        check('D3-04: effective_treasure_bonus baseline = 0',
              row_a.effective_treasure_bonus == UPGRADE_CATALOG['treasure_bonus'].effects[0],
              f'got {row_a.effective_treasure_bonus}')
        check('D3-04: effective_shield_bonus_pct baseline = 0.0',
              row_a.effective_shield_bonus_pct == UPGRADE_CATALOG['shield_bonus_pct'].effects[0],
              f'got {row_a.effective_shield_bonus_pct}')

        # -- D3-03: values match current upgrade levels ------------------------
        # Give player_b some upgrades before their first snapshot (use a fresh session)
        gs2, gr2 = _make_session_with_round()
        _enroll(gs2.id, pid_b)
        db.session.commit()

        # Award diamonds and purchase upgrades for player_b first
        award_diamonds_to_player(
            player_id=pid_b, amount=200, reason='d3_test', admin_player_id=admin_id
        )
        db.session.commit()

        # Buy: steal_token_cap level 0->1, mine_bonus level 0->1->2
        purchase_upgrade(player_id=pid_b, upgrade_type='steal_token_cap')
        db.session.commit()
        purchase_upgrade(player_id=pid_b, upgrade_type='mine_bonus')
        db.session.commit()
        purchase_upgrade(player_id=pid_b, upgrade_type='mine_bonus')
        db.session.commit()

        ensure_all_session_participant_snapshots(gs2.id)
        db.session.commit()

        row_b2 = SessionParticipantSnapshot.query.filter_by(
            session_id=gs2.id, player_id=pid_b
        ).first()

        expected_steal_cap = UPGRADE_CATALOG['steal_token_cap'].effects[1]   # level 1 -> 2
        expected_mine      = UPGRADE_CATALOG['mine_bonus'].effects[2]         # level 2 -> 10
        check('D3-03: effective_steal_token_cap matches level-1 catalog value',
              row_b2.effective_steal_token_cap == expected_steal_cap,
              f'got {row_b2.effective_steal_token_cap}, expected {expected_steal_cap}')
        check('D3-03: effective_mine_bonus matches level-2 catalog value',
              row_b2.effective_mine_bonus == expected_mine,
              f'got {row_b2.effective_mine_bonus}, expected {expected_mine}')
        check('D3-03: effective_treasure_bonus baseline for player_b',
              row_b2.effective_treasure_bonus == 0)
        check('D3-03: effective_shield_bonus_pct baseline for player_b',
              row_b2.effective_shield_bonus_pct == 0.0)

        # -- D3-05: idempotent -- calling ensure_all twice yields no duplicates
        created_again = ensure_all_session_participant_snapshots(gs2.id)
        db.session.commit()
        check('D3-05: second ensure_all call returns empty list (all skipped)',
              len(created_again) == 0,
              f'got {len(created_again)} newly created')
        count_after = SessionParticipantSnapshot.query.filter_by(session_id=gs2.id).count()
        check('D3-05: row count unchanged after repeated ensure_all call',
              count_after == 1,
              f'got {count_after}')

        # -- D3-06: buying upgrade after snapshot does not mutate existing row -
        # player_b already has snapshot for gs2; buy treasure_bonus now
        purchase_upgrade(player_id=pid_b, upgrade_type='treasure_bonus')
        db.session.commit()

        row_b2_reloaded = SessionParticipantSnapshot.query.filter_by(
            session_id=gs2.id, player_id=pid_b
        ).first()
        check('D3-06: post-snapshot purchase leaves effective_treasure_bonus frozen at 0',
              row_b2_reloaded.effective_treasure_bonus == 0,
              f'got {row_b2_reloaded.effective_treasure_bonus}')

        # -- D3-07: new session's snapshot picks up the newly purchased value --
        gs3, gr3 = _make_session_with_round()
        _enroll(gs3.id, pid_b)
        db.session.commit()

        ensure_all_session_participant_snapshots(gs3.id)
        db.session.commit()

        row_b3 = SessionParticipantSnapshot.query.filter_by(
            session_id=gs3.id, player_id=pid_b
        ).first()
        expected_treasure = UPGRADE_CATALOG['treasure_bonus'].effects[1]   # level 1 -> 5
        check('D3-07: new session snapshot includes upgrade purchased between sessions',
              row_b3.effective_treasure_bonus == expected_treasure,
              f'got {row_b3.effective_treasure_bonus}, expected {expected_treasure}')


# -- HTTP route smoke tests (D3-08, D3-09) -------------------------------------
#
# These tests drive the actual admin HTTP routes:
#   POST /admin/classic/<id>/start      -> D3-08
#   POST /admin/classic/<id>/next_round -> D3-09
#
# They confirm that the route-level integration calls
# ensure_all_session_participant_snapshots and that
# SessionParticipantSnapshot rows appear in the database.

def test_http_round_start():
    with flask_app.test_client() as client:
        _login(client, _ADMIN_USER)

        with flask_app.app_context():
            pid_a = _IDS['player_a_id']

            # Create a session in 'waiting' with a GameRound (not yet started)
            gs = GameSession(mode='classic', status='waiting')
            db.session.add(gs)
            db.session.flush()
            gr = GameRound(session_id=gs.id, round_number=1, started_at=None)
            db.session.add(gr)
            db.session.flush()
            _make_classic_config(gr.id)
            _enroll(gs.id, pid_a)
            db.session.commit()
            sid = gs.id

        # D3-08: POST /admin/classic/<id>/start triggers snapshot
        r = client.post(
            f'/admin/classic/{sid}/start',
            follow_redirects=True,
        )
        check('D3-08: start_round route returns 200', r.status_code == 200,
              f'got {r.status_code}')

        with flask_app.app_context():
            rows = SessionParticipantSnapshot.query.filter_by(session_id=sid).all()
            check('D3-08: start_round creates SessionParticipantSnapshot rows',
                  len(rows) == 1,
                  f'got {len(rows)} rows')
            check('D3-08: snapshot row belongs to enrolled player',
                  rows[0].player_id == _IDS['player_a_id'])

        # D3-09: POST /admin/classic/<id>/next_round preserves snapshot
        # First, end the round so the session is back to 'waiting'
        with flask_app.app_context():
            from app.models.game import GameRound as GR
            gr_db = GR.query.filter_by(session_id=sid).first()
            gr_db.ended_at = datetime.now(timezone.utc)
            gs_db = db.session.get(GameSession, sid)
            gs_db.status = 'waiting'
            db.session.commit()

        r = client.post(
            f'/admin/classic/{sid}/next_round',
            data={'carry_over_gold': 'on', 'carry_over_gems': 'on'},
            follow_redirects=True,
        )
        check('D3-09: next_round route returns 200', r.status_code == 200,
              f'got {r.status_code}')

        with flask_app.app_context():
            # Session-scoped snapshots should still be there (same session)
            snap_rows = SessionParticipantSnapshot.query.filter_by(session_id=sid).all()
            check('D3-09: SessionParticipantSnapshot rows preserved across rounds',
                  len(snap_rows) == 1,
                  f'got {len(snap_rows)} rows')


# -- Main ---------------------------------------------------------------------

if __name__ == '__main__':
    print('\nD3 Session Participant Snapshot - Tests')
    print('-' * 60)

    _setup_db()
    test_service()
    test_http_round_start()

    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL D3 TESTS PASSED.')
    else:
        print('SOME D3 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
