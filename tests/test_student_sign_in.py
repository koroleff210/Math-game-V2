"""Run with pytest. Shared tests use TEST_SYSTEM_SOURCE for the adjacent exam app."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models.player import Player
from app.services import shared_identity


class Config:
    TESTING = True
    SECRET_KEY = 'isolated-auth-test'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'


@pytest.fixture
def game():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        admin = Player(username='admin', is_admin=True)
        admin.set_password('test-admin-password')
        legacy = Player(username='legacy', is_admin=False)
        legacy.set_password('existing-password')
        db.session.add_all([admin, legacy])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_local_first_password_reset_and_legacy_progress(game):
    admin = game.test_client()
    admin.post('/login', data=dict(username='admin', password='test-admin-password'))
    assert admin.post('/admin/players/new', data=dict(username='new-student')).status_code == 302
    with game.app_context():
        new_id = Player.query.filter_by(username='new-student').one().id
        legacy_id = Player.query.filter_by(username='legacy').one().id
    student = game.test_client()
    assert b'Create your password' in student.post('/login', data=dict(username='new-student', action='continue')).data
    response = student.post('/login', data=dict(username='new-student', action='create', password='chosen-password', password_confirm='wrong'))
    assert b'do not match' in response.data
    assert student.get('/admin/players/').status_code == 302
    assert student.post('/login', data=dict(username='new-student', action='create', password='chosen-password', password_confirm='chosen-password')).status_code == 302
    assert student.get('/player/dashboard').status_code == 200
    legacy = game.test_client()
    assert legacy.post('/login', data=dict(username='legacy', password='existing-password')).status_code == 302
    assert admin.post(f'/admin/players/{legacy_id}/reset-password').status_code == 302
    assert legacy.get('/admin/players/').status_code == 302
    assert b'Create your password' in legacy.post('/login', data=dict(username='legacy', action='continue')).data
    with game.app_context():
        assert Player.query.filter_by(username='legacy').one().id == legacy_id
        assert Player.query.filter_by(username='new-student').one().id == new_id
    assert admin.post('/admin/players/new', data=dict(username='bad-admin', is_admin='y')).status_code == 200
    with game.app_context():
        assert Player.query.filter_by(username='bad-admin').first() is None
    # Visiting the Hub creates persistent setup rows; deleting an unused student
    # must remove those rows rather than trying to null their required player_id.
    assert admin.post(f'/admin/players/{new_id}/delete').status_code == 302
    with game.app_context():
        assert db.session.get(Player, new_id) is None
        assert db.session.get(Player, legacy_id) is not None
        admin_id = Player.query.filter_by(username='admin').one().id
    admin.post(f'/admin/players/{admin_id}/edit', data=dict(username='admin'))
    with game.app_context():
        assert db.session.get(Player, admin_id).is_admin


@pytest.fixture
def gateway(tmp_path):
    source = os.environ.get('TEST_SYSTEM_SOURCE')
    if not source:
        pytest.skip('Set TEST_SYSTEM_SOURCE to run shared identity integration tests.')
    sys.path.insert(0, source)
    from deploy.identity_gateway import create_gateway
    from exam_platform import create_app as create_exam
    from exam_platform.models import db as exam_db, User, StudentEnrollment
    uri = 'sqlite:///' + str(tmp_path / 'identities.sqlite')
    app = create_gateway(dict(TESTING=True, SQLALCHEMY_DATABASE_URI=uri, IDENTITY_TOKEN='x' * 48))
    with app.app_context():
        exam_db.create_all()
        teacher = User(role='teacher', name='Teacher', email='teacher@example.test')
        exam_db.session.add(teacher)
        exam_db.session.commit()
    return app, create_exam(dict(TESTING=True, SECRET_KEY='exam-test-secret', SQLALCHEMY_DATABASE_URI=uri))


def test_shared_accounts_both_directions_and_session_revocation(game, gateway, monkeypatch):
    gateway_app, exam = gateway
    transport = gateway_app.test_client()
    def bridge(action, **fields):
        response = transport.post('/identity', json=dict(action=action, **fields),
                                  headers={'Authorization': 'Bearer ' + 'x' * 48})
        return response.json if response.status_code == 200 else {'error': 'Invalid details'}
    monkeypatch.setattr(shared_identity, 'call', bridge)
    game.config['SHARED_IDENTITY_URL'] = 'http://127.0.0.1:5061'
    assert transport.post('/identity', json={}).status_code == 403
    admin = game.test_client()
    admin.post('/login', data=dict(username='admin', password='test-admin-password'))
    # Link a legacy identity without replacing the player or its saved progress.
    with game.app_context():
        player_id = Player.query.filter_by(username='legacy').one().id
    response = admin.post(f'/admin/players/{player_id}/edit', data=dict(username='legacy', shared_email='student@example.test'))
    assert response.status_code == 302
    student = game.test_client()
    assert b'Create your password' in student.post('/login', data=dict(username='student@example.test', action='continue')).data
    assert student.post('/login', data=dict(username='student@example.test', action='create', password='shared-password', password_confirm='shared-password')).status_code == 302
    assert student.get('/player/dashboard').status_code == 200
    assert 'id' in bridge('authenticate', email='student@example.test', password='shared-password')
    assert 'error' in bridge('setup', email='student@example.test', password='replacement-password')
    # An exam student can sign into the game without a second teacher-created account.
    bridge('provision', email='exam-student@example.test')
    bridge('setup', email='exam-student@example.test', password='exam-password')
    another = game.test_client()
    assert another.post('/login', data=dict(username='exam-student@example.test', password='exam-password')).status_code == 302
    assert another.get('/player/dashboard').status_code == 200
    # Same credentials work through the real exam login, including enrollment checks.
    exam_client = exam.test_client()
    exam_client.get('/login')
    with exam_client.session_transaction() as sess:
        csrf = sess['csrf']
    assert exam_client.post('/login', data=dict(email='student@example.test', action='login', password='shared-password', csrf=csrf)).status_code == 302
    # Teacher reset in exam invalidates game sessions as well.
    bridge('reset', email='student@example.test')
    assert student.get('/player/dashboard').status_code == 302
    assert 'error' in bridge('authenticate', email='student@example.test', password='shared-password')
    with game.app_context():
        assert Player.query.filter_by(shared_email='student@example.test').one().id == player_id


def test_shared_outage_fails_closed(game, monkeypatch):
    game.config['SHARED_IDENTITY_URL'] = 'http://127.0.0.1:5061'
    def unavailable(*args, **kwargs):
        raise shared_identity.IdentityUnavailable('Shared sign-in is unavailable.')
    monkeypatch.setattr(shared_identity, 'call', unavailable)
    response = game.test_client().post('/login', data=dict(username='student@example.test', password='password'))
    assert response.status_code == 503
    assert b'unavailable' in response.data


def test_login_requires_csrf(game):
    game.config['WTF_CSRF_ENABLED'] = True
    assert game.test_client().post('/login', data=dict(username='admin', password='test-admin-password')).status_code == 400
