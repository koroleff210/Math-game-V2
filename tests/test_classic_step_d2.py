"""
test_classic_step_d2.py
=======================

Focused tests for Classic Mode Step D-2: steal engine helpers and state API.

Tests are pure unit tests — no HTTP requests, no WebSocket connections, no
live DB writes needed for pure engine functions.  DB-backed helpers that
require ORM objects are tested with lightweight fakes.

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_classic_step_d2.py

Expected output: all assertions pass, final line prints "ALL D-2 TESTS PASSED."
"""

import sys
import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modes.classic import engine, state

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pcs(shield_expires_at=None):
    """Return a fake PlayerClassicState with the given shield_expires_at."""
    return SimpleNamespace(shield_expires_at=shield_expires_at)


def _wallet(player_id, gold, username='Player'):
    """Return a fake PlayerWallet with a nested fake .player."""
    w = SimpleNamespace(
        player_id=player_id,
        gold=gold,
        steal_tokens=0,
        player=SimpleNamespace(username=username),
    )
    return w


def _now():
    return datetime.now(timezone.utc)


passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        print(f'  FAIL  {label}')
        failed += 1


# ─────────────────────────────────────────────────────────────────────────────
# calc_steal_amount  (T01–T05)
# ─────────────────────────────────────────────────────────────────────────────
print('\ncalc_steal_amount')

# T01: 100 * 0.10 = 10; capped to [10, 50] → 10
check('T01 basic formula', engine.calc_steal_amount(100, 0.10, 10, 50) == 10)

# T02: target_gold=5; formula → max(10, round(5*0.10))=max(10,1)=10; min(10,5)=5
check('T02 target_gold cap', engine.calc_steal_amount(5, 0.10, 10, 50) == 5)

# T03: 1000 * 0.10 = 100; max_cap=50 → 50
check('T03 upper cap clamp', engine.calc_steal_amount(1000, 0.10, 10, 50) == 50)

# T04: target=8; formula → max(10, round(8*0.10))=max(10,1)=10; min(10,8)=8
check('T04 target_gold < min_cap', engine.calc_steal_amount(8, 0.10, 10, 50) == 8)

# T05: max_cap=-1 means no upper clamp; 1000 * 0.10 = 100 → 100
check('T05 no upper cap (-1)', engine.calc_steal_amount(1000, 0.10, 10, -1) == 100)

# Extra: steal_percent 0.5, high gold → hits max_cap
check('T05b max_cap enforced', engine.calc_steal_amount(200, 0.5, 10, 50) == 50)

# Extra: round() half-even; make sure it doesn't crash
check('T05c round() no crash', isinstance(engine.calc_steal_amount(3, 0.10, 1, 10), int))


# ─────────────────────────────────────────────────────────────────────────────
# is_steal_shield_active  (T06–T08)
# ─────────────────────────────────────────────────────────────────────────────
print('\nis_steal_shield_active')

check('T06 None → False', not engine.is_steal_shield_active(_pcs(None)))
check('T07 past datetime → False',
      not engine.is_steal_shield_active(_pcs(_now() - timedelta(seconds=1))))
check('T08 future datetime → True',
      engine.is_steal_shield_active(_pcs(_now() + timedelta(seconds=60))))

# Naive datetime should be treated as UTC (no crash)
naive_future = datetime.utcnow() + timedelta(seconds=60)
check('T08b naive future → True', engine.is_steal_shield_active(_pcs(naive_future)))


# ─────────────────────────────────────────────────────────────────────────────
# grant_steal_shield  (T09–T10)
# ─────────────────────────────────────────────────────────────────────────────
print('\ngrant_steal_shield')

# T09: no existing shield → new expiry ≈ now + duration
pcs = _pcs(None)
before = _now()
result = engine.grant_steal_shield(pcs, 60)
after = _now()
lower = before + timedelta(seconds=59)
upper = after + timedelta(seconds=61)
check('T09 no shield → now+duration',
      lower <= result <= upper and pcs.shield_expires_at == result)

# T10: already active → new expiry = old_expiry + duration (stacking)
old_expiry = _now() + timedelta(seconds=30)
pcs2 = _pcs(old_expiry)
result2 = engine.grant_steal_shield(pcs2, 60)
expected_min = old_expiry + timedelta(seconds=59)
expected_max = old_expiry + timedelta(seconds=61)
check('T10 stacks onto active shield',
      expected_min <= result2 <= expected_max and pcs2.shield_expires_at == result2)

# T10b: expired shield → treated as no shield (base = now, not expired time)
expired = _now() - timedelta(seconds=10)
pcs3 = _pcs(expired)
before3 = _now()
result3 = engine.grant_steal_shield(pcs3, 60)
after3 = _now()
lower3 = before3 + timedelta(seconds=59)
upper3 = after3 + timedelta(seconds=61)
check('T10b expired shield → base=now', lower3 <= result3 <= upper3)


# ─────────────────────────────────────────────────────────────────────────────
# build_steal_targets  (T11–T12)
# ─────────────────────────────────────────────────────────────────────────────
print('\nbuild_steal_targets')

acting = 1
w_self  = _wallet(1, 100, 'Self')
w_ok    = _wallet(2, 80,  'Alice')
w_zero  = _wallet(3, 0,   'Broke')
w_neg   = _wallet(4, -1,  'Negative')   # also excluded
w_shld  = _wallet(5, 50,  'Shielded')

states_map = {
    5: _pcs(_now() + timedelta(seconds=60)),   # shielded
}

wallets = [w_self, w_ok, w_zero, w_neg, w_shld]
targets = engine.build_steal_targets(wallets, states_map, acting_player_id=acting)

target_ids = [t['player_id'] for t in targets]

check('T11 excludes self',         1 not in target_ids)
check('T11 excludes 0-gold',       3 not in target_ids)
check('T11 excludes negative-gold',4 not in target_ids)
check('T11 excludes shielded',     5 not in target_ids)
check('T11 includes valid target', 2 in target_ids)
check('T11 target dict has keys',
      all(set(t.keys()) >= {'player_id', 'username', 'gold'} for t in targets))

# T12: empty when all excluded
targets_empty = engine.build_steal_targets(wallets, states_map, acting_player_id=1)
# Remove alice to make all invalid
wallets_all_bad = [w_self, w_zero, w_neg, w_shld]
check('T12 empty list when all excluded',
      engine.build_steal_targets(wallets_all_bad, states_map, acting_player_id=1) == [])


# ─────────────────────────────────────────────────────────────────────────────
# generate_winning_chests  (T13)
# ─────────────────────────────────────────────────────────────────────────────
print('\ngenerate_winning_chests')

chests = engine.generate_winning_chests(5, 2)
check('T13 returns frozenset',        isinstance(chests, frozenset))
check('T13 correct winning count',    len(chests) == 2)
check('T13 all values in [1, count]', all(1 <= c <= 5 for c in chests))

# Edge: 1 of 1
solo = engine.generate_winning_chests(1, 1)
check('T13b 1-of-1 chest',            solo == frozenset({1}))


# ─────────────────────────────────────────────────────────────────────────────
# try_award_steal_token  (T14–T15)
# ─────────────────────────────────────────────────────────────────────────────
print('\ntry_award_steal_token')

wallet_at_cap = SimpleNamespace(steal_tokens=1)
result_cap = engine.try_award_steal_token(wallet_at_cap, max_cap=1)
check('T14 at cap → False, tokens unchanged',
      result_cap is False and wallet_at_cap.steal_tokens == 1)

wallet_under = SimpleNamespace(steal_tokens=0)
result_under = engine.try_award_steal_token(wallet_under, max_cap=1)
check('T15 under cap → True, tokens incremented',
      result_under is True and wallet_under.steal_tokens == 1)


# ─────────────────────────────────────────────────────────────────────────────
# State: steal_intent API  (T16)
# ─────────────────────────────────────────────────────────────────────────────
print('\nstate: steal_intent')

state.set_steal_intent(99, session_id=7, round_id=3, problem_id=0)
intent = state.get_steal_intent(99)
check('T16 set/get steal_intent',
      intent == {'session_id': 7, 'round_id': 3, 'problem_id': 0})

state.clear_steal_intent(99)
check('T16 clear steal_intent', state.get_steal_intent(99) is None)

# Missing player → None
check('T16 missing player → None', state.get_steal_intent(0) is None)


# ─────────────────────────────────────────────────────────────────────────────
# State: steal_minigame API  (T17)
# ─────────────────────────────────────────────────────────────────────────────
print('\nstate: steal_minigame')

wc = frozenset({1, 3})
state.set_steal_minigame(99, target_id=5, winning_chests=wc,
                         steal_amount=25, session_id=7, round_id=3)
mg = state.get_steal_minigame(99)
check('T17 set/get steal_minigame',
      mg is not None
      and mg['target_id'] == 5
      and mg['winning_chests'] == wc
      and mg['steal_amount'] == 25
      and mg['session_id'] == 7
      and mg['round_id'] == 3)

state.clear_steal_minigame(99)
check('T17 clear steal_minigame', state.get_steal_minigame(99) is None)


# ─────────────────────────────────────────────────────────────────────────────
# State: action_log API  (T18)
# ─────────────────────────────────────────────────────────────────────────────
print('\nstate: action_log')

for i in range(11):
    state.append_action_log(42, 1, f'entry {i}')

log = state.get_action_log(42, 1)
check('T18 maxlen=10 enforced', len(log) == 10)
check('T18 oldest entry dropped', log[0] == 'entry 1')   # entry 0 was pushed out
check('T18 newest entry present', log[-1] == 'entry 10')

# get on missing key → empty list
check('T18 missing key → []', state.get_action_log(0, 0) == [])


# ─────────────────────────────────────────────────────────────────────────────
# State: clear_session clears steal state  (bonus coverage)
# ─────────────────────────────────────────────────────────────────────────────
print('\nstate: clear_session sweep')

state.set_steal_intent(77, session_id=99, round_id=1, problem_id=0)
state.set_steal_minigame(77, target_id=2, winning_chests=frozenset({1}),
                         steal_amount=10, session_id=99, round_id=1)
state.append_action_log(77, 99, 'test entry')

state.clear_session(99)

check('clear_session removes intent',   state.get_steal_intent(77) is None)
check('clear_session removes minigame', state.get_steal_minigame(77) is None)
check('clear_session removes action log', state.get_action_log(77, 99) == [])


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f'\n{passed} passed, {failed} failed')
if failed:
    print('SOME D-2 TESTS FAILED.')
    sys.exit(1)
else:
    print('ALL D-2 TESTS PASSED.')
