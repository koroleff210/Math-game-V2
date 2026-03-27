"""
test_d5_store_purchase_limits.py
================================

Focused regression tests for Step D5: Store Purchase Limits.

Confirms:
  1. session_stock blocks purchases when session-wide limit is reached
  2. per_player_limit blocks purchases when per-player limit is reached
  3. Both limits working together correctly
  4. -1 (unlimited) works for both fields
  5. No currency deducted on blocked purchases
  6. Admin forms save and edit both fields
  7. Admin store page displays both fields
  8. Existing capacity checks (SC max-1, token cap) still work
  9. System items remain hidden from store catalog
  10. store_items_for includes per_player_limit in output

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_d5_store_purchase_limits.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig, StoreItem, PlayerInventory,
    PlayerWallet, PlayerClassicState,
)
from app.modes.classic import store as classic_store

flask_app = create_app()
flask_app.config['WTF_CSRF_ENABLED'] = False
flask_app.config['TESTING'] = True

SET_NAME = '__test_d5__'
_ADMIN   = '__d5_admin__'
_PLAYER1 = '__d5_player1__'
_PLAYER2 = '__d5_player2__'

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
                PlayerClassicState.query.filter_by(session_id=gs.id).delete()
                ClassicRoundConfig.query.filter(
                    ClassicRoundConfig.round_id.in_(
                        db.session.query(GameRound.id).filter_by(session_id=gs.id)
                    )
                ).delete(synchronize_session=False)
                RoundPlayer.query.filter_by(session_id=gs.id).delete()
                GameRound.query.filter_by(session_id=gs.id).delete()
                db.session.delete(gs)
            db.session.flush()
            for prob in list(ps.problems):
                ps.problems.remove(prob)
            db.session.flush()
            for prob in Problem.query.filter(Problem.title.like('D5 P%')).all():
                db.session.execute(db.text('DELETE FROM player_problem_state WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.execute(db.text('DELETE FROM problem_solver_count WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.delete(prob)
            db.session.delete(ps)
        db.session.flush()
        for uname in (_ADMIN, _PLAYER1, _PLAYER2):
            p = Player.query.filter_by(username=uname).first()
            if p:
                db.session.delete(p)
    db.session.commit()


def _login(client):
    client.post('/login', data={'username': _ADMIN, 'password': 'x'}, follow_redirects=True)


def _setup():
    """Create admin, two players, session, round, config, wallets."""
    _clean()

    admin = Player(username=_ADMIN, is_admin=True)
    admin.set_password('x')
    db.session.add(admin)

    p1 = Player(username=_PLAYER1)
    p1.set_password('x')
    db.session.add(p1)

    p2 = Player(username=_PLAYER2)
    p2.set_password('x')
    db.session.add(p2)

    db.session.flush()

    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='D5 topic')
        db.session.add(topic)
        db.session.flush()

    prob = Problem(title='D5 P1', topic_id=topic.id,
                   difficulty=1, prompt_text='1+1', answer_text='2')
    db.session.add(prob)
    db.session.flush()

    ps = ProblemSet(name=SET_NAME)
    db.session.add(ps)
    db.session.flush()

    prob = Problem(title='D5 P1', topic_id=topic.id,
                   difficulty=1, prompt_text='1+1', answer_text='2')
    db.session.add(prob)
    db.session.flush()
    ps.problems.append(prob)
    db.session.flush()

    gs = GameSession(
        problem_set_id=ps.id,
        mode='classic',
        status='active',
    )
    db.session.add(gs)
    db.session.flush()

    gr = GameRound(session_id=gs.id, problem_id=prob.id,
                   round_number=1, started_at=_now())
    db.session.add(gr)
    db.session.flush()

    config = ClassicRoundConfig(round_id=gr.id)
    db.session.add(config)
    db.session.flush()

    db.session.add(RoundPlayer(session_id=gs.id, player_id=p1.id))
    db.session.add(RoundPlayer(session_id=gs.id, player_id=p2.id))

    w1 = PlayerWallet(player_id=p1.id, session_id=gs.id,
                      gold=500, gems=50, steal_tokens=0)
    w2 = PlayerWallet(player_id=p2.id, session_id=gs.id,
                      gold=500, gems=50, steal_tokens=0)
    db.session.add_all([w1, w2])

    pcs1 = PlayerClassicState(player_id=p1.id, session_id=gs.id)
    pcs2 = PlayerClassicState(player_id=p2.id, session_id=gs.id)
    db.session.add_all([pcs1, pcs2])

    db.session.commit()
    return admin, p1, p2, gs, gr, config, w1, w2


with flask_app.app_context():

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 1: Session stock exhaustion blocks purchase
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Session stock exhaustion ────────────────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    item = StoreItem(
        session_id=gs.id, name='Limited Sword', description='test',
        cost=10, currency='gold', bonus_type='x2_mine', session_stock=2,
    )
    db.session.add(item)
    db.session.commit()

    # P1 buys first copy
    ok1, msg1, gold1 = classic_store.purchase_item(p1.id, gs.id, item.id)
    check('D5-01: first purchase succeeds', ok1, f'msg={msg1}')
    check('D5-02: gold deducted after first purchase', gold1 == 490, f'gold={gold1}')

    # P2 buys second copy (stock=2, sold=1 → ok)
    ok2, msg2, gold2 = classic_store.purchase_item(p2.id, gs.id, item.id)
    check('D5-03: second purchase succeeds (stock not exhausted)', ok2, f'msg={msg2}')

    # P1 tries third purchase — session stock exhausted (2 of 2 sold)
    ok3, msg3, gold3 = classic_store.purchase_item(p1.id, gs.id, item.id)
    check('D5-04: third purchase blocked (session stock exhausted)', not ok3)
    check('D5-05: reason is out of stock', msg3 == 'out of stock', f'msg={msg3}')
    check('D5-06: no gold deducted on blocked purchase', gold3 == 490, f'gold={gold3}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 2: Per-player limit blocks purchase
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Per-player purchase limit ───────────────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    item = StoreItem(
        session_id=gs.id, name='Player-Limited Potion', description='test',
        cost=10, currency='gold', bonus_type='x2_mine',
        session_stock=-1, per_player_limit=1,
    )
    db.session.add(item)
    db.session.commit()

    # P1 buys first copy — should succeed
    ok1, msg1, _ = classic_store.purchase_item(p1.id, gs.id, item.id)
    check('D5-07: first purchase within per-player limit succeeds', ok1, f'msg={msg1}')

    # P1 tries second — blocked by per_player_limit=1
    ok2, msg2, gold2 = classic_store.purchase_item(p1.id, gs.id, item.id)
    check('D5-08: second purchase blocked by per-player limit', not ok2)
    check('D5-09: reason mentions purchase limit',
          'purchase limit reached' in msg2, f'msg={msg2}')
    check('D5-10: no gold deducted', gold2 == 490, f'gold={gold2}')

    # P2 can still buy (different player, limit is per-player)
    ok3, msg3, _ = classic_store.purchase_item(p2.id, gs.id, item.id)
    check('D5-11: different player can still purchase', ok3, f'msg={msg3}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 3: Both limits working together
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Both limits together ────────────────────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    item = StoreItem(
        session_id=gs.id, name='Dual-Limited Item', description='test',
        cost=10, currency='gold', bonus_type='x2_mine',
        session_stock=3, per_player_limit=2,
    )
    db.session.add(item)
    db.session.commit()

    # P1 buys twice (within per-player limit of 2)
    ok_a, _, _ = classic_store.purchase_item(p1.id, gs.id, item.id)
    ok_b, _, _ = classic_store.purchase_item(p1.id, gs.id, item.id)
    check('D5-12: P1 first purchase ok', ok_a)
    check('D5-13: P1 second purchase ok', ok_b)

    # P1 hits per-player limit — even though session stock has 1 left
    ok_c, msg_c, gold_c = classic_store.purchase_item(p1.id, gs.id, item.id)
    check('D5-14: P1 third blocked by per-player limit', not ok_c)
    check('D5-15: reason mentions per player', 'per player' in msg_c, f'msg={msg_c}')

    # P2 buys once (session stock: 3 total, 2 sold → 1 left)
    ok_d, _, _ = classic_store.purchase_item(p2.id, gs.id, item.id)
    check('D5-16: P2 first purchase ok (session stock has room)', ok_d)

    # P2 tries again — now session stock exhausted (3 of 3 sold)
    ok_e, msg_e, _ = classic_store.purchase_item(p2.id, gs.id, item.id)
    check('D5-17: P2 second blocked by session stock', not ok_e)
    check('D5-18: reason is out of stock', msg_e == 'out of stock', f'msg={msg_e}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 4: Unlimited (-1) works for both fields
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Unlimited (-1) for both fields ──────────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    item = StoreItem(
        session_id=gs.id, name='Unlimited Item', description='test',
        cost=1, currency='gold', bonus_type='x2_mine',
        session_stock=-1, per_player_limit=-1,
    )
    db.session.add(item)
    db.session.commit()

    # P1 buys many times — all should succeed
    all_ok = True
    for i in range(10):
        ok, msg, _ = classic_store.purchase_item(p1.id, gs.id, item.id)
        if not ok:
            all_ok = False
            break
    check('D5-19: 10 unlimited purchases all succeed', all_ok)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 5: Admin form saves both fields
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Admin form create with both fields ──────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    with flask_app.test_client() as client:
        _login(client)

        # Create item via admin store form
        resp = client.post(
            f'/admin/classic/{gs.id}/store',
            data={
                'name': 'Form-Created Item',
                'cost': 15,
                'currency': 'gold',
                'bonus_type': 'x2_mine',
                'session_stock': 5,
                'per_player_limit': 2,
                'submit': 'Save Item',
            },
            follow_redirects=True,
        )
        check('D5-20: store create returns 200', resp.status_code == 200)

        created = StoreItem.query.filter_by(
            session_id=gs.id, name='Form-Created Item'
        ).first()
        check('D5-21: item created in DB', created is not None)
        if created:
            check('D5-22: session_stock saved correctly',
                  created.session_stock == 5, f'got {created.session_stock}')
            check('D5-23: per_player_limit saved correctly',
                  created.per_player_limit == 2, f'got {created.per_player_limit}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 6: Admin form edits both fields
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Admin form edit both fields ─────────────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    item = StoreItem(
        session_id=gs.id, name='Editable Item', description='test',
        cost=10, currency='gold', bonus_type='x2_mine',
        session_stock=-1, per_player_limit=-1,
    )
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client)

        resp = client.post(
            f'/admin/classic/{gs.id}/store/{item.id}/edit',
            data={
                'name': 'Editable Item',
                'cost': 10,
                'currency': 'gold',
                'bonus_type': 'x2_mine',
                'session_stock': 8,
                'per_player_limit': 3,
                'submit': 'Save Item',
            },
            follow_redirects=True,
        )
        check('D5-24: store edit returns 200', resp.status_code == 200)

        db.session.refresh(item)
        check('D5-25: session_stock updated to 8',
              item.session_stock == 8, f'got {item.session_stock}')
        check('D5-26: per_player_limit updated to 3',
              item.per_player_limit == 3, f'got {item.per_player_limit}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 7: Admin store page displays both fields
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Admin store page displays both columns ──────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    item_ltd = StoreItem(
        session_id=gs.id, name='Limited Display', description='test',
        cost=10, currency='gold', bonus_type='x2_mine',
        session_stock=5, per_player_limit=2,
    )
    item_unl = StoreItem(
        session_id=gs.id, name='Unlimited Display', description='test',
        cost=5, currency='gold', bonus_type='x2_mine',
        session_stock=-1, per_player_limit=-1,
    )
    db.session.add_all([item_ltd, item_unl])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client)
        resp = client.get(f'/admin/classic/{gs.id}/store')
        html = resp.data.decode()

        check('D5-27: page loads (200)', resp.status_code == 200)
        check('D5-28: "Session Stock" header present',
              'Session Stock' in html)
        check('D5-29: "Per-Player Limit" header present',
              'Per-Player Limit' in html)
        check('D5-30: limited item shows stock total',
              '5 total' in html)
        check('D5-31: unlimited session stock shows "Unlimited"',
              'Unlimited' in html)
        check('D5-32: per_player_limit=2 shown',
              '2 per player' in html)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 8: Existing capacity checks still work
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Existing capacity checks preserved ──────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    # SC capacity check (max 1 active)
    sc_item = StoreItem(
        session_id=gs.id, name='SC', description='test',
        cost=10, currency='gold', bonus_type='shield',
        session_stock=-1, per_player_limit=-1,
    )
    db.session.add(sc_item)
    db.session.commit()

    ok1, _, _ = classic_store.purchase_item(p1.id, gs.id, sc_item.id)
    check('D5-33: first SC purchase succeeds', ok1)

    ok2, msg2, gold2 = classic_store.purchase_item(p1.id, gs.id, sc_item.id)
    check('D5-34: second SC blocked by capacity check', not ok2)
    check('D5-35: reason mentions already have',
          'already have' in msg2.lower(), f'msg={msg2}')
    check('D5-36: no gold deducted', gold2 == 490, f'gold={gold2}')

    # Steal token cap check
    tk_item = StoreItem(
        session_id=gs.id, name='Token', description='test',
        cost=10, currency='gold', bonus_type='steal_token',
        session_stock=-1, per_player_limit=-1,
    )
    db.session.add(tk_item)
    db.session.commit()

    ok3, _, _ = classic_store.purchase_item(p1.id, gs.id, tk_item.id, steal_token_max_cap=1)
    check('D5-37: first steal token purchase succeeds', ok3)

    ok4, msg4, gold4 = classic_store.purchase_item(p1.id, gs.id, tk_item.id, steal_token_max_cap=1)
    check('D5-38: second steal token blocked by cap', not ok4)
    check('D5-39: reason mentions maximum steal tokens',
          'maximum steal tokens' in msg4, f'msg={msg4}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 9: System items hidden from store catalog
    # ══════════════════════════════════════════════════════════════════════
    print('\n── System items hidden ─────────────────────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    sys_item = classic_store.get_or_create_system_sc(gs.id)
    normal = StoreItem(
        session_id=gs.id, name='Visible Item', description='test',
        cost=10, currency='gold', bonus_type='x2_mine', session_stock=-1,
    )
    db.session.add(normal)
    db.session.commit()

    visible = classic_store.store_items_for(gs.id)
    visible_ids = [i['id'] for i in visible]
    check('D5-40: system item NOT in store_items_for',
          sys_item.id not in visible_ids)
    check('D5-41: normal item IS in store_items_for',
          normal.id in visible_ids)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 10: store_items_for includes per_player_limit
    # ══════════════════════════════════════════════════════════════════════
    print('\n── store_items_for output includes per_player_limit ────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    item = StoreItem(
        session_id=gs.id, name='Output Test', description='test',
        cost=10, currency='gold', bonus_type='x2_mine',
        session_stock=5, per_player_limit=3,
    )
    db.session.add(item)
    db.session.commit()

    items = classic_store.store_items_for(gs.id)
    entry = next((i for i in items if i['id'] == item.id), None)
    check('D5-42: item appears in store_items_for', entry is not None)
    if entry:
        check('D5-43: per_player_limit key present',
              'per_player_limit' in entry)
        check('D5-44: per_player_limit value is 3',
              entry.get('per_player_limit') == 3,
              f'got {entry.get("per_player_limit")}')
        check('D5-45: quantity_left computed correctly (5 stock, 0 sold = 5)',
              entry.get('quantity_left') == 5,
              f'got {entry.get("quantity_left")}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 11: Model defaults
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Model defaults ─────────────────────────────────────────')

    admin, p1, p2, gs, gr, cfg, w1, w2 = _setup()

    # StoreItem without explicit session_stock/per_player_limit
    item = StoreItem(
        session_id=gs.id, name='Default Item', description='test',
        cost=10, currency='gold', bonus_type='x2_mine',
    )
    db.session.add(item)
    db.session.flush()
    check('D5-46: session_stock defaults to -1',
          item.session_stock == -1, f'got {item.session_stock}')
    check('D5-47: per_player_limit defaults to -1',
          item.per_player_limit == -1, f'got {item.per_player_limit}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════
    print(f'\n{"=" * 60}')
    print(f'D5 Store Purchase Limits: {passed} passed, {failed} failed')
    print(f'{"=" * 60}')
    if failed:
        sys.exit(1)
