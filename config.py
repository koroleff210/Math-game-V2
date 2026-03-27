import os


class Config:
    # Secret key used to sign sessions and CSRF tokens.
    # In production, set this via the SECRET_KEY environment variable.
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-before-deployment')

    # SQLite database stored in the instance/ folder.
    # Override with DATABASE_URL env variable for other DB engines.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///math_game.db'
    )

    # Disable SQLAlchemy change tracking — not needed and wastes memory.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flask-SocketIO async mode.
    # 'threading' works with simple-websocket (already installed).
    # Switch to 'gevent' later if gevent is added to the environment.
    SOCKETIO_ASYNC_MODE = os.environ.get('SOCKETIO_ASYNC_MODE', 'threading')
