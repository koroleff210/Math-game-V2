# Entry point for math_game_v2.
# Run with: python run.py

import os

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == '__main__':
    if app.config['GAME_ENV'] == 'production':
        raise RuntimeError('Use the production Gunicorn entrypoint; run.py is for local development only.')
    port = int(os.environ.get('PORT', '5000'))

    # host='0.0.0.0' makes the server reachable on the local network (LAN play).
    # debug=True enables auto-reload during development.
    # allow_unsafe_werkzeug=True is required by Flask-SocketIO 5.x when running
    # directly through Werkzeug's dev server (as opposed to `flask run`).
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
