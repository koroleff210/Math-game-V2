"""
test_classic_step_a.py
======================

Exit test for Classic Mode Step A.

Tests the core business-logic layer directly inside a Flask application context
(no HTTP requests, no WebSocket connections required).

Run:
    .venv\\Scripts\\python.exe test_classic_step_a.py

Expected output: all assertions pass, final line prints "ALL TESTS PASSED".
"""

import sys
from datetime import datetime, timezone

# ── Bootstrap ──────────────────────────────────────────────────────────────────

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig, PlayerWallet, PlayerProblemState, ProblemSolverCount
)
from app.core.problem_engine import check_answer
from app.modes.classic import engine, state

flask_app = create_app()


def _clean(set_name='__test_classic__'):
    """Delete test data so the test is repeatable."""
    # Find the test problem set
    ps = ProblemSet.query.filter_by(name=set_name).first()

    # Delete sessions and all their dependants explicitly in FK-safe order
    for gs in GameSession.query.filter_by(mode='classic').all():
        if gs.problem_set and gs.problem_set.name == set_name:
            sid = gs.id
            # Must delete PlayerWallet before GameSession (no cascade)
            PlayerWallet.query.filter_by(session_id=sid).delete()
            # PlayerProblemState + ProblemSolverCount reference game_round
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
            # Now safe to delete the session (cascades rounds, round_players)
            db.session.delete(gs)
    db.session.flush()

    # Detach problems from problem set (M2M) then delete
    if ps:
        # lazy='dynamic' → must remove each item individually
        for prob in ps.problems.all():
            ps.problems.remove(prob)
        db.session.flush()
        # Delete problems that were in this test problem set
        for prob in Problem.query.filter(Problem.title.in_(['Problem 1', 'Problem 2'])).all():
            PlayerProblemState.query.filter_by(problem_id=prob.id).delete()
            ProblemSolverCount.query.filter_by(problem_id=prob.id).delete()
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()

    # Raw SQL player cleanup to avoid FK cascade from cross-session references
    for uname in ('__test_p1__', '__test_p2__'):
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

        def check(label, condition, extra=''):
            if not condition:
                msg = f'FAIL  {label}'
                if extra:
                    msg += f'  ({extra})'
                errors.append(msg)
                print(msg)
            else:
                print(f'PASS  {label}')

        # ── 1. Create problem set & problems ──────────────────────────────────

        topic = Topic.query.first()
        if not topic:
            topic = Topic(name='__test_topic__', description='test')
            db.session.add(topic)
            db.session.flush()

        prob1 = Problem(
            topic_id=topic.id,
            title='Problem 1',
            prompt_text='What is 6 × 7?',
            answer_text='42',
            difficulty=1,
        )
        prob2 = Problem(
            topic_id=topic.id,
            title='Problem 2',
            prompt_text='What is 3 + 5?',
            answer_text='8',
            difficulty=1,
        )
        problem_set = ProblemSet(name='__test_classic__', description='exit test')
        db.session.add_all([prob1, prob2, problem_set])
        db.session.flush()

        # Link problems to set via association table
        problem_set.problems.append(prob1)
        problem_set.problems.append(prob2)
        db.session.flush()

        # ── 2. Create two players ─────────────────────────────────────────────

        p1 = Player(username='__test_p1__', is_admin=False)
        p1.set_password('x')
        p2 = Player(username='__test_p2__', is_admin=False)
        p2.set_password('x')
        db.session.add_all([p1, p2])
        db.session.flush()

        # ── 3. Create session + round + config ────────────────────────────────

        game_session = GameSession(
            mode='classic',
            status='waiting',
            problem_set_id=problem_set.id,
        )
        db.session.add(game_session)
        db.session.flush()

        game_round = GameRound(
            session_id=game_session.id,
            problem_id=None,
            round_number=1,
            started_at=None,   # not started yet
        )
        db.session.add(game_round)
        db.session.flush()

        config = ClassicRoundConfig(
            round_id=game_round.id,
            mine_reward=20,
            treasure_search_reward=5,
            attempts_per_problem=1,
            wrong_answer_penalty=5,
            bonus_timer_duration=120,
            bonus_timer_gold=5,
            first_solver_count=3,
            first_solver_multiplier=2,
        )
        db.session.add(config)
        db.session.commit()

        check("T01  GameSession created with mode='classic'",
              game_session.id is not None and game_session.status == 'waiting')
        check("T02  GameRound created with problem_id=None (Classic mode, no single problem)",
              game_round.problem_id is None)
        check("T03  ClassicRoundConfig linked to round",
              config.round_id == game_round.id)

        # Reload config via backref
        db.session.refresh(game_round)
        check("T04  game_round.classic_config backref works",
              game_round.classic_config is not None)

        # ── 4. Admin starts the round ─────────────────────────────────────────

        now = datetime.now(timezone.utc)
        game_round.started_at = now
        game_session.status = 'active'
        game_session.started_at = now
        db.session.commit()

        state.init_session(game_session.id, now)

        check("T05  Round started (started_at set, session active)",
              game_round.started_at is not None and game_session.status == 'active')
        check("T06  state.is_timer_active returns True right after init",
              state.is_timer_active(game_session.id, config.bonus_timer_duration))

        # ── 5. Both players "join" — wallets + problem states created ─────────

        def simulate_join(player, g_session, g_round, cfg, probs):
            """Replicate what handle_join does in events.py."""
            rp = RoundPlayer.query.filter_by(
                session_id=g_session.id, player_id=player.id
            ).first()
            if not rp:
                rp = RoundPlayer(session_id=g_session.id, player_id=player.id)
                db.session.add(rp)
                db.session.flush()

            wallet = PlayerWallet.query.filter_by(
                player_id=player.id, session_id=g_session.id
            ).first()
            if not wallet:
                wallet = PlayerWallet(player_id=player.id, session_id=g_session.id, gold=0)
                db.session.add(wallet)

            for prob in probs:
                pps = PlayerProblemState.query.filter_by(
                    player_id=player.id, round_id=g_round.id, problem_id=prob.id
                ).first()
                if not pps:
                    pps = PlayerProblemState(
                        player_id=player.id, round_id=g_round.id, problem_id=prob.id
                    )
                    db.session.add(pps)

            db.session.commit()
            return wallet

        problems = problem_set.problems.all()
        wallet1 = simulate_join(p1, game_session, game_round, config, problems)
        wallet2 = simulate_join(p2, game_session, game_round, config, problems)

        check("T07  PlayerWallet created for p1", wallet1.gold == 0)
        check("T08  PlayerWallet created for p2", wallet2.gold == 0)
        check("T09  PlayerProblemState rows: 2 players × 2 problems = 4",
              PlayerProblemState.query.filter_by(round_id=game_round.id).count() == 4)
        check("T10  RoundPlayer rows: 2",
              RoundPlayer.query.filter_by(session_id=game_session.id).count() == 2)

        # ── 6. p1 submits correct answer to prob1 → rank 1 ───────────────────

        pps1_p1 = PlayerProblemState.query.filter_by(
            player_id=p1.id, round_id=game_round.id, problem_id=prob1.id
        ).first()

        correct = check_answer(prob1, '42')
        check("T11  check_answer returns True for '42'", correct)

        pps1_p1.attempts_used += 1
        pps1_p1.is_solved = True
        pps1_p1.is_closed = True

        # Increment solver count (done under lock in events.py)
        lock = state.get_lock(game_session.id)
        with lock:
            psc = ProblemSolverCount.query.filter_by(
                round_id=game_round.id, problem_id=prob1.id
            ).first()
            if not psc:
                psc = ProblemSolverCount(round_id=game_round.id, problem_id=prob1.id, solver_count=0)
                db.session.add(psc)
            psc.solver_count += 1
            solver_rank_p1 = psc.solver_count
            db.session.commit()

        check("T12  p1 is first solver (rank 1)", solver_rank_p1 == 1)

        # p1 chooses mine
        timer_active = state.is_timer_active(game_session.id, config.bonus_timer_duration)
        result1 = engine.calc_mine_reward(config, solver_rank_p1, timer_active)
        wallet1.gold += result1['gold']
        db.session.commit()

        # Expected: 20 (mine) + 6 (fsb: (3-(1-1))*2=6) + 5 (timer) = 31
        check("T13  p1 gold after mine = 31",
              wallet1.gold == 31,
              f"got {wallet1.gold}")
        check("T14  breakdown has 3 components (base + fsb + timer)",
              len(result1['breakdown']) == 3,
              str(result1['breakdown']))

        # ── 7. p2 submits correct answer to prob1 → rank 2 ───────────────────

        pps1_p2 = PlayerProblemState.query.filter_by(
            player_id=p2.id, round_id=game_round.id, problem_id=prob1.id
        ).first()

        pps1_p2.attempts_used += 1
        pps1_p2.is_solved = True
        pps1_p2.is_closed = True

        with lock:
            psc.solver_count += 1
            solver_rank_p2 = psc.solver_count
            db.session.commit()

        check("T15  p2 is second solver (rank 2)", solver_rank_p2 == 2)

        # p2 chooses treasure_search
        result2 = engine.calc_treasure_search_reward(config, solver_rank_p2, timer_active)
        wallet2.gold += result2['gold']
        db.session.commit()

        # Expected: 5 (treasure) + 4 (fsb: (3-(2-1))*2=4) + 5 (timer) = 14
        check("T16  p2 gold after treasure_search = 14",
              wallet2.gold == 14,
              f"got {wallet2.gold}")
        check("T17  breakdown has 3 components for p2",
              len(result2['breakdown']) == 3,
              str(result2['breakdown']))

        # ── 8. p1 submits WRONG answer to prob2 (1 attempt → closes) ─────────

        pps2_p1 = PlayerProblemState.query.filter_by(
            player_id=p1.id, round_id=game_round.id, problem_id=prob2.id
        ).first()

        wrong = check_answer(prob2, 'WRONG')
        check("T18  check_answer returns False for 'WRONG'", not wrong)

        pps2_p1.attempts_used += 1
        if config.attempts_per_problem != -1 and pps2_p1.attempts_used >= config.attempts_per_problem:
            pps2_p1.is_closed = True

        # Apply penalty (gold_before = 31, penalty = 5 → 26)
        old_gold = wallet1.gold
        wallet1.gold = engine.apply_penalty(wallet1.gold, config.wrong_answer_penalty)
        db.session.commit()

        check("T19  prob2 closed for p1 after 1 wrong (attempts_per_problem=1)",
              pps2_p1.is_closed)
        check("T20  penalty applied: 31 - 5 = 26",
              wallet1.gold == 26,
              f"got {wallet1.gold}")

        # ── 9. Cannot submit to closed problem (guard check) ──────────────────

        # Simulate the guard in handle_submit_answer: is_closed check
        is_blocked = pps2_p1.is_closed
        check("T21  Submit blocked: pps2_p1.is_closed = True", is_blocked)

        # ── 10. Gold floor at zero ────────────────────────────────────────────

        floored = engine.apply_penalty(3, 5)
        check("T22  apply_penalty(3, 5) = 0 (gold floor)", floored == 0, f"got {floored}")

        floored2 = engine.apply_penalty(0, 100)
        check("T23  apply_penalty(0, 100) = 0 (gold never negative)", floored2 == 0, f"got {floored2}")

        # ── 11. Admin ends the round ──────────────────────────────────────────

        end_time = datetime.now(timezone.utc)
        game_round.ended_at = end_time
        game_session.status = 'finished'
        game_session.ended_at = end_time
        db.session.commit()

        state.clear_session(game_session.id)

        check("T24  Session status = 'finished' after end_round",
              game_session.status == 'finished')
        check("T25  Round ended_at is set", game_round.ended_at is not None)

        # ── 12. DB row count verification ─────────────────────────────────────

        check("T26  ProblemSolverCount rows: 1 (prob1 solved by both players)",
              ProblemSolverCount.query.filter_by(round_id=game_round.id).count() == 1)
        check("T27  ProblemSolverCount.solver_count = 2 for prob1",
              psc.solver_count == 2)
        check("T28  PlayerProblemState rows: 4 (2 players × 2 problems)",
              PlayerProblemState.query.filter_by(round_id=game_round.id).count() == 4)
        check("T29  ClassicRoundConfig rows: 1",
              ClassicRoundConfig.query.filter_by(round_id=game_round.id).count() == 1)
        check("T30  PlayerWallet rows: 2 (one per player)",
              PlayerWallet.query.filter_by(session_id=game_session.id).count() == 2)

        # ── 13. Engine unit tests (pure functions) ────────────────────────────

        # No first-solver bonus when rank > first_solver_count
        result_late = engine.calc_mine_reward(config, solver_rank=4, timer_active=False)
        check("T31  No fsb when rank > first_solver_count",
              result_late['gold'] == 20 and len(result_late['breakdown']) == 1,
              str(result_late))

        # Timer inactive
        result_no_timer = engine.calc_mine_reward(config, solver_rank=1, timer_active=False)
        check("T32  No timer bonus when timer_active=False",
              result_no_timer['gold'] == 26,   # 20 + 6 fsb, no +5 timer
              f"got {result_no_timer['gold']}")

        # ── Cleanup ───────────────────────────────────────────────────────────

        _clean()

        # ── Summary ───────────────────────────────────────────────────────────

        total = 32
        failed = len(errors)
        passed = total - failed
        print()
        print(f'────────────────────────────────────────')
        print(f'Results: {passed}/{total} passed')
        if errors:
            print(f'Failed:')
            for e in errors:
                print(f'  {e}')
            print()
            sys.exit(1)
        else:
            print('ALL TESTS PASSED ✓')


if __name__ == '__main__':
    run_exit_test()
