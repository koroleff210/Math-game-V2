import pytest

from app import create_app
from app.extensions import db, socketio
from app.models.game import GameSession, RoundPlayer
from app.models.player import Player


class Config:
    TESTING = True
    SECRET_KEY = 'proctoring-test'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'


@pytest.fixture
def game():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        for name in ('teacher', 'student', 'outsider'):
            player = Player(username=name, is_admin=name == 'teacher')
            player.set_password('test-password')
            db.session.add(player)
        classic = GameSession(mode='classic', proctoring_required=True)
        boss = GameSession(mode='boss_rush', proctoring_required=True)
        db.session.add_all([classic, boss])
        db.session.commit()
        ids = classic.id, boss.id
    clients = []
    for name in ('teacher', 'student', 'outsider'):
        client = app.test_client()
        client.post('/login', data={'username': name, 'password': 'test-password'})
        clients.append(client)
    return app, ids, clients


def test_monitor_admission_and_disconnect(game):
    app, (sid, _), (teacher, student, outsider) = game
    data = {'session_id': sid}
    admin = socketio.test_client(app, flask_test_client=teacher)
    player = socketio.test_client(app, flask_test_client=student)
    other = socketio.test_client(app, flask_test_client=outsider)
    assert student.get(f'/admin/proctoring/{sid}').status_code == 403
    assert teacher.get(f'/admin/proctoring/{sid}').status_code == 200
    assert not player.emit('proctor_watch', data, callback=True)['ok']
    assert not player.emit('proctor_share', data | {'surface': 'browser'}, callback=True)['ok']
    assert '/player/dashboard' in student.post('/classic/join', data=data).location

    assert admin.emit('proctor_watch', data, callback=True)['ok']
    assert player.emit('proctor_share', data | {'surface': 'monitor'}, callback=True)['ok']
    player.emit('proctor_share_ready', data)
    peer = next(event['args'][0]['peer'] for event in admin.get_received() if event['name'] == 'proctor_peer')
    other.emit('proctor_viewed', data | {'peers': [peer]})
    assert '/player/dashboard' in student.post('/classic/join', data=data).location
    admin.emit('proctor_viewed', data | {'peers': [peer]})
    assert f'/classic/lobby/{sid}' in student.post('/classic/join', data=data).location

    admin.disconnect()
    player.get_received()
    player.emit('classic_submit_answer', data | {'problem_id': 1, 'answer_text': '4'})
    assert any(event['name'] == 'proctor_required' for event in player.get_received())
    player.emit('classic_buy_item', data | {'item_id': 1})
    assert any(event['name'] == 'proctor_required' for event in player.get_received())
    with app.app_context():
        assert RoundPlayer.query.filter_by(session_id=sid).count() == 1

    assert teacher.post(f'/admin/proctoring/{sid}/disable').status_code == 302
    assert any(event['name'] == 'proctor_ended' for event in player.get_received())
    with app.app_context():
        assert not db.session.get(GameSession, sid).proctoring_required
    assert f'/classic/lobby/{sid}' in student.post('/classic/join', data=data).location


def test_boss_join_and_active_submission_are_gated(game):
    app, (_, sid), (_, student, _) = game
    assert '/player/dashboard' in student.post('/boss-rush/join', data={'session_id': sid}).location
    with app.app_context():
        assert RoundPlayer.query.filter_by(session_id=sid).count() == 0
        game_session = db.session.get(GameSession, sid)
        game_session.status = 'active'
        player = Player.query.filter_by(username='student').one()
        db.session.add(RoundPlayer(session_id=sid, player_id=player.id))
        db.session.commit()
    response = student.post(f'/boss-rush/game/{sid}/answer', data={'answer_text': '4'})
    assert response.location.endswith(f'/boss-rush/game/{sid}')
    with student.session_transaction() as session:
        assert any('Share your entire screen' in message for _, message in session['_flashes'])
