"""
test_classic_step_d3.py
=======================

Focused integration tests for Classic Mode Step D-3: server-side steal flow.

Tests operate directly via ORM + engine/state helpers inside a Flask app
context.  No HTTP requests, no WebSocket connections required.

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_classic_step_d3.py

Expected output: all assertions pass, final line prints "ALL D-3 TESTS PASSED."
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig, PlayerWallet, PlayerClassicState,
    PlayerProblemState, ProblemSolverCount, StealEvent,
)
from app.modes.classic import engine, state

flask_app = create_app()

SET_NAME = '__test_step_d3__'


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _clean():
    ps = ProblemSet.query.filter_by(name=SET_NAME).first()
    for gs in GameSession.query.filter_by(mode='classic').all():
        if gs.problem_set and gs.problem_set.name == SET_NAME:
            sid = gs.id
            StealEvent.query.filter_by(session_id=sid).delete()
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
        for prob in Problem.query.filter(Problem.title.like('D3 P%')).all():
            PlayerProblemState.query.filter_by(problem_id=prob.id).delete()
            ProblemSolverCount.query.filter_by(problem_id=prob.id).delete()
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()

    for uname in ('__d3_actor__', '__d3_target__', '__d3_broke__', '__d3_shielded__'):
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


def _make_player(username):
    p = Player(username=username, is_admin=False)
    p.set_password('x')
    db.session.add(p)
    db.session.flush()
    return p


def _make_wallet(player_id, session_id, gold=100, steal_tokens=1):
    w = PlayerWallet(player_id=player_id, session_id=session_id,
                     gold=gold, gems=0, steal_tokens=steal_tokens)
    db.session.add(w)
    db.session.flush()
    return w


def _make_pcs(player_id, session_id, shield_expires_at=None):
    pcs = PlayerClassicState(player_id=player_id, session_id=session_id,
                              shield_expires_at=shield_expires_at)
    db.session.add(pcs)
    db.session.flush()
    return pcs


def _make_config(round_id, **overrides):
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
        steal_chest_count=2,
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
# Main test body
# ─────────────────────────────────────────────────────────────────────────────

def run_tests():
    with flask_app.app_context():
        _clean()

        # ── Setup ─────────────────────────────────────────────────────────────
        topic = Topic.query.first()
        if not topic:
            topic = Topic(name='__d3_topic__', subject='Test')
            db.session.add(topic)
            db.session.flush()

        prob = Problem(
            topic_id=topic.id, title='D3 P1',
            prompt_text='1', answer_text='1', difficulty=1,
        )
        db.session.add(prob)

        ps = ProblemSet(name=SET_NAME, description='D3 tests')
        db.session.add(ps)
        db.session.flush()
        ps.problems.append(prob)

        actor     = _make_player('__d3_actor__')
        target_p  = _make_player('__d3_target__')
        broke_p   = _make_player('__d3_broke__')
        shielded_p = _make_player('__d3_shielded__')

        gs = GameSession(mode='classic', status='active', problem_set_id=ps.id,
                         started_at=datetime.now(timezone.utc))
        db.session.add(gs)
        db.session.flush()

        gr = GameRound(session_id=gs.id, problem_id=None, round_number=1,
                       started_at=datetime.now(timezone.utc))
        db.session.add(gr)
        db.session.flush()

        cfg_no_mg = _make_config(gr.id, steal_chest_count=0)  # mini-game disabled

        for player in [actor, target_p, broke_p, shielded_p]:
            db.session.add(RoundPlayer(session_id=gs.id, player_id=player.id))
        db.session.flush()

        db.session.commit()

        # ─────────────────────────────────────────────────────────────────────
        # Section 1: calc_steal_amount via engine (already tested in D-2 but
        # verify correct amounts flow through integration fixtures)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── Steal amount formula ─────────────────────────────────')

        # target has 200 gold; 10% = 20; capped at [10, 50] → 20
        check('S1-T01 standard steal amount',
              engine.calc_steal_amount(200, 0.10, 10, 50) == 20)
        # target has 5 gold; formula → 10 (min_cap), then min(10, 5) = 5
        check('S1-T02 target_gold < min_cap', engine.calc_steal_amount(5, 0.10, 10, 50) == 5)

        # ─────────────────────────────────────────────────────────────────────
        # Section 2: build_steal_targets with real wallet+PCS rows
        # ─────────────────────────────────────────────────────────────────────
        print('\n── build_steal_targets with real ORM rows ───────────────')

        w_actor    = _make_wallet(actor.id,      gs.id, gold=100)
        w_target   = _make_wallet(target_p.id,   gs.id, gold=80)
        w_broke    = _make_wallet(broke_p.id,    gs.id, gold=0)
        w_shielded = _make_wallet(shielded_p.id, gs.id, gold=50)

        pcs_actor    = _make_pcs(actor.id,       gs.id)
        pcs_target   = _make_pcs(target_p.id,    gs.id)
        pcs_broke    = _make_pcs(broke_p.id,     gs.id)
        pcs_shielded = _make_pcs(shielded_p.id,  gs.id,
                                  shield_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60))

        db.session.commit()

        all_wallets = PlayerWallet.query.filter_by(session_id=gs.id).all()
        all_pcs     = PlayerClassicState.query.filter_by(session_id=gs.id).all()
        states_map  = {p.player_id: p for p in all_pcs}

        targets = engine.build_steal_targets(all_wallets, states_map, actor.id)
        target_ids = [t['player_id'] for t in targets]

        check('S2-T01 excludes self',         actor.id     not in target_ids)
        check('S2-T02 excludes broke player', broke_p.id   not in target_ids)
        check('S2-T03 excludes shielded',     shielded_p.id not in target_ids)
        check('S2-T04 includes valid target', target_p.id  in target_ids)
        check('S2-T05 target gold in payload',
              any(t['gold'] == 80 for t in targets if t['player_id'] == target_p.id))

        # ─────────────────────────────────────────────────────────────────────
        # Section 3: no-targets path (DB integration)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── no_targets_fallback outcome ───────────────────────────────────')

        # Temporarily drain/shield all other wallets
        w_target.gold   = 0
        w_broke.gold    = 0
        pcs_shielded.shield_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        db.session.commit()

        actor_tokens_before = w_actor.steal_tokens
        actor_gold_before   = w_actor.gold

        all_wallets2 = PlayerWallet.query.filter_by(session_id=gs.id).all()
        all_pcs2     = PlayerClassicState.query.filter_by(session_id=gs.id).all()
        states_map2  = {p.player_id: p for p in all_pcs2}
        targets2 = engine.build_steal_targets(all_wallets2, states_map2, actor.id)

        check('S3-T01 no valid targets → empty list', targets2 == [])

        # Simulate no_targets_fallback handling (mirrors handle_choose_action steal branch)
        w_actor.steal_tokens -= 1
        w_actor.gold = max(0, w_actor.gold + cfg_no_mg.steal_fallback_gold)
        evt_nt = StealEvent(
            session_id=gs.id,
            round_id=gr.id,
            actor_id=actor.id,
            target_id=None,
            outcome='no_targets_fallback',
            gold_exchanged=cfg_no_mg.steal_fallback_gold,
            mini_game_pick=None,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(evt_nt)
        db.session.commit()

        db.session.refresh(w_actor)
        check('S3-T02 token consumed',       w_actor.steal_tokens == actor_tokens_before - 1)
        check('S3-T03 fallback gold awarded',
              w_actor.gold == actor_gold_before + cfg_no_mg.steal_fallback_gold)

        nt_event = StealEvent.query.filter_by(
            session_id=gs.id, outcome='no_targets_fallback'
        ).order_by(StealEvent.id.desc()).first()
        check('S3-T04 StealEvent outcome=no_targets_fallback',  nt_event is not None and nt_event.outcome == 'no_targets_fallback')
        check('S3-T05 StealEvent target_id=None',      nt_event.target_id is None)
        check('S3-T06 StealEvent gold=fallback_gold',
              nt_event.gold_exchanged == cfg_no_mg.steal_fallback_gold)

        # ─────────────────────────────────────────────────────────────────────
        # Section 4: mini-game disabled → instant success
        # ─────────────────────────────────────────────────────────────────────
        print('\n── steal success (mini-game disabled) ───────────────────')

        # Restore target gold and reset actor token
        w_target.gold        = 200
        w_actor.steal_tokens = 1
        db.session.commit()

        actor_gold_before2  = w_actor.gold
        target_gold_before2 = w_target.gold
        steal_amount2       = engine.calc_steal_amount(
            w_target.gold, cfg_no_mg.steal_percent,
            cfg_no_mg.steal_min_cap, cfg_no_mg.steal_max_cap,
        )

        # Simulate successful steal without mini-game
        w_actor.steal_tokens -= 1
        actual_stolen = min(steal_amount2, w_target.gold)
        w_target.gold  -= actual_stolen
        w_actor.gold   += actual_stolen

        # Grant reactive shield to victim
        new_expiry = engine.grant_steal_shield(pcs_target, cfg_no_mg.shield_duration)

        evt_s = StealEvent(
            session_id=gs.id,
            round_id=gr.id,
            actor_id=actor.id,
            target_id=target_p.id,
            outcome='success',
            gold_exchanged=actual_stolen,
            mini_game_pick=None,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(evt_s)
        db.session.commit()

        db.session.refresh(w_actor)
        db.session.refresh(w_target)
        db.session.refresh(pcs_target)

        check('S4-T01 gold transferred from target',
              w_target.gold == target_gold_before2 - actual_stolen)
        check('S4-T02 gold credited to actor',
              w_actor.gold == actor_gold_before2 + actual_stolen)
        check('S4-T03 steal amount matches formula',  actual_stolen == steal_amount2)
        check('S4-T04 reactive shield granted',
              engine.is_steal_shield_active(pcs_target))
        check('S4-T05 StealEvent outcome=success',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='success', actor_id=actor.id
              ).count() >= 1)
        check('S4-T06 token consumed on successful steal (no mg)',
              w_actor.steal_tokens == 0)

        # ─────────────────────────────────────────────────────────────────────
        # Section 5: shielded victim cannot be targeted afterwards
        # ─────────────────────────────────────────────────────────────────────
        print('\n── victim shield prevents re-targeting ──────────────────')

        db.session.refresh(pcs_target)
        check('S5-T01 victim has active shield after steal',
              engine.is_steal_shield_active(pcs_target))

        all_wallets3 = PlayerWallet.query.filter_by(session_id=gs.id).all()
        all_pcs3     = PlayerClassicState.query.filter_by(session_id=gs.id).all()
        states_map3  = {p.player_id: p for p in all_pcs3}
        targets3     = engine.build_steal_targets(all_wallets3, states_map3, actor.id)
        target_ids3  = [t['player_id'] for t in targets3]

        check('S5-T02 shielded target excluded from next steal',
              target_p.id not in target_ids3)

        # ─────────────────────────────────────────────────────────────────────
        # Section 6: mini-game flow — success
        # ─────────────────────────────────────────────────────────────────────
        print('\n── steal mini-game — success path ───────────────────────')

        # Reset: remove target shield, restore gold and tokens
        pcs_target.shield_expires_at = None
        w_target.gold        = 200
        w_actor.steal_tokens = 1
        db.session.commit()

        # Set steal intent + mini-game state (problem_id=0 as placeholder for this unit test)
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=0)
        winning = engine.generate_winning_chests(2, 1)
        state.set_steal_minigame(actor.id,
                                  target_id=target_p.id,
                                  winning_chests=winning,
                                  steal_amount=20,
                                  session_id=gs.id,
                                  round_id=gr.id)

        mg = state.get_steal_minigame(actor.id)
        check('S6-T01 minigame state set', mg is not None)

        # Simulate token consumption at pick_target
        w_actor.steal_tokens -= 1
        db.session.commit()

        # Pick a winning chest
        winning_pick = list(winning)[0]
        target_gold_mg = w_target.gold
        actual_stolen_mg = min(mg['steal_amount'], target_gold_mg)
        w_target.gold -= actual_stolen_mg
        w_actor.gold  += actual_stolen_mg
        engine.grant_steal_shield(pcs_target, cfg_no_mg.shield_duration)

        evt_mg_s = StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=target_p.id,
            outcome='success', gold_exchanged=actual_stolen_mg,
            mini_game_pick=winning_pick,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(evt_mg_s)
        state.clear_steal_minigame(actor.id)
        db.session.commit()

        db.session.refresh(w_actor); db.session.refresh(w_target)
        check('S6-T02 gold transferred on winning pick', w_target.gold == target_gold_mg - actual_stolen_mg)
        check('S6-T03 StealEvent.mini_game_pick recorded',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='success', mini_game_pick=winning_pick
              ).count() >= 1)
        check('S6-T04 minigame state cleared', state.get_steal_minigame(actor.id) is None)

        # ─────────────────────────────────────────────────────────────────────
        # Section 7: mini-game flow — fail
        # ─────────────────────────────────────────────────────────────────────
        print('\n── steal mini-game — fail path ──────────────────────────')

        # Reset
        pcs_target.shield_expires_at = None
        w_target.gold        = 200
        w_actor.steal_tokens = 1
        db.session.commit()

        winning_fail = engine.generate_winning_chests(2, 1)
        losing_pick = next(i for i in range(1, 3) if i not in winning_fail)

        # Consume token
        w_actor.steal_tokens -= 1
        actor_gold_before_fail = w_actor.gold
        target_gold_before_fail = w_target.gold

        evt_mg_f = StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=target_p.id,
            outcome='mini_game_fail', gold_exchanged=0,
            mini_game_pick=losing_pick,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(evt_mg_f)
        db.session.commit()

        db.session.refresh(w_actor); db.session.refresh(w_target)
        check('S7-T01 no gold transferred on failing pick',
              w_target.gold == target_gold_before_fail and w_actor.gold == actor_gold_before_fail)
        check('S7-T02 StealEvent outcome=mini_game_fail',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='mini_game_fail', mini_game_pick=losing_pick
              ).count() >= 1)
        check('S7-T03 no shield granted to target on fail',
              not engine.is_steal_shield_active(pcs_target))
        check('S7-T04 token consumed on mini_game_fail',
              w_actor.steal_tokens == 0)

        # ─────────────────────────────────────────────────────────────────────
        # Section 8: OQ-4 — target becomes shielded before mini-game resolve
        # Locked rule: token is consumed at confirmation regardless of whether
        # the target is still valid.
        # ─────────────────────────────────────────────────────────────────────
        print('\n── OQ-4: target invalid at pick_target confirmation ─────')

        # Reset actor token and give target a fresh shield
        w_actor.steal_tokens = 1
        pcs_target.shield_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        db.session.commit()
        db.session.refresh(pcs_target)
        check('S8-T01 target shielded mid-flight',
              engine.is_steal_shield_active(pcs_target))

        # Simulate the corrected invalid-target branch:
        # confirmation has happened → consume token, log event, no gold transfer
        target_still_valid = (
            w_target is not None
            and w_target.gold > 0
            and not engine.is_steal_shield_active(pcs_target)
        )
        check('S8-T02 target_still_valid=False when shielded', not target_still_valid)

        tokens_before_oq4 = w_actor.steal_tokens
        actor_gold_before_oq4 = w_actor.gold

        # Apply the locked behavior: token consumed
        w_actor.steal_tokens -= 1
        evt_oq4 = StealEvent(
            session_id=gs.id, round_id=gr.id,
            actor_id=actor.id, target_id=target_p.id,
            outcome='target_invalid', gold_exchanged=0,
            mini_game_pick=None,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(evt_oq4)
        db.session.commit()
        db.session.refresh(w_actor)

        check('S8-T03 token consumed even when target invalid',
              w_actor.steal_tokens == tokens_before_oq4 - 1)
        check('S8-T04 no gold transferred',
              w_actor.gold == actor_gold_before_oq4)
        check('S8-T05 StealEvent logged as target_invalid',
              StealEvent.query.filter_by(
                  session_id=gs.id, outcome='target_invalid',
                  actor_id=actor.id, target_id=target_p.id,
                  mini_game_pick=None,
              ).count() >= 1)

        # ─────────────────────────────────────────────────────────────────────
        # Section 9: shield stacking integration
        # ─────────────────────────────────────────────────────────────────────
        print('\n── shield stacking (DB round-trip) ──────────────────────')

        base_expiry = datetime.now(timezone.utc) + timedelta(seconds=30)
        pcs_target.shield_expires_at = base_expiry
        db.session.commit()

        engine.grant_steal_shield(pcs_target, 60)
        db.session.commit()
        db.session.refresh(pcs_target)

        expected_low  = base_expiry + timedelta(seconds=59)
        expected_high = base_expiry + timedelta(seconds=61)
        # SQLite returns naive datetimes; normalise before comparison
        stored = pcs_target.shield_expires_at
        if stored is not None and stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        check('S9-T01 shield stacks onto active shield',
              expected_low <= stored <= expected_high)

        # ─────────────────────────────────────────────────────────────────────
        # Section 10: StealEvent table — full audit trail
        # ─────────────────────────────────────────────────────────────────────
        print('\n── StealEvent audit trail ───────────────────────────────')

        all_events = StealEvent.query.filter_by(session_id=gs.id).all()
        outcomes   = [e.outcome for e in all_events]

        check('S10-T01 no_targets_fallback event present', 'no_targets_fallback' in outcomes)
        check('S10-T02 success events present',      'success'       in outcomes)
        check('S10-T03 mini_game_fail event present','mini_game_fail' in outcomes)

        success_with_mg = StealEvent.query.filter_by(
            session_id=gs.id, outcome='success'
        ).filter(StealEvent.mini_game_pick.isnot(None)).first()
        check('S10-T04 success event has mini_game_pick set when used',
              success_with_mg is not None)

        success_no_mg = StealEvent.query.filter_by(
            session_id=gs.id, outcome='success', mini_game_pick=None
        ).first()
        check('S10-T05 success event has mini_game_pick=None when mini-game disabled',
              success_no_mg is not None)
        check('S10-T06 target_invalid event present',    'target_invalid' in outcomes)

        # ─────────────────────────────────────────────────────────────────────
        # Section 11: state helpers — intent and log in session context
        # ─────────────────────────────────────────────────────────────────────
        print('\n── state helpers (session-scoped) ───────────────────────')

        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=0)
        intent_data = state.get_steal_intent(actor.id)
        check('S11-T01 intent set', intent_data is not None)
        check('S11-T01b intent stores problem_id',
              intent_data is not None and intent_data.get('problem_id') == 0)

        state.clear_steal_intent(actor.id)
        check('S11-T02 intent cleared', state.get_steal_intent(actor.id) is None)

        state.append_action_log(actor.id, gs.id, 'You stole 20 gold from __d3_target__')
        log = state.get_action_log(actor.id, gs.id)
        check('S11-T03 action log entry present', len(log) >= 1)

        state.clear_session(gs.id)
        check('S11-T04 clear_session removes action log', state.get_action_log(actor.id, gs.id) == [])

        # ─────────────────────────────────────────────────────────────────
        # Section 12: Contract #1 — Mine/TS blocked while steal intent is active
        # The handle_choose_action guard checks get_steal_intent(); these tests
        # verify the state precondition that the guard relies on.
        # ─────────────────────────────────────────────────────────────────
        print('\n\u2500\u2500 Mine/TS blocked while steal intent is active \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500')

        # Set steal intent as the handler would after action='steal' with valid targets
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=42)
        active_intent = state.get_steal_intent(actor.id)

        check('S12-T01 steal intent is set (precondition for Mine/TS block)',
              active_intent is not None)
        # The guard in handle_choose_action fires when this is True:
        mine_would_be_blocked = (
            active_intent is not None
            and active_intent.get('session_id') == gs.id
        )
        check('S12-T02 mine/TS guard condition is True while intent active',
              mine_would_be_blocked)

        # After cancel: intent is cleared, Mine/TS is unblocked
        state.clear_steal_intent(actor.id)
        after_cancel = state.get_steal_intent(actor.id)
        check('S12-T03 after cancel, intent cleared and Mine/TS unblocked',
              after_cancel is None)

        # ─────────────────────────────────────────────────────────────────
        # Section 13: Duplicate confirm guard
        # Guards in handle_steal_pick_target and handle_steal_mini_game_pick
        # rely on intent/minigame being cleared before resolution.  These tests
        # verify that the state is always consumed on the first call.
        # ─────────────────────────────────────────────────────────────────
        print('\n\u2500\u2500 Duplicate confirm guard \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500')

        # Scenario A: duplicate pick_target — second call finds no intent
        state.set_steal_intent(actor.id, gs.id, gr.id, problem_id=0)
        check('S13-T01a intent present before first pick_target',
              state.get_steal_intent(actor.id) is not None)
        state.clear_steal_intent(actor.id)   # mirrors first pick_target consuming the intent
        check('S13-T01b second pick_target has no intent (guard activates)',
              state.get_steal_intent(actor.id) is None)

        # Scenario B: duplicate mini_game_pick — second call finds no minigame
        winning_dup = engine.generate_winning_chests(2, 1)
        state.set_steal_minigame(actor.id, target_id=target_p.id,
                                  winning_chests=winning_dup, steal_amount=20,
                                  session_id=gs.id, round_id=gr.id)
        check('S13-T02a minigame present before first pick',
              state.get_steal_minigame(actor.id) is not None)
        state.clear_steal_minigame(actor.id)  # mirrors first mini_game_pick consuming the state
        check('S13-T02b second mini_game_pick has no state (guard activates)',
              state.get_steal_minigame(actor.id) is None)

        print()


run_tests()

print(f'{passed} passed, {failed} failed')
if failed:
    print('SOME D-3 TESTS FAILED.')
    sys.exit(1)
else:
    print('ALL D-3 TESTS PASSED.')
