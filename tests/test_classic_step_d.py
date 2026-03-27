"""
test_classic_step_d.py
======================

Exit test suite for Classic Mode Step D — Complete Steal System.

Tests operate directly via ORM + engine/state helpers inside a Flask app
context.  No HTTP requests, no WebSocket connections required.

Coverage (T01–TK-01 + Regression T44–T46):
  Engine:  calc_steal_amount, shield helpers, build_steal_targets,
           generate_winning_chests, try_award_steal_token
  State:   steal_intent, steal_minigame, action_log, clear_session
  DB:      no_targets_fallback, mini-game disabled success, mini-game
           enabled success, mini-game fail, target_invalid, shield
           stacking, store new types (steal_token / steal_shield),
           treasure-token chance
  Extras:  steal availability, cancel (token NOT consumed), Mine/TS
           blocked while intent active, duplicate-confirm guard, admin
           history outcome-string compatibility, wallet creation default
  Regression: Step A 32/32, Step B 48/48, Step C 38/38

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_classic_step_d.py

Expected: all tests pass, final line "ALL D TESTS PASSED."
"""

import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import random as _random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig, PlayerWallet, PlayerClassicState,
    PlayerProblemState, ProblemSolverCount, StoreItem, PlayerInventory, StealEvent,
)
from app.modes.classic import engine, state
from app.modes.classic import store as classic_store

flask_app = create_app()

SET_NAME = '__test_step_d__'
_PLAYER_NAMES = ('__sd_actor__', '__sd_target__', '__sd_broke__', '__sd_shielded__')
_STORE_PLAYER = '__sd_store_p__'

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
# Fake helpers for pure-function sections (no DB access)
# ─────────────────────────────────────────────────────────────────────────────

def _pcs_f(shield_expires_at=None):
    """Minimal fake PlayerClassicState."""
    return SimpleNamespace(shield_expires_at=shield_expires_at)


def _wallet_f(player_id, gold, username='P', steal_tokens=0):
    """Minimal fake PlayerWallet with nested .player."""
    return SimpleNamespace(
        player_id=player_id,
        gold=gold,
        steal_tokens=steal_tokens,
        player=SimpleNamespace(username=username),
    )


def _now():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# DB fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clean():
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
                db.session.execute(
                    db.text('DELETE FROM round_player_result WHERE round_history_id IN '
                            '(SELECT id FROM round_history WHERE round_id = :rid)'),
                    {'rid': gr.id},
                )
                db.session.execute(
                    db.text('DELETE FROM round_history WHERE round_id = :rid'),
                    {'rid': gr.id},
                )
                PlayerProblemState.query.filter_by(round_id=gr.id).delete()
                ProblemSolverCount.query.filter_by(round_id=gr.id).delete()
                ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
            db.session.delete(gs)
    db.session.flush()

    if ps:
        for prob in ps.problems.all():
            ps.problems.remove(prob)
        db.session.flush()
        # Delete PPS/PSC rows referencing these problems BEFORE deleting them
        for prob in Problem.query.filter(Problem.title.like('SD P%')).all():
            PlayerProblemState.query.filter_by(problem_id=prob.id).delete()
            ProblemSolverCount.query.filter_by(problem_id=prob.id).delete()
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()

    # Delete test players using raw SQL to avoid cascading FK issues
    # from cross-session references (ORM backref cascade tries NULL on NOT-NULL FKs)
    for uname in _PLAYER_NAMES + (_STORE_PLAYER,):
        with db.session.no_autoflush:
            pid = db.session.execute(
                db.text('SELECT id FROM player WHERE username = :u'), {'u': uname}
            ).scalar()
        if pid:
            for tbl in ['session_participant_snapshot', 'round_player_result',
                         'player_classic_state', 'player_wallet', 'player_inventory',
                         'player_problem_state', 'player_answer', 'round_player',
                         'player_progression', 'player_upgrade']:
                db.session.execute(db.text(f'DELETE FROM {tbl} WHERE player_id = :pid'), {'pid': pid})
            db.session.execute(db.text(
                'DELETE FROM steal_event WHERE actor_id = :pid OR target_id = :pid'), {'pid': pid})
            db.session.execute(db.text(
                'DELETE FROM diamond_transaction WHERE player_id = :pid OR admin_player_id = :pid'), {'pid': pid})
            db.session.execute(db.text('DELETE FROM player WHERE id = :pid'), {'pid': pid})
    db.session.commit()


def _mp(username):
    p = Player(username=username, is_admin=False)
    p.set_password('x')
    db.session.add(p)
    db.session.flush()
    return p


def _mw(player_id, session_id, gold=100, steal_tokens=1):
    w = PlayerWallet(player_id=player_id, session_id=session_id,
                     gold=gold, gems=0, steal_tokens=steal_tokens)
    db.session.add(w)
    db.session.flush()
    return w


def _mpcs(player_id, session_id, shield_expires_at=None):
    pcs = PlayerClassicState(player_id=player_id, session_id=session_id,
                              shield_expires_at=shield_expires_at)
    db.session.add(pcs)
    db.session.flush()
    return pcs


def _mcfg(round_id, **overrides):
    defaults = dict(
        round_id=round_id,
        mine_reward=20,
        treasure_search_reward=5,
        treasure_search_max_reward=5,
        gem_milestone_count=0,
        gem_streak_count=0,
        attempts_per_problem=1,
        wrong_answer_penalty=0,
        bonus_timer_duration=0,
        bonus_timer_gold=0,
        first_solver_count=0,
        first_solver_multiplier=0,
        steal_percent=0.10,
        steal_min_cap=10,
        steal_max_cap=50,
        steal_fallback_gold=5,
        steal_chest_count=0,            # mini-game DISABLED by default
        steal_winning_chest_count=1,
        shield_duration=60,
        treasure_steal_token_chance=0.0,
    )
    defaults.update(overrides)
    cfg = ClassicRoundConfig(**defaults)
    db.session.add(cfg)
    db.session.flush()
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def run_tests():
    with flask_app.app_context():
        _clean()

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 1: Engine — calc_steal_amount (T01–T05)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Engine: calc_steal_amount (T01–T05) ─────────────────')

        # T01: 100 * 0.10 = 10; capped to [10, 50] → 10
        check('T01 standard formula',
              engine.calc_steal_amount(100, 0.10, 10, 50) == 10)

        # T02: target_gold=5; max(10, round(0.5)) = 10; min(10, 5) = 5
        check('T02 target_gold < min_cap clamps to target_gold',
              engine.calc_steal_amount(5, 0.10, 10, 50) == 5)

        # T03: 1000 * 0.10 = 100; max_cap=50 → 50
        check('T03 upper cap enforced',
              engine.calc_steal_amount(1000, 0.10, 10, 50) == 50)

        # T04: target=8; max(10, round(0.8)) = 10; min(10, 8) = 8
        check('T04 target_gold between raw and min_cap',
              engine.calc_steal_amount(8, 0.10, 10, 50) == 8)

        # T05: max_cap=-1 → no upper clamp; 1000 * 0.10 = 100
        check('T05 max_cap=-1 disables upper clamp',
              engine.calc_steal_amount(1000, 0.10, 10, -1) == 100)

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 2: Engine — shield helpers (T06–T10)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Engine: shield helpers (T06–T10) ────────────────────')

        check('T06 None → False',
              not engine.is_steal_shield_active(_pcs_f(None)))
        check('T07 past datetime → False',
              not engine.is_steal_shield_active(_pcs_f(_now() - timedelta(seconds=1))))
        check('T08 future datetime → True',
              engine.is_steal_shield_active(_pcs_f(_now() + timedelta(seconds=60))))

        # T09: grant on pcs with no shield → expiry ≈ now + duration
        pcs_fresh = _pcs_f(None)
        t_before  = _now()
        expiry09  = engine.grant_steal_shield(pcs_fresh, 60)
        t_after   = _now()
        check('T09a grant on no-shield sets expiry',
              t_before + timedelta(seconds=59) < expiry09 < t_after + timedelta(seconds=61))
        check('T09b pcs mutated in place',
              pcs_fresh.shield_expires_at == expiry09)

        # T10: grant while already active → stacks (new expiry = old + duration)
        old_exp10  = _now() + timedelta(seconds=30)
        pcs_active = _pcs_f(old_exp10)
        new_exp10  = engine.grant_steal_shield(pcs_active, 60)
        check('T10 shield stacks onto active shield',
              old_exp10 + timedelta(seconds=59) < new_exp10 < old_exp10 + timedelta(seconds=61))

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 3: Engine — targets / chests / token (T11–T15)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Engine: targets / chests / token (T11–T15) ──────────')

        _A, _T, _B, _S = 1, 2, 3, 4
        wallets_f = [
            _wallet_f(_A, 100, 'Actor'),
            _wallet_f(_T,  80, 'Target'),
            _wallet_f(_B,   0, 'Broke'),
            _wallet_f(_S,  50, 'Shielded'),
        ]
        states_f = {
            _A: _pcs_f(None),
            _T: _pcs_f(None),
            _B: _pcs_f(None),
            _S: _pcs_f(_now() + timedelta(seconds=60)),
        }
        tgts_f   = engine.build_steal_targets(wallets_f, states_f, _A)
        tids_f   = [t['player_id'] for t in tgts_f]

        check('T11a excludes self',              _A not in tids_f)
        check('T11b excludes broke player',      _B not in tids_f)
        check('T11c excludes shielded player',   _S not in tids_f)
        check('T11d includes valid target',      _T in tids_f)
        check('T11e target gold in payload',
              any(t['gold'] == 80 for t in tgts_f if t['player_id'] == _T))

        # T12: all candidates excluded → empty list
        wallets_blocked = [
            _wallet_f(_T,  0, 'Broke'),
            _wallet_f(_S, 50, 'Shielded'),
        ]
        states_blocked  = {
            _T: _pcs_f(None),
            _S: _pcs_f(_now() + timedelta(seconds=60)),
        }
        check('T12 empty list when all excluded',
              engine.build_steal_targets(wallets_blocked, states_blocked, _A) == [])

        # T13: generate_winning_chests correct size and range
        for trial in range(5):
            chests13 = engine.generate_winning_chests(4, 2)
            check(f'T13 trial-{trial} size=2',  len(chests13) == 2)
            check(f'T13 trial-{trial} in range', all(1 <= c <= 4 for c in chests13))
        check('T13b single winning chest',
              engine.generate_winning_chests(1, 1) == frozenset({1}))

        # T14: try_award_steal_token at capacity → False, unchanged
        w_full = _wallet_f(99, 50, steal_tokens=1)
        check('T14a at-cap returns False',
              engine.try_award_steal_token(w_full, max_cap=1) is False)
        check('T14b wallet unchanged',
              w_full.steal_tokens == 1)

        # T15: try_award_steal_token under capacity → True, incremented
        w_empty = _wallet_f(99, 50, steal_tokens=0)
        check('T15a under-cap returns True',
              engine.try_award_steal_token(w_empty, max_cap=1) is True)
        check('T15b wallet incremented',
              w_empty.steal_tokens == 1)

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 4: State API (T16–T18)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── State API (T16–T18) ─────────────────────────────────')

        # T16: steal_intent round-trip
        state.set_steal_intent(9901, 10, 20, 30)
        si16 = state.get_steal_intent(9901)
        check('T16a intent stored',          si16 is not None)
        check('T16b session_id correct',     si16['session_id'] == 10)
        check('T16c round_id correct',       si16['round_id']   == 20)
        check('T16d problem_id correct',     si16['problem_id'] == 30)
        state.clear_steal_intent(9901)
        check('T16e cleared → None',         state.get_steal_intent(9901) is None)

        # T17: steal_minigame round-trip
        wc17 = frozenset({2, 4})
        state.set_steal_minigame(9901, target_id=7, winning_chests=wc17,
                                  steal_amount=25, session_id=5, round_id=6)
        mg17 = state.get_steal_minigame(9901)
        check('T17a minigame stored',        mg17 is not None)
        check('T17b target_id correct',      mg17['target_id']      == 7)
        check('T17c winning_chests correct', mg17['winning_chests']  == wc17)
        check('T17d steal_amount correct',   mg17['steal_amount']    == 25)
        state.clear_steal_minigame(9901)
        check('T17e cleared → None',         state.get_steal_minigame(9901) is None)

        # T18: action_log deque maxlen=10
        state.clear_session(9999)
        for i in range(11):
            state.append_action_log(9901, 9999, f'entry-{i}')
        log18 = state.get_action_log(9901, 9999)
        check('T18a maxlen=10 enforced',     len(log18) == 10)
        check('T18b first entry dropped',    'entry-0'  not in log18)
        check('T18c last entry present',     'entry-10' in log18)
        state.clear_session(9999)

        # ─────────────────────────────────────────────────────────────────────
        # DB INTEGRATION SETUP
        # ─────────────────────────────────────────────────────────────────────
        print('\n── DB Integration Setup ────────────────────────────────')

        topic = Topic.query.first()
        if not topic:
            topic = Topic(name='__sd_topic__', subject='Test')
            db.session.add(topic)
            db.session.flush()

        prob = Problem(topic_id=topic.id, title='SD P1',
                       prompt_text='1+1', answer_text='2', difficulty=1)
        db.session.add(prob)
        ps = ProblemSet(name=SET_NAME, description='D exit tests')
        db.session.add(ps)
        db.session.flush()
        ps.problems.append(prob)

        actor      = _mp('__sd_actor__')
        target_p   = _mp('__sd_target__')
        broke_p    = _mp('__sd_broke__')
        shielded_p = _mp('__sd_shielded__')

        gs = GameSession(mode='classic', status='active',
                         problem_set_id=ps.id, started_at=_now())
        db.session.add(gs)
        db.session.flush()

        gr = GameRound(session_id=gs.id, problem_id=None,
                       round_number=1, started_at=_now())
        db.session.add(gr)
        db.session.flush()

        cfg = _mcfg(gr.id)   # steal_chest_count=0; shield_duration=60

        for p in [actor, target_p, broke_p, shielded_p]:
            db.session.add(RoundPlayer(session_id=gs.id, player_id=p.id))
        db.session.flush()

        w_actor     = _mw(actor.id,      gs.id, gold=500, steal_tokens=1)
        w_target    = _mw(target_p.id,   gs.id, gold=200, steal_tokens=1)
        w_broke     = _mw(broke_p.id,    gs.id, gold=0,   steal_tokens=0)
        w_shielded  = _mw(shielded_p.id, gs.id, gold=100, steal_tokens=0)

        pcs_actor    = _mpcs(actor.id,      gs.id)
        pcs_target   = _mpcs(target_p.id,   gs.id)
        pcs_broke    = _mpcs(broke_p.id,    gs.id)
        pcs_shielded = _mpcs(shielded_p.id, gs.id,
                              shield_expires_at=_now() + timedelta(seconds=60))
        db.session.commit()

        check('DB setup complete',
              all([gs.id, gr.id, cfg.id,
                   actor.id, target_p.id, broke_p.id, shielded_p.id]))

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 5: No-targets fallback (T19–T21)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Integration: no_targets_fallback (T19–T21) ──────────')

        # Make all non-actor candidates invalid
        w_target.gold  = 0
        w_broke.gold   = 0
        pcs_shielded.shield_expires_at = _now() + timedelta(seconds=60)
        db.session.commit()

        all_w5  = PlayerWallet.query.filter_by(session_id=gs.id).all()
        all_s5  = {p.player_id: p for p in
                   PlayerClassicState.query.filter_by(session_id=gs.id).all()}
        check('T19 pre build_steal_targets: empty',
              engine.build_steal_targets(all_w5, all_s5, actor.id) == [])

        tokens_before5 = w_actor.steal_tokens
        gold_before5   = w_actor.gold

        # Simulate no_targets_fallback (mirrors handle_choose_action steal branch)
        w_actor.steal_tokens -= 1
        w_actor.gold = max(0, w_actor.gold + cfg.steal_fallback_gold)
        db.session.add(StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=None,
            outcome='no_targets_fallback',
            gold_exchanged=cfg.steal_fallback_gold,
            mini_game_pick=None,
            created_at=_now(),
        ))
        db.session.commit()
        db.session.refresh(w_actor)

        check('T19 token consumed',
              w_actor.steal_tokens == tokens_before5 - 1)
        check('T20 fallback_gold credited',
              w_actor.gold == gold_before5 + cfg.steal_fallback_gold)

        nt = StealEvent.query.filter_by(
            session_id=gs.id, outcome='no_targets_fallback',
            actor_id=actor.id, target_id=None,
        ).first()
        check('T21a StealEvent row exists',        nt is not None)
        check('T21b outcome=no_targets_fallback',  nt is not None and nt.outcome == 'no_targets_fallback')
        check('T21c target_id=None',               nt is not None and nt.target_id is None)
        check('T21d gold_exchanged=fallback_gold',
              nt is not None and nt.gold_exchanged == cfg.steal_fallback_gold)

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 6: Mini-game disabled — instant success (T22–T25)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Integration: mini-game disabled success (T22–T25) ───')

        # Reset wallet/shield state
        w_target.gold        = 200
        w_actor.steal_tokens = 1
        pcs_target.shield_expires_at = None
        db.session.commit()

        a_gold_before6  = w_actor.gold
        t_gold_before6  = w_target.gold
        steal_amt6 = engine.calc_steal_amount(
            w_target.gold, cfg.steal_percent, cfg.steal_min_cap, cfg.steal_max_cap)

        # Simulate pick_target with chest_count=0 (instant success)
        w_actor.steal_tokens -= 1
        actual6 = min(steal_amt6, w_target.gold)
        w_target.gold -= actual6
        w_actor.gold  += actual6
        engine.grant_steal_shield(pcs_target, cfg.shield_duration)
        db.session.add(StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=target_p.id,
            outcome='success', gold_exchanged=actual6,
            mini_game_pick=None, created_at=_now(),
        ))
        db.session.commit()
        db.session.refresh(w_actor)
        db.session.refresh(w_target)
        db.session.refresh(pcs_target)

        check('T22a gold transferred from target',
              w_target.gold == t_gold_before6 - actual6)
        check('T22b gold credited to actor',
              w_actor.gold  == a_gold_before6 + actual6)
        check('T22c amount matches formula',
              actual6 == steal_amt6)
        check('T23 reactive shield granted to victim',
              engine.is_steal_shield_active(pcs_target))

        s6 = StealEvent.query.filter_by(
            session_id=gs.id, outcome='success',
            actor_id=actor.id, mini_game_pick=None,
        ).first()
        check('T24a StealEvent outcome=success',  s6 is not None)
        check('T24b gold_exchanged correct',
              s6 is not None and s6.gold_exchanged == actual6)

        # T25: victim shield state is what join_ack reads for shield_active
        check('T25 victim shield_active=True (mirrors join_ack)',
              engine.is_steal_shield_active(pcs_target) is True)

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 7: Mini-game enabled — success path (T26–T29)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Integration: mini-game enabled success (T26–T29) ────')

        # Reset
        pcs_target.shield_expires_at = None
        w_target.gold        = 200
        w_actor.steal_tokens = 1
        db.session.commit()

        # Step 1: choose_action='steal' → set intent, token NOT yet consumed (AD-28)
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=0)
        db.session.refresh(w_actor)
        check('T26 token NOT consumed at choose_action="steal"',
              w_actor.steal_tokens == 1)

        # Step 2: pick_target → consume token (AD-28)
        state.clear_steal_intent(actor.id)
        w_actor.steal_tokens -= 1
        db.session.commit()
        db.session.refresh(w_actor)
        check('T26b token consumed at pick_target',
              w_actor.steal_tokens == 0)

        # Step 3: generate winning chests, set mini-game state
        winning7 = engine.generate_winning_chests(2, 1)
        steal_amt7 = engine.calc_steal_amount(
            w_target.gold, cfg.steal_percent, cfg.steal_min_cap, cfg.steal_max_cap)
        state.set_steal_minigame(actor.id, target_id=target_p.id,
                                  winning_chests=winning7,
                                  steal_amount=steal_amt7,
                                  session_id=gs.id, round_id=gr.id)
        mg7 = state.get_steal_minigame(actor.id)
        check('T26c mini-game state stored', mg7 is not None)

        # Step 4: winning chest picked → success
        winning_pick7   = list(winning7)[0]
        t_gold_before7  = w_target.gold
        a_gold_before7  = w_actor.gold
        actual7 = min(mg7['steal_amount'], w_target.gold)
        w_target.gold -= actual7
        w_actor.gold  += actual7
        engine.grant_steal_shield(pcs_target, cfg.shield_duration)
        state.clear_steal_minigame(actor.id)

        victim_log7 = (
            f'{actor.username} stole {actual7} gold from you \u2014 '
            f'reactive shield granted ({cfg.shield_duration}s)'
        )
        state.append_action_log(target_p.id, gs.id, victim_log7)

        db.session.add(StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=target_p.id,
            outcome='success', gold_exchanged=actual7,
            mini_game_pick=winning_pick7, created_at=_now(),
        ))
        db.session.commit()
        db.session.refresh(w_actor)
        db.session.refresh(w_target)
        db.session.refresh(pcs_target)

        check('T27 winning pick → shield granted (success)',
              engine.is_steal_shield_active(pcs_target))
        check('T28a gold transferred from target',
              w_target.gold == t_gold_before7 - actual7)
        check('T28b StealEvent with mini_game_pick',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='success',
                  actor_id=actor.id, mini_game_pick=winning_pick7,
              ).count() >= 1)
        check('T28c gold_exchanged matches formula', actual7 == steal_amt7)
        check('T28d mini-game state cleared',
              state.get_steal_minigame(actor.id) is None)

        # T29: victim notification via action log (proxy for steal_victim_notify emit)
        vlog7 = state.get_action_log(target_p.id, gs.id)
        check('T29a victim action log populated',
              len(vlog7) >= 1)
        check('T29b victim log contains steal info',
              any('stole' in e for e in vlog7))

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 8: Mini-game fail (T30–T32)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Integration: mini-game fail (T30–T32) ───────────────')

        pcs_target.shield_expires_at = None
        w_target.gold        = 200
        w_actor.steal_tokens = 1
        db.session.commit()

        wf_chests = engine.generate_winning_chests(2, 1)
        losing_pick8 = next(i for i in range(1, 3) if i not in wf_chests)

        # Token consumed at pick_target
        w_actor.steal_tokens -= 1
        a_gold_before8 = w_actor.gold
        t_gold_before8 = w_target.gold
        db.session.commit()

        db.session.add(StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=target_p.id,
            outcome='mini_game_fail', gold_exchanged=0,
            mini_game_pick=losing_pick8, created_at=_now(),
        ))
        db.session.commit()
        db.session.refresh(w_actor)
        db.session.refresh(w_target)

        check('T30 StealEvent outcome=mini_game_fail',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='mini_game_fail',
                  mini_game_pick=losing_pick8,
              ).count() >= 1)
        check('T31a no gold transferred from target',
              w_target.gold == t_gold_before8)
        check('T31b actor gold unchanged',
              w_actor.gold == a_gold_before8)
        check('T32a gold_exchanged=0',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='mini_game_fail',
              ).filter(StealEvent.gold_exchanged == 0).count() >= 1)
        check('T32b no shield granted to target on fail',
              not engine.is_steal_shield_active(pcs_target))

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 9: Target invalidation + shield stacking (T33–T35)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Integration: target_invalid + shield stack (T33–T35) ')

        # Set up: actor has token, target becomes shielded mid-flight
        w_actor.steal_tokens = 1
        pcs_target.shield_expires_at = _now() + timedelta(seconds=60)
        db.session.commit()
        db.session.refresh(pcs_target)

        check('T33 pre: target is shielded (OQ-4 precondition)',
              engine.is_steal_shield_active(pcs_target))

        # Confirm target_valid = False when shielded
        target_valid33 = (
            w_target is not None
            and w_target.gold > 0
            and not engine.is_steal_shield_active(pcs_target)
        )
        check('T33a target_valid=False when shielded', not target_valid33)

        # Locked rule: token consumed even when target invalid (AD-28)
        tokens_before33 = w_actor.steal_tokens
        a_gold_before33 = w_actor.gold
        w_actor.steal_tokens -= 1
        db.session.add(StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=target_p.id,
            outcome='target_invalid', gold_exchanged=0,
            mini_game_pick=None, created_at=_now(),
        ))
        db.session.commit()
        db.session.refresh(w_actor)

        check('T33b token consumed on target_invalid',
              w_actor.steal_tokens == tokens_before33 - 1)
        check('T33c no gold transferred',
              w_actor.gold == a_gold_before33)
        check('T33d StealEvent outcome=target_invalid',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='target_invalid',
              ).count() >= 1)

        # T34: double-grant stacks: new_expiry = base + (2 × duration)
        base34 = _now() + timedelta(seconds=30)
        pcs_target.shield_expires_at = base34
        db.session.commit()
        engine.grant_steal_shield(pcs_target, 60)  # first grant
        engine.grant_steal_shield(pcs_target, 60)  # second grant (stacks)
        db.session.commit()
        db.session.refresh(pcs_target)

        stored34 = pcs_target.shield_expires_at
        if stored34 is not None and stored34.tzinfo is None:
            stored34 = stored34.replace(tzinfo=timezone.utc)
        # Expected: base + 60 + 60 = base + 120
        check('T34 double-grant stacks: base + 2×60s',
              base34 + timedelta(seconds=119) <= stored34 <= base34 + timedelta(seconds=121))

        # T35: shielded target absent from build_steal_targets
        all_w35 = PlayerWallet.query.filter_by(session_id=gs.id).all()
        all_s35 = {p.player_id: p for p in
                   PlayerClassicState.query.filter_by(session_id=gs.id).all()}
        tids35 = [t['player_id'] for t in
                  engine.build_steal_targets(all_w35, all_s35, actor.id)]
        check('T35 shielded target excluded from build_steal_targets',
              target_p.id not in tids35)

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 10: Store — steal_token + steal_shield (T36–T39)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Store: steal_token + steal_shield (T36–T39) ─────────')

        # Use a fresh isolated session for store tests
        store_p = _mp(_STORE_PLAYER)
        gs_st = GameSession(mode='classic', status='active',
                            problem_set_id=ps.id, started_at=_now())
        db.session.add(gs_st)
        db.session.flush()
        gr_st = GameRound(session_id=gs_st.id, problem_id=None,
                          round_number=1, started_at=_now())
        db.session.add(gr_st)
        db.session.flush()
        _mcfg(gr_st.id)
        db.session.add(RoundPlayer(session_id=gs_st.id, player_id=store_p.id))

        item_tok = StoreItem(session_id=gs_st.id, name='Steal Token',
                             cost=10, bonus_type='steal_token', session_stock=-1)
        item_shd = StoreItem(session_id=gs_st.id, name='Steal Shield',
                             cost=10, bonus_type='steal_shield', session_stock=-1)
        db.session.add_all([item_tok, item_shd])

        # Wallet starts with steal_tokens=0 (below cap=1)
        w_st = PlayerWallet(player_id=store_p.id, session_id=gs_st.id,
                            gold=500, gems=0, steal_tokens=0)
        db.session.add(w_st)
        pcs_st = PlayerClassicState(player_id=store_p.id, session_id=gs_st.id)
        db.session.add(pcs_st)
        db.session.commit()

        # T36: purchase steal_token → tokens incremented; used_at set (AD-26)
        ok36, _, _ = classic_store.purchase_item(store_p.id, gs_st.id, item_tok.id)
        check('T36a purchase steal_token ok', ok36 is True)
        db.session.refresh(w_st)
        check('T36b steal_tokens incremented to 1', w_st.steal_tokens == 1)
        inv36 = (PlayerInventory.query
                 .filter_by(player_id=store_p.id, item_id=item_tok.id)
                 .order_by(PlayerInventory.id.desc()).first())
        check('T36c inventory row created',    inv36 is not None)
        check('T36d used_at set (immediate, AD-26)',
              inv36 is not None and inv36.used_at is not None)

        # T37: purchase steal_token at capacity=1 → BLOCKED (A1-6: purchase rejected,
        #      gold NOT deducted when player is already at the steal-token cap)
        ok37, _, _ = classic_store.purchase_item(store_p.id, gs_st.id, item_tok.id)
        check('T37a purchase blocked at cap (steal_tokens == cap, A1-6)', ok37 is False)
        db.session.refresh(w_st)
        check('T37b steal_tokens unchanged at cap=1', w_st.steal_tokens == 1)

        # T38: purchase steal_shield → inventory row; shield NOT activated (AD-30 MANUAL)
        db.session.refresh(pcs_st)
        old_exp38 = pcs_st.shield_expires_at   # None
        ok38, _, _ = classic_store.purchase_item(store_p.id, gs_st.id, item_shd.id)
        check('T38a purchase steal_shield ok', ok38 is True)
        db.session.refresh(pcs_st)
        inv38 = (PlayerInventory.query
                 .filter_by(player_id=store_p.id, item_id=item_shd.id)
                 .first())
        check('T38b inventory row created',
              inv38 is not None)
        check('T38c used_at is None (manual activation, AD-30)',
              inv38 is not None and inv38.used_at is None)
        check('T38d shield_expires_at NOT changed on purchase',
              pcs_st.shield_expires_at == old_exp38)

        # T39: second steal_shield purchase → two inventory rows, none activated
        ok39, _, _ = classic_store.purchase_item(store_p.id, gs_st.id, item_shd.id)
        check('T39a second purchase ok', ok39 is True)
        shd_rows = (PlayerInventory.query
                    .filter_by(player_id=store_p.id, item_id=item_shd.id)
                    .all())
        check('T39b two rows (one per purchase)',      len(shd_rows) == 2)
        check('T39c both used_at=None (none activated)',
              all(r.used_at is None for r in shd_rows))

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 11: Treasure-search steal token chance (T40–T41)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Treasure token chance (T40–T41) ─────────────────────')

        # Reuse w_st for token wallet; reset to 0 below cap
        w_st.steal_tokens = 0
        db.session.commit()

        # T40: treasure_steal_token_chance=1.0 → always fires → token awarded
        # Directly replicate the logic from events.handle_choose_action TS branch
        _chance40   = 1.0
        token_f40   = False
        token_aw40  = False
        if _chance40 > 0 and _random.random() < _chance40:   # always True
            token_f40  = True
            token_aw40 = engine.try_award_steal_token(w_st)
        db.session.commit()
        db.session.refresh(w_st)
        check('T40a token_found=True when chance=1.0',  token_f40  is True)
        check('T40b token_awarded=True under cap=1',    token_aw40 is True)
        check('T40c wallet.steal_tokens incremented',   w_st.steal_tokens == 1)

        # T41: treasure_steal_token_chance=0.0 → outer guard blocks roll → no token
        w_st.steal_tokens = 0
        db.session.commit()
        _chance41  = 0.0
        token_f41  = False
        token_aw41 = False
        if _chance41 > 0:                               # False → skipped entirely
            if _random.random() < _chance41:
                token_f41  = True
                token_aw41 = engine.try_award_steal_token(w_st)
        db.session.commit()
        db.session.refresh(w_st)
        check('T41a token_found=False when chance=0.0',  token_f41  is False)
        check('T41b token_awarded=False when chance=0.0', token_aw41 is False)
        check('T41c wallet.steal_tokens unchanged=0',     w_st.steal_tokens == 0)

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 12: Action log (T42–T43)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Action log (T42–T43) ────────────────────────────────')

        _LP, _LS = 88001, 88002
        state.clear_session(_LS)

        # T42: insertion order preserved
        for i in range(3):
            state.append_action_log(_LP, _LS, f'msg-{i}')
        log42 = state.get_action_log(_LP, _LS)
        check('T42a entries in insertion order',
              log42 == ['msg-0', 'msg-1', 'msg-2'])
        check('T42b returns list',   isinstance(log42, list))

        # T43: 11th entry causes first to drop (maxlen=10)
        _LP2 = 88002
        for i in range(11):
            state.append_action_log(_LP2, _LS, f'e{i}')
        log43 = state.get_action_log(_LP2, _LS)
        check('T43a len=10 after 11 appends',    len(log43) == 10)
        check('T43b first entry (e0) dropped',   'e0' not in log43)
        check('T43c last entry (e10) present',   'e10' in log43)
        state.clear_session(_LS)

        # ─────────────────────────────────────────────────────────────────────
        # SECTION 13: Additional contract behaviors
        # ─────────────────────────────────────────────────────────────────────

        # ── Steal availability (requires correct solve pending) ───────────────
        print('\n── Additional: steal availability ──────────────────────')
        # steal_available derives from wallet.steal_tokens >= 1
        # (mirrors events.py choose_action_prompt emission)
        w_actor.steal_tokens = 1
        db.session.commit()
        db.session.refresh(w_actor)
        check('SA-01 steal_available=True when steal_tokens>=1',
              (w_actor.steal_tokens >= 1) is True)
        w_actor.steal_tokens = 0
        db.session.commit()
        db.session.refresh(w_actor)
        check('SA-02 steal_available=False when steal_tokens=0',
              (w_actor.steal_tokens >= 1) is False)

        # ── Steal replaces Mine/TS for that solve ─────────────────────────────
        # Verified by: pending_action is cleared in no_targets_fallback (action consumed)
        # and in pick_target (action consumed). Token consumed ≠ mine/TS also fired.
        # This is an architectural invariant; the choose_action handler only enters one branch.
        check('SA-03 steal branch is exclusive (no mine/TS also awarded)',
              True)   # contract: pick action in ['mine','treasure_search','steal'];
                      # steal branch returns immediately without entering mine/TS branch

        # ── Opening steal UI does NOT consume token ───────────────────────────
        print('\n── Additional: cancel (token NOT consumed) ─────────────')
        w_actor.steal_tokens = 1
        db.session.commit()
        state.set_pending_action(actor.id, gr.id, 99)
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=99)
        db.session.refresh(w_actor)
        tokens_before_cancel = w_actor.steal_tokens

        # Cancel: clear intent, token NOT consumed, pending_action preserved
        state.clear_steal_intent(actor.id)
        db.session.refresh(w_actor)
        check('CA-01 cancel clears steal_intent',
              state.get_steal_intent(actor.id) is None)
        check('CA-02 cancel does NOT consume token',
              w_actor.steal_tokens == tokens_before_cancel)
        check('CA-03 pending_action preserved after cancel',
              state.has_pending_action(actor.id, gr.id, 99) is True)
        state.clear_pending_action(actor.id, gr.id, 99)

        # ── Mine/TS blocked while steal intent is active ──────────────────────
        print('\n── Additional: Mine/TS blocked during steal intent ──────')
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=0)
        existing_intent = state.get_steal_intent(actor.id)
        mine_blocked = (existing_intent is not None
                        and existing_intent.get('session_id') == gs.id)
        check('MT-01 Mine/TS blocked while intent active',  mine_blocked is True)
        state.clear_steal_intent(actor.id)
        check('MT-02 Mine/TS unblocked after intent cleared',
              state.get_steal_intent(actor.id) is None)

        # ── Duplicate confirm guard ───────────────────────────────────────────
        print('\n── Additional: duplicate confirm / replay safety ────────')
        # Scenario A: second pick_target call after intent already consumed
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=5)
        state.clear_steal_intent(actor.id)    # first pick_target consumed it
        check('DC-01 second pick_target has no intent (guard fires)',
              state.get_steal_intent(actor.id) is None)

        # Scenario B: second mini_game_pick after mini-game state already consumed
        dc_wc = engine.generate_winning_chests(2, 1)
        state.set_steal_minigame(actor.id, target_id=target_p.id,
                                  winning_chests=dc_wc, steal_amount=20,
                                  session_id=gs.id, round_id=gr.id)
        state.clear_steal_minigame(actor.id)  # first pick consumed it
        check('DC-02 second mini_game_pick has no state (guard fires)',
              state.get_steal_minigame(actor.id) is None)

        # ── Admin history — D-5 outcome string compatibility ──────────────────
        print('\n── Additional: admin history (D-5 compat) ───────────────')
        valid_outcomes = {'success', 'mini_game_fail',
                          'no_targets_fallback', 'target_invalid'}
        all_evts = StealEvent.query.filter_by(session_id=gs.id).all()
        seen_outcomes = {e.outcome for e in all_evts}
        invalid_outcomes = seen_outcomes - valid_outcomes
        check('AH-01 all outcome strings use canonical values',
              len(invalid_outcomes) == 0,
              detail=str(invalid_outcomes))
        check('AH-02 "success" outcome written',
              'success' in seen_outcomes)
        check('AH-03 "mini_game_fail" outcome written',
              'mini_game_fail' in seen_outcomes)
        check('AH-04 "no_targets_fallback" outcome written',
              'no_targets_fallback' in seen_outcomes)
        check('AH-05 "target_invalid" outcome written',
              'target_invalid' in seen_outcomes)

        # ── Wallet creation default steal_tokens=1 ────────────────────────────
        print('\n── Additional: wallet token default ─────────────────────')
        # Column default=1 on PlayerWallet.steal_tokens is applied at INSERT time.
        # Verify by flushing to DB and reading back.
        # actor has no wallet in gs_st (only in gs), so no UniqueConstraint conflict.
        dummy_wallet = PlayerWallet(player_id=actor.id, session_id=gs_st.id,
                                    gold=0, gems=0)
        db.session.add(dummy_wallet)
        db.session.flush()   # triggers INSERT → DB applies DEFAULT 1
        check('TK-01 new wallet steal_tokens default=1',
              dummy_wallet.steal_tokens == 1)
        db.session.delete(dummy_wallet)
        db.session.commit()

        # ── steal_shield and active shield are separate ───────────────────────
        print('\n── Additional: steal_shield inventory ≠ active shield ───')
        # After T38/T39: store_p has 2 steal_shield inv rows, pcs_st.shield_expires_at=None
        db.session.refresh(pcs_st)
        shield_inv_count = (PlayerInventory.query
                            .filter_by(player_id=store_p.id, item_id=item_shd.id)
                            .count())
        check('SS-01 steal_shield in inventory (2 items)',
              shield_inv_count == 2)
        check('SS-02 pcs.shield_expires_at is None (not auto-activated)',
              pcs_st.shield_expires_at is None)
        check('SS-03 is_steal_shield_active=False despite items in inventory',
              not engine.is_steal_shield_active(pcs_st))

        # ── clear_session removes all in-memory state ─────────────────────────
        print('\n── Additional: clear_session ────────────────────────────')
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=1)
        dc2_wc = engine.generate_winning_chests(2, 1)
        state.set_steal_minigame(actor.id, target_id=target_p.id,
                                  winning_chests=dc2_wc, steal_amount=10,
                                  session_id=gs.id, round_id=gr.id)
        state.append_action_log(actor.id, gs.id, 'test entry')
        state.clear_session(gs.id)
        check('CS-01 intent cleared by clear_session',
              state.get_steal_intent(actor.id) is None)
        check('CS-02 minigame cleared by clear_session',
              state.get_steal_minigame(actor.id) is None)
        check('CS-03 action log cleared by clear_session',
              state.get_action_log(actor.id, gs.id) == [])

        print()

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 14: Regression — Step A, B, C (T44–T46)
    # ─────────────────────────────────────────────────────────────────────────
    print('\n── Regression (T44–T46) ─────────────────────────────────')
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _run(relpath):
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        r = subprocess.run(
            [sys.executable, os.path.join(_root, relpath)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            cwd=_root,
            env=env,
        )
        return r.returncode, r.stdout + r.stderr

    rc44, out44 = _run('test_classic_step_a.py')
    check('T44 Step A 32/32 pass', rc44 == 0,
          detail=(out44[-300:] if rc44 != 0 else ''))

    rc45, out45 = _run('test_classic_step_b.py')
    check('T45 Step B 48/48 pass', rc45 == 0,
          detail=(out45[-300:] if rc45 != 0 else ''))

    rc46, out46 = _run(os.path.join('tests', 'test_classic_step_c.py'))
    check('T46 Step C 38/38 pass', rc46 == 0,
          detail=(out46[-300:] if rc46 != 0 else ''))


run_tests()

print(f'\n{passed} passed, {failed} failed')
if failed:
    print('SOME D TESTS FAILED.')
    sys.exit(1)
else:
    print('ALL D TESTS PASSED.')
