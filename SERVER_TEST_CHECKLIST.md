# Game v2: first Linux server test

This package starts three services: `caddy` → one `web` Gunicorn worker →
`postgres`. The first database is empty except schema and the initial admin.
Use a dedicated test server/project directory. Run commands below inside
`math-game-online/`; prefix `docker` with `sudo` if your account needs it.

## 1. Prerequisites and upload

```bash
docker --version
docker compose version
unzip math-game-online-test-v2.zip
cd math-game-online
cp .env.example .env
chmod 600 .env
```

The ZIP can be uploaded with your preferred secure file transfer tool. Keep
`.env` only on the server. If this Compose project name was used previously,
inspect `docker volume ls` before launching: a previous `postgres_data` volume
would mean the database is not fresh. Do not delete an existing volume without
first identifying and backing up its contents.

## 2. Configure `.env`

Generate separate secrets and edit the seven production fields near the end
of `.env` (uncomment them and replace every placeholder):

```bash
openssl rand -hex 32   # POSTGRES_PASSWORD: URL-safe hexadecimal
openssl rand -hex 32   # SECRET_KEY: use a different value
nano .env
```

Set `GAME_DOMAIN`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`SECRET_KEY`, `INITIAL_ADMIN_USERNAME`, and `INITIAL_ADMIN_PASSWORD`. Use a
new admin name and password (at least 12 characters); never use the local
`admin/admin123` credentials. Keep the bottom `GAME_ENV`, `DATABASE_URL`, and
`GAME_PUBLIC_ORIGINS` examples commented: Compose sets them for `web` from
your values. The PostgreSQL password must be URL-safe because Compose builds
`DATABASE_URL` from it. Confirm configuration without printing secrets:

```bash
docker compose config --quiet
```

### Safe test before DNS is ready

For a **server-only** initial check, set `GAME_DOMAIN=localhost` in `.env`.
Caddy then uses its local certificate authority. On the server, run
`curl -kfsS https://localhost/healthz` and `curl -kI https://localhost/login`.
The `-k` flag is only for this local certificate check; do not use this setup
to send real credentials over an unverified remote connection. When DNS is
ready, change `GAME_DOMAIN` to the public hostname, point its A record to the
server's public IPv4 address, allow TCP 80/443, and run
`docker compose up -d` again. Caddy then obtains its public HTTPS certificate.
Only begin remote browser/player tests after `curl -fsS
https://YOUR_HOSTNAME/healthz` succeeds **without** `-k`. Caddy's local-IP and
public-domain certificate behavior is documented in its
[Caddyfile address guide](https://caddyserver.com/docs/caddyfile/concepts).

## 3. Launch and verify the fresh database

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=200
docker volume ls
docker inspect "$(docker compose ps -q postgres)" --format '{{json .Mounts}}'
docker inspect "$(docker compose ps -q web)" --format '{{json .Mounts}}'
docker compose exec -T web python -m flask --app run:app db current
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version;"'
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT username, is_admin FROM player;"'
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM player;"'
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM subject;"'
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM topic;"'
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM problem;"'
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM game_session;"'
docker compose top web
```

Expected: `postgres` and `web` are healthy; Caddy runs; Alembic reports
`b7c8d9e0f1a2`; `player` count is 1 with the configured admin name and
`is_admin=true`; `subject`, `topic`, `problem`, and `game_session` counts are
0; the inspect output shows a named PostgreSQL data volume mounted at
`/var/lib/postgresql/data`, and a named media volume mounted in web at
`/data/media`; `docker compose top web` shows one Gunicorn master
and **one worker**. The startup log should show migrations and one admin
creation. Inspect all logs for errors and unexpected warnings. A migration or
bootstrap failure should stop `web`, not silently continue.

Run `docker compose restart web` once and inspect its logs: bootstrap should
say an administrator already exists and should not create another account.
The `player` count must remain 1. After successfully logging in, remove the
`INITIAL_ADMIN_PASSWORD` line from `.env` and recreate web with
`docker compose up -d --no-deps --force-recreate web` so the secret is no longer
in its container environment.

## 4. Web and account checks

With `GAME_DOMAIN=localhost`, use the server-only `curl -k` checks above.
With a public hostname and trusted HTTPS certificate:

```bash
curl -fsS https://YOUR_HOSTNAME/healthz
curl -fsSI https://YOUR_HOSTNAME/login
```

Expected health response: `{"status":"ok"}`. The login page should load.
Sign in with the new admin; try `admin/admin123` and confirm it fails. Verify
in `docker compose exec -T web python -c 'from config import Config; print(Config.GAME_ENV)'`
that the mode is `production`. A player must receive 403 or a login redirect
at admin URLs. Repeated failed logins should eventually be rate limited.

## 5. Create content and test multiplayer

In the admin UI, create two test players and a class, assign both players,
create a Subject, Topic, at least two Problems with known answers, and a
Problem Set enabled for Classic. Create a Classic session for the class.
Record the usernames and expected answers privately.

At **Content Import**, upload a small Questionbank v4 ZIP and select Validate.
Confirm counts, representative errors, and the proposed new/update/skip actions
before confirming Import. Revalidate the same ZIP: unchanged source IDs must
show as skipped. Confirm an imported image and any image-only MCQ options render
in the normal problem preview. Create an uploaded face and gear image at
**Assets**; verify the face in a player avatar and the gear layer on the
existing catalog item. An in-use image must show references and require explicit
confirmation for deletion. Keep the source ZIP outside the application archive.

Use three independent browsers/profiles: admin, player 1, and player 2.
Preferably put one player on a different Internet/mobile connection. Confirm
all three connect at the public HTTPS origin and browser network tools show
Socket.IO polling/WebSocket activity (secure `wss://` after upgrade). Check:

- both players join the same session; admin sees them live;
- each submits a known correct answer, and both leaderboards update;
- admin live supervision updates after each solve;
- Mine, Treasure, Steal, store, round end, and next round work;
- refreshing at action choice, Treasure, and Steal restores pending UI;
- briefly disconnect one player and reconnect while the other continues;
- history/analytics show completed results.

Do not restart web during this live round merely for a persistence check.
Classic's pending actions/timers/locks are process-local and can be lost on
web restart; this is a known limitation of the one-process release.

## 6. Persistence and log checks

After ending the test round, record the player/problem/session counts from
PostgreSQL and repeat them after each step below. Also verify admin login,
created records, and a sample `/media/<id>` image in the UI. Both named
`postgres_data` and `media_data` volumes must survive:

```bash
docker compose restart web
docker compose down
docker compose up -d
docker compose up -d --build
docker compose ps
docker compose logs --tail=200 web postgres caddy
```

Never use `docker compose down -v` for this test. Confirm there is still only
one Gunicorn worker with `docker compose top web`. Investigate all startup,
database, proxy, or Socket.IO errors/warnings in logs.

## 7. Backup and restore

Create a manual backup before any major update; save a copy off the server:

```bash
mkdir -p backups && chmod 700 backups
umask 077
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/game-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T web python -c 'import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz"); t.add("/data/media",arcname="media"); t.close()' > "backups/media-$(date +%Y%m%d-%H%M%S).tar.gz"
ls -lh backups/*.dump backups/*.tar.gz
```

From your own computer, copy a specific backup (replace user, host, and name):

```bash
scp friend@SERVER:~/math-game-online/backups/game-YYYYMMDD-HHMMSS.dump .
```

Restore only when you intend to **replace** the current test database. Make
another backup first, stop web, substitute the actual backup filename, then:

```bash
docker compose stop web
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < backups/game-YYYYMMDD-HHMMSS.dump
docker compose run --rm --no-deps -T web python -c 'import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode="r|gz"); t.extractall("/data",filter="data"); t.close()' < backups/media-YYYYMMDD-HHMMSS.tar.gz
docker compose up -d web caddy
```

Check restore output and recheck Alembic head, `/healthz`, admin login, and
sample player/problem records and uploaded media. Report the server's Docker/Compose versions,
pass/fail for each section, and relevant log excerpts without secrets.
