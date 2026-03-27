"""
test_classic_step_b.py
======================

Exit test for Classic Mode Step B: Store system, x2 mine bonus, shield token.

Tests the entire feature layer directly inside a Flask application context
(no HTTP requests, no WebSocket connections required).

Run:
    .venv\\Scripts\\python.exe test_classic_step_b.py

Expected output: all assertions pass, final line prints "ALL TESTS PASSED".
"""

import sys
from datetime import datetime, timezone

# ── Bootstrap ─────────────────────────────────────────────────────────────────

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
from app.modes.classic import store as classic_store

flask_app = create_app()

SET_NAME = '__test_step_b__'


def _clean():
    """Remove all test data so the test is fully repeatable."""
    ps = ProblemSet.query.filter_by(name=SET_NAME).first()

    for gs in GameSession.query.filter_by(mode='classic').all():
        if gs.problem_set and gs.problem_set.name == SET_NAME:
            sid = gs.id
            # Delete store inventory + items
            PlayerInventory.query.filter_by(session_id=sid).delete()
            StoreItem.query.filter_by(session_id=sid).delete()
            # Wallet
            PlayerWallet.query.filter_by(session_id=sid).delete()
            # Round-level rows
            for gr in GameRound.query.filter_by(session_id=sid).all():
                # Delete history rows BEFORE GameRound (FK constraint)
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
        for prob in Problem.query.filter(Problem.title.in_(['StepB P1', 'StepB P2'])).all():
            PlayerProblemState.query.filter_by(problem_id=prob.id).delete()
            ProblemSolverCount.query.filter_by(problem_id=prob.id).delete()
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()

    for uname in ('__sb_p1__', '__sb_p2__'):
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

        print('\n── Step B Setup ─────────────────────────────────────────')

        # ── T01: Create test players ──────────────────────────────────────────
        p1 = Player(username='__sb_p1__', is_admin=False)
        p1.set_password('x')
        p2 = Player(username='__sb_p2__', is_admin=False)
        p2.set_password('x')
        db.session.add_all([p1, p2])
        db.session.flush()
        check('T01 players created', p1.id and p2.id)

        # ── T02: Create problem set + problems ────────────────────────────────
        topic = Topic.query.first()
        if not topic:
            topic = Topic(name='__sb_topic__', subject='Test')
            db.session.add(topic)
            db.session.flush()

        prob1 = Problem(topic_id=topic.id, title='StepB P1', prompt_text='1+1', answer_text='2', difficulty=1)
        prob2 = Problem(topic_id=topic.id, title='StepB P2', prompt_text='2+2', answer_text='4', difficulty=1)
        db.session.add_all([prob1, prob2])
        db.session.flush()
        ps = ProblemSet(name=SET_NAME, description='Step B test set')
        db.session.add(ps)
        db.session.flush()
        ps.problems.append(prob1)
        ps.problems.append(prob2)
        db.session.flush()
        check('T02 problem set created', ps.id and prob1.id and prob2.id)

        # ── T03: Create game session + round + config ─────────────────────────
        gs = GameSession(mode='classic', status='waiting', problem_set_id=ps.id)
        db.session.add(gs)
        db.session.flush()
        gr = GameRound(session_id=gs.id, problem_id=None, round_number=1, started_at=None)
        db.session.add(gr)
        db.session.flush()
        cfg = ClassicRoundConfig(
            round_id=gr.id,
            mine_reward=20, treasure_search_reward=5,
            attempts_per_problem=-1,    # unlimited so we can test shield
            wrong_answer_penalty=10,    # must be > 0 to test shield
            bonus_timer_duration=0, bonus_timer_gold=0,
            first_solver_count=0, first_solver_multiplier=0,
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
        check('T04 session active', gs.status == 'active')

        # ── T05: Create store items ───────────────────────────────────────────
        item_x2 = StoreItem(
            session_id=gs.id, name='Double Mine', cost=10,
            bonus_type='x2_mine', session_stock=-1, description='Doubles mine reward'
        )
        item_shield = StoreItem(
            session_id=gs.id, name='Shield', cost=5,
            bonus_type='shield', session_stock=2, description='Block one penalty'
        )
        db.session.add_all([item_x2, item_shield])
        db.session.commit()
        check('T05 store items created', item_x2.id and item_shield.id)
        check('T05 x2_mine session_stock=-1', item_x2.session_stock == -1)
        check('T05 shield session_stock=2',   item_shield.session_stock == 2)

        # ── T06: store_items_for() returns correct data ───────────────────────
        items = classic_store.store_items_for(gs.id)
        check('T06 store_items_for length', len(items) == 2)
        shield_data = next(i for i in items if i['bonus_type'] == 'shield')
        check('T06 shield qty_left=2', shield_data['quantity_left'] == 2)
        x2_data = next(i for i in items if i['bonus_type'] == 'x2_mine')
        check('T06 x2_mine qty_left=-1 (unlimited)', x2_data['quantity_left'] == -1)

        # ── T07: Give p1 a wallet and some gold ───────────────────────────────
        w1 = PlayerWallet(player_id=p1.id, session_id=gs.id, gold=50)
        db.session.add(w1)
        db.session.commit()
        check('T07 wallet gold=50', w1.gold == 50)

        # ── T08: purchase_item — success for x2_mine ─────────────────────────
        ok, msg, new_gold = classic_store.purchase_item(p1.id, gs.id, item_x2.id)
        check('T08 buy x2_mine ok', ok is True)
        check('T08 buy x2_mine msg=ok', msg == 'ok')
        check('T08 buy x2_mine gold deducted (50-10=40)', new_gold == 40)
        w1 = db.session.get(PlayerWallet, w1.id)
        check('T08 wallet updated in DB', w1.gold == 40)

        # ── T09: purchase_item — success for shield ───────────────────────────
        ok, msg, new_gold = classic_store.purchase_item(p1.id, gs.id, item_shield.id)
        check('T09 buy shield ok', ok is True)
        check('T09 gold after shield (40-5=35)', new_gold == 35)

        # ── T10: PlayerInventory rows exist ───────────────────────────────────
        inv_rows = PlayerInventory.query.filter_by(player_id=p1.id, session_id=gs.id).all()
        check('T10 inventory has 2 rows', len(inv_rows) == 2)
        check('T10 all rows used_at=None', all(r.used_at is None for r in inv_rows))

        # ── T11: get_active_counts ────────────────────────────────────────────
        counts = classic_store.get_active_counts(p1.id, gs.id)
        check('T11 x2_mine count=1', counts.get('x2_mine') == 1)
        check('T11 shield count=1',  counts.get('shield')  == 1)

        # ── T12: purchase_item — insufficient gold ────────────────────────────
        ok, msg, gold = classic_store.purchase_item(p1.id, gs.id, item_x2.id)
        # wallet is 35, item costs 10 → succeeds; drain to 25
        check('T12 second x2_mine purchase ok', ok is True)
        # Now drain wallet manually to test insufficient gold
        w1 = db.session.get(PlayerWallet, w1.id)
        w1.gold = 3
        db.session.commit()
        ok, msg, gold = classic_store.purchase_item(p1.id, gs.id, item_shield.id)
        check('T12 buy fails insufficient gold', ok is False)
        check('T12 msg=not enough gold', msg == 'not enough gold')
        check('T12 gold unchanged in return', gold == 3)

        # ── T13: purchase_item — out of stock ─────────────────────────────────
        # shield quantity=2; buy one for p2
        w2 = PlayerWallet(player_id=p2.id, session_id=gs.id, gold=100)
        db.session.add(w2)
        db.session.commit()
        ok, msg, _ = classic_store.purchase_item(p2.id, gs.id, item_shield.id)
        check('T13 p2 buys shield ok', ok is True)
        # Now shield is sold out (2/2)
        ok, msg, _ = classic_store.purchase_item(p2.id, gs.id, item_shield.id)
        check('T13 third shield purchase rejected', ok is False)
        check('T13 msg=out of stock', msg == 'out of stock')

        # ── T14: shield quantity_left reflects purchases ───────────────────────
        items = classic_store.store_items_for(gs.id)
        shield_data = next(i for i in items if i['bonus_type'] == 'shield')
        check('T14 shield qty_left=0 after sellout',
              shield_data['quantity_left'] == 0)

        # ── T15: consume_item — shield blocks wrong-answer penalty ─────────────
        # Restore p1 wallet to test penalty
        w1 = db.session.get(PlayerWallet, w1.id)
        w1.gold = 30
        db.session.commit()
        gold_before = w1.gold

        # p1 has 1 active shield (from T09 purchase; x2_mine×2 from T08+T12)
        # Simulate wrong answer: consume shield → no penalty
        shield_inv = classic_store.consume_item(p1.id, gs.id, 'shield')
        check('T15 shield consumed (row returned)', shield_inv is not None)
        check('T15 shield used_at set', shield_inv.used_at is not None)

        # Gold SHOULD NOT be deducted (caller decides; we only test consume returned non-None)
        # (In events.py the caller skips the deduction if shield_inv is not None)
        w1 = db.session.get(PlayerWallet, w1.id)
        check('T15 gold unchanged after shield consume', w1.gold == gold_before)

        # ── T16: consume_item — second call finds no shield (used up) ─────────
        shield_inv2 = classic_store.consume_item(p1.id, gs.id, 'shield')
        check('T16 no remaining shield returns None', shield_inv2 is None)

        # ── T17: get_active_counts after consuming shield ──────────────────────
        counts = classic_store.get_active_counts(p1.id, gs.id)
        check('T17 shield count=0 after consume', counts.get('shield', 0) == 0)
        check('T17 x2_mine count still 2', counts.get('x2_mine', 0) == 2)

        # ── T18: engine.apply_x2_mine doubles gold ────────────────────────────
        base_result = {'gold': 25, 'breakdown': ['base mine: 20', 'first-solver bonus: 5']}
        doubled = engine.apply_x2_mine(base_result)
        check('T18 x2_mine doubles gold (25→50)', doubled['gold'] == 50)
        check('T18 x2_mine appends breakdown entry',
              any('x2 mine bonus' in b for b in doubled['breakdown']))
        check('T18 original result unchanged', base_result['gold'] == 25)

        # ── T19: consume x2_mine → mine reward doubled in flow ────────────────
        # p1 has 2 active x2_mine items; consuming one should leave 1
        x2_inv = classic_store.consume_item(p1.id, gs.id, 'x2_mine')
        check('T19 x2_mine consume returns row', x2_inv is not None)
        check('T19 x2_mine used_at set', x2_inv.used_at is not None)

        counts = classic_store.get_active_counts(p1.id, gs.id)
        check('T19 x2_mine count=1 after one consume', counts.get('x2_mine', 0) == 1)

        # ── T20: calc_mine_reward + apply_x2_mine integration ─────────────────
        mine_result = engine.calc_mine_reward(cfg, solver_rank=1, timer_active=False)
        check('T20 base mine_reward=20 (fsb 0, timer 0)', mine_result['gold'] == 20)
        doubled_mine = engine.apply_x2_mine(mine_result)
        check('T20 doubled mine = 40', doubled_mine['gold'] == 40)

        # ── T21: DB row counts ─────────────────────────────────────────────────
        si_count  = StoreItem.query.filter_by(session_id=gs.id).count()
        inv_count = PlayerInventory.query.filter_by(session_id=gs.id).count()
        check('T21 store_item rows = 2',      si_count == 2)
        # p1 bought: x2_mine(T08), shield(T09), x2_mine(T12) = 3 rows
        # p2 bought: shield(T13) = 1 row → total = 4
        check('T21 player_inventory rows = 4', inv_count == 4)

        # ── T22: store_items_for item_id stability ─────────────────────────────
        items2 = classic_store.store_items_for(gs.id)
        check('T22 store_items_for returns 2 items', len(items2) == 2)
        for it in items2:
            check(f'T22 item {it["id"]} has required keys',
                  all(k in it for k in ('id', 'name', 'cost', 'bonus_type', 'quantity_left')))

        # ── Summary ──────────────────────────────────────────────────────────────

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
