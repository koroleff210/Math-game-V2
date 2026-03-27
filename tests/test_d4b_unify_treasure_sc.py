"""
test_d4b_unify_treasure_sc.py
=============================

Focused tests for Step D4b: Unify Treasure-granted Second Chance with store
inventory semantics.

Confirms:
  1.  Treasure SC is stored via unified PlayerInventory path
  2.  HUD/active bonus count includes Treasure SC correctly
  3.  Player cannot hold both store SC and treasure SC simultaneously
  4.  Store purchase blocked if player already has Treasure SC
  5.  Treasure grant blocked if player already has store SC
  6.  Wrong-answer consumption uses the unified path
  7.  System StoreItem does not appear in visible store catalog
  8.  get_or_create_system_sc is idempotent
  9.  is_system flag persists correctly

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_d4b_unify_treasure_sc.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound
from app.models.classic import (
    ClassicRoundConfig, PlayerWallet, PlayerClassicState,
    PlayerProblemState, ProblemSolverCount,
    StoreItem, PlayerInventory,
)
from app.modes.classic import store as classic_store

flask_app = create_app()
flask_app.config['WTF_CSRF_ENABLED'] = False
flask_app.config['TESTING'] = True

SET_NAME = '__test_d4b__'
_ADMIN   = '__d4b_admin__'
_PLAYER  = '__d4b_player__'

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


def _now():
    return datetime.now(timezone.utc)


def _clean():
    """Remove all test artefacts from the DB."""
    with db.session.no_autoflush:
        ps = ProblemSet.query.filter_by(name=SET_NAME).first()
        if ps:
            for gs in GameSession.query.filter_by(problem_set_id=ps.id).all():
                PlayerInventory.query.filter_by(session_id=gs.id).delete()
                PlayerWallet.query.filter_by(session_id=gs.id).delete()
                PlayerClassicState.query.filter_by(session_id=gs.id).delete()
                PlayerProblemState.query.filter(
                    PlayerProblemState.round_id.in_(
                        db.session.query(GameRound.id).filter_by(session_id=gs.id)
                    )
                ).delete(synchronize_session='fetch')
                ProblemSolverCount.query.filter(
                    ProblemSolverCount.round_id.in_(
                        db.session.query(GameRound.id).filter_by(session_id=gs.id)
                    )
                ).delete(synchronize_session='fetch')
                for gr in GameRound.query.filter_by(session_id=gs.id).all():
                    ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
                    db.session.delete(gr)
                StoreItem.query.filter_by(session_id=gs.id).delete()
                db.session.delete(gs)
            db.session.flush()
            for prob in list(ps.problems):
                ps.problems.remove(prob)
            db.session.flush()
            for prob in Problem.query.filter(Problem.title.like('D4b P%')).all():
                db.session.execute(db.text('DELETE FROM player_problem_state WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.execute(db.text('DELETE FROM problem_solver_count WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.delete(prob)
            db.session.delete(ps)
        db.session.flush()
        for uname in (_ADMIN, _PLAYER):
            p = Player.query.filter_by(username=uname).first()
            if p:
                db.session.delete(p)
    db.session.commit()


def _login(client):
    client.post('/login', data={'username': _ADMIN, 'password': 'x'}, follow_redirects=True)


def _setup():
    """Create test users, problem set, session, round, config."""
    admin = Player(username=_ADMIN, is_admin=True)
    admin.set_password('x')
    db.session.add(admin)

    player = Player(username=_PLAYER, is_admin=False)
    player.set_password('x')
    db.session.add(player)
    db.session.flush()

    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='D4b_topic')
        db.session.add(topic)
        db.session.flush()

    ps = ProblemSet(name=SET_NAME)
    db.session.add(ps)
    db.session.flush()
    prob = Problem(title='D4b P1', prompt_text='2+2?', answer_text='4', topic_id=topic.id)
    db.session.add(prob)
    db.session.flush()
    ps.problems.append(prob)
    db.session.flush()

    gs = GameSession(mode='classic', status='active', problem_set_id=ps.id)
    db.session.add(gs)
    db.session.flush()

    gr = GameRound(session_id=gs.id, problem_id=None, round_number=1, started_at=_now())
    db.session.add(gr)
    db.session.flush()

    config = ClassicRoundConfig(
        round_id=gr.id,
        mine_reward=20,
        treasure_search_reward=5,
        treasure_search_max_reward=10,
        gem_treasure_chance=0.3,
        treasure_steal_token_chance=0.1,
        treasure_active_shield_chance=0.2,
        treasure_second_chance_chance=0.1,
        shield_duration=60,
    )
    db.session.add(config)
    db.session.flush()

    wallet = PlayerWallet(player_id=player.id, session_id=gs.id, gold=100, gems=5)
    db.session.add(wallet)
    db.session.flush()

    db.session.commit()
    return admin, player, ps, gs, gr, config, wallet


with flask_app.app_context():
    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 1: get_or_create_system_sc
    # ══════════════════════════════════════════════════════════════════════
    print('\n── get_or_create_system_sc ─────────────────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    sys_item = classic_store.get_or_create_system_sc(gs.id)
    check('D4b-01: system SC item created',
          sys_item is not None and sys_item.id is not None)
    check('D4b-02: is_system=True',
          sys_item.is_system is True)
    check('D4b-03: bonus_type=shield',
          sys_item.bonus_type == 'shield')
    check('D4b-04: cost=0',
          sys_item.cost == 0)

    # Idempotent: calling again returns the same item
    sys_item2 = classic_store.get_or_create_system_sc(gs.id)
    check('D4b-05: idempotent (same id)',
          sys_item2.id == sys_item.id)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 2: Treasure SC stored via unified inventory
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Treasure SC via unified inventory ───────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    sys_item = classic_store.get_or_create_system_sc(gs.id)

    # Initially no SC
    counts = classic_store.get_active_counts(player.id, gs.id)
    check('D4b-06: no SC initially',
          counts.get('shield', 0) == 0)

    # Grant treasure SC via inventory row
    inv = PlayerInventory(
        player_id=player.id, session_id=gs.id,
        item_id=sys_item.id, purchased_at=_now(), used_at=None,
    )
    db.session.add(inv)
    db.session.flush()

    counts = classic_store.get_active_counts(player.id, gs.id)
    check('D4b-07: SC count=1 after treasure grant',
          counts.get('shield', 0) == 1)

    # Consume via unified path
    consumed = classic_store.consume_item(player.id, gs.id, 'shield')
    check('D4b-08: consume_item returns inventory row',
          consumed is not None)
    check('D4b-09: consumed row has used_at set',
          consumed.used_at is not None)

    counts = classic_store.get_active_counts(player.id, gs.id)
    check('D4b-10: SC count=0 after consumption',
          counts.get('shield', 0) == 0)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 3: HUD/bonus count includes both sources
    # ══════════════════════════════════════════════════════════════════════
    print('\n── HUD counts include Treasure SC ──────────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    # Give player a Treasure-granted SC
    sys_item = classic_store.get_or_create_system_sc(gs.id)
    inv = PlayerInventory(
        player_id=player.id, session_id=gs.id,
        item_id=sys_item.id, purchased_at=_now(), used_at=None,
    )
    db.session.add(inv)
    db.session.flush()

    counts = classic_store.get_active_counts(player.id, gs.id)
    check('D4b-11: HUD shows shield=1 for treasure SC',
          counts.get('shield', 0) == 1)

    # Now also give a store-purchased SC — should be blocked by capacity
    # in practice, but let's verify counts if both existed
    store_item = StoreItem(
        session_id=gs.id, name='Store SC', description='test',
        cost=10, currency='gold', bonus_type='shield', session_stock=-1,
    )
    db.session.add(store_item)
    db.session.flush()

    inv2 = PlayerInventory(
        player_id=player.id, session_id=gs.id,
        item_id=store_item.id, purchased_at=_now(), used_at=None,
    )
    db.session.add(inv2)
    db.session.flush()

    counts = classic_store.get_active_counts(player.id, gs.id)
    check('D4b-12: HUD shows shield=2 if both somehow exist',
          counts.get('shield', 0) == 2,
          f'got {counts.get("shield", 0)}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 4: Store purchase blocked when treasure SC active
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Store purchase blocked by treasure SC ───────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    # Give player a Treasure SC first
    sys_item = classic_store.get_or_create_system_sc(gs.id)
    inv = PlayerInventory(
        player_id=player.id, session_id=gs.id,
        item_id=sys_item.id, purchased_at=_now(), used_at=None,
    )
    db.session.add(inv)
    db.session.flush()

    # Create a buyable store SC item
    store_item = StoreItem(
        session_id=gs.id, name='SC for sale', description='test',
        cost=5, currency='gold', bonus_type='shield', session_stock=-1,
    )
    db.session.add(store_item)
    db.session.flush()

    # Attempt purchase — should be blocked
    ok, msg, _ = classic_store.purchase_item(player.id, gs.id, store_item.id)
    check('D4b-13: store SC purchase blocked',
          not ok)
    check('D4b-14: reason mentions "already have"',
          'already have' in msg.lower(),
          f'msg={msg}')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 5: Treasure grant blocked when store SC active
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Treasure SC blocked by store SC ─────────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    # Give player a store-purchased SC
    store_item = StoreItem(
        session_id=gs.id, name='Store SC', description='test',
        cost=10, currency='gold', bonus_type='shield', session_stock=-1,
    )
    db.session.add(store_item)
    db.session.flush()

    inv = PlayerInventory(
        player_id=player.id, session_id=gs.id,
        item_id=store_item.id, purchased_at=_now(), used_at=None,
    )
    db.session.add(inv)
    db.session.flush()

    # Check capacity — same query used in events.py treasure SC grant
    sc_active = (
        PlayerInventory.query
        .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
        .filter(
            PlayerInventory.player_id  == player.id,
            PlayerInventory.session_id == gs.id,
            StoreItem.bonus_type       == 'shield',
            PlayerInventory.used_at    == None,  # noqa: E711
        )
        .count()
    )
    check('D4b-15: store SC exists (count=1)',
          sc_active == 1)
    check('D4b-16: treasure grant would be blocked (capacity >= 1)',
          sc_active >= 1)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 6: System item hidden from store catalog
    # ══════════════════════════════════════════════════════════════════════
    print('\n── System item hidden from store ────────────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    # Create system SC and a normal store item
    sys_item = classic_store.get_or_create_system_sc(gs.id)
    normal_item = StoreItem(
        session_id=gs.id, name='Normal Item', description='test',
        cost=10, currency='gold', bonus_type='x2_mine', session_stock=-1,
    )
    db.session.add(normal_item)
    db.session.flush()

    # store_items_for should NOT include system items
    visible = classic_store.store_items_for(gs.id)
    visible_ids = [i['id'] for i in visible]
    check('D4b-17: system item NOT in store_items_for',
          sys_item.id not in visible_ids)
    check('D4b-18: normal item IS in store_items_for',
          normal_item.id in visible_ids)

    # Admin store page should also not show system items
    client = flask_app.test_client()
    _login(client)
    resp = client.get(f'/admin/classic/{gs.id}/store')
    html = resp.data.decode()
    check('D4b-19: admin store page loads (200)',
          resp.status_code == 200)
    check('D4b-20: system item name NOT in admin store HTML',
          'Treasure Second Chance' not in html)
    check('D4b-21: normal item name IS in admin store HTML',
          'Normal Item' in html)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 7: Wrong-answer consumption unified
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Wrong-answer unified consumption ────────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    # Give player a treasure SC
    sys_item = classic_store.get_or_create_system_sc(gs.id)
    inv = PlayerInventory(
        player_id=player.id, session_id=gs.id,
        item_id=sys_item.id, purchased_at=_now(), used_at=None,
    )
    db.session.add(inv)
    db.session.flush()

    # Confirm SC is active
    check('D4b-22: SC active before wrong answer',
          classic_store.get_active_counts(player.id, gs.id).get('shield', 0) == 1)

    # Simulate consume_item (same call the wrong-answer handler uses)
    consumed = classic_store.consume_item(player.id, gs.id, 'shield')
    check('D4b-23: consume_item works for treasure SC',
          consumed is not None)
    check('D4b-24: SC consumed (count=0)',
          classic_store.get_active_counts(player.id, gs.id).get('shield', 0) == 0)

    # Second consume should return None (nothing left)
    consumed2 = classic_store.consume_item(player.id, gs.id, 'shield')
    check('D4b-25: second consume returns None',
          consumed2 is None)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 8: is_system flag on model
    # ══════════════════════════════════════════════════════════════════════
    print('\n── is_system flag ──────────────────────────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    # Normal item defaults to is_system=False
    normal = StoreItem(
        session_id=gs.id, name='Normal', description='',
        cost=5, currency='gold', bonus_type='x2_mine', session_stock=-1,
    )
    db.session.add(normal)
    db.session.flush()
    check('D4b-26: normal item is_system=False',
          normal.is_system is False)

    sys_item = classic_store.get_or_create_system_sc(gs.id)
    check('D4b-27: system item is_system=True',
          sys_item.is_system is True)
    check('D4b-28: system item session matches',
          sys_item.session_id == gs.id)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 9: PlayerClassicState no longer has boolean
    # ══════════════════════════════════════════════════════════════════════
    print('\n── has_treasure_second_chance removed ──────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    pcs = PlayerClassicState(player_id=player.id, session_id=gs.id)
    db.session.add(pcs)
    db.session.flush()

    has_attr = hasattr(pcs, 'has_treasure_second_chance')
    check('D4b-29: has_treasure_second_chance attribute removed',
          not has_attr,
          f'still has attribute' if has_attr else '')

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 10: Capacity is truly unified across sources
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Unified capacity ────────────────────────────────────────')

    admin, player, ps, gs, gr, config, wallet = _setup()

    # Player buys a store SC
    store_item = StoreItem(
        session_id=gs.id, name='Buyable SC', description='test',
        cost=5, currency='gold', bonus_type='shield', session_stock=-1,
    )
    db.session.add(store_item)
    db.session.flush()

    ok, msg, _ = classic_store.purchase_item(player.id, gs.id, store_item.id)
    check('D4b-30: first store SC purchase succeeds',
          ok, f'msg={msg}')

    # Second purchase should be blocked
    ok2, msg2, _ = classic_store.purchase_item(player.id, gs.id, store_item.id)
    check('D4b-31: second store SC purchase blocked',
          not ok2)

    # Consume the store SC
    consumed = classic_store.consume_item(player.id, gs.id, 'shield')
    check('D4b-32: store SC consumed',
          consumed is not None)

    # Now treasure SC should be grantable
    sys_item = classic_store.get_or_create_system_sc(gs.id)
    sc_count = classic_store.get_active_counts(player.id, gs.id).get('shield', 0)
    check('D4b-33: SC count=0 after consumption',
          sc_count == 0)

    inv = PlayerInventory(
        player_id=player.id, session_id=gs.id,
        item_id=sys_item.id, purchased_at=_now(), used_at=None,
    )
    db.session.add(inv)
    db.session.flush()

    sc_count = classic_store.get_active_counts(player.id, gs.id).get('shield', 0)
    check('D4b-34: treasure SC granted after store SC consumed (count=1)',
          sc_count == 1)

    # Now store purchase should be blocked again
    ok3, msg3, _ = classic_store.purchase_item(player.id, gs.id, store_item.id)
    check('D4b-35: store purchase blocked while treasure SC active',
          not ok3)

    _clean()

    # ══════════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════════
    print(f'\n{"=" * 60}')
    print(f'Step D4b unification results: {passed} passed, {failed} failed')
    if failed == 0:
        print('ALL TESTS PASSED.')
    else:
        print('SOME TESTS FAILED.')
    print('=' * 60)

    sys.exit(1 if failed else 0)
