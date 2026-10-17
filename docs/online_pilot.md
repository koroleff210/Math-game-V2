# Online pilot: fresh accounts and an empty problem library

**Superseded for the current release:** use [self-hosted deployment](self_hosted_deployment.md) for the requested Ubuntu/Docker Compose/Caddy installation. The Render Blueprint and notes below are retained as an earlier pilot option; the self-hosted deployment does not require Render.

_Prepared 2026-10-01. This is a deployment candidate, not a record of a completed cloud deployment._

## Recommended first layout

Use one Render Python web service and one Render Postgres database in the same
region. The checked-in `render.yaml` selects one paid web instance and a
persistent paid database. It runs one threaded Gunicorn worker because Classic
still keeps pending actions, locks, and some stage state in one process. Render
handles the public HTTPS URL and WebSocket transport.

Do not upload `instance/math_game.db`, run `seed.py`, or run the
`fresh-start` maintenance command. The new database starts with schema and
   one admin account; it has zero problems and zero student players. The local database,
student records, gear, and assets remain untouched.

## Before deployment

1. Review and preserve the current dirty working tree. Include the untracked
   latest migration, `app/services/player_reset.py`, avatar assets, and other
   code/assets needed by the app. The cloud build sees committed files only.
2. Run direct-script Classic, Boss Rush, admin, and importer checks. Run a
   local two-player rehearsal on a disposable database.
3. Validate the full migration chain against a disposable PostgreSQL database.
   The current audit has validated a fresh SQLite migration only.
4. Review player passwords and public-login controls before inviting real
   students. The current app has no login rate limiting or self-service
   password reset. Use distinct strong pilot passwords and distribute them
   privately.

## Deploy

1. Push the reviewed deployment branch to the connected Git repository.
2. In Render, create a Blueprint from this repository's `render.yaml`. Review
   its paid web and database resources before confirming creation.
3. Set `INITIAL_ADMIN_USERNAME` and a unique `INITIAL_ADMIN_PASSWORD` of
   at least 12 characters when prompted. Render generates `SECRET_KEY` and
   connects the web service to the database internally.
4. The pre-deploy command applies Alembic migrations and creates the first
   admin exactly once. Later deploys leave that account and password alone.
5. Open the service's `/healthz` endpoint, then log in at `/login`.
6. After the first successful admin login, remove
   `INITIAL_ADMIN_PASSWORD` from the Render environment. The bootstrap
   command skips creation when an admin already exists.

The application starts with no problem content. The admin can create player
accounts, classes, subjects, topics, problems, and problem sets through the
existing UI. There is no public player registration endpoint.

## Build the first test round

1. Admin: create two or more player accounts and a class/group; assign the
   players to the class. Use the new accounts to test simultaneous browsers.
2. Admin: create a Subject and Topic, then a few text-input and multiple
   choice Problems. The New Problem form leads to the full content editor.
3. Admin: create one Problem Set and add problems. Mark it usable in Classic
   and Boss Rush attack. Create a separate recovery set for Boss Rush and mark
   it usable as recovery.
4. Admin: create a Classic session, select the class and set, let players join,
   then start and end a round. Exercise Mine, Treasure, Steal, and the store.
5. Admin: create a Boss Rush session with attack and recovery sets. Have both
   players join; test correct/wrong answers, recovery, an ability, round
   transition, boss defeat, and reward finalization.
6. Check History/Analytics and player progress. Restart the web service only
   between rounds until live state is persisted.

The current editor supports stored text, multiple choice, and graph/image body
blocks. It does not provide a general image-upload storage service. For the
first online pilot, use text and multiple choice content; add uploaded media
storage as a separate task.

## Current limits and next hardening pass

- A service restart or deploy during an active Classic round can discard
  process-local pending state. More than one Gunicorn worker or web instance
  would also split that state. Keep `--workers 1` and `numInstances: 1`.
- Postgres migration and live cloud Socket.IO behavior require verification
  before inviting players; the local SQLite rehearsal does not prove them.
- Public login needs rate limiting, account recovery, and a student-data
  privacy review before broad internet use.
- If you add a custom domain, set `GAME_PUBLIC_ORIGINS` to its HTTPS origin
  (or a comma-separated list of origins). Render's assigned HTTPS origin is
  allowed automatically.
- A future multi-instance release needs persisted live state and a shared
  Socket.IO message queue. Team and Expedition remain outside this pilot.
- Clean unused code only after an inventory and behavior tests. Preserve all
  working routes, game mechanics, admin tools, and migration history.

Render references:
[Flask deployment](https://render.com/docs/deploy-flask),
[WebSockets](https://render.com/docs/websocket),
[Blueprints](https://render.com/docs/blueprint-spec),
[Postgres](https://render.com/docs/postgresql),
[Flask-SocketIO deployment](https://flask-socketio.readthedocs.io/en/latest/deployment.html).
