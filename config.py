import os


def _database_uri():
    uri = os.environ.get('DATABASE_URL', 'sqlite:///math_game.db')
    # Render supplies a standard PostgreSQL URL. Select psycopg 3 explicitly.
    if uri.startswith('postgres://'):
        return 'postgresql+psycopg://' + uri[len('postgres://'):]
    if uri.startswith('postgresql://'):
        return 'postgresql+psycopg://' + uri[len('postgresql://'):]
    return uri


class Config:
    INSTANCE_PATH = os.environ.get('GAME_INSTANCE_PATH')
    GAME_ENV = os.environ.get('GAME_ENV', 'development').lower()
    # Secret key used to sign sessions and CSRF tokens.
    # In production, set this via the SECRET_KEY environment variable.
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-before-deployment')

    # SQLite database stored in the instance/ folder.
    # Override with DATABASE_URL env variable for other DB engines.
    SQLALCHEMY_DATABASE_URI = _database_uri()

    # Disable SQLAlchemy change tracking — not needed and wastes memory.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-SocketIO async mode.
    # 'threading' works with simple-websocket (already installed).
    # Switch to 'gevent' later if gevent is added to the environment.
    SOCKETIO_ASYNC_MODE = os.environ.get('SOCKETIO_ASYNC_MODE', 'threading')

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = GAME_ENV == 'production'

    # One production web process uses a small in-memory login failure window.
    LOGIN_RATE_LIMIT_ENABLED = GAME_ENV == 'production'
    SESSION_COOKIE_NAME = 'math_game_session'
    SHARED_IDENTITY_URL = os.environ.get('GAME_IDENTITY_URL', '')
    SHARED_IDENTITY_TOKEN = os.environ.get('GAME_IDENTITY_TOKEN', '')

    MEDIA_ROOT = os.environ.get('GAME_MEDIA_ROOT', os.path.join(os.path.dirname(__file__), 'instance', 'media'))
    MAX_CONTENT_LENGTH = int(os.environ.get('GAME_MAX_REQUEST_BYTES', str(128 * 1024 * 1024)))
    IMPORT_MAX_FILES = int(os.environ.get('GAME_IMPORT_MAX_FILES', '6000'))
    IMPORT_MAX_EXPANDED_BYTES = int(os.environ.get('GAME_IMPORT_MAX_EXPANDED_BYTES', str(256 * 1024 * 1024)))
