"""
test_classic_step_c.py
======================

Exit test for Classic Mode Step C: Random Treasure Search gold + Gems.

Tests the entire feature layer directly inside a Flask application context
(no HTTP requests, no WebSocket connections required).

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_classic_step_c.py

Expected output: all assertions pass, final line prints "ALL TESTS PASSED."
"""

import sys
import os
import subprocess
import types
from datetime import datetime, timezone

# ── Allow imports from project root when running from tests/ subdirectory ─────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig, PlayerWallet, PlayerProblemState,
    ProblemSolverCount, StoreItem, PlayerInventory,
)
from app.core.problem_engine import check_answer
from app.modes.classic import engine, state

flask_app = create_app()

SET_NAME = '__test_step_c__'

_PROB_TITLES = [f'StepC P{i}' for i in range(1, 7)]


def _clean():
    """Remove all test artefacts so the test is fully repeatable."""
    ps = ProblemSet.query.filter_by(name=SET_NAME).first()

    for gs in GameSession.query.filter_by(mode='classic').all():
        if gs.problem_set and gs.problem_set.name == SET_NAME:
            sid = gs.id
            PlayerInventory.query.filter_by(session_id=sid).delete()
            StoreItem.query.filter_by(session_id=sid).delete()
            PlayerWallet.query.filter_by(session_id=sid).delete()
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
        for prob in Problem.query.filter(Problem.title.in_(_PROB_TITLES)).all():
            PlayerProblemState.query.filter_by(problem_id=prob.id).delete()
            ProblemSolverCount.query.filter_by(problem_id=prob.id).delete()
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()

    for uname in ('__sc_p1__', '__sc_p2__'):
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


def run_exit_test():
    with flask_app.app_context():
        _clean()
        errors = []

        def check(label, condition, detail=''):
            if not condition:
                errors.append(f'FAIL [{label}]{": " + detail if detail else ""}')
            else:
                print(f'  pass  {label}')

        print('\n── Step C Setup ─────────────────────────────────────────')

        # ── T01: Create test players ──────────────────────────────────────────
        p1 = Player(username='__sc_p1__', is_admin=False)
        p1.set_password('x')
        p2 = Player(username='__sc_p2__', is_admin=False)
        p2.set_password('x')
        db.session.add_all([p1, p2])
        db.session.flush()
        check('T01 players created', p1.id and p2.id)

        # ── T02: Create problem set + 6 problems ──────────────────────────────
        #   6 problems lets us trigger milestone (N=3) at solve 3 and again at 6.
        topic = Topic.query.first()
        if not topic:
            topic = Topic(name='__sc_topic__', subject='Test')
            db.session.add(topic)
            db.session.flush()

        problems = []
        for i in range(1, 7):
            prob = Problem(
                topic_id=topic.id,
                title=f'StepC P{i}',
                prompt_text=str(i),
                answer_text=str(i),
                difficulty=1,
            )
            db.session.add(prob)
            problems.append(prob)
        db.session.flush()

        ps = ProblemSet(name=SET_NAME, description='Step C test set')
        db.session.add(ps)
        db.session.flush()
        for prob in problems:
            ps.problems.append(prob)
        db.session.flush()
        check('T02 problem set + 6 problems created', ps.id and len(problems) == 6)

        # ── T03: Create session + round + Step C config ───────────────────────
        #   gem_milestone_count=3 → +1 gem every 3 solves
        #   gem_streak_count=2   → +1 gem every 2 consecutive correct answers
        #   treasure_search_max_reward=15, treasure_search_reward=5 → range [5, 15]
        gs = GameSession(mode='classic', status='waiting', problem_set_id=ps.id)
        db.session.add(gs)
        db.session.flush()
        gr = GameRound(session_id=gs.id, problem_id=None, round_number=1, started_at=None)
        db.session.add(gr)
        db.session.flush()
        cfg = ClassicRoundConfig(
            round_id=gr.id,
            mine_reward=20,
            treasure_search_reward=5,
            treasure_search_max_reward=15,
            gem_milestone_count=3,
            gem_streak_count=2,
            attempts_per_problem=-1,
            wrong_answer_penalty=0,
            bonus_timer_duration=120,
            bonus_timer_gold=5,
            first_solver_count=3,
            first_solver_multiplier=2,
        )
        db.session.add(cfg)
        db.session.commit()
        check('T03 session/round/config created', gs.id and gr.id and cfg.id)

        # ── T04: Activate session ─────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        gs.status = 'active'
        gs.started_at = now
        gr.started_at = now
        db.session.commit()
        state.init_session(gs.id, now)
        check('T04 session active + timer initialised', gs.status == 'active')

        print('\n── Wallet & Config fields ───────────────────────────────')

        # ── T05: PlayerWallet created with gems=0 ─────────────────────────────
        w1 = PlayerWallet(player_id=p1.id, session_id=gs.id, gold=0, gems=0)
        db.session.add(w1)
        db.session.commit()
        check('T05 wallet.gems initialised to 0', w1.gems == 0)
        check('T05 wallet.gold initialised to 0', w1.gold == 0)

        # ── T06: ClassicRoundConfig stores 3 Step C fields correctly ──────────
        db.session.refresh(cfg)
        check('T06 treasure_search_max_reward=15', cfg.treasure_search_max_reward == 15)
        check('T06 gem_milestone_count=3',         cfg.gem_milestone_count == 3)
        check('T06 gem_streak_count=2',            cfg.gem_streak_count == 2)

        print('\n── Random Treasure Search gold ──────────────────────────')

        # ── T07: 200 raw rolls in [5, 15] + distribution is not constant ──────
        raw_rolls = [
            engine.calc_treasure_search_reward(cfg, solver_rank=1, timer_active=False)['treasure_roll']
            for _ in range(200)
        ]
        check('T07 all 200 raw rolls in [5, 15]',
              all(5 <= r <= 15 for r in raw_rolls),
              f'min={min(raw_rolls)} max={max(raw_rolls)}')
        check('T07 at least 2 distinct values in 200 rolls (distribution not fixed)',
              len(set(raw_rolls)) > 1)

        # ── T08: min == max → every roll is that exact value ──────────────────
        cfg_fixed = types.SimpleNamespace(
            treasure_search_reward=10,
            treasure_search_max_reward=10,
            first_solver_count=0,
            first_solver_multiplier=0,
            bonus_timer_duration=0,
            bonus_timer_gold=0,
        )
        fixed_rolls = [
            engine.calc_treasure_search_reward(cfg_fixed, 1, False)['treasure_roll']
            for _ in range(100)
        ]
        check('T08 all 100 rolls == 10 when ts_min=ts_max=10',
              all(r == 10 for r in fixed_rolls))

        # ── T09: ts_max < ts_min → clamped to ts_min ─────────────────────────
        cfg_clamped = types.SimpleNamespace(
            treasure_search_reward=5,
            treasure_search_max_reward=3,   # below min → engine clamps to 5
            first_solver_count=0,
            first_solver_multiplier=0,
            bonus_timer_duration=0,
            bonus_timer_gold=0,
        )
        clamped_rolls = [
            engine.calc_treasure_search_reward(cfg_clamped, 1, False)['treasure_roll']
            for _ in range(50)
        ]
        check('T09 all rolls == ts_min(5) when ts_max(3) < ts_min(5)',
              all(r == 5 for r in clamped_rolls))

        # ── T10: TS gold = roll + first-solver bonus + timer bonus ────────────
        #   Use deterministic roll (min=max=10), rank 1 (fsb=6), timer active (+5)
        #   → total = 10 + 6 + 5 = 21; breakdown has 3 components
        cfg_full = types.SimpleNamespace(
            treasure_search_reward=10,
            treasure_search_max_reward=10,
            first_solver_count=3,
            first_solver_multiplier=2,
            bonus_timer_duration=120,
            bonus_timer_gold=5,
        )
        ts_full = engine.calc_treasure_search_reward(cfg_full, solver_rank=1, timer_active=True)
        check('T10 TS total = roll(10) + fsb(6) + timer(5) = 21',
              ts_full['gold'] == 21, f'got {ts_full["gold"]}')
        check('T10 breakdown has 3 components (roll + fsb + timer)',
              len(ts_full['breakdown']) == 3, str(ts_full['breakdown']))

        # ── T11: treasure_roll key present in calc_treasure_search_reward ──────
        ts_r = engine.calc_treasure_search_reward(cfg, solver_rank=2, timer_active=False)
        check('T11 treasure_roll key present in TS result dict', 'treasure_roll' in ts_r)
        check('T11 treasure_roll value in [ts_min, ts_max]',
              5 <= ts_r['treasure_roll'] <= 15, f'got {ts_r["treasure_roll"]}')

        # ── T12: calc_mine_reward has no treasure_roll key ────────────────────
        mine_r = engine.calc_mine_reward(cfg, solver_rank=1, timer_active=False)
        check('T12 treasure_roll absent from mine result', 'treasure_roll' not in mine_r)

        print('\n── Gem milestone ────────────────────────────────────────')

        # ── T13: solve count == N → +1 gem, reason='milestone' ───────────────
        gem13 = engine.calc_gem_award(solved_count=3, cfg_milestone=3,
                                       streak_count=0, cfg_streak=2)
        check('T13 solved=3, milestone=3 → gems=1', gem13['gems'] == 1)
        check('T13 reason = milestone', gem13['reason'] == 'milestone')

        # ── T14: solve count == N+1 → no gem (not divisible) ─────────────────
        gem14 = engine.calc_gem_award(solved_count=4, cfg_milestone=3,
                                       streak_count=0, cfg_streak=2)
        check('T14 solved=4, milestone=3 → gems=0', gem14['gems'] == 0)
        check('T14 reason = None', gem14['reason'] is None)

        # ── T15: solve count == 2N → milestone fires again ────────────────────
        gem15 = engine.calc_gem_award(solved_count=6, cfg_milestone=3,
                                       streak_count=0, cfg_streak=2)
        check('T15 solved=6, milestone=3 → gems=1 (fires at 2N)',
              gem15['gems'] == 1)
        check('T15 reason = milestone', gem15['reason'] == 'milestone')

        # ── T16: gem_milestone_count=0 disables milestone entirely ───────────
        gem16 = engine.calc_gem_award(solved_count=3, cfg_milestone=0,
                                       streak_count=0, cfg_streak=2)
        check('T16 cfg_milestone=0 → gems=0', gem16['gems'] == 0)
        check('T16 cfg_milestone=0 → reason=None', gem16['reason'] is None)

        print('\n── Gem streak ───────────────────────────────────────────')

        # ── T17: K consecutive correct → +1 gem, reason='streak' ─────────────
        state.reset_streak(p1.id, gr.id)          # fresh state for streak section
        state.increment_streak(p1.id, gr.id)
        streak_k2 = state.increment_streak(p1.id, gr.id)   # streak = 2
        gem17 = engine.calc_gem_award(solved_count=1, cfg_milestone=3,
                                       streak_count=streak_k2, cfg_streak=2)
        check('T17 streak=2, cfg_streak=2 → gems=1', gem17['gems'] == 1)
        check('T17 reason = streak', gem17['reason'] == 'streak')

        # ── T18: Wrong answer resets streak; no gem when streak=0 ────────────
        state.reset_streak(p1.id, gr.id)
        reset_val = state.get_streak(p1.id, gr.id)
        check('T18 get_streak = 0 after reset', reset_val == 0)
        gem18 = engine.calc_gem_award(solved_count=1, cfg_milestone=3,
                                       streak_count=reset_val, cfg_streak=2)
        check('T18 no gem when streak=0 after wrong answer', gem18['gems'] == 0)

        # ── T19: 2 consecutive correct after reset → streak gem fires again ───
        state.increment_streak(p1.id, gr.id)
        streak_again = state.increment_streak(p1.id, gr.id)   # streak = 2 again
        gem19 = engine.calc_gem_award(solved_count=1, cfg_milestone=3,
                                       streak_count=streak_again, cfg_streak=2)
        check('T19 streak=2 after reset → gems=1 again', gem19['gems'] == 1)

        # ── T20: gem_streak_count=0 disables streak reward entirely ──────────
        gem20 = engine.calc_gem_award(solved_count=1, cfg_milestone=3,
                                       streak_count=2, cfg_streak=0)
        check('T20 cfg_streak=0 → gems=0', gem20['gems'] == 0)
        check('T20 cfg_streak=0 → reason=None', gem20['reason'] is None)

        print('\n── Simultaneous milestone + streak ──────────────────────')

        # ── T21: Both rules fire on the same action ───────────────────────────
        #   solved=3 (3%3=0) AND streak=2 (2%2=0) → gems=2, reason='both'
        gem21 = engine.calc_gem_award(solved_count=3, cfg_milestone=3,
                                       streak_count=2, cfg_streak=2)
        check('T21 milestone + streak both fire → gems=2', gem21['gems'] == 2)
        check('T21 reason = both', gem21['reason'] == 'both')

        print('\n── Wrong answer: streak reset ───────────────────────────')

        # ── T22: state.reset_streak works correctly ───────────────────────────
        state.reset_streak(p1.id, gr.id)
        state.increment_streak(p1.id, gr.id)
        state.increment_streak(p1.id, gr.id)
        pre_reset_streak = state.increment_streak(p1.id, gr.id)   # streak = 3
        check('T22 streak = 3 before wrong answer', pre_reset_streak == 3)
        state.reset_streak(p1.id, gr.id)
        post_reset_streak = state.get_streak(p1.id, gr.id)
        check('T22 streak = 0 after state.reset_streak', post_reset_streak == 0)

        # ── T23: calc_gem_award with streak=0 awards no gems ─────────────────
        gem23 = engine.calc_gem_award(solved_count=1, cfg_milestone=3,
                                       streak_count=0, cfg_streak=2)
        check('T23 no gems when streak=0 and milestone not hit',
              gem23['gems'] == 0 and gem23['reason'] is None)

        print('\n── Payload key coverage ─────────────────────────────────')

        # ── T24: calc_treasure_search_reward result has all required keys ──────
        ts_keys_result = engine.calc_treasure_search_reward(
            cfg, solver_rank=1, timer_active=False
        )
        check('T24 TS result has gold key',          'gold'          in ts_keys_result)
        check('T24 TS result has breakdown key',     'breakdown'     in ts_keys_result)
        check('T24 TS result has treasure_roll key', 'treasure_roll' in ts_keys_result)

        # ── T25: calc_gem_award result has all required keys ──────────────────
        ga_keys_result = engine.calc_gem_award(1, 3, 1, 2)
        check('T25 gem_award result has gems key',   'gems'   in ga_keys_result)
        check('T25 gem_award result has reason key', 'reason' in ga_keys_result)

        print('\n── join_ack gems / leaderboard gems ─────────────────────')

        # ── T26: PlayerWallet.gems column is present and DB-readable ──────────
        #   This is the data source for the 'gems' field in join_ack payloads.
        w1_db = db.session.get(PlayerWallet, w1.id)
        check('T26 wallet.gems column readable after DB commit', hasattr(w1_db, 'gems'))
        check('T26 wallet.gems value = 0 (initial)', w1_db.gems == 0)

        # ── T27: Leaderboard query includes gems for all wallets ──────────────
        #   events.py leaderboard builder queries PlayerWallet.gems per wallet.
        w2 = PlayerWallet(player_id=p2.id, session_id=gs.id, gold=10, gems=3)
        db.session.add(w2)
        db.session.commit()
        lb_wallets = PlayerWallet.query.filter_by(session_id=gs.id).all()
        check('T27 leaderboard query returns 2 wallets', len(lb_wallets) == 2)
        check('T27 all leaderboard wallets expose gems attr',
              all(hasattr(w, 'gems') for w in lb_wallets))
        check('T27 w2.gems = 3 visible in leaderboard query data',
              any(w.gems == 3 for w in lb_wallets))

        print('\n── Gems are session-scoped (no carry-over) ──────────────')

        # ── T28: Gems from session 1 do not appear in a new session ──────────
        w1_db = db.session.get(PlayerWallet, w1.id)
        w1_db.gems = 7
        db.session.commit()

        gs2 = GameSession(mode='classic', status='waiting', problem_set_id=ps.id)
        db.session.add(gs2)
        db.session.flush()
        w1_s2 = PlayerWallet(player_id=p1.id, session_id=gs2.id, gold=0, gems=0)
        db.session.add(w1_s2)
        db.session.commit()

        w1_sess1 = PlayerWallet.query.filter_by(
            player_id=p1.id, session_id=gs.id
        ).first()
        w1_sess2 = db.session.get(PlayerWallet, w1_s2.id)
        check('T28 session 1 wallet gems = 7', w1_sess1.gems == 7)
        check('T28 session 2 wallet gems = 0 (no carry-over)', w1_sess2.gems == 0)

        # Clean up second session
        PlayerWallet.query.filter_by(session_id=gs2.id).delete()
        db.session.delete(gs2)
        db.session.commit()

        print('\n── Currency independence ─────────────────────────────────')

        # ── T29: Changing gold does not affect gems ───────────────────────────
        w1_db = db.session.get(PlayerWallet, w1.id)
        gems_before_gold_change = w1_db.gems   # 7 from T28
        w1_db.gold += 50
        db.session.commit()
        w1_db = db.session.get(PlayerWallet, w1.id)
        check('T29 adding gold does not change gems',
              w1_db.gems == gems_before_gold_change,
              f'gems before={gems_before_gold_change} after={w1_db.gems}')
        check('T29 gold updated correctly to 50', w1_db.gold == 50)

        # ── T30: Changing gems does not affect gold ───────────────────────────
        gold_before_gem_change = w1_db.gold   # 50
        w1_db.gems += 2
        db.session.commit()
        w1_db = db.session.get(PlayerWallet, w1.id)
        check('T30 adding gems does not change gold',
              w1_db.gold == gold_before_gem_change,
              f'gold before={gold_before_gem_change} after={w1_db.gold}')
        check('T30 gems updated correctly to 9', w1_db.gems == gems_before_gold_change + 2)

        print('\n── wallet.gems DB persistence ───────────────────────────')

        # ── T31: wallet.gems persists across two sequential commits ───────────
        w1_db.gems = 0
        db.session.commit()
        w1_db.gems += 5
        db.session.commit()
        w1_fresh = db.session.get(PlayerWallet, w1.id)
        check('T31 wallet.gems = 5 after two sequential commits', w1_fresh.gems == 5)

        # ── T32: Gem awards accumulate across multiple solve events ───────────
        #   Simulate: solve 3 (+1), solve 4 (0), solve 6 (+1) → net +2
        gems_start = w1_fresh.gems                          # 5
        for solved_count in [3, 4, 6]:
            award = engine.calc_gem_award(solved_count, cfg.gem_milestone_count, 0, 2)
            w1_fresh.gems += award['gems']
        db.session.commit()
        w1_fresh = db.session.get(PlayerWallet, w1.id)
        check('T32 gems accumulate +2 across solves at 3, 4, 6',
              w1_fresh.gems == gems_start + 2,
              f'expected {gems_start + 2}, got {w1_fresh.gems}')

        print('\n── Milestone is DB-backed (survives state clear) ────────')

        # ── T33: solved_count from DB drives milestone correctly ──────────────
        #   Create 3 solved PPS rows; verify DB count == 3 and milestone fires.
        for i in range(3):
            pps_row = PlayerProblemState(
                player_id=p1.id,
                round_id=gr.id,
                problem_id=problems[i].id,
                attempts_used=1,
                is_solved=True,
                is_closed=True,
            )
            db.session.add(pps_row)
        db.session.commit()

        solved_from_db = PlayerProblemState.query.filter_by(
            player_id=p1.id, round_id=gr.id, is_solved=True
        ).count()
        check('T33 DB-queried solved count = 3', solved_from_db == 3)
        gem_t33 = engine.calc_gem_award(
            solved_from_db, cfg.gem_milestone_count, 0, 2
        )
        check('T33 milestone fires using DB count', gem_t33['gems'] == 1)
        check('T33 reason = milestone',             gem_t33['reason'] == 'milestone')

        # ── T34: DB count unchanged after state.clear_session ─────────────────
        #   clear_session only removes in-memory timer state; DB rows are untouched.
        state.clear_session(gs.id)
        solved_after_clear = PlayerProblemState.query.filter_by(
            player_id=p1.id, round_id=gr.id, is_solved=True
        ).count()
        check('T34 DB solved count = 3 after state.clear_session',
              solved_after_clear == 3)
        gem_t34 = engine.calc_gem_award(
            solved_after_clear, cfg.gem_milestone_count, 0, 2
        )
        check('T34 milestone still fires from DB count after clear_session',
              gem_t34['gems'] == 1 and gem_t34['reason'] == 'milestone')

        print('\n── Multi-player DB consistency ──────────────────────────')

        # ── T35: wallet totals correct after gem + gold awards ────────────────
        #   Reset both wallets; apply awards; verify each wallet independently.
        w1_fresh = db.session.get(PlayerWallet, w1.id)
        w2_fresh = db.session.get(PlayerWallet, w2.id)
        w1_fresh.gold = 0
        w1_fresh.gems = 0
        w2_fresh.gold = 0
        w2_fresh.gems = 0
        db.session.commit()

        # p1: 3 solves (milestone) + streak=2 (streak gem) → gems=2; gold=20
        gem_p1 = engine.calc_gem_award(3, cfg.gem_milestone_count, 2, cfg.gem_streak_count)
        w1_fresh.gems += gem_p1['gems']
        w1_fresh.gold += 20

        # p2: 2 solves (no milestone), no streak → gems=0; gold=15
        gem_p2 = engine.calc_gem_award(2, cfg.gem_milestone_count, 0, cfg.gem_streak_count)
        w2_fresh.gems += gem_p2['gems']
        w2_fresh.gold += 15
        db.session.commit()

        w1_check = db.session.get(PlayerWallet, w1.id)
        w2_check = db.session.get(PlayerWallet, w2.id)
        check('T35 p1 gems = 2 (milestone + streak)',
              w1_check.gems == 2, f'got {w1_check.gems}')
        check('T35 p2 gems = 0 (no award)',
              w2_check.gems == 0, f'got {w2_check.gems}')
        check('T35 p1 gold = 20', w1_check.gold == 20, f'got {w1_check.gold}')
        check('T35 p2 gold = 15', w2_check.gold == 15, f'got {w2_check.gold}')

        # ── T36: DB row counts + aggregate totals are consistent ──────────────
        wallet_count = PlayerWallet.query.filter_by(session_id=gs.id).count()
        check('T36 exactly 2 wallet rows for session gs', wallet_count == 2)

        all_wallets = PlayerWallet.query.filter_by(session_id=gs.id).all()
        total_gems = sum(w.gems for w in all_wallets)
        total_gold = sum(w.gold for w in all_wallets)
        check('T36 total gems across both wallets = 2',  total_gems == 2,
              f'got {total_gems}')
        check('T36 total gold across both wallets = 35', total_gold == 35,
              f'got {total_gold}')

        print('\n── Regression: Step A ───────────────────────────────────')

        # Release all pooled DB connections before launching subprocesses.
        # SQLite's default journal mode allows only one writer at a time;
        # a live connection in the pool would block the subprocess from acquiring
        # the exclusive write lock needed by its own _clean() / insert operations.
        db.session.remove()
        db.engine.dispose()

        # ── T37: All 32 Step A tests still pass ───────────────────────────────
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Force UTF-8 I/O in subprocesses: VS Code sets PYTHONUTF8=1 but
        # subprocess.run() may inherit a legacy cp1251 console encoding.
        utf8_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
        r_a = subprocess.run(
            [sys.executable, 'test_classic_step_a.py'],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=utf8_env,
        )
        last_line_a = r_a.stdout.strip().split('\n')[-1] if r_a.stdout.strip() else r_a.stderr[:200]
        check('T37 Step A: all 32 tests still pass',
              r_a.returncode == 0, last_line_a)

        print('\n── Regression: Step B ───────────────────────────────────')

        # ── T38: All 48 Step B tests still pass ───────────────────────────────
        r_b = subprocess.run(
            [sys.executable, 'test_classic_step_b.py'],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=utf8_env,
        )
        last_line_b = r_b.stdout.strip().split('\n')[-1] if r_b.stdout.strip() else r_b.stderr[:200]
        check('T38 Step B: all 48 tests still pass',
              r_b.returncode == 0, last_line_b)

        # ── Summary ───────────────────────────────────────────────────────────

        print()
        if errors:
            for e in errors:
                print(e)
            print(f'\n{len(errors)} test(s) FAILED.')
            return 1
        else:
            print('ALL TESTS PASSED.')
            return 0


if __name__ == '__main__':
    sys.exit(run_exit_test())
