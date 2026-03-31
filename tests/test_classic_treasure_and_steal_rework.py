import atexit
import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

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
    PlayerProblemState,
    PlayerWallet,
    StoreItem,
)
from app.modes.classic import engine, state
from app.modes.classic.forms import ClassicSessionForm


_DB_FILE = tempfile.NamedTemporaryFile(
    prefix='classic_treasure_steal_rework_',
    suffix='.sqlite3',
    delete=False,
)
_DB_FILE.close()


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_DB_FILE.name.replace(os.sep, '/')}"
    SECRET_KEY = 'classic-treasure-steal-rework-secret'
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
        follow_redirects=False,
    )


def _reset_db():
    db.session.remove()
    db.drop_all()
    db.create_all()


def _make_world(
    *,
    suffix,
    include_target=True,
    actor_tokens=1,
    target_gold=50,
    chest_count=0,
    winning_chests=1,
    fallback_gold=7,
    treasure_overrides=None,
    pre_solved=True,
):
    topic = Topic(name=f'__tr_topic_{suffix}__')
    db.session.add(topic)
    db.session.flush()

    problem = Problem(
        topic_id=topic.id,
        title=f'Treasure Problem {suffix}',
        prompt_text='2+2?',
        answer_text='4',
        difficulty=1,
    )
    db.session.add(problem)
    db.session.flush()

    problem_set = ProblemSet(name=f'__tr_set_{suffix}__')
    db.session.add(problem_set)
    db.session.flush()
    problem_set.problems.append(problem)

    actor = _make_player(f'__tr_actor_{suffix}__')
    target = _make_player(f'__tr_target_{suffix}__') if include_target else None
    admin = _make_player(f'__tr_admin_{suffix}__', is_admin=True)

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

    config_kwargs = dict(
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
        steal_percent=0.5,
        steal_min_cap=10,
        steal_max_cap=50,
        steal_fallback_gold=fallback_gold,
        steal_chest_count=chest_count,
        steal_winning_chest_count=winning_chests,
        shield_duration=60,
        active_shield_duration=60,
        reactive_shield_duration=30,
        treasure_steal_token_chance=0.0,
        treasure_active_shield_chance=0.0,
        treasure_second_chance_chance=0.0,
    )
    if treasure_overrides:
        config_kwargs.update(treasure_overrides)
    config = ClassicRoundConfig(**config_kwargs)
    db.session.add(config)

    db.session.add(RoundPlayer(session_id=session.id, player_id=actor.id))
    db.session.add(PlayerWallet(player_id=actor.id, session_id=session.id, gold=20, gems=0, steal_tokens=actor_tokens))

    if target is not None:
        db.session.add(RoundPlayer(session_id=session.id, player_id=target.id))
        db.session.add(PlayerWallet(player_id=target.id, session_id=session.id, gold=target_gold, gems=0, steal_tokens=0))

    db.session.add(
        PlayerProblemState(
            player_id=actor.id,
            round_id=round_row.id,
            problem_id=problem.id,
            attempts_used=1 if pre_solved else 0,
            is_solved=pre_solved,
            is_closed=False,
        )
    )

    db.session.commit()
    if pre_solved:
        state.set_pending_action(
            actor.id,
            round_row.id,
            problem.id,
            session_id=session.id,
            solver_rank=1,
            timer_active=False,
            steal_available=actor_tokens >= 1,
        )
    return {
        'admin': admin,
        'actor': actor,
        'target': target,
        'session': session,
        'round': round_row,
        'problem': problem,
        'config': config,
    }


def _inventory_count(player_id, session_id, bonus_type):
    return (
        PlayerInventory.query
        .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
        .filter(
            PlayerInventory.player_id == player_id,
            PlayerInventory.session_id == session_id,
            StoreItem.bonus_type == bonus_type,
            PlayerInventory.used_at == None,  # noqa: E711
        )
        .count()
    )


def _event(received, name):
    for evt in received:
        if evt['name'] == name:
            return evt['args'][0] if evt.get('args') else {}
    raise AssertionError(f'Event {name} not found in {received!r}')


def run():
    with flask_app.app_context():
        print('\n-- Treasure engine: one chest per eligible reward, independent fill, shuffled order --')
        candidates = engine.build_treasure_chest_candidates(
            type(
                'Cfg',
                (),
                {
                    'gem_treasure_chance': 0.9,
                    'treasure_steal_token_chance': 0.4,
                    'treasure_active_shield_chance': 0.0,
                    'treasure_second_chance_chance': 0.2,
                },
            )(),
            {
                'gem': True,
                'steal_token': False,
                'shield_token': True,
                'second_chance': True,
            },
        )
        with patch('app.modes.classic.engine.random.random', side_effect=[0.05, 0.8]), \
             patch('app.modes.classic.engine.random.shuffle', side_effect=lambda seq: seq.reverse()):
            rolled = engine.roll_treasure_chests(candidates)
        ok = (
            [c['reward_type'] for c in candidates] == ['gem', 'second_chance']
            and [c['reward_type'] for c in rolled] == ['second_chance', 'gem']
            and rolled[0]['filled'] is False
            and rolled[1]['filled'] is True
            and [c['index'] for c in rolled] == [1, 2]
        )
        print('PASS chest candidates/fill/order behave as expected' if ok else f'FAIL rolled={rolled}')
        if not ok:
            raise SystemExit(1)

        print('\n-- Treasure runtime: no eligible rewards skips chest phase --')
        _reset_db()
        world = _make_world(suffix='skip')
        client = flask_app.test_client()
        _login(client, world['actor'].username)
        sock = socketio.test_client(flask_app, flask_test_client=client)
        sock.emit(
            'classic_choose_action',
            {
                'session_id': world['session'].id,
                'problem_id': world['problem'].id,
                'action': 'treasure_search',
            },
        )
        payload = _event(sock.get_received(), 'reward_applied')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        ok = (
            payload.get('treasure_phase') == 'skipped_no_eligible_rewards'
            and actor_wallet.gold == 25
            and state.get_treasure_chests(world['actor'].id) is None
        )
        print('PASS treasure skips chest phase when nothing is eligible' if ok else f'FAIL payload={payload} gold={actor_wallet.gold}')
        if not ok:
            raise SystemExit(1)
        sock.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Correct solve: refresh restores pending post-solve action without duplicate grant --')
        _reset_db()
        world = _make_world(suffix='action_resume', pre_solved=False)
        db.session.add(PlayerClassicState(player_id=world['actor'].id, session_id=world['session'].id))
        db.session.commit()

        client1 = flask_app.test_client()
        _login(client1, world['actor'].username)
        sock1 = socketio.test_client(flask_app, flask_test_client=client1)
        sock1.emit(
            'classic_submit_answer',
            {
                'session_id': world['session'].id,
                'problem_id': world['problem'].id,
                'answer_text': '4',
            },
        )
        prompt = _event(sock1.get_received(), 'choose_action_prompt')
        pps = PlayerProblemState.query.filter_by(
            player_id=world['actor'].id,
            round_id=world['round'].id,
            problem_id=world['problem'].id,
        ).first()
        sock1.disconnect()

        client2 = flask_app.test_client()
        _login(client2, world['actor'].username)
        sock2 = socketio.test_client(flask_app, flask_test_client=client2)
        sock2.emit('classic_join', {'session_id': world['session'].id})
        join_ack = _event(sock2.get_received(), 'join_ack')
        restored = join_ack.get('pending_action_prompt') or {}
        sock2.emit(
            'classic_choose_action',
            {
                'session_id': world['session'].id,
                'problem_id': world['problem'].id,
                'action': 'mine',
            },
        )
        reward = _event(sock2.get_received(), 'reward_applied')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        gold_after_reward = actor_wallet.gold
        sock2.emit(
            'classic_choose_action',
            {
                'session_id': world['session'].id,
                'problem_id': world['problem'].id,
                'action': 'mine',
            },
        )
        duplicate_attempt = _event(sock2.get_received(), 'error')

        client3 = flask_app.test_client()
        _login(client3, world['actor'].username)
        sock3 = socketio.test_client(flask_app, flask_test_client=client3)
        sock3.emit('classic_join', {'session_id': world['session'].id})
        cleared_ack = _event(sock3.get_received(), 'join_ack')

        ok = (
            prompt.get('problem_id') == world['problem'].id
            and pps is not None and pps.is_solved is True and pps.is_closed is True
            and restored.get('problem_id') == world['problem'].id
            and restored.get('solver_rank') == prompt.get('solver_rank')
            and restored.get('timer_active') == prompt.get('timer_active')
            and reward.get('new_balance') == gold_after_reward
            and duplicate_attempt.get('msg') == 'no pending action for this problem'
            and cleared_ack.get('pending_action_prompt') is None
        )
        print('PASS refresh restores pending post-solve action and grants it only once' if ok else f'FAIL prompt={prompt} restored={restored} reward={reward} duplicate={duplicate_attempt} cleared={cleared_ack}')
        if not ok:
            raise SystemExit(1)
        sock2.disconnect()
        sock3.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Treasure runtime: only selected filled chest grants reward --')
        _reset_db()
        world = _make_world(
            suffix='selected',
            treasure_overrides={
                'gem_treasure_chance': 1.0,
                'treasure_active_shield_chance': 1.0,
            },
        )
        client = flask_app.test_client()
        _login(client, world['actor'].username)
        sock = socketio.test_client(flask_app, flask_test_client=client)
        with patch(
            'app.modes.classic.events.engine.roll_treasure_chests',
            return_value=[
                {'index': 1, 'reward_type': 'shield_token', 'fill_chance': 1.0, 'filled': True},
                {'index': 2, 'reward_type': 'gem', 'fill_chance': 1.0, 'filled': True},
            ],
        ):
            sock.emit(
                'classic_choose_action',
                {
                    'session_id': world['session'].id,
                    'problem_id': world['problem'].id,
                    'action': 'treasure_search',
                },
            )
        offer = _event(sock.get_received(), 'treasure_chest_offer')
        sock.emit(
            'classic_treasure_pick_chest',
            {'session_id': world['session'].id, 'chest_index': 2},
        )
        result = _event(sock.get_received(), 'treasure_chest_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        ok = (
            len(offer.get('chests', [])) == 2
            and all(chest.get('revealed') is False for chest in offer['chests'])
            and result.get('selected_reward_granted') is True
            and result.get('selected_reward_label') == 'Gem'
            and actor_wallet.gems == 1
            and _inventory_count(world['actor'].id, world['session'].id, 'steal_shield') == 0
        )
        print('PASS only the selected treasure chest grants its reward' if ok else f'FAIL offer={offer} result={result} gems={actor_wallet.gems}')
        if not ok:
            raise SystemExit(1)
        sock.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Treasure runtime: reconnect restores pending overlay and does not duplicate grants --')
        _reset_db()
        world = _make_world(
            suffix='treasure_resume',
            treasure_overrides={
                'gem_treasure_chance': 1.0,
                'treasure_active_shield_chance': 1.0,
            },
        )
        db.session.add(PlayerClassicState(player_id=world['actor'].id, session_id=world['session'].id))
        db.session.commit()
        client1 = flask_app.test_client()
        _login(client1, world['actor'].username)
        sock1 = socketio.test_client(flask_app, flask_test_client=client1)
        with patch(
            'app.modes.classic.events.engine.roll_treasure_chests',
            return_value=[
                {'index': 1, 'reward_type': 'shield_token', 'fill_chance': 1.0, 'filled': False},
                {'index': 2, 'reward_type': 'gem', 'fill_chance': 1.0, 'filled': True},
            ],
        ):
            sock1.emit(
                'classic_choose_action',
                {
                    'session_id': world['session'].id,
                    'problem_id': world['problem'].id,
                    'action': 'treasure_search',
                },
            )
        treasure_offer = _event(sock1.get_received(), 'treasure_chest_offer')
        sock1.emit(
            'classic_treasure_select_chest',
            {'session_id': world['session'].id, 'chest_index': 2},
        )
        sock1.disconnect()

        client2 = flask_app.test_client()
        _login(client2, world['actor'].username)
        sock2 = socketio.test_client(flask_app, flask_test_client=client2)
        sock2.emit('classic_join', {'session_id': world['session'].id})
        join_ack = _event(sock2.get_received(), 'join_ack')
        restored = join_ack.get('pending_treasure') or {}
        sock2.emit(
            'classic_treasure_pick_chest',
            {'session_id': world['session'].id, 'chest_index': 2},
        )
        treasure_result = _event(sock2.get_received(), 'treasure_chest_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()

        client3 = flask_app.test_client()
        _login(client3, world['actor'].username)
        sock3 = socketio.test_client(flask_app, flask_test_client=client3)
        sock3.emit('classic_join', {'session_id': world['session'].id})
        reveal_ack = _event(sock3.get_received(), 'join_ack')
        pending_reveal = reveal_ack.get('pending_treasure') or {}
        gems_before_repeat = actor_wallet.gems
        sock3.emit(
            'classic_treasure_pick_chest',
            {'session_id': world['session'].id, 'chest_index': 1},
        )
        repeated_result = _event(sock3.get_received(), 'treasure_chest_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        sock3.emit('classic_stage_event_closed', {'session_id': world['session'].id, 'event_type': 'treasure'})

        client4 = flask_app.test_client()
        _login(client4, world['actor'].username)
        sock4 = socketio.test_client(flask_app, flask_test_client=client4)
        sock4.emit('classic_join', {'session_id': world['session'].id})
        cleared_ack = _event(sock4.get_received(), 'join_ack')

        ok = (
            restored.get('phase') == 'selected_pending_confirm'
            and restored.get('selected_chest') == 2
            and restored.get('chests') == treasure_offer.get('chests')
            and treasure_result.get('selected_reward_label') == 'Gem'
            and pending_reveal.get('phase') == 'revealing'
            and pending_reveal.get('reveal_result', {}).get('selected_chest') == 2
            and repeated_result.get('selected_reward_label') == 'Gem'
            and actor_wallet.gems == gems_before_repeat
            and cleared_ack.get('pending_treasure') is None
        )
        print('PASS treasure reconnect restores the same pending event without duplicate grants' if ok else f'FAIL restored={restored} pending_reveal={pending_reveal} repeated={repeated_result} gems={actor_wallet.gems}')
        if not ok:
            raise SystemExit(1)
        sock2.disconnect()
        sock3.disconnect()
        sock4.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Admin form: treasure chest fill chances no longer require subtotal <= 1 --')
        _reset_db()
        topic = Topic(name='__admin_topic__')
        db.session.add(topic)
        db.session.flush()
        problem = Problem(topic_id=topic.id, title='Admin Problem', prompt_text='1+1?', answer_text='2', difficulty=1)
        db.session.add(problem)
        db.session.flush()
        problem_set = ProblemSet(name='__admin_set__')
        db.session.add(problem_set)
        db.session.flush()
        problem_set.problems.append(problem)
        db.session.commit()
        with flask_app.test_request_context('/admin/classic/new', method='POST'):
            form = ClassicSessionForm(formdata=MultiDict({
                'problem_set_id': problem_set.id,
                'group_id': 0,
                'mine_reward': 20,
                'treasure_search_reward': 5,
                'treasure_search_max_reward': 10,
                'attempts_per_problem': 1,
                'wrong_answer_penalty': 0,
                'bonus_timer_duration': 0,
                'bonus_timer_gold': 0,
                'first_solver_count': 0,
                'first_solver_multiplier': 0,
                'gem_milestone_count': 0,
                'gem_streak_count': 0,
                'gem_treasure_chance': 0.6,
                'treasure_steal_token_chance': 0.6,
                'treasure_active_shield_chance': 0.6,
                'treasure_second_chance_chance': 0.6,
                'steal_percent': 0.1,
                'steal_min_cap': 10,
                'steal_max_cap': 50,
                'steal_fallback_gold': 5,
                'steal_chest_count': 0,
                'steal_winning_chest_count': 1,
                'shield_duration': 60,
                'active_shield_duration': 60,
                'reactive_shield_duration': 45,
            }))
            form.problem_set_id.choices = [(problem_set.id, problem_set.name)]
            form.group_id.choices = [(0, 'Open')]
            ok = form.validate()
        print('PASS admin form accepts independent chest fill chances over 1.0 total' if ok else f'FAIL errors={getattr(form, "errors", {})}')
        if not ok:
            raise SystemExit(1)

        template_html = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'templates', 'admin', 'classic', 'new.html'), encoding='utf-8').read()
        review_js = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'static', 'js', 'admin.js'), encoding='utf-8').read()
        ok = (
            'Treasure Side Rewards' not in template_html
            and 'Treasure Chests' in template_html
            and 'side-reward subtotal' not in review_js
            and 'nothing chance' not in review_js.lower()
            and 'subtotal is above 1.0' not in review_js
            and 'Each eligible chest fills independently' in review_js
        )
        print('PASS admin review copy no longer uses pooled treasure subtotal semantics' if ok else 'FAIL stale pooled treasure copy still present')
        if not ok:
            raise SystemExit(1)

        print('\n-- Steal runtime: no targets becomes stranger steal --')
        _reset_db()
        world = _make_world(suffix='notarget', include_target=False, fallback_gold=9)
        client = flask_app.test_client()
        _login(client, world['actor'].username)
        sock = socketio.test_client(flask_app, flask_test_client=client)
        sock.emit(
            'classic_choose_action',
            {
                'session_id': world['session'].id,
                'problem_id': world['problem'].id,
                'action': 'steal',
            },
        )
        result = _event(sock.get_received(), 'steal_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        ok = (
            result.get('outcome') == 'stranger_no_targets'
            and actor_wallet.gold == 29
            and actor_wallet.steal_tokens == 0
        )
        print('PASS no-target steals always resolve to stranger gold' if ok else f'FAIL result={result} wallet={actor_wallet.gold}/{actor_wallet.steal_tokens}')
        if not ok:
            raise SystemExit(1)
        sock.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Steal runtime: losing chest becomes stranger steal and leaves target untouched --')
        _reset_db()
        world = _make_world(suffix='strangerchest', chest_count=2, winning_chests=1, fallback_gold=8)
        client = flask_app.test_client()
        _login(client, world['actor'].username)
        sock = socketio.test_client(flask_app, flask_test_client=client)
        with patch('app.modes.classic.events.engine.generate_winning_chests', return_value=frozenset({1})):
            sock.emit(
                'classic_choose_action',
                {
                    'session_id': world['session'].id,
                    'problem_id': world['problem'].id,
                    'action': 'steal',
                },
            )
            targets = _event(sock.get_received(), 'steal_targets')
            sock.emit(
                'classic_steal_pick_target',
                {'session_id': world['session'].id, 'target_player_id': world['target'].id},
            )
            start_payload = _event(sock.get_received(), 'steal_mini_game_start')
            sock.emit(
                'classic_steal_mini_game_pick',
                {'session_id': world['session'].id, 'chest_index': 2},
            )
        result = _event(sock.get_received(), 'steal_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        target_wallet = PlayerWallet.query.filter_by(
            player_id=world['target'].id,
            session_id=world['session'].id,
        ).first()
        target_pcs = PlayerClassicState.query.filter_by(
            player_id=world['target'].id,
            session_id=world['session'].id,
        ).first()
        ok = (
            len(targets.get('targets', [])) == 1
            and start_payload.get('target', {}).get('username') == world['target'].username
            and len(start_payload.get('target', {}).get('layers', [])) > 0
            and result.get('outcome') == 'stranger_chest'
            and actor_wallet.gold == 28
            and actor_wallet.steal_tokens == 0
            and target_wallet.gold == 50
            and target_pcs is None
        )
        print('PASS losing steal chest yields stranger gold without touching target' if ok else f'FAIL result={result} actor={actor_wallet.gold} target={target_wallet.gold}')
        if not ok:
            raise SystemExit(1)
        sock.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Steal runtime: reconnect restores pending overlay and does not duplicate resolution --')
        _reset_db()
        world = _make_world(suffix='steal_resume', chest_count=3, winning_chests=1, fallback_gold=8)
        db.session.add(PlayerClassicState(player_id=world['actor'].id, session_id=world['session'].id))
        db.session.commit()
        client1 = flask_app.test_client()
        _login(client1, world['actor'].username)
        sock1 = socketio.test_client(flask_app, flask_test_client=client1)
        with patch('app.modes.classic.events.engine.generate_winning_chests', return_value=frozenset({1})):
            sock1.emit(
                'classic_choose_action',
                {
                    'session_id': world['session'].id,
                    'problem_id': world['problem'].id,
                    'action': 'steal',
                },
            )
            _event(sock1.get_received(), 'steal_targets')
            sock1.emit(
                'classic_steal_pick_target',
                {'session_id': world['session'].id, 'target_player_id': world['target'].id},
            )
        steal_offer = _event(sock1.get_received(), 'steal_mini_game_start')
        sock1.emit(
            'classic_steal_select_container',
            {'session_id': world['session'].id, 'chest_index': 1},
        )
        sock1.disconnect()

        client2 = flask_app.test_client()
        _login(client2, world['actor'].username)
        sock2 = socketio.test_client(flask_app, flask_test_client=client2)
        sock2.emit('classic_join', {'session_id': world['session'].id})
        join_ack = _event(sock2.get_received(), 'join_ack')
        restored = join_ack.get('pending_steal') or {}
        sock2.emit(
            'classic_steal_mini_game_pick',
            {'session_id': world['session'].id, 'chest_index': 1},
        )
        steal_result = _event(sock2.get_received(), 'steal_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()

        client3 = flask_app.test_client()
        _login(client3, world['actor'].username)
        sock3 = socketio.test_client(flask_app, flask_test_client=client3)
        sock3.emit('classic_join', {'session_id': world['session'].id})
        reveal_ack = _event(sock3.get_received(), 'join_ack')
        pending_reveal = reveal_ack.get('pending_steal') or {}
        gold_before_repeat = actor_wallet.gold
        sock3.emit(
            'classic_steal_mini_game_pick',
            {'session_id': world['session'].id, 'chest_index': 2},
        )
        repeated_result = _event(sock3.get_received(), 'steal_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        sock3.emit('classic_stage_event_closed', {'session_id': world['session'].id, 'event_type': 'steal'})

        client4 = flask_app.test_client()
        _login(client4, world['actor'].username)
        sock4 = socketio.test_client(flask_app, flask_test_client=client4)
        sock4.emit('classic_join', {'session_id': world['session'].id})
        cleared_ack = _event(sock4.get_received(), 'join_ack')

        ok = (
            restored.get('phase') == 'selected_pending_confirm'
            and restored.get('selected_chest') == 1
            and restored.get('containers') == steal_offer.get('containers')
            and restored.get('target', {}).get('username') == world['target'].username
            and pending_reveal.get('phase') == 'revealing'
            and pending_reveal.get('reveal_result', {}).get('selected_chest') == 1
            and repeated_result.get('selected_chest') == 1
            and actor_wallet.gold == gold_before_repeat
            and cleared_ack.get('pending_steal') is None
        )
        print('PASS steal reconnect restores the same pending event without duplicate resolution' if ok else f'FAIL restored={restored} pending_reveal={pending_reveal} repeated={repeated_result} gold={actor_wallet.gold}')
        if not ok:
            raise SystemExit(1)
        sock2.disconnect()
        sock3.disconnect()
        sock4.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Steal runtime: winning chest converts to stranger steal if target becomes invalid --')
        _reset_db()
        world = _make_world(suffix='invalidlater', chest_count=2, winning_chests=1, fallback_gold=6)
        client = flask_app.test_client()
        _login(client, world['actor'].username)
        sock = socketio.test_client(flask_app, flask_test_client=client)
        with patch('app.modes.classic.events.engine.generate_winning_chests', return_value=frozenset({1})):
            sock.emit(
                'classic_choose_action',
                {
                    'session_id': world['session'].id,
                    'problem_id': world['problem'].id,
                    'action': 'steal',
                },
            )
            _event(sock.get_received(), 'steal_targets')
            sock.emit(
                'classic_steal_pick_target',
                {'session_id': world['session'].id, 'target_player_id': world['target'].id},
            )
            _event(sock.get_received(), 'steal_mini_game_start')
            target_wallet = PlayerWallet.query.filter_by(
                player_id=world['target'].id,
                session_id=world['session'].id,
            ).first()
            target_wallet.gold = 0
            db.session.commit()
            sock.emit(
                'classic_steal_mini_game_pick',
                {'session_id': world['session'].id, 'chest_index': 1},
            )
        result = _event(sock.get_received(), 'steal_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        ok = result.get('outcome') == 'stranger_target_invalid' and actor_wallet.gold == 26 and actor_wallet.steal_tokens == 0
        print('PASS winning chest converts to stranger steal when target is invalid at resolution' if ok else f'FAIL result={result} actor={actor_wallet.gold}')
        if not ok:
            raise SystemExit(1)
        sock.disconnect()
        state.clear_session(world['session'].id)

        print('\n-- Steal runtime: direct targeted steal still applies reactive protection --')
        _reset_db()
        world = _make_world(suffix='targeted', chest_count=0, fallback_gold=6)
        client = flask_app.test_client()
        _login(client, world['actor'].username)
        sock = socketio.test_client(flask_app, flask_test_client=client)
        sock.emit(
            'classic_choose_action',
            {
                'session_id': world['session'].id,
                'problem_id': world['problem'].id,
                'action': 'steal',
            },
        )
        _event(sock.get_received(), 'steal_targets')
        sock.emit(
            'classic_steal_pick_target',
            {'session_id': world['session'].id, 'target_player_id': world['target'].id},
        )
        result = _event(sock.get_received(), 'steal_result')
        actor_wallet = PlayerWallet.query.filter_by(
            player_id=world['actor'].id,
            session_id=world['session'].id,
        ).first()
        target_wallet = PlayerWallet.query.filter_by(
            player_id=world['target'].id,
            session_id=world['session'].id,
        ).first()
        target_pcs = PlayerClassicState.query.filter_by(
            player_id=world['target'].id,
            session_id=world['session'].id,
        ).first()
        ok = (
            result.get('resolved_outcome') == 'targeted_success'
            and actor_wallet.gold == 45
            and target_wallet.gold == 25
            and target_pcs is not None
            and engine.is_steal_shield_active(target_pcs)
        )
        print('PASS targeted steals still apply real victim loss and reactive protection' if ok else f'FAIL result={result}')
        if not ok:
            raise SystemExit(1)
        sock.disconnect()
        state.clear_session(world['session'].id)

        print('\nALL TREASURE/STEAL REWORK TESTS PASSED.')


if __name__ == '__main__':
    run()
