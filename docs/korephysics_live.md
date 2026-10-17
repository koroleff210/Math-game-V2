# Live KorePhysics game

Deployed and verified on 17 October 2026.

**Current data state after the user-requested V4 fresh start (17 October 2026):**
the online game has zero student profiles, classes, problems, sets, sessions,
progress records and history/analytics. The existing admin, eight gear definitions,
avatar assets, layouts and shared test-site accounts were preserved. V4 questions
have not yet been imported; future sets will be selected from V4. Counts below
describing the original migration are historical, before this reset.

The pre-reset snapshot `game-20261017-161805.zip` was restored into a separate
database and verified for equality across all 46 tables / 12,728 rows. A private
local copy and reset report are in
`C:/Users/korol/AppData/Local/KorePhysics/game-deployment/v4-reset-20261017/`.
The server report is
`/var/backups/korephysics-game/v4-fresh-start-20261017-161804.json`.
The reset preserved admin/gear/media/schema records exactly; all 14 checked public
admin/health pages returned HTTP 200 afterward. The old local development database
and the original V4 source bank were not changed by the online reset.

Game: https://game.korephysics.com/ · Admin: https://game.korephysics.com/admin/

The game runs on the rented OVH server independently of this laptop. The existing
examination site remains at https://paper1atest.korephysics.com/.

## Signing in and managing students

The game admin username is `admin`. The demonstration admin password was replaced
with a random password, saved privately on this laptop in
`C:/Users/korol/AppData/Local/KorePhysics/game-deployment/20261017-125227/admin-access.txt`.
Student accounts use shared email/password credentials. Admin credentials remain
specific to each application.

- In **Players → Create Player**, enter a username and the student's email. Leave
  Password blank. The email is required for new online student accounts.
- A new student enters that email and chooses a password at first sign-in. That
  password works on both sites. An existing exam student uses their existing password.
- Existing exam students can enter the game without another account being created
  manually; their game profile is created when they successfully sign in.
- The 26 previous game students and their game progress were removed by the V4
  fresh start. Their prior data is recoverable from the private pre-reset backup.
  Shared exam identities were not deleted. An existing exam student signing in
  again receives a new game profile with fresh progress.
- **Reset Password** lets the student choose a new password. For a linked student,
  this changes sign-in on both sites and invalidates old sessions. Progress stays.
  The separate **Reset Player** action still clears character/gear/upgrades and
  resets the Diamond balance, as its confirmation explains.
- Classes, class membership, sets and game supervision remain in the existing game
  admin interface. Classes are managed separately on the two sites.
- Deleting an unused game account leaves its shared exam identity intact. Accounts
  referenced by saved game or audit records cannot be deleted.

The first-password flow follows the examination system's teacher-provisioned
account model; it does not add email verification or public registration.

## What was preserved and repaired

The import verified all 12,727 application rows in 45 tables, including 27 accounts,
1,708 questions, two sets, one class, three sessions and four saved rounds. All
1,039 static files matched their SHA-256 checksums. The existing custom
`overlay_layouts.json` was copied too. A final comparison found only the intended
admin password/version change in existing records.

The old SQLite database contained 205 dangling rows referring to games or a student
that had already been deleted. Their exact contents are preserved in
`/var/backups/korephysics-game/migration-20261017/legacy-orphans.json` and in the
private local deployment directory. Only the migration copy was cleaned; the
original snapshots remain. These detached rows are excluded from live game tables.

Repairs cover first-password setup, shared login/password reset, safe deletion of
unused students, protection of the last admin account, hidden Hub notifications,
Hub controls clipped in short desktop windows, PostgreSQL Boolean migration
defaults, and persistent writable layout settings. Existing Classic, Boss Rush,
gear, content import and authoring code remains in use. Team mode and the separate
Expedition prototype are still outside this application's implemented modes.

## Server operation

Nginx terminates HTTPS and proxies the game to loopback port 5060, including
WebSocket upgrades. PostgreSQL and the identity adapter are private. The identity
adapter runs separately on loopback port 5061 and uses the exam application's own
student/password models; the exam app source and interface were not modified.

| Item | Location |
|---|---|
| Source | `/opt/korephysics-game/app` |
| Runtime | `/opt/korephysics-game/venv` |
| PostgreSQL database / role | `korephysics_game` |
| Game configuration | `/etc/korephysics-game/app.env` |
| Private identity configuration | `/etc/korephysics-game/identity.env` |
| Persistent instance/layout/media | `/var/lib/korephysics-game` |
| Backups and migration evidence | `/var/backups/korephysics-game` |

Use the existing pinned SSH key `C:/Users/korol/.ssh/korephysics_ovh_ed25519` and
host `ubuntu@158.69.213.70`. Never automatically accept a changed host key.

```bash
systemctl is-active korephysics korephysics-game korephysics-identity nginx
sudo journalctl -u korephysics-game -n 80 --no-pager
curl -fsS https://game.korephysics.com/healthz
sudo systemctl start korephysics-game-backup.service
sudo systemctl list-timers korephysics-game-backup.timer
```

Game and identity services start at boot and restart after a crash. Keep exactly
one Gunicorn worker: Classic pending actions and locks are process-local. Schedule
code changes/restarts between rounds. A process restart can lose pending actions
in an active round, while committed history remains stored.

## Backups and updates

The game backup timer runs around 02:20 and 14:20 UTC. It stores a PostgreSQL custom
dump, uploaded media, layout settings and private configuration. Retention is up
to 60 snapshots / 5 GiB, retaining the newest two. Snapshots contain secrets and
student data; keep them private. The examination system keeps its existing
separate backup schedule, including the shared credential database. Recover both
applications deliberately so linked student IDs and credentials remain consistent.

A game snapshot was restored into a separate PostgreSQL database. All 46 tables
(including Alembic's version table), 12,728 rows and the layout file matched the live
database. A verified backup was also downloaded to this laptop's private deployment
directory. The existing Windows scheduled exam-backup task does not automatically
download game backups.

For updates, take current game and exam backups, upload reviewed source into a
staging directory, install changed dependencies if needed, apply migrations with
the private game environment, then replace source and restart only the game.
Validate health, login, both modes and WebSocket connections. Do not rerun
`prepare_server.py` or `migrate_existing.py` against an established installation.
Do not replace the live database with the older local development copy.

For recovery, stop the game, preserve a new snapshot, restore the selected dump
into a separately prepared database, verify it and its matching media/layout,
then switch configuration and start the game. Restore environment files only
when required. `deploy/verify_backup_restore.py` rehearses restoration against a
fixed disposable database; `deploy/verify_postgres.py` uses only the dedicated QA
database. The game certificate renews through the existing Certbot timer and Nginx
reload hook.

## Verification and limits

- Shared first-password setup was exercised through both public sites with a
  disposable student; passwords worked in both directions and reset invalidated
  the game session. The disposable accounts and exam sessions were removed.
- Two student logins established public TLS WebSocket connections and received Hub
  acknowledgements. The live Hub's avatar layers/background were checked visually.
- All 15 admin navigation pages returned HTTP 200.
- The new login, import/assets and token UI tests passed locally and on Ubuntu.
  PostgreSQL regressions passed for Classic live supervision, Boss Rush lifecycle,
  multiple rounds, set builder and gear updates. Existing focused reset, Hub,
  character, treasure/steal and other regression scripts also passed.
- Backups were checksum-checked, extracted and restored with full row equality.
- No full class rehearsal on school Wi-Fi or physical Safari/iOS devices was done.
  Browser checks covered the Hub's normal, phone and short-desktop layouts; this
  is a targeted repair pass, not a claim that every visual combination is flawless.

The laptop's development database was backed up and schema-upgraded in place;
its records and credentials remain local and separate from online writes.
