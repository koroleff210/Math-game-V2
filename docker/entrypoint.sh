#!/bin/sh
set -eu

# Compose waits for a healthy PostgreSQL service; this also tolerates a brief
# connection delay during a restart or manual container launch.
python - <<'PY'
import sys
import time
from sqlalchemy import create_engine, text
from config import Config

for attempt in range(30):
    try:
        engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, connect_args={'connect_timeout': 3})
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        engine.dispose()
        break
    except Exception as exc:
        if attempt == 29:
            print(f'PostgreSQL unavailable after 30 attempts: {type(exc).__name__}', file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
PY

# Never invoke local seed, reset, or destructive maintenance commands here.
python -m flask --app run:app db upgrade
python -m flask --app run:app create-admin

# Classic pending actions and locks are process-local. Keep exactly one worker.
exec gunicorn --worker-class gthread --workers 1 --threads 32 \
    --bind 0.0.0.0:8000 --timeout 120 run:app
