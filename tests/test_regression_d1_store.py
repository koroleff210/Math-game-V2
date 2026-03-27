"""
test_regression_d1_store.py
============================

Regression tests for Store/Admin Polish Step D1:
  - Per-item currency selection (gold / gems)
  - Store update push mechanism (push_store route)
  - Form field presence for currency and random-rewards fields

Coverage:
  D1-STR-01: StoreItem accepts currency='gold' (default)
  D1-STR-02: StoreItem accepts currency='gems'
  D1-STR-03: Gold purchase deducts gold, does not touch gems
  D1-STR-04: Gem purchase deducts gems, does not touch gold
  D1-STR-05: Gold purchase blocked when player has insufficient gold
  D1-STR-06: Gem purchase blocked when player has insufficient gems
  D1-STR-07: store_items_for includes 'currency' field in returned dicts
  D1-STR-08: Item without explicit currency defaults to 'gold' in store_items_for
  D1-STR-09: Gem failure reason is 'not enough gems'
  D1-STR-10: Gold failure reason is 'not enough gold'
  D1-STR-11: After a gem purchase, player gold balance is unchanged (regression guard)
  D1-STR-12: push_store route is registered in the url map
  D1-STR-13: StoreItemForm has currency SelectField with gold and gems choices
  D1-STR-14: ClassicSessionForm has treasure_steal_token_chance field
  D1-STR-15: Prior B1 regression suite still passes

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_d1_store.py

Expected: all tests pass, final line "ALL D1 STORE TESTS PASSED."
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import ProblemSet
from app.models.game import GameSession, GameRound
from app.models.classic import (
    PlayerWallet, StoreItem, PlayerInventory,
)
from app.modes.classic import store as classic_store
from app.modes.classic.forms import ClassicSessionForm, StoreItemForm

flask_app = create_app()

_P1 = '__d1str_p1__'
_P2 = '__d1str_p2__'
_SET = '__d1str_set__'

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
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


def _clean():
    # Purge sessions before deleting players (avoids FK cascade / autoflush issues)
    ps = ProblemSet.query.filter_by(name=_SET).first()
    if ps:
        for gs in GameSession.query.filter_by(problem_set_id=ps.id).all():
            _purge_session(gs)
        db.session.flush()
        db.session.delete(ps)
        db.session.flush()
    for name in [_P1, _P2]:
        p = Player.query.filter_by(username=name).first()
        if p:
            db.session.delete(p)
    db.session.commit()


def _purge_session(gs):
    for inv in PlayerInventory.query.filter_by(session_id=gs.id).all():
        db.session.delete(inv)
    for item in StoreItem.query.filter_by(session_id=gs.id).all():
        db.session.delete(item)
    for w in PlayerWallet.query.filter_by(session_id=gs.id).all():
        db.session.delete(w)
    for gr in GameRound.query.filter_by(session_id=gs.id).all():
        cfg = getattr(gr, 'classic_config', None)
        if cfg:
            db.session.delete(cfg)
        db.session.delete(gr)
    db.session.delete(gs)


def _make_player(name):
    p = Player.query.filter_by(username=name).first()
    if not p:
        p = Player(username=name)
        p.set_password('test')
        db.session.add(p)
        db.session.commit()
    return p


def _make_session():
    ps = ProblemSet.query.filter_by(name=_SET).first()
    if not ps:
        ps = ProblemSet(name=_SET)
        db.session.add(ps)
        db.session.commit()
    gs = GameSession(mode='classic', status='waiting', problem_set_id=ps.id)
    db.session.add(gs)
    db.session.flush()
    gr = GameRound(session_id=gs.id, problem_id=None, round_number=1, started_at=None)
    db.session.add(gr)
    db.session.commit()
    return gs


def _make_wallet(player_id, session_id, gold=50, gems=20):
    w = PlayerWallet.query.filter_by(player_id=player_id, session_id=session_id).first()
    if not w:
        w = PlayerWallet(player_id=player_id, session_id=session_id, gold=gold, gems=gems)
        db.session.add(w)
    else:
        w.gold = gold
        w.gems = gems
    db.session.commit()
    return w


def _make_item(sid, cost, currency='gold', bonus_type='shield', session_stock=-1):
    item = StoreItem(
        session_id=sid,
        name=f'd1str {currency} {bonus_type}',
        cost=cost,
        currency=currency,
        bonus_type=bonus_type,
        session_stock=session_stock,
    )
    db.session.add(item)
    db.session.commit()
    return item


# ─────────────────────────────────────────────────────────────────────────────
# D1-STR-01 through D1-STR-11: Currency-aware purchases
# ─────────────────────────────────────────────────────────────────────────────

print('\n── D1 Store: currency-aware purchases ──────────────────')

with flask_app.app_context():
    _clean()
    p1 = _make_player(_P1)
    gs = _make_session()
    sid = gs.id

    gold_item = _make_item(sid, cost=10, currency='gold', bonus_type='x2_mine')
    gem_item  = _make_item(sid, cost=5,  currency='gems', bonus_type='x2_mine')

    # D1-STR-01: gold currency stored correctly
    check('D1-STR-01: StoreItem currency=gold stored',
          gold_item.currency == 'gold')

    # D1-STR-02: gem currency stored correctly
    check('D1-STR-02: StoreItem currency=gems stored',
          gem_item.currency == 'gems')

    # D1-STR-03: gold purchase deducts gold, gems unchanged
    w = _make_wallet(p1.id, sid, gold=50, gems=20)
    ok, _, _ = classic_store.purchase_item(p1.id, sid, gold_item.id)
    w = db.session.get(PlayerWallet, w.id)
    check('D1-STR-03a: gold purchase deducts gold (50→40)',
          ok and w.gold == 40, f'ok={ok} gold={w.gold}')
    check('D1-STR-03b: gold purchase leaves gems unchanged (20)',
          w.gems == 20, f'gems={w.gems}')

    # D1-STR-04: gem purchase deducts gems, gold unchanged
    w.gold = 50; w.gems = 20; db.session.commit()
    ok2, _, _ = classic_store.purchase_item(p1.id, sid, gem_item.id)
    w = db.session.get(PlayerWallet, w.id)
    check('D1-STR-04a: gem purchase deducts gems (20→15)',
          ok2 and w.gems == 15, f'ok={ok2} gems={w.gems}')
    check('D1-STR-04b: gem purchase leaves gold unchanged (50)',
          w.gold == 50, f'gold={w.gold}')

    # D1-STR-05: insufficient gold blocks gold purchase
    w.gold = 5; w.gems = 20; db.session.commit()
    ok3, msg3, _ = classic_store.purchase_item(p1.id, sid, gold_item.id)
    check('D1-STR-05: insufficient gold blocks gold purchase',
          not ok3, f'ok={ok3}')

    # D1-STR-06: insufficient gems blocks gem purchase
    w.gold = 50; w.gems = 2; db.session.commit()
    ok4, msg4, _ = classic_store.purchase_item(p1.id, sid, gem_item.id)
    check('D1-STR-06: insufficient gems blocks gem purchase',
          not ok4, f'ok={ok4}')

    # D1-STR-07: store_items_for includes currency field
    w.gold = 50; w.gems = 20; db.session.commit()
    items_listed = classic_store.store_items_for(sid)
    check('D1-STR-07: store_items_for includes currency in all items',
          all('currency' in itm for itm in items_listed),
          f'items={items_listed}')

    # D1-STR-08: item without explicit currency defaults to gold
    # Model default is 'gold', so any row with no explicit value resolves to 'gold'.
    legacy_item = StoreItem(
        session_id=sid, name='d1str legacy', cost=5,
        bonus_type='shield', session_stock=-1,
        # currency deliberately not passed — relies on model default
    )
    db.session.add(legacy_item)
    db.session.commit()
    items_legacy = classic_store.store_items_for(sid)
    leg = next((itm for itm in items_legacy if itm['id'] == legacy_item.id), None)
    check('D1-STR-08: legacy item currency defaults to gold',
          leg is not None and leg['currency'] == 'gold',
          f'currency={leg["currency"] if leg else None}')

    # D1-STR-09: gem failure reason
    check('D1-STR-09: gem failure reason is "not enough gems"',
          msg4 == 'not enough gems', f'msg={msg4!r}')

    # D1-STR-10: gold failure reason
    check('D1-STR-10: gold failure reason is "not enough gold"',
          msg3 == 'not enough gold', f'msg={msg3!r}')

    # D1-STR-11: gem purchase leaves gold unchanged (regression guard)
    w.gold = 50; w.gems = 20; db.session.commit()
    ok11, _, _ = classic_store.purchase_item(p1.id, sid, gem_item.id)
    w = db.session.get(PlayerWallet, w.id)
    check('D1-STR-11: gem purchase leaves gold unchanged',
          ok11 and w.gold == 50, f'ok={ok11} gold={w.gold}')

    _clean()


# ─────────────────────────────────────────────────────────────────────────────
# D1-STR-12: push_store route is registered
# ─────────────────────────────────────────────────────────────────────────────

print('\n── D1 Store: push_store route ──────────────────────────')

with flask_app.app_context():
    endpoints = [rule.endpoint for rule in flask_app.url_map.iter_rules()]
    check('D1-STR-12: push_store route is registered',
          'classic_admin.push_store' in endpoints,
          f'classic_admin endpoints: {[e for e in endpoints if "classic_admin" in e]}')


# ─────────────────────────────────────────────────────────────────────────────
# D1-STR-13/14: Form fields
# ─────────────────────────────────────────────────────────────────────────────

print('\n── D1 Store: form fields ───────────────────────────────')

with flask_app.app_context():
    # D1-STR-13: StoreItemForm has currency with gold + gems
    with flask_app.test_request_context():
        sf = StoreItemForm()
        has_cur = hasattr(sf, 'currency')
        check('D1-STR-13a: StoreItemForm has currency field', has_cur)
        if has_cur:
            vals = [c[0] for c in sf.currency.choices]
            check('D1-STR-13b: currency choices include gold', 'gold' in vals, f'choices={vals}')
            check('D1-STR-13c: currency choices include gems', 'gems' in vals, f'choices={vals}')

    # D1-STR-14: ClassicSessionForm has treasure_steal_token_chance
    check('D1-STR-14: ClassicSessionForm has treasure_steal_token_chance',
          'treasure_steal_token_chance' in dir(ClassicSessionForm))


# ─────────────────────────────────────────────────────────────────────────────
# D1-STR-15: Prior B1 regression suite
# ─────────────────────────────────────────────────────────────────────────────

print('\n── D1 Store: prior B1 regression suite ─────────────────')

_b1 = os.path.join(os.path.dirname(__file__), 'test_regression_b1.py')
_utf8_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
_res = subprocess.run(
    [sys.executable, _b1],
    capture_output=True, text=True,
    encoding='utf-8', errors='replace',
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env=_utf8_env,
)
b1_ok = 'ALL B1 TESTS PASSED' in _res.stdout
check('D1-STR-15: prior B1 test suite still passes', b1_ok,
      _res.stdout[-400:] if not b1_ok else '')
if not b1_ok:
    print('    STDOUT:', _res.stdout[-800:])
    print('    STDERR:', _res.stderr[-400:])


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print(f'\n{"─"*55}')
print(f'Results: {passed} passed, {failed} failed')
if failed == 0:
    print('ALL D1 STORE TESTS PASSED.')
else:
    print(f'FAILED: {failed} test(s) need attention.')
    sys.exit(1)
