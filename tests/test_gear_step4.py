"""
test_gear_step4.py
==================

Targeted regression tests for Gear V1 Step 4:
  - gear bonuses freeze into SessionParticipantSnapshot
  - inactive equipped items are normalized out before freeze
  - runtime calculations use frozen snapshot values, not live gear rows

Run:
    .venv\\Scripts\\python.exe tests\\test_gear_step4.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.classic import PlayerClassicState, PlayerWallet
from app.models.game import GameSession
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.models.progression import SessionParticipantSnapshot
from app.services.progression import (
    ensure_session_participant_snapshot,
    get_session_player_modifiers,
)
from app.modes.classic import engine


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'gear-step-4-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0
_IDS = {}


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


def _make_player(username, password='pass1234'):
    p = Player(username=username, is_admin=False)
    p.set_password(password)
    db.session.add(p)
    db.session.flush()
    return p


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def _make_session(status='waiting'):
    gs = GameSession(mode='classic', status=status)
    db.session.add(gs)
    db.session.flush()
    return gs


def _ensure_participation_rows(player_id, session_id):
    wallet = PlayerWallet.query.filter_by(player_id=player_id, session_id=session_id).first()
    if wallet is None:
        wallet = PlayerWallet(player_id=player_id, session_id=session_id, gold=0, gems=0)
        db.session.add(wallet)
    pcs = PlayerClassicState.query.filter_by(player_id=player_id, session_id=session_id).first()
    if pcs is None:
        pcs = PlayerClassicState(player_id=player_id, session_id=session_id)
        db.session.add(pcs)
    db.session.flush()


def _make_item(item_id, slot_type, **kwargs):
    item = GearItemDefinition(
        id=item_id,
        slot_type=slot_type,
        name=kwargs.pop('name', item_id.replace('_', ' ').title()),
        description=kwargs.pop('description', ''),
        diamond_cost=kwargs.pop('diamond_cost', 1),
        **kwargs,
    )
    db.session.add(item)
    db.session.flush()
    return item


def _own(player_id, item_id):
    db.session.add(PlayerGearOwnership(player_id=player_id, item_id=item_id))
    db.session.flush()


def _set_loadout(player_id, **slot_values):
    loadout = PlayerGearLoadout.query.filter_by(player_id=player_id).first()
    if loadout is None:
        loadout = PlayerGearLoadout(player_id=player_id)
        db.session.add(loadout)
        db.session.flush()
    for attr, value in slot_values.items():
        setattr(loadout, attr, value)
    db.session.flush()
    return loadout


class _Cfg:
    mine_reward = 20
    bonus_timer_duration = 0
    bonus_timer_gold = 0
    first_solver_count = 0
    first_solver_multiplier = 0
    shield_duration = 60
    steal_percent = 0.10
    steal_min_cap = 5
    steal_max_cap = 50


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        player = _make_player('__gear4_player__')
        db.session.commit()
        _IDS['player_id'] = player.id


def test_join_freeze_and_normalization():
    with flask_app.app_context():
        pid = _IDS['player_id']

        _make_item('gear4_mine', 'main_hand', mine_gold_delta=3)
        _make_item('gear4_steal', 'pocket', steal_gold_delta=4)
        _make_item('gear4_shield', 'off_hand', shield_duration_delta=7)
        _make_item('gear4_inactive', 'head', mine_gold_delta=99, is_active=False)
        _own(pid, 'gear4_mine')
        _own(pid, 'gear4_steal')
        _own(pid, 'gear4_shield')
        _own(pid, 'gear4_inactive')
        _set_loadout(
            pid,
            main_hand_item_id='gear4_mine',
            pocket1_item_id='gear4_steal',
            off_hand_item_id='gear4_shield',
            head_item_id='gear4_inactive',
        )
        gs = _make_session(status='waiting')
        session_id = gs.id
        db.session.commit()

    with flask_app.test_client() as client:
        _login(client, '__gear4_player__')
        r = client.post(
            '/classic/join',
            data={'session_id': session_id},
            follow_redirects=True,
        )
        check('G4-01: join route still works', r.status_code == 200, f'got {r.status_code}')

    with flask_app.app_context():
        pid = _IDS['player_id']
        snap = SessionParticipantSnapshot.query.filter_by(session_id=session_id, player_id=pid).first()
        loadout = PlayerGearLoadout.query.filter_by(player_id=pid).first()
        check('G4-01: join freezes mine gear bonus into snapshot',
              snap is not None and snap.effective_gear_mine_gold_delta == 3,
              f'got {None if snap is None else snap.effective_gear_mine_gold_delta}')
        check('G4-02: join freezes steal gear bonus into snapshot',
              snap is not None and snap.effective_gear_steal_gold_delta == 4,
              f'got {None if snap is None else snap.effective_gear_steal_gold_delta}')
        check('G4-03: join freezes shield-duration gear bonus into snapshot',
              snap is not None and snap.effective_gear_shield_duration_delta == 7,
              f'got {None if snap is None else snap.effective_gear_shield_duration_delta}')
        check('G4-04: inactive equipped item does not contribute to frozen values',
              snap is not None and snap.effective_gear_mine_gold_delta == 3,
              f'got {None if snap is None else snap.effective_gear_mine_gold_delta}')
        check('G4-04: inactive equipped item normalized out of persisted loadout',
              loadout is not None and loadout.head_item_id is None,
              f'head_item_id={None if loadout is None else loadout.head_item_id!r}')


def test_snapshot_is_immutable_after_join():
    with flask_app.app_context():
        pid = _IDS['player_id']
        _make_item('gear4_immutable_old', 'main_hand', mine_gold_delta=5)
        _make_item('gear4_immutable_new', 'main_hand', mine_gold_delta=17)
        _own(pid, 'gear4_immutable_old')
        _own(pid, 'gear4_immutable_new')
        _set_loadout(pid, main_hand_item_id='gear4_immutable_old')
        gs = _make_session(status='waiting')
        ensure_session_participant_snapshot(gs.id, pid)
        db.session.commit()

        snap_before = SessionParticipantSnapshot.query.filter_by(session_id=gs.id, player_id=pid).first()
        _set_loadout(pid, main_hand_item_id='gear4_immutable_new')
        item_old = db.session.get(GearItemDefinition, 'gear4_immutable_old')
        item_old.mine_gold_delta = 99
        db.session.commit()

        db.session.expire_all()
        snap_after = SessionParticipantSnapshot.query.filter_by(session_id=gs.id, player_id=pid).first()
        check('G4-05: changing persistent loadout after snapshot does not change frozen values',
              snap_before.effective_gear_mine_gold_delta == 5 and snap_after.effective_gear_mine_gold_delta == 5,
              f'before={snap_before.effective_gear_mine_gold_delta} after={snap_after.effective_gear_mine_gold_delta}')
        check('G4-06: changing item definition after snapshot does not change frozen values',
              snap_after.effective_gear_mine_gold_delta == 5,
              f'got {snap_after.effective_gear_mine_gold_delta}')


def test_runtime_uses_frozen_snapshot_only():
    with flask_app.app_context():
        pid = _IDS['player_id']
        _make_item('gear4_runtime_mine', 'main_hand', mine_gold_delta=6)
        _make_item('gear4_runtime_steal', 'pocket', steal_gold_delta=7)
        _make_item('gear4_runtime_shield', 'off_hand', shield_duration_delta=8)
        _own(pid, 'gear4_runtime_mine')
        _own(pid, 'gear4_runtime_steal')
        _own(pid, 'gear4_runtime_shield')
        _set_loadout(
            pid,
            main_hand_item_id='gear4_runtime_mine',
            pocket1_item_id='gear4_runtime_steal',
            off_hand_item_id='gear4_runtime_shield',
        )
        gs = _make_session(status='active')
        _ensure_participation_rows(pid, gs.id)
        ensure_session_participant_snapshot(gs.id, pid)
        db.session.commit()

        # Mutate persistent gear rows after the snapshot exists.
        _set_loadout(pid, main_hand_item_id=None, pocket1_item_id=None, off_hand_item_id=None)
        db.session.query(PlayerGearOwnership).filter_by(player_id=pid).delete()
        db.session.get(GearItemDefinition, 'gear4_runtime_mine').mine_gold_delta = 100
        db.session.get(GearItemDefinition, 'gear4_runtime_steal').steal_gold_delta = 100
        db.session.get(GearItemDefinition, 'gear4_runtime_shield').shield_duration_delta = 100
        db.session.commit()

        mods = get_session_player_modifiers(gs.id, pid)
        mine_result = engine.calc_mine_reward(_Cfg(), solver_rank=1, timer_active=False)
        final_mine = mine_result['gold'] + mods.effective_mine_bonus + mods.effective_gear_mine_gold_delta
        final_steal = engine.calc_effective_steal_amount(
            100,
            _Cfg.steal_percent,
            _Cfg.steal_min_cap,
            _Cfg.steal_max_cap,
            mods.effective_gear_steal_gold_delta,
        )
        final_shield = engine.calc_effective_shield_duration(
            _Cfg.shield_duration,
            mods.effective_shield_bonus_pct,
            mods.effective_gear_shield_duration_delta,
        )

        check('G4-07: runtime mine behavior uses frozen snapshot value, not live gear rows',
              final_mine == 26,
              f'got {final_mine}')
        check('G4-08: runtime steal behavior uses frozen snapshot value, not live gear rows',
              final_steal == 17,
              f'got {final_steal}')
        check('G4-09: runtime shield duration behavior uses frozen snapshot value, not live gear rows',
              final_shield == 68,
              f'got {final_shield}')
        check('G4-10: runtime reads no longer depend on live ownership/loadout rows',
              mods.effective_gear_mine_gold_delta == 6
              and mods.effective_gear_steal_gold_delta == 7
              and mods.effective_gear_shield_duration_delta == 8,
              f'mods=({mods.effective_gear_mine_gold_delta}, {mods.effective_gear_steal_gold_delta}, {mods.effective_gear_shield_duration_delta})')


if __name__ == '__main__':
    print('\nGear Step 4 - Tests')
    print('-' * 60)
    _setup_db()
    test_join_freeze_and_normalization()
    test_snapshot_is_immutable_after_join()
    test_runtime_uses_frozen_snapshot_only()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL GEAR STEP 4 TESTS PASSED.')
    else:
        print('SOME GEAR STEP 4 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
