"""
test_regression_d1.py
=====================

Regression tests for D1 — Admin Diamonds award flow.

Coverage:
  D1-01: get_or_create_player_progression creates a row for a new player
  D1-02: get_or_create_player_progression returns existing row without duplicating
  D1-03: award_diamonds_to_player increments balance correctly
  D1-04: award_diamonds_to_player creates exactly one DiamondTransaction row
  D1-05: DiamondTransaction.balance_after matches PlayerProgression.diamonds_balance
  D1-06: Two sequential awards accumulate balance correctly
  D1-07: award_diamonds_to_player raises ValueError for amount=0
  D1-08: award_diamonds_to_player raises ValueError for negative amount
  D1-09: award_diamonds_to_player raises ValueError for empty reason
  D1-10: ValueError leaves no partial state (no row written)
  D1-11: GET /admin/diamonds/ requires authentication
  D1-12: GET /admin/diamonds/ requires admin role
  D1-13: POST /admin/diamonds/award requires authentication
  D1-14: POST /admin/diamonds/award requires admin role
  D1-15: GET /admin/diamonds/ returns 200 for admin
  D1-16: GET /admin/diamonds/ renders player list
  D1-17: POST /admin/diamonds/award awards correctly via HTTP
  D1-18: POST /admin/diamonds/award with amount=0 rejects without state change
  D1-19: POST /admin/diamonds/award with blank reason rejects without state change
  D1-20: POST /admin/diamonds/award targeting an admin player is rejected
  D1-21: Diamonds balance is separate from PlayerWallet gems/gold
  D1-22: DiamondTransaction.admin_player_id is set to the awarding admin
  D1-23: Repeated award does not duplicate PlayerProgression rows

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_d1.py

Expected: all tests pass, final line "ALL D1 TESTS PASSED."
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.game import GameSession
from app.models.classic import PlayerWallet
from app.models.progression import PlayerProgression, DiamondTransaction
from app.services.progression import get_or_create_player_progression, award_diamonds_to_player


# ── App config ─────────────────────────────────────────────────────────────────

class _TestConfig:
    TESTING                        = True
    SQLALCHEMY_DATABASE_URI        = 'sqlite:///:memory:'
    SECRET_KEY                     = 'd1-test-secret'
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

_ADMIN_USER  = '__d1_admin__'
_PLAYER_USER = '__d1_player__'
_ADMIN2_USER = '__d1_admin2__'   # second admin for admin-target rejection test
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
        admin  = _make_player(_ADMIN_USER,  is_admin=True)
        player = _make_player(_PLAYER_USER, is_admin=False)
        admin2 = _make_player(_ADMIN2_USER, is_admin=True)
        db.session.commit()
        _IDS['admin_id']   = admin.id
        _IDS['player_id']  = player.id
        _IDS['admin2_id']  = admin2.id


def _login(client, username, password='pass1234'):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


# ── Service-layer tests (D1-01 … D1-10) ───────────────────────────────────────

def test_service_layer():
    with flask_app.app_context():
        player_id = _IDS['player_id']
        admin_id  = _IDS['admin_id']

        # D1-01: creates row for new player
        prog = get_or_create_player_progression(player_id)
        db.session.commit()
        check('D1-01: get_or_create creates row for new player',
              prog is not None and prog.player_id == player_id and prog.diamonds_balance == 0)

        # D1-02: idempotent — no duplicate
        prog2 = get_or_create_player_progression(player_id)
        db.session.commit()
        count = PlayerProgression.query.filter_by(player_id=player_id).count()
        check('D1-02: get_or_create is idempotent (no duplicate row)',
              count == 1 and prog2.id == prog.id)

        # D1-03: award increments balance
        new_bal = award_diamonds_to_player(
            player_id=player_id, amount=10, reason='test_award', admin_player_id=admin_id
        )
        db.session.commit()
        prog_fresh = PlayerProgression.query.filter_by(player_id=player_id).first()
        check('D1-03: award increments balance to 10',
              new_bal == 10 and prog_fresh.diamonds_balance == 10)

        # D1-04: exactly one DiamondTransaction row after first award
        tx_count = DiamondTransaction.query.filter_by(player_id=player_id).count()
        check('D1-04: exactly one DiamondTransaction row created', tx_count == 1)

        # D1-05: balance_after matches progression
        tx = DiamondTransaction.query.filter_by(player_id=player_id).first()
        check('D1-05: DiamondTransaction.balance_after matches progression.diamonds_balance',
              tx.balance_after == prog_fresh.diamonds_balance)

        # D1-06: second award accumulates
        award_diamonds_to_player(
            player_id=player_id, amount=5, reason='second_award', admin_player_id=admin_id
        )
        db.session.commit()
        prog_updated = PlayerProgression.query.filter_by(player_id=player_id).first()
        tx_count2 = DiamondTransaction.query.filter_by(player_id=player_id).count()
        check('D1-06: two sequential awards accumulate balance to 15',
              prog_updated.diamonds_balance == 15 and tx_count2 == 2)

        # D1-07: amount=0 raises ValueError
        raised = False
        try:
            award_diamonds_to_player(player_id=player_id, amount=0, reason='bad', admin_player_id=admin_id)
        except ValueError:
            raised = True
        db.session.rollback()
        check('D1-07: amount=0 raises ValueError', raised)

        # D1-08: negative amount raises ValueError
        raised = False
        try:
            award_diamonds_to_player(player_id=player_id, amount=-5, reason='bad', admin_player_id=admin_id)
        except ValueError:
            raised = True
        db.session.rollback()
        check('D1-08: negative amount raises ValueError', raised)

        # D1-09: empty reason raises ValueError
        raised = False
        try:
            award_diamonds_to_player(player_id=player_id, amount=1, reason='   ', admin_player_id=admin_id)
        except ValueError:
            raised = True
        db.session.rollback()
        check('D1-09: blank reason raises ValueError', raised)

        # D1-10: no partial state after ValueError
        bal_before = PlayerProgression.query.filter_by(player_id=player_id).first().diamonds_balance
        tx_before  = DiamondTransaction.query.filter_by(player_id=player_id).count()
        try:
            award_diamonds_to_player(player_id=player_id, amount=0, reason='oops', admin_player_id=admin_id)
        except ValueError:
            db.session.rollback()
        bal_after = PlayerProgression.query.filter_by(player_id=player_id).first().diamonds_balance
        tx_after  = DiamondTransaction.query.filter_by(player_id=player_id).count()
        check('D1-10: ValueError leaves no partial state',
              bal_after == bal_before and tx_after == tx_before)

        # D1-22: admin_player_id recorded on transaction
        tx_latest = (
            DiamondTransaction.query
            .filter_by(player_id=player_id)
            .order_by(DiamondTransaction.id.desc())
            .first()
        )
        check('D1-22: DiamondTransaction.admin_player_id set correctly',
              tx_latest.admin_player_id == admin_id)

        # D1-23: no duplicate PlayerProgression rows after multiple awards
        tot = PlayerProgression.query.filter_by(player_id=player_id).count()
        check('D1-23: no duplicate PlayerProgression rows after multiple awards', tot == 1)


# ── HTTP route tests (D1-11 … D1-21) ──────────────────────────────────────────

def test_http_routes():
    with flask_app.test_client() as client:
        # D1-11: GET /admin/diamonds/ requires auth
        r = client.get('/admin/diamonds/', follow_redirects=False)
        check('D1-11: GET /admin/diamonds/ redirects unauthenticated',
              r.status_code in (301, 302))

        _login(client, _PLAYER_USER)

        # D1-12: GET /admin/diamonds/ requires admin
        r = client.get('/admin/diamonds/', follow_redirects=False)
        check('D1-12: GET /admin/diamonds/ rejects non-admin (403 or redirect)',
              r.status_code in (302, 403))

        # D1-13: POST /admin/diamonds/award requires auth — log out first
        client.get('/logout', follow_redirects=True)
        r = client.post('/admin/diamonds/award',
                        data={'player_id': _IDS['player_id'], 'amount': 1, 'reason': 'x'},
                        follow_redirects=False)
        check('D1-13: POST /admin/diamonds/award redirects unauthenticated',
              r.status_code in (301, 302))

        # D1-14: POST requires admin
        _login(client, _PLAYER_USER)
        r = client.post('/admin/diamonds/award',
                        data={'player_id': _IDS['player_id'], 'amount': 1, 'reason': 'x'},
                        follow_redirects=False)
        check('D1-14: POST /admin/diamonds/award rejects non-admin',
              r.status_code in (302, 403))
        client.get('/logout', follow_redirects=True)

        # Switch to admin
        _login(client, _ADMIN_USER)

        # D1-15: GET returns 200 for admin
        r = client.get('/admin/diamonds/')
        check('D1-15: GET /admin/diamonds/ returns 200 for admin', r.status_code == 200)

        # D1-16: renders player username in balances table
        check('D1-16: page renders player username',
              _PLAYER_USER.encode() in r.data)

        # D1-17: POST award via HTTP works
        with flask_app.app_context():
            bal_before = (
                PlayerProgression.query.filter_by(player_id=_IDS['player_id']).first()
                or type('obj', (), {'diamonds_balance': 0})()
            ).diamonds_balance

        r = client.post('/admin/diamonds/award',
                        data={
                            'player_id': _IDS['player_id'],
                            'amount': 7,
                            'reason': 'http_test',
                        },
                        follow_redirects=True)
        check('D1-17: POST award returns 200 after redirect', r.status_code == 200)

        with flask_app.app_context():
            prog = PlayerProgression.query.filter_by(player_id=_IDS['player_id']).first()
            check('D1-17: balance increased by 7',
                  prog is not None and prog.diamonds_balance == bal_before + 7)

        # D1-18: amount=0 rejected, no state change
        with flask_app.app_context():
            bal_snap = PlayerProgression.query.filter_by(player_id=_IDS['player_id']).first().diamonds_balance
            tx_snap  = DiamondTransaction.query.filter_by(player_id=_IDS['player_id']).count()

        client.post('/admin/diamonds/award',
                    data={'player_id': _IDS['player_id'], 'amount': 0, 'reason': 'bad'},
                    follow_redirects=True)

        with flask_app.app_context():
            bal_now = PlayerProgression.query.filter_by(player_id=_IDS['player_id']).first().diamonds_balance
            tx_now  = DiamondTransaction.query.filter_by(player_id=_IDS['player_id']).count()
        check('D1-18: amount=0 via HTTP leaves balance unchanged', bal_now == bal_snap)
        check('D1-18: amount=0 via HTTP writes no ledger row',     tx_now == tx_snap)

        # D1-19: blank reason rejected
        with flask_app.app_context():
            bal_snap2 = PlayerProgression.query.filter_by(player_id=_IDS['player_id']).first().diamonds_balance

        client.post('/admin/diamonds/award',
                    data={'player_id': _IDS['player_id'], 'amount': 3, 'reason': ''},
                    follow_redirects=True)

        with flask_app.app_context():
            bal_now2 = PlayerProgression.query.filter_by(player_id=_IDS['player_id']).first().diamonds_balance
        check('D1-19: blank reason via HTTP leaves balance unchanged', bal_now2 == bal_snap2)

        # D1-20: targeting an admin player is rejected
        with flask_app.app_context():
            admin2_id = _IDS['admin2_id']
            prog_before = PlayerProgression.query.filter_by(player_id=admin2_id).first()
            admin2_bal_before = prog_before.diamonds_balance if prog_before else 0

        client.post('/admin/diamonds/award',
                    data={'player_id': admin2_id, 'amount': 5, 'reason': 'should_fail'},
                    follow_redirects=True)

        with flask_app.app_context():
            prog_after = PlayerProgression.query.filter_by(player_id=admin2_id).first()
            admin2_bal_after = prog_after.diamonds_balance if prog_after else 0
        check('D1-20: awarding to admin player is rejected (balance unchanged)',
              admin2_bal_after == admin2_bal_before)

        # D1-21: Diamonds are separate from wallet gems/gold
        with flask_app.app_context():
            session = GameSession(mode='classic', status='waiting')
            db.session.add(session)
            db.session.flush()
            wallet = PlayerWallet(
                player_id=_IDS['player_id'],
                session_id=session.id,
                gold=100,
                gems=50,
            )
            db.session.add(wallet)
            db.session.commit()
            w = PlayerWallet.query.filter_by(player_id=_IDS['player_id']).first()
            prog = PlayerProgression.query.filter_by(player_id=_IDS['player_id']).first()
            check('D1-21: Diamonds balance separate from PlayerWallet gems/gold',
                  w.gold == 100 and w.gems == 50 and prog.diamonds_balance > 0)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('\nD1 Diamonds Admin Award \u2014 Tests')
    print('\u2500' * 60)

    _setup_db()
    test_service_layer()
    test_http_routes()

    print('\u2500' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL D1 TESTS PASSED.')
    else:
        print('SOME D1 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
