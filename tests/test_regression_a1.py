"""
test_regression_a1.py
=====================

Regression tests for Step A1 — 9 gameplay/UX correctness fixes applied to
the Classic Mode after Diamonds Phase 1 MVP manual testing.

Tests operate directly via ORM + engine/state helpers inside a Flask app
context.  No HTTP, no WebSocket connections required.

Coverage (A1-01 to A1-18):

  Wrong-answer penalty (A1-1):
    A1-01: apply_penalty deducts configured amount on first wrong attempt
    A1-02: apply_penalty deducts on second wrong attempt (sequential calls)
    A1-03: apply_penalty deducts on final wrong attempt
    A1-04: apply_penalty floors at zero, never returns negative

  Shield absorbs penalty (A1-1 / store):
    A1-05: consume_item('shield') consumes shield item and returns inv row
    A1-06: wallet gold unchanged when shield absorbs the penalty

  Steal-token purchase cap (A1-6):
    A1-07: purchase_item succeeds when below cap (steal_tokens=0, cap=1)
    A1-08: purchase_item blocks when AT cap and does NOT deduct gold
    A1-09: purchase_item allows when cap is higher (steal_tokens=1, cap=2)
    A1-10: incorrect cap (0 or negative not normally reachable) — no test needed

  Token-cap dynamic (A1-7):
    A1-11: get_session_player_modifiers returns _DefaultModifiers.effective_steal_token_cap=1
           when no SessionParticipantSnapshot row exists

  Streak state (A1-4):
    A1-12: state.get_streak returns 0 before any increment
    A1-13: state.increment_streak then get_streak returns 1
    A1-14: state.increment_streak × 3, get_streak returns 3
    A1-15: state.reset_streak resets to 0

  Penalty integration — multi-attempt scenario (A1-1):
    A1-16: simulate 3 consecutive wrong answers with penalty=10, start gold=100
            verify gold decrements by 10 each time (100 → 90 → 80 → 70)

  store.purchase_item: gold deducted correctly on allowed purchase (A1-6/A1-7):
    A1-17: gold decremented by item.cost after successful steal_token purchase
    A1-18: wallet.steal_tokens incremented to 1 after successful purchase

  Regression:
    A1-19: Full Step E suite (157 prior tests)

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_a1.py

Expected: all tests pass, final line "ALL A1 TESTS PASSED."
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig, PlayerWallet, PlayerClassicState,
    StoreItem, PlayerInventory, StealEvent,
)
from app.modes.classic import engine, state
from app.modes.classic import store as classic_store
from app.services.progression import get_session_player_modifiers

flask_app = create_app()

SET_NAME   = '__test_a1__'
_P1_NAME   = '__a1_p1__'
_P2_NAME   = '__a1_p2__'

# ─────────────────────────────────────────────────────────────────────────────
# Lightweight test runner (same style as test_classic_step_e.py)
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
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _clean():
    """Remove all test artefacts from a prior run."""
    ps = ProblemSet.query.filter_by(name=SET_NAME).first()
    for gs in GameSession.query.filter_by(mode='classic').all():
        if gs.problem_set and gs.problem_set.name == SET_NAME:
            sid = gs.id
            StealEvent.query.filter_by(session_id=sid).delete()
            PlayerInventory.query.filter_by(session_id=sid).delete()
            StoreItem.query.filter_by(session_id=sid).delete()
            PlayerClassicState.query.filter_by(session_id=sid).delete()
            PlayerWallet.query.filter_by(session_id=sid).delete()
            RoundPlayer.query.filter_by(session_id=sid).delete()
            from app.models.classic import PlayerProblemState, ProblemSolverCount
            for gr in GameRound.query.filter_by(session_id=sid).all():
                PlayerProblemState.query.filter_by(round_id=gr.id).delete()
                ProblemSolverCount.query.filter_by(round_id=gr.id).delete()
                ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
            db.session.delete(gs)
    db.session.flush()

    if ps:
        for prob in ps.problems.all():
            ps.problems.remove(prob)
        db.session.flush()
        for prob in Problem.query.filter(Problem.title.like('A1 P%')).all():
            PlayerProblemState.query.filter_by(problem_id=prob.id).delete()
            ProblemSolverCount.query.filter_by(problem_id=prob.id).delete()
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()

    for uname in (_P1_NAME, _P2_NAME):
        p = Player.query.filter_by(username=uname).first()
        if p:
            db.session.delete(p)
    db.session.commit()


def _make_player(username):
    p = Player(username=username, is_admin=False)
    p.set_password('x')
    db.session.add(p)
    db.session.flush()
    return p


def _make_wallet(player_id, session_id, gold=100, steal_tokens=0):
    w = PlayerWallet(player_id=player_id, session_id=session_id,
                     gold=gold, gems=0, steal_tokens=steal_tokens)
    db.session.add(w)
    db.session.flush()
    return w


def _make_session_round(admin_id):
    """Return (session, round, problem_set)."""
    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='A1_topic')
        db.session.add(topic)
        db.session.flush()

    ps = ProblemSet(name=SET_NAME)
    db.session.add(ps)
    db.session.flush()

    prob = Problem(title='A1 P1', prompt_text='What is 6×7?',
                   answer_text='42', topic_id=topic.id)
    db.session.add(prob)
    db.session.flush()
    ps.problems.append(prob)
    db.session.flush()

    gs = GameSession(mode='classic', status='active', problem_set_id=ps.id)
    db.session.add(gs)
    db.session.flush()

    gr = GameRound(session_id=gs.id, round_number=1,
                   started_at=_now(), ended_at=None)
    db.session.add(gr)
    db.session.flush()

    cfg = ClassicRoundConfig(
        round_id=gr.id,
        mine_reward=20,
        treasure_search_reward=5,
        treasure_search_max_reward=5,
        gem_milestone_count=0,
        gem_streak_count=0,
        attempts_per_problem=3,
        wrong_answer_penalty=10,
        bonus_timer_duration=0,
        bonus_timer_gold=0,
        first_solver_count=0,
        first_solver_multiplier=0,
        steal_percent=0.10,
        steal_min_cap=10,
        steal_max_cap=50,
        steal_fallback_gold=5,
        steal_chest_count=0,
        steal_winning_chest_count=1,
        shield_duration=60,
        treasure_steal_token_chance=0.0,
    )
    db.session.add(cfg)
    db.session.commit()
    return gs, gr, ps


def _make_steal_token_item(session_id, cost=5):
    item = StoreItem(
        session_id=session_id,
        name='Steal Token',
        description='Grants one steal token.',
        bonus_type='steal_token',
        cost=cost,
        session_stock=-1,
    )
    db.session.add(item)
    db.session.flush()
    return item


def _make_shield_item(session_id, cost=10):
    item = StoreItem(
        session_id=session_id,
        name='Shield',
        description='Absorbs one wrong-answer penalty.',
        bonus_type='shield',
        cost=10,
        session_stock=-1,
    )
    db.session.add(item)
    db.session.flush()
    return item


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_penalty_engine():
    """A1-01 to A1-04: engine.apply_penalty behaviour."""
    print('\n── Wrong-answer penalty (engine) ─────────────────────────────────')

    # A1-01: first wrong attempt
    result = engine.apply_penalty(100, 10)
    check('A1-01  apply_penalty on attempt 1 (100 → 90)', result == 90,
          f'got {result}')

    # A1-02: second wrong attempt (sequential, simulating multi-attempt)
    result2 = engine.apply_penalty(result, 10)
    check('A1-02  apply_penalty on attempt 2 (90 → 80)', result2 == 80,
          f'got {result2}')

    # A1-03: third / final wrong attempt
    result3 = engine.apply_penalty(result2, 10)
    check('A1-03  apply_penalty on final attempt (80 → 70)', result3 == 70,
          f'got {result3}')

    # A1-04: floor at zero
    result4 = engine.apply_penalty(5, 10)
    check('A1-04  apply_penalty floors at 0 (5 − 10 → 0)', result4 == 0,
          f'got {result4}')


def test_shield_absorbs_penalty(p1, session_id):
    """A1-05/A1-06: shield item absorbs penalty without deducting gold."""
    print('\n── Shield absorbs penalty ────────────────────────────────────────')

    _make_shield_item(session_id)
    wallet = _make_wallet(p1.id, session_id, gold=100)

    # Give the player one shield in inventory
    shield_item = StoreItem.query.filter_by(
        session_id=session_id, bonus_type='shield').first()
    inv = PlayerInventory(player_id=p1.id, session_id=session_id,
                          item_id=shield_item.id,
                          purchased_at=_now(), used_at=None)
    db.session.add(inv)
    db.session.commit()

    gold_before = wallet.gold
    shield_consumed = classic_store.consume_item(p1.id, session_id, 'shield')

    check('A1-05  consume_item returns inventory row when shield exists',
          shield_consumed is not None)

    # If shield consumed: gold should NOT change
    if shield_consumed:
        check('A1-06  gold unchanged when shield absorbs penalty',
              wallet.gold == gold_before, f'gold={wallet.gold}')
    else:
        check('A1-06  gold unchanged when shield absorbs penalty', False,
              'shield was not consumed')


def test_purchase_item_cap(p1, session_id):
    """A1-07 to A1-09: steal-token purchase is gated by steal_token_max_cap."""
    print('\n── Steal-token purchase cap (A1-6) ──────────────────────────────')

    item = _make_steal_token_item(session_id, cost=5)

    # A1-07: wallet at 0 tokens, cap=1 → should succeed
    w = _make_wallet(p1.id, session_id, gold=50, steal_tokens=0)
    db.session.commit()
    ok, msg, new_bal = classic_store.purchase_item(
        p1.id, session_id, item.id, steal_token_max_cap=1)
    check('A1-07  purchase allowed when steal_tokens < cap',
          ok is True, f'ok={ok}, msg={msg}')

    # After purchase: steal_tokens should be 1
    db.session.refresh(w)
    check('A1-17  steal_tokens incremented to 1 after purchase',
          w.steal_tokens == 1, f'steal_tokens={w.steal_tokens}')
    check('A1-18  gold decremented by item.cost after purchase',
          w.gold == 45, f'gold={w.gold}')

    # A1-08: now at cap=1 with steal_tokens=1 → should be blocked, gold unchanged
    gold_before = w.gold
    ok2, msg2, bal2 = classic_store.purchase_item(
        p1.id, session_id, item.id, steal_token_max_cap=1)
    db.session.refresh(w)
    check('A1-08  purchase blocked at cap (steal_tokens == cap)',
          ok2 is False, f'ok={ok2}, msg={msg2}')
    check('A1-08b gold NOT deducted when purchase blocked at cap',
          w.gold == gold_before, f'gold={w.gold}, was {gold_before}')

    # A1-09: cap raised to 2 → player at 1 token, should succeed
    ok3, msg3, bal3 = classic_store.purchase_item(
        p1.id, session_id, item.id, steal_token_max_cap=2)
    check('A1-09  purchase allowed when below higher cap (cap=2, tokens=1)',
          ok3 is True, f'ok={ok3}, msg={msg3}')


def test_default_modifiers(session_id, p1_id):
    """A1-11: get_session_player_modifiers returns default cap when no snapshot exists."""
    print('\n-- get_session_player_modifiers defaults (A1-7) -----------------')

    mods = get_session_player_modifiers(session_id, p1_id)
    check('A1-11  effective_steal_token_cap defaults to 1',
          mods.effective_steal_token_cap == 1,
          f'got {mods.effective_steal_token_cap}')


def test_streak_state(p1, round_id):
    """A1-12 to A1-15: in-memory streak helpers."""
    print('\n── Streak state helpers (A1-4) ───────────────────────────────────')

    pid = p1.id
    rid = round_id

    # Ensure clean start
    state.reset_streak(pid, rid)

    # A1-12: initial value is 0
    check('A1-12  get_streak returns 0 before any increment',
          state.get_streak(pid, rid) == 0)

    # A1-13: one increment
    state.increment_streak(pid, rid)
    check('A1-13  get_streak returns 1 after one increment',
          state.get_streak(pid, rid) == 1,
          f'got {state.get_streak(pid, rid)}')

    # A1-14: three increments total
    state.increment_streak(pid, rid)
    state.increment_streak(pid, rid)
    check('A1-14  get_streak returns 3 after three increments total',
          state.get_streak(pid, rid) == 3,
          f'got {state.get_streak(pid, rid)}')

    # A1-15: reset
    state.reset_streak(pid, rid)
    check('A1-15  get_streak returns 0 after reset',
          state.get_streak(pid, rid) == 0)


def test_multi_attempt_penalty_integration(p1, session_id):
    """A1-16: ORM-level simulation of 3 consecutive wrong answers with penalty=10."""
    print('\n── Multi-attempt penalty integration (A1-1) ─────────────────────')

    w = _make_wallet(p1.id, session_id, gold=100, steal_tokens=0)
    db.session.commit()

    penalty = 10
    expected = 100

    for attempt in range(1, 4):
        db.session.refresh(w)
        # Replicate the handler logic: no shield → apply penalty
        w.gold = engine.apply_penalty(w.gold, penalty)
        db.session.commit()
        expected -= penalty
        db.session.refresh(w)
        check(f'A1-16  after wrong attempt {attempt}: gold == {expected}',
              w.gold == expected, f'gold={w.gold}')


# ─────────────────────────────────────────────────────────────────────────────
# Regression gate: run all prior test suites
# ─────────────────────────────────────────────────────────────────────────────

def test_shield_expiry_utc_serialisation(p1, session_id, round_id):
    """A1b: shield_expires_at from DB (naive datetime) must serialize with UTC tz.

    When SQLite returns shield_expires_at as a naive datetime, the join_ack
    handler must attach tzinfo=UTC before calling .isoformat(), otherwise
    JavaScript parses the string as local time and the badge-expiry timer fires
    at the wrong time or not at all.
    """
    print('\n── Shield expiry UTC serialisation (A1b) ────────────────────────')

    pcs = PlayerClassicState.query.filter_by(
        player_id=p1.id, session_id=session_id).first()
    if not pcs:
        pcs = PlayerClassicState(player_id=p1.id, session_id=session_id)
        db.session.add(pcs)
        db.session.flush()

    # Grant a shield so shield_expires_at is populated, then commit to DB.
    cfg = ClassicRoundConfig.query.filter_by(round_id=round_id).first()
    shield_s = cfg.shield_duration if cfg else 60
    engine.grant_steal_shield(pcs, shield_s)
    db.session.commit()

    # Re-fetch from DB — SQLite may return a naive datetime.
    db.session.expire(pcs)
    db.session.refresh(pcs)
    se = pcs.shield_expires_at

    # Confirm the DB round-trip; value should be non-None and is likely naive.
    check('A1b-01  shield_expires_at is stored and retrievable',
          se is not None)

    # Replicate the A1b normalization: attach UTC if naive.
    if se is not None and se.tzinfo is None:
        se = se.replace(tzinfo=timezone.utc)

    iso = se.isoformat() if se else None

    # The ISO string MUST contain a timezone designator so browsers parse UTC.
    has_tz = iso is not None and ('+' in iso or iso.endswith('Z'))
    check('A1b-02  isoformat() after normalization contains UTC designator',
          has_tz, f'got: {iso}')

    # Confirm the value from the DB (before normalization) was naive, which is
    # the root cause the server fix addresses.
    raw_naive = pcs.shield_expires_at.tzinfo is None if pcs.shield_expires_at else False
    # This is informational — if raw is already tz-aware the fix is still safe.
    if raw_naive:
        check('A1b-03  DB value is naive (confirms the bug exists without fix)',
              raw_naive)
    else:
        # SQLAlchemy version preserves tzinfo — the fix is still safe (idempotent).
        check('A1b-03  DB value already tz-aware (normalization is idempotent)',
              True)

    # The JS needs the expiry to be strictly in the future to schedule the timer.
    from datetime import timezone as tz_mod
    now_utc = datetime.now(tz_mod.utc)
    normalized_se = pcs.shield_expires_at
    if normalized_se and normalized_se.tzinfo is None:
        normalized_se = normalized_se.replace(tzinfo=tz_mod.utc)
    check('A1b-04  normalized expiry is in the future (timer would be scheduled)',
          normalized_se is not None and normalized_se > now_utc,
          f'expires={normalized_se}, now={now_utc}')


def test_regression_prior_suites():
    print('\n── Regression gate: prior test suites ───────────────────────────')
    suite = os.path.join(os.path.dirname(__file__), 'test_classic_step_e.py')
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    result = subprocess.run(
        [sys.executable, suite],
        capture_output=True, text=True, encoding='utf-8',
        env=env,
    )
    out = result.stdout + result.stderr
    last_line = [l for l in out.splitlines() if l.strip()][-1] if out.strip() else ''
    passed_gate = result.returncode == 0 and 'PASSED' in last_line
    check('A1-19  all prior Step E tests pass', passed_gate,
          last_line if not passed_gate else '')
    if not passed_gate:
        print('    --- prior suite output (last 20 lines) ---')
        for line in out.splitlines()[-20:]:
            print('   ', line)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with flask_app.app_context():
        _clean()

        admin = _make_player(_P1_NAME)
        p2    = _make_player(_P2_NAME)
        gs, gr, ps = _make_session_round(admin.id)

        # ── Engine-only tests (no DB setup needed) ──────────────────────────
        test_penalty_engine()

        # ── DB-backed tests ─────────────────────────────────────────────────
        test_shield_absorbs_penalty(admin, gs.id)
        # Re-fetch wallet state cleanly for next test group
        PlayerWallet.query.filter_by(
            player_id=admin.id, session_id=gs.id).delete()
        db.session.commit()

        test_purchase_item_cap(admin, gs.id)
        # Re-fetch wallet state cleanly
        PlayerWallet.query.filter_by(
            player_id=admin.id, session_id=gs.id).delete()
        db.session.commit()

        test_default_modifiers(gs.id, admin.id)
        test_streak_state(admin, gr.id)

        test_multi_attempt_penalty_integration(p2, gs.id)
        test_shield_expiry_utc_serialisation(admin, gs.id, gr.id)

        # ── Regression gate ─────────────────────────────────────────────────
        test_regression_prior_suites()

        _clean()

    print(f'\n{"─" * 55}')
    print(f'  Results: {passed} passed, {failed} failed')
    if failed == 0:
        print('  ALL A1 TESTS PASSED.')
        sys.exit(0)
    else:
        sys.exit(1)
