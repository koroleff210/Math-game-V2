import atexit
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig,
    PlayerClassicState,
    PlayerInventory,
    PlayerWallet,
    StoreItem,
)
from app.modes.classic import engine
from app.modes.classic import store as classic_store
from app.modes.classic.events import _manual_shield_base_duration, _reactive_shield_base_duration


_DB_FILE = tempfile.NamedTemporaryFile(
    prefix='classic_shield_alignment_',
    suffix='.sqlite3',
    delete=False,
)
_DB_FILE.close()


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_DB_FILE.name.replace(os.sep, '/')}"
    SECRET_KEY = 'classic-shield-alignment-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)


@atexit.register
def _cleanup_db_file():
    try:
        os.remove(_DB_FILE.name)
    except OSError:
        pass


def _now():
    return datetime.now(timezone.utc)


def _make_player(username, *, is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    return client.post(
        '/login',
        data={'username': username, 'password': 'pass1234'},
        follow_redirects=True,
    )


def _setup_world():
    db.create_all()

    actor = _make_player('__shield_actor__')
    target = _make_player('__shield_target__')

    topic = Topic(name='__shield_topic__')
    db.session.add(topic)
    db.session.flush()

    problem = Problem(
        topic_id=topic.id,
        title='Shield Problem',
        prompt_text='2+2?',
        answer_text='4',
        difficulty=1,
    )
    db.session.add(problem)
    db.session.flush()

    problem_set = ProblemSet(name='__shield_set__')
    db.session.add(problem_set)
    db.session.flush()
    problem_set.problems.append(problem)

    session = GameSession(mode='classic', status='active', problem_set_id=problem_set.id)
    db.session.add(session)
    db.session.flush()

    round_row = GameRound(
        session_id=session.id,
        round_number=1,
        started_at=_now(),
    )
    db.session.add(round_row)
    db.session.flush()

    config = ClassicRoundConfig(
        round_id=round_row.id,
        mine_reward=20,
        treasure_search_reward=5,
        treasure_search_max_reward=5,
        attempts_per_problem=1,
        wrong_answer_penalty=0,
        bonus_timer_duration=0,
        bonus_timer_gold=0,
        first_solver_count=0,
        first_solver_multiplier=0,
        gem_milestone_count=0,
        gem_streak_count=0,
        gem_treasure_chance=0.0,
        steal_percent=0.1,
        steal_min_cap=10,
        steal_max_cap=50,
        steal_fallback_gold=5,
        steal_chest_count=0,
        steal_winning_chest_count=1,
        shield_duration=60,
        active_shield_duration=90,
        reactive_shield_duration=45,
        treasure_steal_token_chance=0.0,
        treasure_active_shield_chance=0.2,
        treasure_second_chance_chance=0.0,
    )
    db.session.add(config)

    db.session.add(RoundPlayer(session_id=session.id, player_id=actor.id))
    db.session.add(RoundPlayer(session_id=session.id, player_id=target.id))
    db.session.add(PlayerWallet(player_id=actor.id, session_id=session.id, gold=20, gems=0, steal_tokens=1))
    db.session.add(PlayerWallet(player_id=target.id, session_id=session.id, gold=50, gems=0, steal_tokens=1))

    shield_item = StoreItem(
        session_id=session.id,
        name='Shield Token',
        description='Manual anti-steal protection',
        cost=10,
        currency='gold',
        bonus_type='steal_shield',
        session_stock=-1,
        per_player_limit=-1,
    )
    db.session.add(shield_item)
    db.session.flush()

    db.session.commit()
    return actor, target, session, round_row, config, shield_item


def _unused_shield_count(player_id, session_id):
    return (
        PlayerInventory.query
        .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
        .filter(
            PlayerInventory.player_id == player_id,
            PlayerInventory.session_id == session_id,
            StoreItem.bonus_type == 'steal_shield',
            PlayerInventory.used_at == None,  # noqa: E711
        )
        .count()
    )


def run():
    with flask_app.app_context():
        actor, target, session, _round, config, shield_item = _setup_world()

        print('\n-- Shield alignment: treasure grants token, not runtime protection --')
        sys_item = classic_store.get_or_create_system_shield_token(session.id)
        inv = PlayerInventory(
            player_id=actor.id,
            session_id=session.id,
            item_id=sys_item.id,
            purchased_at=_now(),
            used_at=None,
        )
        db.session.add(inv)
        db.session.commit()
        pcs = PlayerClassicState.query.filter_by(player_id=actor.id, session_id=session.id).first()
        ok = pcs is None or not engine.is_steal_shield_active(pcs)
        print('PASS treasure reward leaves runtime protection inactive' if ok else 'FAIL treasure reward activated runtime protection')
        if not ok:
            raise SystemExit(1)

        print('\n-- Shield alignment: manual activation blocked while already protected --')
        extra_inv = PlayerInventory(
            player_id=actor.id,
            session_id=session.id,
            item_id=shield_item.id,
            purchased_at=_now(),
            used_at=None,
        )
        db.session.add(extra_inv)
        pcs = PlayerClassicState(player_id=actor.id, session_id=session.id, shield_expires_at=_now() + timedelta(seconds=30))
        db.session.add(pcs)
        db.session.commit()
        count_before = _unused_shield_count(actor.id, session.id)

        client = flask_app.test_client()
        _login(client, actor.username)
        socket_client = socketio.test_client(flask_app, flask_test_client=client)
        socket_client.emit('classic_activate_steal_shield', {'session_id': session.id})
        received = socket_client.get_received()
        count_after = _unused_shield_count(actor.id, session.id)
        blocked = any(evt['name'] == 'shield_activation_blocked' for evt in received)
        ok = blocked and count_after == count_before
        print('PASS blocked activation preserves token count' if ok else f'FAIL blocked={blocked} before={count_before} after={count_after}')
        if not ok:
            raise SystemExit(1)
        socket_client.disconnect()

        print('\n-- Shield alignment: player page exposes shield token/protection UI hooks --')
        page_client = flask_app.test_client()
        _login(page_client, actor.username)
        page = page_client.get(f'/classic/game/{session.id}')
        html = page.get_data(as_text=True)
        ok = (
            page.status_code == 200
            and 'player-shield-status' in html
            and 'shield-status-message' in html
            and 'context-log-panel' in html
            and 'treasure-overlay' in html
            and 'confirmTreasureSelection' in html
            and 'TREASURE_SLOT_LAYOUTS' in html
            and 'steal-overlay' in html
            and 'confirmStealSelection' in html
            and 'STEAL_SLOT_LAYOUTS' in html
            and 'STEAL_AVATAR_LAYOUT' in html
            and 'overlay_layouts' not in html
            and 'copyTreasureOverlayLayout' not in html
            and 'copyStealOverlayLayout' not in html
            and 'OVERLAY_LAYOUT_DEBUG' not in html
            and 'renderOverlayDebugGuide' not in html
            and 'shield-tokens-display' not in html
            and 'id="problem-window"' in html
            and '.prob-btn.available' in html
            and '.prob-btn.solved' in html
            and '.prob-btn.closed' in html
            and 'id="steal-targets-list"' in html
            and 'max-height: 180px;' in html
            and 'function clearSelectedProblemContext(options)' in html
            and 'preserveInteractionShell' in html
            and 'Intentional UX: once a correct submission enters reward/steal resolution' in html
            and 'return isPortraitMobileMode() || selectedProblemId !== null;' in html
        )
        print('PASS player page exposes shield status UI' if ok else 'FAIL player page missing shield UI hooks')
        if not ok:
            raise SystemExit(1)

        print('\n-- Shield alignment: separate manual/reactive base durations --')
        manual_base = _manual_shield_base_duration(config)
        reactive_base = _reactive_shield_base_duration(config)
        ok = manual_base == 90 and reactive_base == 45 and manual_base != reactive_base
        print('PASS manual/reactive durations separated' if ok else f'FAIL manual={manual_base} reactive={reactive_base}')
        if not ok:
            raise SystemExit(1)

        print('\n-- Shield alignment: target filtering still uses shared runtime protection state --')
        target_pcs = PlayerClassicState.query.filter_by(player_id=target.id, session_id=session.id).first()
        if not target_pcs:
            target_pcs = PlayerClassicState(player_id=target.id, session_id=session.id)
            db.session.add(target_pcs)
            db.session.flush()
        engine.grant_steal_shield(target_pcs, reactive_base)
        db.session.commit()
        wallets = PlayerWallet.query.filter_by(session_id=session.id).all()
        states = {row.player_id: row for row in PlayerClassicState.query.filter_by(session_id=session.id).all()}
        targets = engine.build_steal_targets(wallets, states, actor.id)
        ok = all(row['player_id'] != target.id for row in targets)
        print('PASS protected target excluded from steal targets' if ok else 'FAIL protected target still targetable')
        if not ok:
            raise SystemExit(1)

        print('\nALL SHIELD ALIGNMENT TESTS PASSED.')


if __name__ == '__main__':
    run()
