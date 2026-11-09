"""Cross-client delivery of enrollment, store, gold and successful steals."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from app import create_app
from app.extensions import db, socketio
from app.models.player import Player
from app.models.groups import PlayerGroup
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound
from app.models.classic import ClassicRoundConfig, PlayerClassicState, PlayerWallet, PlayerProblemState, StealEvent
from app.modes.classic import state


@pytest.fixture
def game():
    class Config:
        TESTING = True
        SECRET_KEY = 'realtime-test'
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SOCKETIO_ASYNC_MODE = 'threading'
        WTF_CSRF_ENABLED = False
        SHARED_IDENTITY_URL = ''

    app = create_app(Config)
    with app.app_context():
        db.create_all()
        admin = Player(username='teacher', password_hash='unused', is_admin=True)
        actor = Player(username='actor', password_hash='unused')
        victim = Player(username='victim', password_hash='unused')
        topic = Topic(name='Physics')
        problems = [Problem(topic=topic, title=f'Q{i}', prompt_text='2 + 2?', answer_text='4') for i in range(2)]
        bank = ProblemSet(name='Set')
        bank.problems.extend(problems)
        session = GameSession(mode='classic', status='active', problem_set=bank)
        db.session.add_all([admin, actor, victim, session])
        db.session.flush()
        round_ = GameRound(session_id=session.id, round_number=1, started_at=datetime.now(timezone.utc))
        db.session.add(round_)
        db.session.flush()
        db.session.add(ClassicRoundConfig(round_id=round_.id, mine_reward=20,
            bonus_timer_duration=0, first_solver_count=0, steal_chest_count=0,
            steal_percent=.1, steal_min_cap=10, steal_max_cap=50))
        db.session.commit()
        ids = dict(admin=admin.id, actor=actor.id, victim=victim.id,
                   session=session.id, problems=[p.id for p in problems])
    clients = {}
    for role in ('admin', 'actor', 'victim'):
        client = app.test_client()
        with client.session_transaction() as browser:
            browser['_user_id'] = str(ids[role])
            browser['_fresh'] = True
        clients[role] = client
    sockets = []

    def connect(role):
        sock = socketio.test_client(app, flask_test_client=clients[role])
        sockets.append(sock)
        return sock

    yield app, ids, clients, connect
    for sock in sockets:
        if sock.is_connected():
            sock.disconnect()
    state.clear_session(ids['session'])
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def payload(events, name):
    matches = [e['args'][0] for e in events if e['name'] == name]
    assert matches, f'Missing {name}; received {[e["name"] for e in events]}'
    return matches[-1]


def test_admission_notifies_before_player_page_connects(game, monkeypatch):
    app, ids, clients, connect = game
    watcher = connect('admin')
    watcher.emit('classic_admin_watch', {'session_id': ids['session']})
    watcher.get_received()
    response = clients['actor'].post('/classic/join', data={'session_id': ids['session']})
    assert response.status_code == 302
    assert payload(watcher.get_received(), 'player_joined')['players'] == ['actor']
    from app.modes.classic import events
    monkeypatch.setattr(events, '_render_problem_body_html', lambda *_: pytest.fail('Lobby rendered questions'))
    player = connect('actor')
    player.emit('classic_join', {'session_id': ids['session'], 'view': 'lobby'})
    ack = payload(player.get_received(), 'join_ack')
    assert ack['round_status'] == 'active'
    assert 'problem_list' not in ack
    with app.app_context():
        assert PlayerProblemState.query.count() == 0


def test_store_gold_steal_and_admin_reconnect(game):
    app, ids, clients, connect = game
    watcher = connect('admin')
    watcher.emit('classic_admin_watch', {'session_id': ids['session']})
    players = {}
    for role in ('actor', 'victim'):
        assert clients[role].post('/classic/join', data={'session_id': ids['session']}).status_code == 302
        players[role] = connect(role)
        players[role].emit('classic_join', {'session_id': ids['session']})
        assert len(payload(players[role].get_received(), 'join_ack')['problem_list']) == 2
    with app.app_context():
        PlayerWallet.query.filter_by(player_id=ids['victim']).one().gold = 100
        PlayerWallet.query.filter_by(player_id=ids['actor']).one().steal_tokens = 1
        db.session.commit()
    watcher.get_received()
    for sock in players.values():
        sock.get_received()
    # The same committed store version reaches both connected players.
    assert clients['admin'].post(f'/admin/classic/{ids["session"]}/push_store').status_code == 302
    stores = [payload(sock.get_received(), 'store_updated') for sock in players.values()]
    assert stores[0] == stores[1]
    assert watcher.emit('classic_push_store', {'session_id': ids['session']}, callback=True) == {'ok': True}
    stores = [payload(sock.get_received(), 'store_updated') for sock in players.values()]
    assert stores[0] == stores[1]
    denied = players['actor'].emit('classic_push_store', {'session_id': ids['session']}, callback=True)
    assert denied['ok'] is False
    assert not any(e['name'] == 'store_updated' for e in players['victim'].get_received())
    actor = players['actor']
    for index, action in enumerate(('mine', 'steal')):
        actor.emit('classic_submit_answer', dict(session_id=ids['session'], problem_id=ids['problems'][index], answer_text='4'))
        payload(actor.get_received(), 'choose_action_prompt')
        actor.emit('classic_choose_action', dict(session_id=ids['session'], problem_id=ids['problems'][index], action=action))
        if action == 'mine':
            result = payload(actor.get_received(), 'reward_applied')
            assert result['new_balance'] == 25
            rows = payload(players['victim'].get_received(), 'leaderboard_update')['leaderboard']
            assert next(r for r in rows if r['username'] == 'actor')['gold'] == 25
        else:
            payload(actor.get_received(), 'steal_targets')
            players['victim'].get_received()
            actor.emit('classic_steal_pick_target', dict(session_id=ids['session'], target_player_id=ids['victim']))
            actor_events = actor.get_received()
            victim_events = players['victim'].get_received()
            assert payload(actor_events, 'steal_result')['new_balance'] == 40
            assert payload(victim_events, 'steal_victim_notify')['new_balance'] == 90
            assert payload(actor_events, 'leaderboard_update') == payload(victim_events, 'leaderboard_update')
    watcher.disconnect()
    replacement = connect('admin')
    replacement.emit('classic_admin_watch', {'session_id': ids['session']})
    events = replacement.get_received()
    assert set(payload(events, 'player_joined')['players']) == {'actor', 'victim'}
    assert {r['username']: r['gold'] for r in payload(events, 'leaderboard_update')['leaderboard']} == {'actor': 40, 'victim': 90}


@pytest.mark.parametrize('shield_before_target_pick', [True, False])
def test_protected_target_resolves_at_confirmation_and_survives_reconnect(game, shield_before_target_pick):
    app, ids, clients, connect = game
    sid, pid = ids['session'], ids['problems'][0]
    for role in ('actor', 'victim'):
        clients[role].post('/classic/join', data={'session_id': sid})
    with app.app_context():
        config = ClassicRoundConfig.query.one()
        config.steal_chest_count = 5
        config.steal_fallback_gold = 8
        PlayerWallet.query.filter_by(player_id=ids['victim']).one().gold = 100
        db.session.commit()

    def protect():
        with app.app_context():
            shield = PlayerClassicState.query.filter_by(player_id=ids['victim']).one()
            shield.shield_expires_at = datetime.now(timezone.utc) + timedelta(seconds=40)
            db.session.commit()

    watcher = connect('admin')
    watcher.emit('classic_admin_watch', {'session_id': sid})
    actor = connect('actor')
    actor.emit('classic_join', {'session_id': sid})
    actor.get_received()
    actor.emit('classic_submit_answer', dict(session_id=sid, problem_id=pid, answer_text='4'))
    answer_events = actor.get_received()
    payload(answer_events, 'choose_action_prompt')
    assert all(event['name'] != 'admin_summary_update' for event in answer_events)
    assert 'actor' in payload(watcher.get_received(), 'admin_summary_update')['progress_html']
    actor.emit('classic_choose_action', dict(session_id=sid, problem_id=pid, action='steal'))
    payload(actor.get_received(), 'steal_targets')
    if shield_before_target_pick:
        protect()
    actor.emit('classic_steal_pick_target', dict(session_id=sid, target_player_id=ids['victim']))
    payload(actor.get_received(), 'steal_mini_game_start')
    if not shield_before_target_pick:
        protect()
    actor.emit('classic_steal_select_container', dict(session_id=sid, chest_index=1))
    actor.disconnect()
    actor = connect('actor')
    actor.emit('classic_join', {'session_id': sid})
    pending = payload(actor.get_received(), 'join_ack')['pending_steal']
    assert (pending['problem_id'], pending['selected_chest'], pending['phase']) == (pid, 1, 'selected_pending_confirm')
    for _ in range(2):
        actor.emit('classic_steal_mini_game_pick', dict(session_id=sid, chest_index=1))
        result = payload(actor.get_received(), 'steal_result')
        assert result['outcome'] == 'stranger_target_invalid'
        assert result['successful'] and result['gold_gained'] == 8
    with app.app_context():
        assert PlayerWallet.query.filter_by(player_id=ids['victim']).one().gold == 100
        assert StealEvent.query.count() == 1


def test_final_results_require_both_class_membership_and_enrollment(game):
    app, ids, clients, _ = game
    sid = ids['session']
    clients['actor'].post('/classic/join', data={'session_id': sid})
    with app.app_context():
        actor = db.session.get(Player, ids['actor'])
        victim = db.session.get(Player, ids['victim'])
        session = db.session.get(GameSession, sid)
        group = PlayerGroup(name='Class')
        db.session.add(group)
        group.members.extend([actor, victim])
        session.group = group
        session.status = 'finished'
        db.session.commit()
    path = f'/classic/round_over/{sid}'
    assert b'Final Results' in clients['actor'].get(path).data
    assert clients['victim'].get(path).status_code == 302
    with app.app_context():
        PlayerGroup.query.one().members.remove(db.session.get(Player, ids['actor']))
        db.session.commit()
    assert clients['actor'].get(path).status_code == 302
