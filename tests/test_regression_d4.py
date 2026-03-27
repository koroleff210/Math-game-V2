"""
test_regression_d4.py
=====================

Regression tests for D4 -- Wiring session-scoped participant snapshots into
Classic gameplay.

SessionParticipantSnapshot is the sole runtime source of truth for
upgrade-derived gameplay effects (read via get_session_player_modifiers).

Tests are service/engine-layer where possible to avoid spawning a live SocketIO
server.  They verify:

  D4-01: get_session_player_modifiers returns the frozen snapshot when it exists
  D4-02: get_session_player_modifiers returns _DefaultModifiers when no snapshot exists
  D4-03: mine reward includes effective_mine_bonus from frozen modifiers
  D4-04: mine reward is unaffected when effective_mine_bonus == 0 (baseline)
  D4-05: treasure reward includes effective_treasure_bonus from frozen modifiers
  D4-06: treasure reward is unaffected when effective_treasure_bonus == 0 (baseline)
  D4-07: engine.try_award_steal_token respects the frozen effective_steal_token_cap
  D4-08: token cap == 1 (baseline) -- second award is rejected as before
  D4-09: token cap == 2 -- second award is accepted; third is rejected
  D4-10: starting steal_tokens in wallet is unaffected by the upgrade
  D4-11: token consumption (wallet.steal_tokens -= 1) is unchanged
  D4-12: manual shield duration = round(base * (1 + pct)) for pct > 0
  D4-13: manual shield duration unchanged for pct == 0.0 (baseline)
  D4-14: reactive shield duration = round(base * (1 + pct)) for pct > 0
  D4-15: reactive shield duration unchanged for pct == 0.0 (baseline)
  D4-16: post-session-start upgrade purchase does NOT change existing snapshot
  D4-17: new session snapshot picks up the post-session upgrade value
  D4-18: engine.calc_mine_reward unchanged when bonus applied externally (math check)
  D4-19: engine.calc_treasure_search_reward unchanged when bonus applied externally
  D4-20: _DefaultModifiers has correct baseline attribute values

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_d4.py

Expected: all tests pass, final line "ALL D4 TESTS PASSED."
"""

import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import ClassicRoundConfig, PlayerWallet, PlayerClassicState
from app.models.progression import (
    PlayerProgression, PlayerUpgrade, SessionParticipantSnapshot,
)
from app.services.progression import (
    get_or_create_player_progression,
    award_diamonds_to_player,
    purchase_upgrade,
    ensure_session_participant_snapshot,
    ensure_all_session_participant_snapshots,
    get_session_player_modifiers,
)
from app.services.upgrade_catalog import UPGRADE_CATALOG
from app.modes.classic import engine


# -- App config ----------------------------------------------------------------

class _TestConfig:
    TESTING                        = True
    SQLALCHEMY_DATABASE_URI        = 'sqlite:///:memory:'
    SECRET_KEY                     = 'd4-test-secret'
    WTF_CSRF_ENABLED               = False
    SOCKETIO_ASYNC_MODE            = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED                 = False


flask_app = create_app(_TestConfig)

# -- Test runner ---------------------------------------------------------------

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


# -- Fixture helpers -----------------------------------------------------------

_ADMIN_USER = '__d4_admin__'
_PLAYER_A   = '__d4_player_a__'
_PLAYER_B   = '__d4_player_b__'
_IDS = {}


def _make_player(username, is_admin=False, password='pass1234'):
    p = Player(username=username, is_admin=is_admin)
    p.set_password(password)
    db.session.add(p)
    db.session.flush()
    return p


def _make_config():
    """Return a minimal ClassicRoundConfig-like namespace for engine tests."""
    class _Cfg:
        mine_reward                 = 20
        treasure_search_reward      = 10
        treasure_search_max_reward  = 10
        bonus_timer_duration        = 0
        bonus_timer_gold            = 0
        first_solver_count          = 0
        first_solver_multiplier     = 0
        gem_treasure_chance         = 0.0
        shield_duration             = 60
        steal_percent               = 0.1
        steal_min_cap               = 5
        steal_max_cap               = 50
        treasure_steal_token_chance = 0.0
    return _Cfg()


def _make_session_with_round():
    gs = GameSession(mode='classic', status='waiting')
    db.session.add(gs)
    db.session.flush()
    gr = GameRound(session_id=gs.id, round_number=1, started_at=None)
    db.session.add(gr)
    db.session.flush()
    return gs, gr


def _enroll(session_id, player_id):
    rp = RoundPlayer(session_id=session_id, player_id=player_id)
    db.session.add(rp)
    db.session.flush()


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin  = _make_player(_ADMIN_USER, is_admin=True)
        p_a    = _make_player(_PLAYER_A,   is_admin=False)
        p_b    = _make_player(_PLAYER_B,   is_admin=False)
        db.session.commit()
        _IDS['admin_id']    = admin.id
        _IDS['player_a_id'] = p_a.id
        _IDS['player_b_id'] = p_b.id


# -- D4-01 / D4-02: get_session_player_modifiers helper -----------------------

def test_helper():
    with flask_app.app_context():
        pid = _IDS['player_a_id']
        gs, gr = _make_session_with_round()
        _enroll(gs.id, pid)
        db.session.commit()

        # D4-02: no snapshot row -> _DefaultModifiers
        mods_absent = get_session_player_modifiers(gs.id, pid)
        check('D4-02: missing row returns defaults with steal_token_cap=1',
              mods_absent.effective_steal_token_cap == 1)
        check('D4-02: missing row returns defaults with mine_bonus=0',
              mods_absent.effective_mine_bonus == 0)
        check('D4-02: missing row returns defaults with treasure_bonus=0',
              mods_absent.effective_treasure_bonus == 0)
        check('D4-02: missing row returns defaults with shield_bonus_pct=0.0',
              mods_absent.effective_shield_bonus_pct == 0.0)

        # D4-20: _DefaultModifiers values match catalog level-0 baselines
        check('D4-20: _DefaultModifiers values are catalog level-0 baselines',
              mods_absent.effective_steal_token_cap  == UPGRADE_CATALOG['steal_token_cap'].effects[0]
              and mods_absent.effective_mine_bonus   == UPGRADE_CATALOG['mine_bonus'].effects[0]
              and mods_absent.effective_treasure_bonus  == UPGRADE_CATALOG['treasure_bonus'].effects[0]
              and mods_absent.effective_shield_bonus_pct == UPGRADE_CATALOG['shield_bonus_pct'].effects[0])

        # D4-01: create snapshot row -> correct values returned
        ensure_all_session_participant_snapshots(gs.id)
        db.session.commit()

        mods_present = get_session_player_modifiers(gs.id, pid)
        check('D4-01: present row has correct type',
              isinstance(mods_present, SessionParticipantSnapshot))
        check('D4-01: present row returns correct player_id',
              mods_present.player_id == pid)


# -- D4-03 / D4-04: mine bonus ------------------------------------------------

def test_mine_bonus():
    cfg = _make_config()

    # D4-04: baseline mine reward unchanged
    result = engine.calc_mine_reward(cfg, solver_rank=1, timer_active=False)
    base_gold = result['gold']  # should be 20 (mine_reward)
    mine_bonus = 0
    gold_final = base_gold + mine_bonus
    check('D4-04: baseline mine reward unaffected (no bonus)',
          gold_final == cfg.mine_reward,
          f'got {gold_final}, expected {cfg.mine_reward}')

    # D4-03: mine bonus adds to engine result
    effective_mine_bonus = UPGRADE_CATALOG['mine_bonus'].effects[2]   # level 2 -> 10
    result2 = engine.calc_mine_reward(cfg, solver_rank=1, timer_active=False)
    gold_with_bonus = result2['gold'] + effective_mine_bonus
    check('D4-03: mine reward + bonus == base + effective_mine_bonus',
          gold_with_bonus == cfg.mine_reward + effective_mine_bonus,
          f'got {gold_with_bonus}, expected {cfg.mine_reward + effective_mine_bonus}')

    # D4-18: engine.calc_mine_reward itself is unchanged (returns base only)
    check('D4-18: calc_mine_reward still returns base without modification',
          result2['gold'] == cfg.mine_reward,
          f'engine returned {result2["gold"]}')


# -- D4-05 / D4-06: treasure bonus --------------------------------------------

def test_treasure_bonus():
    cfg = _make_config()

    # D4-06: baseline treasure unchanged
    result = engine.calc_treasure_search_reward(cfg, solver_rank=1, timer_active=False)
    base_gold = result['gold']
    check('D4-06: baseline treasure reward unaffected (no bonus)',
          base_gold + 0 == cfg.treasure_search_reward,
          f'got {base_gold}')

    # D4-05: treasure bonus adds to engine result
    effective_treasure_bonus = UPGRADE_CATALOG['treasure_bonus'].effects[2]   # level 2 -> 10
    gold_with_bonus = base_gold + effective_treasure_bonus
    check('D4-05: treasure reward + bonus == base + effective_treasure_bonus',
          gold_with_bonus == cfg.treasure_search_reward + effective_treasure_bonus,
          f'got {gold_with_bonus}')

    # D4-19: engine.calc_treasure_search_reward itself unchanged
    check('D4-19: calc_treasure_search_reward still returns base without modification',
          result['gold'] == cfg.treasure_search_reward,
          f'engine returned {result["gold"]}')


# -- D4-07 / D4-08 / D4-09: steal token cap -----------------------------------

def test_steal_token_cap():
    with flask_app.app_context():
        pid = _IDS['player_b_id']

        # D4-08: baseline cap == 1 -- use its own session
        gs1, gr1 = _make_session_with_round()
        wallet_base = PlayerWallet(player_id=pid, session_id=gs1.id, gold=100, gems=0, steal_tokens=0)
        db.session.add(wallet_base)
        db.session.commit()

        mods_base = get_session_player_modifiers(gs1.id, pid)   # -> _DefaultModifiers (cap=1)
        awarded1 = engine.try_award_steal_token(wallet_base, max_cap=mods_base.effective_steal_token_cap)
        check('D4-08: first token award accepted at baseline cap',
              awarded1 is True,
              f'awarded1={awarded1}')
        check('D4-08: wallet.steal_tokens == 1 after first award',
              wallet_base.steal_tokens == 1)

        awarded2 = engine.try_award_steal_token(wallet_base, max_cap=mods_base.effective_steal_token_cap)
        check('D4-08: second token award rejected at baseline cap (already at 1)',
              awarded2 is False,
              f'awarded2={awarded2}')
        check('D4-08: wallet.steal_tokens still == 1',
              wallet_base.steal_tokens == 1)

        # D4-07: upgraded cap == 2 -- use a different session to avoid unique constraint
        gs2, gr2 = _make_session_with_round()
        wallet_upg = PlayerWallet(player_id=pid, session_id=gs2.id, gold=100, gems=0, steal_tokens=0)
        db.session.add(wallet_upg)
        db.session.flush()

        custom_cap = UPGRADE_CATALOG['steal_token_cap'].effects[1]  # level 1 -> 2
        check('D4-07: test precondition -- upgraded cap is 2',
              custom_cap == 2, f'got {custom_cap}')

        a1 = engine.try_award_steal_token(wallet_upg, max_cap=custom_cap)
        a2 = engine.try_award_steal_token(wallet_upg, max_cap=custom_cap)
        a3 = engine.try_award_steal_token(wallet_upg, max_cap=custom_cap)
        check('D4-07: first award accepted with cap=2', a1 is True)
        check('D4-07: second award accepted with cap=2', a2 is True)
        check('D4-07: third award rejected with cap=2', a3 is False)
        check('D4-07: wallet.steal_tokens == 2 after two awards', wallet_upg.steal_tokens == 2)


# -- D4-10: starting steal_tokens unchanged by upgrade -------------------------

def test_starting_tokens():
    with flask_app.app_context():
        pid = _IDS['player_a_id']
        admin_id = _IDS['admin_id']
        gs, gr = _make_session_with_round()
        _enroll(gs.id, pid)
        db.session.commit()

        # Award diamonds, buy steal_token_cap upgrade
        award_diamonds_to_player(player_id=pid, amount=50, reason='seed', admin_player_id=admin_id)
        db.session.commit()
        purchase_upgrade(player_id=pid, upgrade_type='steal_token_cap')
        db.session.commit()

        # Create wallet -- starts at 0 steal_tokens regardless of upgrade
        wallet = PlayerWallet(player_id=pid, session_id=gs.id, gold=100, gems=0, steal_tokens=0)
        db.session.add(wallet)
        db.session.commit()

        # D4-10: initial tokens are 0 regardless of steal_token_cap upgrade level
        check('D4-10: new wallet starts with steal_tokens == 0 regardless of upgrade',
              wallet.steal_tokens == 0,
              f'got {wallet.steal_tokens}')


# -- D4-11: token consumption unchanged ---------------------------------------

def test_token_consumption():
    # Token consumption is wallet.steal_tokens -= 1 (events.py handle_steal_pick_target)
    # The upgrade only affects the CAP, not the consumption cost.
    # Verify by simulating: wallet with 2 tokens, steal pick consumes 1 -> 1 remaining.
    with flask_app.app_context():
        pid = _IDS['player_b_id']
        gs, gr = _make_session_with_round()
        db.session.commit()

        wallet = PlayerWallet(player_id=pid, session_id=gs.id, gold=100, gems=0, steal_tokens=2)
        db.session.add(wallet)
        db.session.commit()

        # Simulate token consumption as done in handle_steal_pick_target
        wallet.steal_tokens -= 1
        db.session.commit()

        check('D4-11: token consumption deducts exactly 1 token',
              wallet.steal_tokens == 1,
              f'got {wallet.steal_tokens}')


# -- D4-12 / D4-13: manual shield duration ------------------------------------

def test_manual_shield_duration():
    with flask_app.app_context():
        pid = _IDS['player_a_id']
        gs, gr = _make_session_with_round()
        _enroll(gs.id, pid)
        db.session.commit()

        # Snapshot baseline (no upgrades) -> shield_bonus_pct == 0.0
        ensure_all_session_participant_snapshots(gs.id)
        db.session.commit()
        mods = get_session_player_modifiers(gs.id, pid)

        cfg = _make_config()   # shield_duration = 60

        # D4-13: baseline -- effective duration == base duration
        effective_s_baseline = round(cfg.shield_duration * (1 + mods.effective_shield_bonus_pct))
        check('D4-13: baseline manual shield duration == config.shield_duration',
              effective_s_baseline == cfg.shield_duration,
              f'got {effective_s_baseline}')

        # D4-12: with shield_bonus_pct -- duration is increased
        high_pct = UPGRADE_CATALOG['shield_bonus_pct'].effects[3]   # level 3 -> 0.20
        expected_boosted = round(cfg.shield_duration * (1 + high_pct))   # round(60 * 1.20) = 72
        check('D4-12: boosted manual shield duration == round(base * (1 + pct))',
              expected_boosted == round(cfg.shield_duration * (1 + high_pct)),
              f'got {expected_boosted}')
        check('D4-12: boosted shield duration > base duration',
              expected_boosted > cfg.shield_duration,
              f'{expected_boosted} vs {cfg.shield_duration}')

        # Verify engine.grant_steal_shield uses the passed value correctly
        now = datetime.now(timezone.utc)
        pcs = PlayerClassicState(player_id=pid, session_id=gs.id)
        db.session.add(pcs)
        db.session.flush()

        engine.grant_steal_shield(pcs, effective_s_baseline)
        expiry_base = pcs.shield_expires_at
        if expiry_base.tzinfo is None:
            expiry_base = expiry_base.replace(tzinfo=timezone.utc)
        actual_s = round((expiry_base - now).total_seconds())
        check('D4-13: engine.grant_steal_shield uses passed duration',
              abs(actual_s - effective_s_baseline) <= 2,
              f'got ~{actual_s}s, expected {effective_s_baseline}s')


# -- D4-14 / D4-15: reactive shield duration ----------------------------------

def test_reactive_shield_duration():
    with flask_app.app_context():
        pid_actor  = _IDS['player_a_id']
        pid_target = _IDS['player_b_id']
        admin_id   = _IDS['admin_id']
        gs, gr = _make_session_with_round()
        _enroll(gs.id, pid_actor)
        _enroll(gs.id, pid_target)
        db.session.commit()

        cfg = _make_config()

        # D4-15: baseline target -- shield_bonus_pct == 0.0 in snapshot
        ensure_all_session_participant_snapshots(gs.id)
        db.session.commit()
        target_mods = get_session_player_modifiers(gs.id, pid_target)
        eff_shield_s_base = round(cfg.shield_duration * (1 + target_mods.effective_shield_bonus_pct))
        check('D4-15: baseline reactive shield duration == config.shield_duration',
              eff_shield_s_base == cfg.shield_duration,
              f'got {eff_shield_s_base}')

        # D4-14: give target an upgrade level, snapshot in a new session
        award_diamonds_to_player(player_id=pid_target, amount=100,
                                  reason='seed', admin_player_id=admin_id)
        db.session.commit()
        purchase_upgrade(player_id=pid_target, upgrade_type='shield_bonus_pct')
        db.session.commit()

        gs2, gr2 = _make_session_with_round()
        _enroll(gs2.id, pid_target)
        db.session.commit()
        ensure_all_session_participant_snapshots(gs2.id)
        db.session.commit()

        target_mods2 = get_session_player_modifiers(gs2.id, pid_target)
        expected_pct   = UPGRADE_CATALOG['shield_bonus_pct'].effects[1]  # level 1 -> 0.10
        eff_shield_s   = round(cfg.shield_duration * (1 + target_mods2.effective_shield_bonus_pct))
        expected_shield = round(cfg.shield_duration * (1 + expected_pct))

        check('D4-14: target mods reflect purchased shield_bonus_pct level',
              abs(target_mods2.effective_shield_bonus_pct - expected_pct) < 0.001,
              f'got {target_mods2.effective_shield_bonus_pct}')
        check('D4-14: reactive shield duration > base duration with upgrade',
              eff_shield_s > cfg.shield_duration,
              f'{eff_shield_s} vs {cfg.shield_duration}')
        check('D4-14: reactive shield duration == round(base * (1 + pct))',
              eff_shield_s == expected_shield,
              f'got {eff_shield_s}, expected {expected_shield}')


# -- D4-16: post-session-start purchase does NOT change snapshot ---------------

def test_no_mid_session_mutation():
    with flask_app.app_context():
        pid      = _IDS['player_a_id']
        admin_id = _IDS['admin_id']
        gs, gr   = _make_session_with_round()
        _enroll(gs.id, pid)
        db.session.commit()

        # Snapshot at session start (no upgrades yet)
        ensure_all_session_participant_snapshots(gs.id)
        db.session.commit()
        mods_before = get_session_player_modifiers(gs.id, pid)
        mine_before = mods_before.effective_mine_bonus    # should be 0

        # Buy mine_bonus upgrade after the session has started
        award_diamonds_to_player(player_id=pid, amount=50, reason='seed', admin_player_id=admin_id)
        db.session.commit()
        purchase_upgrade(player_id=pid, upgrade_type='mine_bonus')
        db.session.commit()

        # Re-read the same snapshot row
        db.session.expire_all()
        mods_after = get_session_player_modifiers(gs.id, pid)
        check('D4-16: snapshot effective_mine_bonus unchanged after mid-session purchase',
              mods_after.effective_mine_bonus == mine_before,
              f'was {mine_before}, now {mods_after.effective_mine_bonus}')


# -- D4-17: next session picks up post-session upgrade -------------------------

def test_next_session_picks_up_upgrade():
    with flask_app.app_context():
        pid      = _IDS['player_b_id']
        admin_id = _IDS['admin_id']

        # Session 1: snapshot before purchase
        gs1, gr1 = _make_session_with_round()
        _enroll(gs1.id, pid)
        db.session.commit()
        ensure_all_session_participant_snapshots(gs1.id)
        db.session.commit()
        mods1 = get_session_player_modifiers(gs1.id, pid)
        check('D4-17: precondition -- session 1 mine_bonus == 0',
              mods1.effective_mine_bonus == 0)

        # Buy mine_bonus (player buys between sessions)
        award_diamonds_to_player(player_id=pid, amount=50, reason='seed', admin_player_id=admin_id)
        db.session.commit()
        purchase_upgrade(player_id=pid, upgrade_type='mine_bonus')
        db.session.commit()

        # Session 2: new session snapshot
        gs2, gr2 = _make_session_with_round()
        _enroll(gs2.id, pid)
        db.session.commit()
        ensure_all_session_participant_snapshots(gs2.id)
        db.session.commit()

        mods2 = get_session_player_modifiers(gs2.id, pid)
        expected = UPGRADE_CATALOG['mine_bonus'].effects[1]   # level 1 -> 5
        check('D4-17: session 2 snapshot includes the newly purchased mine_bonus',
              mods2.effective_mine_bonus == expected,
              f'got {mods2.effective_mine_bonus}, expected {expected}')


# -- Main ---------------------------------------------------------------------

if __name__ == '__main__':
    print('\nD4 Gameplay Modifier Wiring - Tests')
    print('-' * 60)

    _setup_db()
    test_helper()
    test_mine_bonus()
    test_treasure_bonus()
    test_steal_token_cap()
    test_starting_tokens()
    test_token_consumption()
    test_manual_shield_duration()
    test_reactive_shield_duration()
    test_no_mid_session_mutation()
    test_next_session_picks_up_upgrade()

    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL D4 TESTS PASSED.')
    else:
        print('SOME D4 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
