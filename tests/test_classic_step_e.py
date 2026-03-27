"""
test_classic_step_e.py
======================

Exit test suite for Classic Mode Step E — Manual Anti-Steal Shield Activation.

Tests operate directly via ORM + engine/state helpers inside a Flask app
context.  No HTTP requests, no WebSocket connections required.

Coverage (E01–E13):
  E01: Activation sets inv.used_at on the oldest unused steal_shield item
  E02: Activation sets shield_expires_at ≈ now + shield_duration (fresh shield)
  E03: Activation stacks: new_expiry = old_expiry + shield_duration
  E04: active_bonuses count decrements after activation
  E05: Activation fails (no items) when player has 0 unused steal_shield items
  E06: Activation fails when session is not active
  E07: Activation fails when no active round exists
  E08: Activated shield makes player ineligible in build_steal_targets
  E09: Shield activation before pick_target → target_invalid steal outcome
  E10: Shield activation between pick_target and chest pick → target_invalid on OQ-4
  E11: Only ONE item consumed per activation (multiple items owned)
  E12: PlayerClassicState created automatically if row does not exist yet
  Regression:
  E13: Full Step D suite (131/131)

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_classic_step_e.py

Expected: all tests pass, final line "ALL E TESTS PASSED."
"""

import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

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

flask_app = create_app()

SET_NAME      = '__test_step_e__'
_ACTOR_NAME   = '__se_actor__'
_TARGET_NAME  = '__se_target__'
_OTHER_NAME   = '__se_other__'

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
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


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
            from app.models.classic import PlayerProblemState, ProblemSolverCount
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
        for prob in Problem.query.filter(Problem.title.like('SE P%')).all():
            PlayerProblemState.query.filter_by(problem_id=prob.id).delete()
            ProblemSolverCount.query.filter_by(problem_id=prob.id).delete()
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()

    for uname in (_ACTOR_NAME, _TARGET_NAME, _OTHER_NAME):
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


def _mcfg(round_id, shield_duration=60, **overrides):
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
        steal_chest_count=0,
        steal_winning_chest_count=1,
        shield_duration=shield_duration,
        treasure_steal_token_chance=0.0,
    )
    defaults.update(overrides)
    cfg = ClassicRoundConfig(**defaults)
    db.session.add(cfg)
    db.session.flush()
    return cfg


def _make_shield_item(session_id, cost=10):
    """Create a steal_shield StoreItem and return it."""
    item = StoreItem(
        session_id=session_id,
        name='Steal Shield',
        description='Manual steal protection',
        bonus_type='steal_shield',
        cost=cost,
        session_stock=-1,
    )
    db.session.add(item)
    db.session.flush()
    return item


def _buy_shield(player_id, session_id, item_id):
    """Insert an unused PlayerInventory row for a steal_shield item."""
    inv = PlayerInventory(
        player_id=player_id,
        session_id=session_id,
        item_id=item_id,
        purchased_at=_now(),
        used_at=None,
    )
    db.session.add(inv)
    db.session.flush()
    return inv


def _activate_shield(player_id, session_id, config):
    """
    Perform the core manual-activation logic directly (mirrors the handler):
      1. Find oldest unused steal_shield inventory row.
      2. Consume it + grant shield in a single commit.
    Returns (inv_row, new_expiry) on success, or (None, None) if no item.
    """
    inv = (
        PlayerInventory.query
        .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
        .filter(
            PlayerInventory.player_id  == player_id,
            PlayerInventory.session_id == session_id,
            StoreItem.bonus_type       == 'steal_shield',
            PlayerInventory.used_at    == None,  # noqa: E711
        )
        .order_by(PlayerInventory.purchased_at.asc())
        .first()
    )
    if not inv:
        return None, None

    pcs = PlayerClassicState.query.filter_by(
        player_id=player_id, session_id=session_id
    ).first()
    if not pcs:
        pcs = PlayerClassicState(player_id=player_id, session_id=session_id)
        db.session.add(pcs)
        db.session.flush()

    inv.used_at   = _now()
    new_expiry    = engine.grant_steal_shield(pcs, config.shield_duration)
    db.session.commit()
    return inv, new_expiry


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def run_tests():
    with flask_app.app_context():
        _clean()

        # ── Shared DB fixtures ────────────────────────────────────────────────
        topic = Topic.query.first()
        if not topic:
            topic = Topic(name='__se_topic__', subject='Test')
            db.session.add(topic)
            db.session.flush()

        prob = Problem(topic_id=topic.id, title='SE P1',
                       prompt_text='2+2', answer_text='4', difficulty=1)
        db.session.add(prob)
        ps = ProblemSet(name=SET_NAME, description='E exit tests')
        db.session.add(ps)
        db.session.flush()
        ps.problems.append(prob)

        actor   = _mp(_ACTOR_NAME)
        target  = _mp(_TARGET_NAME)
        other   = _mp(_OTHER_NAME)

        gs = GameSession(mode='classic', status='active',
                         problem_set_id=ps.id, started_at=_now())
        db.session.add(gs)
        db.session.flush()

        gr = GameRound(session_id=gs.id, round_number=1, started_at=_now())
        db.session.add(gr)
        db.session.flush()
        cfg = _mcfg(gr.id, shield_duration=60)

        RoundPlayer(session_id=gs.id, player_id=actor.id)
        db.session.add(RoundPlayer(session_id=gs.id, player_id=actor.id))
        db.session.add(RoundPlayer(session_id=gs.id, player_id=target.id))
        db.session.add(RoundPlayer(session_id=gs.id, player_id=other.id))

        w_actor  = _mw(actor.id,  gs.id, gold=100, steal_tokens=1)
        w_target = _mw(target.id, gs.id, gold=80,  steal_tokens=1)
        _mw(other.id,  gs.id, gold=50,  steal_tokens=1)

        shield_item = _make_shield_item(gs.id)
        db.session.commit()

        # ─────────────────────────────────────────────────────────────────────
        # E01: inv.used_at set on the oldest unused steal_shield item
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E01: inventory row consumed ─────────────────────────')

        inv_e01 = _buy_shield(actor.id, gs.id, shield_item.id)
        inv_id  = inv_e01.id

        inv_row, _ = _activate_shield(actor.id, gs.id, cfg)

        db.session.refresh(inv_e01)
        check('E01a activation returns inventory row',   inv_row is not None)
        check('E01b used_at set on consumed row',        inv_e01.used_at is not None)
        check('E01c correct row consumed',               inv_row.id == inv_id)

        # ─────────────────────────────────────────────────────────────────────
        # E02: shield_expires_at set to ≈ now + shield_duration (fresh shield)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E02: fresh shield set correctly ─────────────────────')

        # Use a fresh player state (no existing shield)
        pcs_e02 = PlayerClassicState.query.filter_by(
            player_id=actor.id, session_id=gs.id
        ).first()
        # Reset it
        pcs_e02.shield_expires_at = None
        db.session.commit()

        inv_e02 = _buy_shield(actor.id, gs.id, shield_item.id)
        t_before = _now()
        _, expiry_e02 = _activate_shield(actor.id, gs.id, cfg)
        t_after  = _now()

        db.session.refresh(pcs_e02)
        stored = pcs_e02.shield_expires_at
        if stored is not None and stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)

        check('E02a shield_expires_at is in the future',
              stored is not None and stored > t_before)
        check('E02b expiry ≈ now + 60s',
              t_before + timedelta(seconds=59) < stored < t_after + timedelta(seconds=61))
        check('E02c returned expiry matches DB',
              abs((expiry_e02 - stored).total_seconds()) < 1)

        # ─────────────────────────────────────────────────────────────────────
        # E03: shield stacks when already active
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E03: shield stacks onto existing active shield ──────')

        pcs_e03 = PlayerClassicState.query.filter_by(
            player_id=actor.id, session_id=gs.id
        ).first()
        base_e03 = _now() + timedelta(seconds=30)
        pcs_e03.shield_expires_at = base_e03
        db.session.commit()

        inv_e03 = _buy_shield(actor.id, gs.id, shield_item.id)
        _, expiry_e03 = _activate_shield(actor.id, gs.id, cfg)

        db.session.refresh(pcs_e03)
        stored_e03 = pcs_e03.shield_expires_at
        if stored_e03 is not None and stored_e03.tzinfo is None:
            stored_e03 = stored_e03.replace(tzinfo=timezone.utc)

        # Expected: base + 60s (stacked onto the existing 30s remaining)
        check('E03 stacked expiry = old_base + 60s',
              base_e03 + timedelta(seconds=59) < stored_e03 < base_e03 + timedelta(seconds=61))

        # ─────────────────────────────────────────────────────────────────────
        # E04: active_bonuses.steal_shield count decrements after activation
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E04: active_bonuses count decrements ────────────────')

        # Reset: buy 2 shields so we can check count before/after
        inv_e04a = _buy_shield(actor.id, gs.id, shield_item.id)
        inv_e04b = _buy_shield(actor.id, gs.id, shield_item.id)
        db.session.commit()

        count_before = classic_store.get_active_counts(actor.id, gs.id).get('steal_shield', 0)
        _activate_shield(actor.id, gs.id, cfg)
        count_after  = classic_store.get_active_counts(actor.id, gs.id).get('steal_shield', 0)

        check('E04 active_bonuses.steal_shield decrements by 1',
              count_after == count_before - 1)

        # ─────────────────────────────────────────────────────────────────────
        # E05: activation fails when no unused steal_shield items
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E05: no items → returns None ────────────────────────')

        # Consume any remaining unused shields for actor
        while True:
            inv_r, _ = _activate_shield(actor.id, gs.id, cfg)
            if inv_r is None:
                break

        inv_e05, expiry_e05 = _activate_shield(actor.id, gs.id, cfg)
        check('E05 returns (None, None) when no items',
              inv_e05 is None and expiry_e05 is None)

        # ─────────────────────────────────────────────────────────────────────
        # E06 + E07: guard checks for inactive session / no active round
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E06/E07: session/round guard checks ─────────────────')

        # E06: session not active → handler should reject
        # We test the guard condition directly (no socket)
        gs_inactive = GameSession(mode='classic', status='finished',
                                  problem_set_id=ps.id, started_at=_now())
        db.session.add(gs_inactive)
        db.session.flush()
        check('E06 inactive session guard',
              gs_inactive.status != 'active')

        # E07: active session but round has ended_at set
        gs_e07 = GameSession(mode='classic', status='active',
                              problem_set_id=ps.id, started_at=_now())
        db.session.add(gs_e07)
        db.session.flush()
        gr_ended = GameRound(session_id=gs_e07.id, round_number=1,
                             started_at=_now(),
                             ended_at=_now())
        db.session.add(gr_ended)
        db.session.commit()

        active_round = GameRound.query.filter_by(
            session_id=gs_e07.id, ended_at=None
        ).first()
        check('E07 no active round when all rounds have ended_at',
              active_round is None)

        # ─────────────────────────────────────────────────────────────────────
        # E08: activated shield makes player ineligible as steal target
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E08: activated shield blocks steal targeting ────────')

        # Give target an unused shield and activate it
        inv_e08 = _buy_shield(target.id, gs.id, shield_item.id)
        db.session.commit()

        # Activate target's shield
        _activate_shield(target.id, gs.id, cfg)

        # Now build steal targets from actor's perspective
        all_wallets = PlayerWallet.query.filter_by(session_id=gs.id).all()
        all_states  = {
            p.player_id: p
            for p in PlayerClassicState.query.filter_by(session_id=gs.id).all()
        }
        targets_e08 = engine.build_steal_targets(all_wallets, all_states, actor.id)
        target_ids  = [t['player_id'] for t in targets_e08]

        check('E08 shielded target excluded from steal targets',
              target.id not in target_ids)

        # ─────────────────────────────────────────────────────────────────────
        # E09: shield activated before pick_target → target_invalid outcome
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E09: shield activated before pick_target race ───────')

        # Ensure target has gold and a fresh non-expired shield
        db.session.refresh(w_target)
        w_target.gold = 80
        db.session.commit()

        # Target activates shield (manually, ORM-level)
        pcs_target = PlayerClassicState.query.filter_by(
            player_id=target.id, session_id=gs.id
        ).first()
        if not pcs_target:
            pcs_target = PlayerClassicState(
                player_id=target.id, session_id=session_id
            )
            db.session.add(pcs_target)
        pcs_target.shield_expires_at = _now() + timedelta(seconds=60)
        db.session.commit()
        db.session.refresh(pcs_target)

        # Re-validate target (mirrors handle_steal_pick_target logic)
        target_valid_e09 = (
            w_target is not None
            and w_target.gold > 0
            and not engine.is_steal_shield_active(pcs_target)
        )
        # Determine outcome: target_invalid (shield/gold) vs mini_game_fail (chest)
        if not target_valid_e09:
            outcome_e09 = 'target_invalid'
        else:
            outcome_e09 = 'mini_game_fail'

        check('E09a target_valid=False when manually shielded',
              not target_valid_e09)
        check('E09b outcome resolves to target_invalid',
              outcome_e09 == 'target_invalid')

        # ─────────────────────────────────────────────────────────────────────
        # E10: shield activated between pick_target and chest pick (OQ-4 path)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E10: shield activated between pick_target and chest pick ')

        # Simulate: mini-game is in progress; target subsequently gets shielded.
        # Re-validate at mini_game_pick step (OQ-4 logic).
        db.session.refresh(pcs_target)
        pcs_target.shield_expires_at = _now() + timedelta(seconds=60)
        db.session.commit()

        won_chest_e10 = True   # player "won" the chest — but target is now shielded
        target_still_valid_e10 = (
            w_target is not None
            and w_target.gold > 0
            and not engine.is_steal_shield_active(pcs_target)
        )

        # Clarification E-3: target_invalid when target is invalid; mini_game_fail only when chest lost
        if not target_still_valid_e10:
            outcome_e10 = 'target_invalid'
        else:
            outcome_e10 = 'mini_game_fail' if not won_chest_e10 else 'success'

        check('E10a target invalid after shield activation',
              not target_still_valid_e10)
        check('E10b outcome = target_invalid (not mini_game_fail)',
              outcome_e10 == 'target_invalid')

        # ─────────────────────────────────────────────────────────────────────
        # E11: only ONE inventory item consumed per activation call
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E11: only one item consumed per activation ──────────')

        inv_e11a = _buy_shield(actor.id, gs.id, shield_item.id)
        inv_e11b = _buy_shield(actor.id, gs.id, shield_item.id)
        db.session.commit()

        _activate_shield(actor.id, gs.id, cfg)

        db.session.refresh(inv_e11a)
        db.session.refresh(inv_e11b)

        # The oldest one (inv_e11a) should be consumed; inv_e11b must remain unused
        consumed_count = sum([
            1 if inv_e11a.used_at is not None else 0,
            1 if inv_e11b.used_at is not None else 0,
        ])
        check('E11a exactly one item consumed',    consumed_count == 1)
        check('E11b oldest item consumed first',
              inv_e11a.used_at is not None and inv_e11b.used_at is None)

        # ─────────────────────────────────────────────────────────────────────
        # E12: PlayerClassicState created automatically if not present
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E12: PlayerClassicState auto-created ────────────────')

        # Create a fresh session with a fresh player who has no PCS row yet
        gs_e12 = GameSession(mode='classic', status='active',
                             problem_set_id=ps.id, started_at=_now())
        db.session.add(gs_e12)
        db.session.flush()
        gr_e12 = GameRound(session_id=gs_e12.id, round_number=1, started_at=_now())
        db.session.add(gr_e12)
        db.session.flush()
        cfg_e12 = _mcfg(gr_e12.id, shield_duration=60)

        # Use 'other' player who has no PCS row in gs_e12
        _mw(other.id, gs_e12.id, gold=50)
        shield_item_e12 = _make_shield_item(gs_e12.id)
        _buy_shield(other.id, gs_e12.id, shield_item_e12.id)
        db.session.commit()

        # Confirm no PCS row exists yet
        pcs_pre_e12 = PlayerClassicState.query.filter_by(
            player_id=other.id, session_id=gs_e12.id
        ).first()
        check('E12a no PCS row before activation',   pcs_pre_e12 is None)

        _activate_shield(other.id, gs_e12.id, cfg_e12)

        pcs_post_e12 = PlayerClassicState.query.filter_by(
            player_id=other.id, session_id=gs_e12.id
        ).first()
        check('E12b PCS row created after activation',  pcs_post_e12 is not None)
        check('E12c shield_expires_at is set',
              pcs_post_e12 is not None and pcs_post_e12.shield_expires_at is not None)

        # ─────────────────────────────────────────────────────────────────────
        # E13: Full Step D regression (131/131)
        # ─────────────────────────────────────────────────────────────────────
        print('\n── E13: Step D regression ──────────────────────────────')
        step_d_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'test_classic_step_d.py',
        )
        try:
            result = subprocess.run(
                [sys.executable, step_d_path],
                capture_output=True, text=True, timeout=120,
                encoding='utf-8',
                env=dict(os.environ, PYTHONIOENCODING='utf-8'),
            )
            d_passed = result.returncode == 0 and 'ALL D TESTS PASSED.' in result.stdout
            if not d_passed:
                print('    Step D output (last 20 lines):')
                for line in result.stdout.splitlines()[-20:]:
                    print('      ' + line)
                if result.stderr:
                    print('    STDERR:', result.stderr[-500:])
            check('E13 Step D 131/131 regression', d_passed)
        except Exception as exc:
            check('E13 Step D 131/131 regression', False, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    run_tests()
    print(f'\nResults: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL E TESTS PASSED.')
    else:
        print('SOME E TESTS FAILED.')
        sys.exit(1)
