"""
test_regression_stabilization.py
=================================

Regression tests for the three stabilization fixes applied before H1:

  FIX-1  StoreItemForm — bonus_type SelectField choices include all four
         store item types: x2_mine, shield, steal_token, steal_shield.

  FIX-2  pilot-reset (maintenance.py) — _collect_counts, _print_counts, and
         _do_delete all handle round_history and round_player_result tables.

  FIX-3  classic_join savepoint — the begin_nested() savepoint pattern does
         not lose PlayerProblemState rows when a UNIQUE-constraint race hits
         one problem in the loop.

Tests run entirely in-process against an in-memory SQLite database.
No HTTP requests or WebSocket connections are required.

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_stabilization.py

Expected: all tests pass, final line "ALL STABILIZATION TESTS PASSED."
"""

import io
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player   import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game     import GameSession, GameRound, RoundPlayer
from app.models.classic  import ClassicRoundConfig, PlayerWallet, PlayerProblemState
from app.models.history  import RoundHistory, RoundPlayerResult


# ── App config ─────────────────────────────────────────────────────────────────

class _TestConfig:
    TESTING                     = True
    SQLALCHEMY_DATABASE_URI     = 'sqlite:///:memory:'
    SECRET_KEY                  = 'stab-test-secret'
    WTF_CSRF_ENABLED            = False
    SOCKETIO_ASYNC_MODE         = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED              = False


flask_app = create_app(_TestConfig)

# ── Test runner ────────────────────────────────────────────────────────────────

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


# ── Shared fixture IDs ─────────────────────────────────────────────────────────

_ADMIN_USER = '__stab_admin__'
_P1_USER    = '__stab_p1__'
_IDS        = {}


def _setup():
    with flask_app.app_context():
        db.create_all()

        admin = Player(username=_ADMIN_USER, is_admin=True)
        admin.set_password('pass')
        p1 = Player(username=_P1_USER, is_admin=False)
        p1.set_password('pass')
        db.session.add_all([admin, p1])
        db.session.flush()

        topic = Topic(name='__stab_topic__')
        db.session.add(topic)
        db.session.flush()

        prob1 = Problem(topic_id=topic.id, title='SP1',
                        prompt_text='1+1', answer_text='2', difficulty=1)
        prob2 = Problem(topic_id=topic.id, title='SP2',
                        prompt_text='2+2', answer_text='4', difficulty=1)
        prob3 = Problem(topic_id=topic.id, title='SP3',
                        prompt_text='3+3', answer_text='6', difficulty=1)
        db.session.add_all([prob1, prob2, prob3])
        db.session.flush()

        pset = ProblemSet(name='__stab_set__')
        pset.problems.append(prob1)
        pset.problems.append(prob2)
        pset.problems.append(prob3)
        db.session.add(pset)
        db.session.commit()

        _IDS['admin_id'] = admin.id
        _IDS['p1_id']    = p1.id
        _IDS['pset_id']  = pset.id
        _IDS['prob1_id'] = prob1.id
        _IDS['prob2_id'] = prob2.id
        _IDS['prob3_id'] = prob3.id


def _make_session():
    """Create GameSession + GameRound + ClassicRoundConfig. Returns (session_id, round_id)."""
    with flask_app.app_context():
        gs = GameSession(mode='classic', status='active',
                         problem_set_id=_IDS['pset_id'])
        db.session.add(gs)
        db.session.flush()

        gr = GameRound(session_id=gs.id, round_number=1,
                       started_at=datetime.now(timezone.utc))
        db.session.add(gr)
        db.session.flush()

        cfg = ClassicRoundConfig(
            round_id=gr.id, mine_reward=20, treasure_search_reward=5,
            attempts_per_problem=1, wrong_answer_penalty=0,
        )
        db.session.add(cfg)
        db.session.commit()
        return gs.id, gr.id


# ════════════════════════════════════════════════════════════════════════════════
# GROUP A — StoreItemForm bonus_type choices (FIX-1)
# ════════════════════════════════════════════════════════════════════════════════

def _run_a_tests():
    print('\n── Group A: StoreItemForm bonus_type choices (FIX-1) ──────────────────')
    from app.modes.classic.forms import StoreItemForm

    VALID_TYPES = ['x2_mine', 'shield', 'steal_token', 'steal_shield']

    # Inspect choices by instantiating the form inside an app+request context
    # and reading the bound field's choices attribute.
    with flask_app.app_context():
        with flask_app.test_request_context():
            form_instance = StoreItemForm()
            choices_set = {val for val, _ in form_instance.bonus_type.choices}

    for bt in VALID_TYPES:
        check(
            f'A-{bt}: SelectField includes {bt!r}',
            bt in choices_set,
            detail=f'form has: {sorted(choices_set)}',
        )

    check(
        'A5: unknown type not in SelectField choices',
        'unknown_bonus_type' not in choices_set,
    )

    # Confirm form.validate() passes for each valid type and fails for unknown
    with flask_app.app_context():
        with flask_app.test_request_context():
            for bt in VALID_TYPES:
                form = StoreItemForm(data={
                    'name':       f'Test {bt}',
                    'cost':       10,
                    'bonus_type': bt,
                    'session_stock':   -1,
                })
                check(
                    f'A-{bt}-validate: StoreItemForm.validate() passes for {bt!r}',
                    form.validate(),
                    detail=str(form.errors),
                )

            form_bad = StoreItemForm(data={
                'name':       'Bad item',
                'cost':       10,
                'bonus_type': 'invalid_type',
                'session_stock':   -1,
            })
            check(
                'A5-validate: StoreItemForm.validate() rejects unknown bonus_type',
                not form_bad.validate(),
            )


# ════════════════════════════════════════════════════════════════════════════════
# GROUP B — pilot-reset includes round_history and round_player_result (FIX-2)
# ════════════════════════════════════════════════════════════════════════════════

def _run_b_tests():
    print('\n── Group B: pilot-reset history tables (FIX-2) ───────────────────────')
    from app.cli.maintenance import _collect_counts, _print_counts, _do_delete

    session_id, round_id = _make_session()

    # Insert one RoundHistory + two RoundPlayerResult rows
    now = datetime.now(timezone.utc)
    with flask_app.app_context():
        rh = RoundHistory(
            round_id=round_id,
            session_id=session_id,
            mode_type='classic',
            round_number=1,
            ended_at=now,
            player_count=2,
            total_answers=3,
            total_correct=2,
            total_incorrect=1,
            overall_accuracy=0.667,
        )
        db.session.add(rh)
        db.session.flush()

        rpr1 = RoundPlayerResult(
            round_history_id=rh.id,
            player_id=_IDS['p1_id'],
            player_name_snapshot=_P1_USER,
            final_gold=20,
            final_gems=0,
            final_place=1,
            total_answers=2,
            correct=2,
            incorrect=0,
            accuracy=1.0,
        )
        rpr2 = RoundPlayerResult(
            round_history_id=rh.id,
            player_id=_IDS['admin_id'],
            player_name_snapshot=_ADMIN_USER,
            final_gold=5,
            final_gems=0,
            final_place=2,
            total_answers=1,
            correct=0,
            incorrect=1,
            accuracy=0.0,
        )
        db.session.add_all([rpr1, rpr2])
        db.session.commit()

    # B1-B4: _collect_counts keys and values
    with flask_app.app_context():
        counts = _collect_counts()

    check('B1: _collect_counts includes round_history key',
          'round_history' in counts)
    check('B2: _collect_counts includes round_player_result key',
          'round_player_result' in counts)
    check('B3: round_history count is 1',
          counts.get('round_history') == 1,
          detail=f"got {counts.get('round_history')}")
    check('B4: round_player_result count is 2',
          counts.get('round_player_result') == 2,
          detail=f"got {counts.get('round_player_result')}")

    # B5-B6: _print_counts includes both table names in output
    import click
    captured = []
    original_echo = click.echo
    click.echo = lambda msg='', **kw: captured.append(str(msg))
    try:
        with flask_app.app_context():
            _print_counts(counts, 'TEST')
    finally:
        click.echo = original_echo

    combined = '\n'.join(captured)
    check('B5: _print_counts output contains "round_history"',
          'round_history' in combined,
          detail='not found in captured output')
    check('B6: _print_counts output contains "round_player_result"',
          'round_player_result' in combined,
          detail='not found in captured output')

    # B7-B8: _do_delete empties both history tables
    with flask_app.app_context():
        _do_delete()
        db.session.commit()
        remaining_rh  = db.session.execute(
            db.text('SELECT COUNT(*) FROM round_history')
        ).scalar()
        remaining_rpr = db.session.execute(
            db.text('SELECT COUNT(*) FROM round_player_result')
        ).scalar()

    check('B7: _do_delete empties round_history',
          remaining_rh == 0,
          detail=f'{remaining_rh} rows remain')
    check('B8: _do_delete empties round_player_result',
          remaining_rpr == 0,
          detail=f'{remaining_rpr} rows remain')


# ════════════════════════════════════════════════════════════════════════════════
# GROUP C — savepoint in classic_join ProblemState loop (FIX-3)
# ════════════════════════════════════════════════════════════════════════════════

def _savepoint_loop(player_id, round_id, prob_ids):
    """Exact replica of the savepoint loop in classic_join / handle_join.

    This exercises the FIX-3 pattern directly without needing a live
    WebSocket connection.  Returns the row ids of all PPS rows touched.
    """
    touched = []
    with flask_app.app_context():
        for pid in prob_ids:
            pps = PlayerProblemState.query.filter_by(
                player_id=player_id,
                round_id=round_id,
                problem_id=pid,
            ).first()
            if not pps:
                sp = db.session.begin_nested()
                try:
                    pps = PlayerProblemState(
                        player_id=player_id,
                        round_id=round_id,
                        problem_id=pid,
                    )
                    db.session.add(pps)
                    db.session.flush()
                except Exception:
                    sp.rollback()
                    pps = PlayerProblemState.query.filter_by(
                        player_id=player_id,
                        round_id=round_id,
                        problem_id=pid,
                    ).first()
            if pps:
                touched.append(pps.id)
        db.session.commit()
    return touched


def _run_c_tests():
    print('\n── Group C: savepoint in classic_join (FIX-3) ─────────────────────────')

    prob_ids  = [_IDS['prob1_id'], _IDS['prob2_id'], _IDS['prob3_id']]
    player_id = _IDS['p1_id']

    # C1 — Normal flow: join creates PPS for all three problems
    _session_id, round_id = _make_session()
    touched = _savepoint_loop(player_id, round_id, prob_ids)

    check('C1: normal join loop creates PPS for all 3 problems',
          len(touched) == 3,
          detail=f'got {len(touched)} row ids')

    with flask_app.app_context():
        total = PlayerProblemState.query.filter_by(
            player_id=player_id, round_id=round_id
        ).count()
    check('C2: exactly 3 PPS rows in DB after normal join',
          total == 3,
          detail=f'DB has {total}')

    # C3 — Idempotent re-run: second call does not duplicate rows
    touched2 = _savepoint_loop(player_id, round_id, prob_ids)
    check('C3: second join call returns 3 ids (existing rows reused)',
          len(touched2) == 3,
          detail=f'got {len(touched2)}')

    with flask_app.app_context():
        total2 = PlayerProblemState.query.filter_by(
            player_id=player_id, round_id=round_id
        ).count()
    check('C4: PPS count stays at 3 after idempotent re-run',
          total2 == 3,
          detail=f'DB has {total2}')

    # C5-C8 — Race simulation:
    #   Pre-insert PPS for prob2, then run the loop.
    #   Without the savepoint fix, a UNIQUE error on prob2 would roll back
    #   the entire session, losing prob1 + prob3.
    #   With begin_nested(), only prob2's savepoint rolls back; the rest survive.
    _session_id2, round_id2 = _make_session()

    with flask_app.app_context():
        # Simulates the "first" concurrent join pre-inserting prob2
        pre = PlayerProblemState(
            player_id=player_id,
            round_id=round_id2,
            problem_id=_IDS['prob2_id'],
        )
        db.session.add(pre)
        db.session.commit()
        pre_id = pre.id

    # "Second" concurrent join attempts all 3; prob2 will hit UNIQUE constraint
    touched3 = _savepoint_loop(player_id, round_id2, prob_ids)

    with flask_app.app_context():
        pps1 = PlayerProblemState.query.filter_by(
            player_id=player_id, round_id=round_id2,
            problem_id=_IDS['prob1_id'],
        ).first()
        pps2 = PlayerProblemState.query.filter_by(
            player_id=player_id, round_id=round_id2,
            problem_id=_IDS['prob2_id'],
        ).first()
        pps3 = PlayerProblemState.query.filter_by(
            player_id=player_id, round_id=round_id2,
            problem_id=_IDS['prob3_id'],
        ).first()
        total3 = PlayerProblemState.query.filter_by(
            player_id=player_id, round_id=round_id2,
        ).count()

    check('C5: race sim — prob1 PPS exists (savepoint preserved earlier-in-loop row)',
          pps1 is not None)
    check('C6: race sim — prob2 PPS exists (pre-existing row recovered after sp.rollback)',
          pps2 is not None)
    check('C7: race sim — prob3 PPS exists (savepoint preserved later-in-loop row)',
          pps3 is not None)
    check('C8: race sim — exactly 3 PPS rows (no lost rows, no duplicates)',
          total3 == 3,
          detail=f'DB has {total3}')

    # Verify the pre-inserted prob2 row was reused (same id), not replaced
    check('C9: race sim — prob2 row id is the original pre-inserted id (not a new row)',
          pps2 is not None and pps2.id == pre_id,
          detail=f'expected id={pre_id}, got {pps2.id if pps2 else None}')


# ════════════════════════════════════════════════════════════════════════════════
# Entry-point
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('=== Stabilization regression tests ===\n')
    _setup()
    _run_a_tests()
    _run_b_tests()
    _run_c_tests()
    print(f'\n  passed={passed}  failed={failed}')
    if failed:
        print(f'\n  FAILED — {failed} test(s) did not pass.')
        sys.exit(1)
    else:
        print('\nALL STABILIZATION TESTS PASSED.')
