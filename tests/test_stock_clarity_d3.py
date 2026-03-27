"""
test_stock_clarity_d3.py
========================

Focused regression tests for Step D3: stock clarity display.

Confirms:
  1. Admin store page shows "Session Stock" header and sold counts
  2. Limited items show total, sold, and remaining
  3. Unlimited items display clearly as "Unlimited"
  4. Sold count reflects actual session purchases
  5. No purchase logic changes (stock check still works)
  6. Explanatory note is present on the page

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_stock_clarity_d3.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession
from app.models.classic import StoreItem, PlayerInventory, PlayerWallet

flask_app = create_app()
flask_app.config['WTF_CSRF_ENABLED'] = False
flask_app.config['TESTING'] = True

SET_NAME = '__test_d3__'
_ADMIN   = '__d3_admin__'
_PLAYER  = '__d3_player__'

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


def _now():
    return datetime.now(timezone.utc)


def _clean():
    """Remove all test artefacts from the DB."""
    with db.session.no_autoflush:
        ps = ProblemSet.query.filter_by(name=SET_NAME).first()
        if ps:
            for gs in GameSession.query.filter_by(problem_set_id=ps.id).all():
                PlayerInventory.query.filter_by(session_id=gs.id).delete()
                PlayerWallet.query.filter_by(session_id=gs.id).delete()
                StoreItem.query.filter_by(session_id=gs.id).delete()
                db.session.delete(gs)
            db.session.flush()
            for prob in list(ps.problems):
                ps.problems.remove(prob)
            db.session.flush()
            for prob in Problem.query.filter(Problem.title.like('D3 P%')).all():
                db.session.execute(db.text('DELETE FROM player_problem_state WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.execute(db.text('DELETE FROM problem_solver_count WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.delete(prob)
            db.session.delete(ps)
        db.session.flush()
        for uname in (_ADMIN, _PLAYER):
            p = Player.query.filter_by(username=uname).first()
            if p:
                db.session.delete(p)
    db.session.commit()


def _login(client):
    client.post('/login', data={'username': _ADMIN, 'password': 'x'}, follow_redirects=True)


with flask_app.app_context():
    _clean()

    # Create test users
    admin = Player(username=_ADMIN, is_admin=True)
    admin.set_password('x')
    db.session.add(admin)

    player = Player(username=_PLAYER, is_admin=False)
    player.set_password('x')
    db.session.add(player)
    db.session.flush()

    # Create problem set + session
    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='D3_topic')
        db.session.add(topic)
        db.session.flush()

    ps = ProblemSet(name=SET_NAME)
    db.session.add(ps)
    db.session.flush()
    prob = Problem(title='D3 P1', prompt_text='1+1?', answer_text='2', topic_id=topic.id)
    db.session.add(prob)
    db.session.flush()
    ps.problems.append(prob)
    db.session.flush()

    gs = GameSession(mode='classic', status='active', problem_set_id=ps.id)
    db.session.add(gs)
    db.session.flush()
    sid = gs.id

    # Create store items
    item_limited = StoreItem(
        session_id=sid, name='Limited Sword', description='A sharp sword',
        cost=10, currency='gold', bonus_type='x2_mine', session_stock=5,
    )
    item_unlimited = StoreItem(
        session_id=sid, name='Magic Potion', description='Heals all',
        cost=5, currency='gold', bonus_type='x2_mine', session_stock=-1,
    )
    item_zero_sold = StoreItem(
        session_id=sid, name='Rare Shield', description='Very rare',
        cost=20, currency='gems', bonus_type='shield', session_stock=3,
    )
    db.session.add_all([item_limited, item_unlimited, item_zero_sold])
    db.session.flush()

    # Simulate some purchases for item_limited (3 of 5 sold)
    for i in range(3):
        inv = PlayerInventory(
            player_id=player.id, session_id=sid,
            item_id=item_limited.id, purchased_at=_now(),
        )
        db.session.add(inv)

    # Simulate 1 purchase for unlimited item
    inv_unlim = PlayerInventory(
        player_id=player.id, session_id=sid,
        item_id=item_unlimited.id, purchased_at=_now(),
    )
    db.session.add(inv_unlim)

    # item_zero_sold has 0 purchases
    db.session.commit()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 1: Admin store page structure and wording
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Store page structure & wording ──────────────────────────')

    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(f'/admin/classic/{sid}/store')
        html = resp.data.decode()

        check('D3-01: store page returns 200', resp.status_code == 200)

        # Column header
        check('D3-02: "Session Stock" column header present',
              'Session Stock' in html)

        # Sold column header
        check('D3-03: "Sold" column header present',
              '<th>Sold</th>' in html)

        # Explanatory note
        check('D3-04: stock explanation note present',
              'total number of purchases' in html.lower())

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 2: Limited item display
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Limited item display ────────────────────────────────────')

    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(f'/admin/classic/{sid}/store')
        html = resp.data.decode()

        # Limited Sword: session_stock=5, sold=3, remaining=2
        check('D3-05: limited item shows "5 total"',
              '5 total' in html)
        check('D3-06: limited item shows "2 remaining"',
              '2 remaining' in html)
        check('D3-07: limited item sold count is 3',
              '>3<' in html.replace(' ', ''),
              'sold count 3 not found in a cell')

        # Rare Shield: session_stock=3, sold=0, remaining=3
        check('D3-08: zero-sold item shows "3 total"',
              '3 total' in html)
        check('D3-09: zero-sold item shows "3 remaining"',
              '3 remaining' in html)

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 3: Unlimited item display
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Unlimited item display ──────────────────────────────────')

    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(f'/admin/classic/{sid}/store')
        html = resp.data.decode()

        check('D3-10: unlimited item shows "Unlimited"',
              'Unlimited' in html)
        # Unlimited item should NOT show "total" or "remaining"
        # (Unlimited entry won't have "unlimited total" text)
        check('D3-11: unlimited item does not show "total" in stock cell',
              'Unlimited' in html and '-1 total' not in html)

        # Sold count for unlimited item should be 1
        check('D3-12: unlimited item sold count shown',
              '>1<' in html.replace(' ', ''),
              'sold count 1 not found')

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 4: sold_counts data correctness
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Sold count data correctness ─────────────────────────────')

    # Add 2 more purchases for limited item (now 5 of 5 = sold out)
    for i in range(2):
        inv = PlayerInventory(
            player_id=player.id, session_id=sid,
            item_id=item_limited.id, purchased_at=_now(),
        )
        db.session.add(inv)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(f'/admin/classic/{sid}/store')
        html = resp.data.decode()

        check('D3-13: sold-out item shows "0 remaining"',
              '0 remaining' in html)
        check('D3-14: sold-out item sold count is 5',
              '>5<' in html.replace(' ', ''),
              'sold count 5 not found')

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 5: Purchase logic NOT changed (stock check still works)
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Purchase logic unchanged ────────────────────────────────')

    from app.modes.classic.store import purchase_item

    # Give player some gold
    wallet = PlayerWallet.query.filter_by(player_id=player.id, session_id=sid).first()
    if not wallet:
        wallet = PlayerWallet(player_id=player.id, session_id=sid, gold=1000, gems=100)
        db.session.add(wallet)
    else:
        wallet.gold = 1000
        wallet.gems = 100
    db.session.commit()

    # Limited item is sold out (5 of 5) — purchase should fail
    ok, msg, _ = purchase_item(player.id, sid, item_limited.id)
    check('D3-15: sold-out item purchase fails', not ok)
    check('D3-16: sold-out reason is "out of stock"',
          msg == 'out of stock', f'got: {msg}')

    # Unlimited item should still be purchasable
    ok2, msg2, _ = purchase_item(player.id, sid, item_unlimited.id)
    check('D3-17: unlimited item purchase succeeds', ok2, f'msg: {msg2}')

    # Rare Shield (session_stock=3, sold=0) should succeed
    ok3, msg3, _ = purchase_item(player.id, sid, item_zero_sold.id)
    check('D3-18: limited item with stock remaining succeeds', ok3, f'msg: {msg3}')

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 6: Add Item form label clarity
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Form label clarity ─────────────────────────────────────')

    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(f'/admin/classic/{sid}/store')
        html = resp.data.decode()

        check('D3-19: form label says "Session Stock"',
              'Session Stock' in html)

    # ══════════════════════════════════════════════════════════════════════
    _clean()

    print(f'\n{"=" * 60}')
    print(f'Step D3 stock clarity results: {passed} passed, {failed} failed')
    if failed:
        print('SOME TESTS FAILED.')
        sys.exit(1)
    else:
        print('ALL TESTS PASSED.')
        sys.exit(0)
