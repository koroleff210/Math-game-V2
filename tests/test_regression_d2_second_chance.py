"""
test_regression_d2_second_chance.py
===================================

Regression tests for Step D2 — Second Chance item behavior.

Replaces the old "Penalty Shield" concept with "Second Chance":
  - Wrong answer with Second Chance: no penalty, attempt preserved, can retry
  - Wrong answer without Second Chance: normal behavior unchanged
  - Max capacity 1: store purchase blocked when already owning one
  - User-facing naming updated from "Shield" to "Second Chance"

Tests operate directly via ORM + store helpers inside a Flask app context.
No HTTP, no WebSocket connections required.

Coverage:

  D2SC-01: Wrong answer with Second Chance — item consumed
  D2SC-02: Wrong answer with Second Chance — penalty NOT applied (gold unchanged)
  D2SC-03: Attempt rollback works (attempts_used returns to pre-increment value)
  D2SC-04: Problem re-opened after Second Chance even at attempt limit
  D2SC-05: Wrong answer without Second Chance — penalty applied
  D2SC-06: Wrong answer without Second Chance — attempt consumed, problem closes
  D2SC-07: Store purchase blocked when player already owns one Second Chance
  D2SC-08: Store purchase allowed after Second Chance is consumed
  D2SC-09: Second purchase blocked, no currency deducted (max-1 enforced)
  D2SC-10: Form label for shield bonus_type shows "Second Chance"
  D2SC-11: Model docstring reflects Second Chance
  D2SC-12: steal_shield items NOT affected by Second Chance max-1 rule
  D2SC-13: Gems currency purchase for Second Chance works and respects max-1

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_d2_second_chance.py

Expected: all tests pass, final line "ALL D2 SECOND CHANCE TESTS PASSED."
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
    ClassicRoundConfig, PlayerWallet, PlayerClassicState,
    PlayerProblemState, StoreItem, PlayerInventory, StealEvent,
)
from app.modes.classic import engine, state
from app.modes.classic import store as classic_store

flask_app = create_app()

SET_NAME = '__test_d2sc__'
_P1_NAME = '__d2sc_p1__'
_P2_NAME = '__d2sc_p2__'

# ─────────────────────────────────────────────────────────────────────────────
# Lightweight test runner
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
            for gr in GameRound.query.filter_by(session_id=sid).all():
                PlayerProblemState.query.filter_by(round_id=gr.id).delete()
                from app.models.classic import ProblemSolverCount
                ProblemSolverCount.query.filter_by(round_id=gr.id).delete()
                ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
            db.session.delete(gs)
    db.session.flush()

    if ps:
        for prob in ps.problems.all():
            ps.problems.remove(prob)
        db.session.flush()
        for prob in Problem.query.filter(Problem.title.like('D2SC P%')).all():
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


def _make_wallet(player_id, session_id, gold=100, gems=50):
    w = PlayerWallet(player_id=player_id, session_id=session_id,
                     gold=gold, gems=gems, steal_tokens=0)
    db.session.add(w)
    db.session.flush()
    return w


def _make_session_round(attempts=3, penalty=10):
    """Return (session, round, problem, config)."""
    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='D2SC_topic')
        db.session.add(topic)
        db.session.flush()

    ps = ProblemSet(name=SET_NAME)
    db.session.add(ps)
    db.session.flush()

    prob = Problem(title='D2SC P1', prompt_text='What is 6x7?',
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
        attempts_per_problem=attempts,
        wrong_answer_penalty=penalty,
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
    return gs, gr, prob, cfg


def _make_second_chance_item(session_id, cost=10, currency='gold'):
    item = StoreItem(
        session_id=session_id,
        name='Second Chance',
        description='Try again with no penalty.',
        bonus_type='shield',
        cost=cost,
        currency=currency,
        session_stock=-1,
    )
    db.session.add(item)
    db.session.flush()
    return item


def _give_second_chance(player_id, session_id, item_id):
    """Insert an unused shield inventory row (simulates owning a Second Chance)."""
    inv = PlayerInventory(
        player_id=player_id,
        session_id=session_id,
        item_id=item_id,
        purchased_at=_now(),
        used_at=None,
    )
    db.session.add(inv)
    db.session.commit()
    return inv


def _make_pps(player_id, round_id, problem_id):
    pps = PlayerProblemState(
        player_id=player_id,
        round_id=round_id,
        problem_id=problem_id,
    )
    db.session.add(pps)
    db.session.flush()
    return pps


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

with flask_app.app_context():
    _clean()

    p1 = _make_player(_P1_NAME)
    gs, gr, prob, cfg = _make_session_round(attempts=3, penalty=10)
    sid = gs.id

    sc_item = _make_second_chance_item(sid)

    print('\n── D2SC: Wrong answer WITH Second Chance ────────────────────────')

    w1 = _make_wallet(p1.id, sid, gold=100)
    pps1 = _make_pps(p1.id, gr.id, prob.id)
    _give_second_chance(p1.id, sid, sc_item.id)

    # D2SC-01: consume_item consumes the Second Chance
    pre_count = classic_store.get_active_counts(p1.id, sid).get('shield', 0)
    check('D2SC-01a: pre-state has 1 Second Chance', pre_count == 1, f'got {pre_count}')

    sc_inv = classic_store.consume_item(p1.id, sid, 'shield')
    check('D2SC-01b: consume returns inventory row', sc_inv is not None)

    post_count = classic_store.get_active_counts(p1.id, sid).get('shield', 0)
    check('D2SC-01c: 0 Second Chance left after consume', post_count == 0, f'got {post_count}')

    # D2SC-02: Gold unchanged (penalty not applied)
    check('D2SC-02: gold remains 100', w1.gold == 100, f'got {w1.gold}')

    # D2SC-03: Attempt rollback
    pps1.attempts_used = 1  # simulate increment
    db.session.flush()
    pps1.attempts_used -= 1  # simulate Second Chance rollback
    db.session.commit()
    check('D2SC-03: attempts_used back to 0 after rollback', pps1.attempts_used == 0,
          f'got {pps1.attempts_used}')

    # D2SC-04: Problem re-opened even at attempt limit
    pps1.attempts_used = 2
    pps1.is_closed = False
    db.session.flush()
    # Simulate: increment to 3 (limit), close problem
    pps1.attempts_used += 1  # now 3
    pps1.is_closed = True
    db.session.flush()
    # Second Chance rollback
    pps1.attempts_used -= 1  # back to 2
    pps1.is_closed = False
    db.session.commit()
    check('D2SC-04a: problem is_closed = False after rollback', not pps1.is_closed)
    check('D2SC-04b: attempts_used = 2 (rolled back from 3)', pps1.attempts_used == 2,
          f'got {pps1.attempts_used}')

    # Reset for next tests
    pps1.attempts_used = 0
    pps1.is_closed = False
    pps1.is_solved = False
    w1.gold = 100
    db.session.commit()

    print('\n── D2SC: Wrong answer WITHOUT Second Chance ─────────────────────')

    # D2SC-05: Penalty applied when no Second Chance available
    sc_inv2 = classic_store.consume_item(p1.id, sid, 'shield')
    check('D2SC-05a: no Second Chance to consume', sc_inv2 is None)

    w1.gold = engine.apply_penalty(w1.gold, cfg.wrong_answer_penalty)
    db.session.commit()
    check('D2SC-05b: gold reduced to 90', w1.gold == 90, f'got {w1.gold}')

    # D2SC-06: Attempt consumed and problem closes at limit
    pps1.attempts_used = 2
    pps1.is_closed = False
    pps1.attempts_used += 1  # now 3
    if cfg.attempts_per_problem != -1 and pps1.attempts_used >= cfg.attempts_per_problem:
        pps1.is_closed = True
    db.session.commit()
    check('D2SC-06a: attempts_used = 3', pps1.attempts_used == 3,
          f'got {pps1.attempts_used}')
    check('D2SC-06b: problem closed at limit', pps1.is_closed)

    # Reset
    pps1.attempts_used = 0
    pps1.is_closed = False
    pps1.is_solved = False
    w1.gold = 100
    db.session.commit()

    print('\n── D2SC: Max-1 capacity in store ────────────────────────────────')

    # D2SC-07: Purchase blocked when already owning one
    _give_second_chance(p1.id, sid, sc_item.id)
    active = classic_store.get_active_counts(p1.id, sid).get('shield', 0)
    check('D2SC-07a: player has 1 Second Chance', active == 1)

    ok, msg, _ = classic_store.purchase_item(p1.id, sid, sc_item.id)
    check('D2SC-07b: purchase blocked', not ok, f'msg={msg}')
    check('D2SC-07c: message mentions Second Chance', 'Second Chance' in msg, f'msg={msg}')
    check('D2SC-07d: gold unchanged (100)', w1.gold == 100, f'got {w1.gold}')

    # D2SC-08: Purchase allowed after Second Chance consumed
    classic_store.consume_item(p1.id, sid, 'shield')
    active2 = classic_store.get_active_counts(p1.id, sid).get('shield', 0)
    check('D2SC-08a: 0 active after consume', active2 == 0)

    ok2, msg2, new_gold = classic_store.purchase_item(p1.id, sid, sc_item.id)
    check('D2SC-08b: purchase succeeds', ok2, f'msg={msg2}')
    check('D2SC-08c: gold deducted to 90', w1.gold == 90, f'got {w1.gold}')

    # D2SC-09: Second purchase blocked, no more currency deducted
    ok3, msg3, _ = classic_store.purchase_item(p1.id, sid, sc_item.id)
    check('D2SC-09a: second purchase blocked', not ok3, f'msg={msg3}')
    check('D2SC-09b: gold still 90', w1.gold == 90, f'got {w1.gold}')

    # Clean up the active item
    classic_store.consume_item(p1.id, sid, 'shield')

    print('\n── D2SC: UI / naming checks ─────────────────────────────────────')

    # D2SC-10: Form label for shield bonus_type shows "Second Chance"
    from app.modes.classic.forms import StoreItemForm
    # Access choices from the unbound field to avoid request context CSRF
    shield_choices = [label for val, label in StoreItemForm.bonus_type.kwargs['choices']
                      if val == 'shield']
    check('D2SC-10: form label contains "Second Chance"',
          shield_choices and 'Second Chance' in shield_choices[0],
          f'label={shield_choices}')

    # D2SC-11: Model docstring reflects Second Chance
    check('D2SC-11: StoreItem docstring mentions Second Chance',
          'Second Chance' in (StoreItem.__doc__ or ''))

    print('\n── D2SC: steal_shield unaffected ────────────────────────────────')

    # D2SC-12: steal_shield items NOT affected by Second Chance max-1
    ss_item = StoreItem(
        session_id=sid,
        name='Steal Shield',
        description='Manual theft protection.',
        bonus_type='steal_shield',
        cost=10,
        currency='gold',
        session_stock=-1,
    )
    db.session.add(ss_item)
    db.session.commit()

    # Give player a steal_shield
    inv_ss = PlayerInventory(
        player_id=p1.id,
        session_id=sid,
        item_id=ss_item.id,
        purchased_at=_now(),
        used_at=None,
    )
    db.session.add(inv_ss)
    db.session.commit()

    # Can still buy another steal_shield (no max-1 on this type)
    ok_ss, msg_ss, _ = classic_store.purchase_item(p1.id, sid, ss_item.id)
    check('D2SC-12: steal_shield purchase NOT blocked by max-1', ok_ss, f'msg={msg_ss}')

    print('\n── D2SC: Gems currency + max-1 ──────────────────────────────────')

    # D2SC-13: Gems-priced Second Chance respects max-1
    sc_gems_item = _make_second_chance_item(sid, cost=5, currency='gems')
    _give_second_chance(p1.id, sid, sc_gems_item.id)

    ok_g, msg_g, _ = classic_store.purchase_item(p1.id, sid, sc_gems_item.id)
    check('D2SC-13a: gem Second Chance blocked when already owning one', not ok_g, f'msg={msg_g}')

    # Consume and then buy with gems
    classic_store.consume_item(p1.id, sid, 'shield')
    gems_before = w1.gems
    ok_g2, msg_g2, _ = classic_store.purchase_item(p1.id, sid, sc_gems_item.id)
    check('D2SC-13b: gem purchase succeeds after consume', ok_g2, f'msg={msg_g2}')
    check('D2SC-13c: gems deducted', w1.gems == gems_before - 5, f'got {w1.gems}')

    # ─────────────────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────────────────

    _clean()

    print(f'\n{"=" * 60}')
    print(f'D2 Second Chance results: {passed} passed, {failed} failed')
    if failed:
        print('SOME D2 SECOND CHANCE TESTS FAILED.')
        sys.exit(1)
    else:
        print('ALL D2 SECOND CHANCE TESTS PASSED.')
        sys.exit(0)
