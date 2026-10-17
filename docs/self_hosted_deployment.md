# Self-hosted Internet pilot

For the actual deployment alongside the KorePhysics exam site, use [live server operation](korephysics_live.md). The Docker/Caddy setup below remains a standalone-server alternative.

This deploys the existing game to one Ubuntu VPS with Docker Compose: Caddy → one Flask-SocketIO/Gunicorn web process → PostgreSQL. The database starts empty. Admin creates players and problem content in the existing interface. No seed or content import runs at startup. Local Windows development still uses `python run.py` and SQLite.

## Prepare the server

Use an Ubuntu server with a public IP and a domain you control. Create an **A record** such as `game.example.com` pointing to the server's public IPv4 address. Add an AAAA record only if the server has working public IPv6. Allow inbound TCP 22 (preferably restricted to your IP), TCP 80, and TCP 443; UDP 443 is optional for HTTP/3. Do not open 5432 or 8000. If Ubuntu's `ufw` is enabled, allow SSH before enabling it:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
```

Also check the VPS provider's network firewall. Docker's published ports can bypass some host firewall rules; the Compose file publishes only Caddy's 80/443. [Docker's Ubuntu install instructions](https://docs.docker.com/engine/install/ubuntu/) are the current source for installing Docker Engine and the Compose plugin. On a fresh supported Ubuntu release:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker compose version
```

Use `sudo docker compose` in the commands below unless you have deliberately configured Docker access for your user. Docker group access is effectively root access.

## First deployment

First preserve and review the local working tree, including untracked migration and avatar files, then commit and push the release you want to deploy. A server clone contains only committed files. On the server:

```bash
git clone https://github.com/koroleff210/Math-game-V2.git game-v2
cd game-v2
cp .env.example .env
chmod 600 .env
openssl rand -hex 32   # use this output for POSTGRES_PASSWORD
openssl rand -hex 32   # use different output for SECRET_KEY
nano .env
```

Uncomment and set `GAME_DOMAIN`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `SECRET_KEY`, `INITIAL_ADMIN_USERNAME`, and `INITIAL_ADMIN_PASSWORD`. Use a new admin password of at least 12 characters. Keep the PostgreSQL password URL-safe (hexadecimal from the command above), because Compose places it in `DATABASE_URL`. `.env` stays on the server and is ignored by Git. Compose sets `GAME_ENV=production`, `DATABASE_URL`, and `GAME_PUBLIC_ORIGINS=https://$GAME_DOMAIN` for web.

After DNS resolves to this server:

```bash
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 web caddy
curl -fsS https://game.example.com/healthz
```

Replace the example hostname in `curl`. `/healthz` should return `{"status":"ok"}`. Open `https://game.example.com/login` and sign in with the new admin credentials. The web entrypoint waits for PostgreSQL, runs `flask db upgrade`, then `flask create-admin` before Gunicorn starts. An existing admin is left unchanged on future starts. If migrations or bootstrap fail, web does not start; inspect `sudo docker compose logs web`.

After successful first login, remove the `INITIAL_ADMIN_PASSWORD=...` line from `.env`, then recreate just web to remove that secret from its container environment:

```bash
nano .env
sudo docker compose up -d --no-deps --force-recreate web
```

The bootstrap command skips password requirements when an admin already exists. Keep the admin password in your password manager. Admin creates fresh player accounts in the UI; there is no public registration. Use **Content Import** to upload a Questionbank v4 ZIP, validate it, review the counts and errors, then explicitly confirm import. The ZIP must contain `problems/*.json` and `assets/*` under its root or one enclosing folder. Supported v4 records are approved four-option MCQs; structured questions are reported as unsupported and excluded. You can also create problems manually. Assign problems to a Problem Set usable in Classic/Boss Rush before testing a round. **Assets** manages persistent avatar faces and images attached to existing Gear Catalog items.

## Operations

Run these in the project directory. Make a matching **database and media** backup before upgrades or restore operations. Both files are written on the host and must be stored securely off the VPS too. Pause uploads/imports while taking the pair.

```bash
mkdir -p backups && chmod 700 backups
sudo docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/game-$(date +%Y%m%d-%H%M%S).dump"
sudo docker compose exec -T web python -c 'import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz"); t.add("/data/media",arcname="media"); t.close()' > "backups/media-$(date +%Y%m%d-%H%M%S).tar.gz"
chmod 600 backups/*.dump backups/*.tar.gz
sudo docker volume ls
sudo docker compose restart web
sudo docker compose restart
```

To restore a matching backup pair **into this existing pilot**, first make another pair, then stop web so it cannot write during restore. This overwrites database contents and restores the matching uploaded images. Replace both filenames:

```bash
sudo docker compose stop web
sudo docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < backups/game-YYYYMMDD-HHMMSS.dump
sudo docker compose run --rm --no-deps -T web python -c 'import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode="r|gz"); t.extractall("/data",filter="data"); t.close()' < backups/media-YYYYMMDD-HHMMSS.tar.gz
sudo docker compose up -d web caddy
```

Check restore output for errors and verify `/healthz`, admin login, sample records, and a sample uploaded image. `postgres_data` and `media_data` are named volumes; recreating web does not erase them. **Never run `docker compose down -v`** unless you intend to remove stored data. Caddy's certificate state lives in `caddy_data`.

For an ordinary code update, back up first, then:

```bash
git pull --ff-only
sudo docker compose build web
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 web caddy
curl -fsS https://game.example.com/healthz
```

The web entrypoint applies pending Alembic migrations at every start. Review migration effects before updating: restoring an older code version does not automatically reverse a database migration.

## Verification and limits

Run the [server test checklist](../SERVER_TEST_CHECKLIST.md) with one admin browser and two separate player browsers, preferably with players on different networks. Confirm the browser uses `wss://` (or successful Socket.IO polling followed by WebSocket upgrade) at the public HTTPS origin. Test Classic, Boss Rush, reconnect, and admin authorization. The single web process is intentional: Classic pending actions, timers, and locks are process-local. A web restart during an active round can lose that pending state, although saved database history remains. Schedule updates between rounds. Do not raise Gunicorn workers above one without a separate persistent runtime-state design and shared Socket.IO backend.

The import and media features have focused local tests, but this updated release has not yet been exercised against a real Ubuntu VPS, public DNS name, or remote browser WebSocket session. Complete those checks before inviting students. Team and Expedition remain outside this server pilot.
