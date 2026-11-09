"""Run the isolated local game without the debug reloader."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001)
    args = parser.parse_args()
    home = ROOT / 'instance/local-play'
    if not (home / 'sync-report.json').exists():
        raise SystemExit('Run tools/sync_local_content.py first.')
    os.environ.update(GAME_ENV='development', GAME_INSTANCE_PATH=str(home),
                      DATABASE_URL='sqlite:///' + (home / 'math_game.db').as_posix(),
                      GAME_MEDIA_ROOT=str(home / 'media'), GAME_IDENTITY_URL='', GAME_IDENTITY_TOKEN='')
    from app import create_app
    from app.extensions import socketio
    app = create_app()
    marker = home / 'server.json'
    marker.write_text(json.dumps(dict(pid=os.getpid(), port=args.port)))
    try:
        socketio.run(app, host='127.0.0.1', port=args.port, debug=False, allow_unsafe_werkzeug=True)
    finally:
        marker.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
