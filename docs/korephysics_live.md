# Live KorePhysics game

Deployed and verified on 17 October 2026.

**Data state immediately after the user-requested V4 fresh start (17 October 2026):**
the online game had zero student profiles, classes, problems, sets, sessions,
progress records and history/analytics. The existing admin, eight gear definitions,
avatar assets, layouts and shared test-site accounts were preserved. V4 questions
were not yet imported at that point. Four Topic A test sets were subsequently added
on 18 October 2026; see [Topic A test content](topic-a-test-content-20261018.md). Counts below
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

## Live updates follow-up — 19 October 2026

Classic enrollment now notifies watchers immediately after commit; the lobby no
longer renders the complete question bank. Store pushes use the existing live
connection with an admin-only acknowledgment, and reconnecting admin watchers
recover the current roster and balances. WebSocket-first setup retains a polling
fallback. See [measurements, validation and remaining network latency](realtime-release-20261019.md).
The final eight-file release preserved all 47 table counts and had no unfinished
sessions at restart. Source rollback and verification are at
`/var/backups/korephysics-game/realtime-20261019-052518/`.

## Workshop, Hub and measurement follow-up — 18 October 2026

Gear Studio now includes an eraser with pixel Undo/Redo and zoom, plus all 35
bundled/catalog gear references and the nine male/six female faces. Source-frame
metadata preserves erased edges when artwork is saved and reopened. Hub effect
and upgrade counters use the existing resource icons; unselected Treasure reveal
rewards are shaded. Read [release and measurement findings](workshop-hub-release-20261018.md).

All 14 deployed file hashes matched. Fresh game/exam backups and rollback copies
are at `/var/backups/korephysics-game/workshop-hub-20261018-153621/`. There were
no unfinished sessions at restart. Database counts, uploaded media, catalog prices,
ownership and player loadouts were preserved; no migration or shop seeding ran.

## Classic fullscreen refinement — 18 October 2026

The icon counters, inline shield inventory, readable admin-configured round
instructions, bounded leaderboard rows and translucent fullscreen layout are
deployed. The persistent frame now fills the screen with a compact fullscreen
control. Lobby/overlay asset warmup and 35 additional WebP derivatives reduce
first-use image work; Plotly is loaded only when a graph question is shown.
See [release findings and test checklist](classic-ui-release-20261018.md).

The user authorized restarting active session #4. Fresh game/examination backups
were taken, all 49 deployed file hashes matched and table counts were preserved.
Final rollback evidence is at
`/var/backups/korephysics-game/classic-design-20261018-095725/`.
Authenticated public page checks, polling handshake and TLS WebSocket upgrade
passed. No migration or rule/economy change was required.

## Player interface release — 17 October 2026

The image-loading and Blacksmith improvements are deployed. The follow-up
refinement keeps the page layout visible while assets load, with a small,
nonblocking status badge only after 400 ms. The main scene background and complete
avatar are revealed after decoding. Avatar changes
keep the current character visible until the replacement layers are ready, with
background preloading for nearby choices. Failed character images offer a retry;
failed scene backgrounds fall back to a flat background.

Content-addressed WebP display copies preserve the original PNG assets and avatar
canvas dimensions. The Hub background is now 223 KB instead of 3.17 MB, and the
Blacksmith background is 172 KB instead of 2.35 MB. Display copies have immutable
browser caching. Rebuild them with `tools/build_ui_images.py` after asset changes.

The Blacksmith has one translucent owned-gear list with item icons and effects.
Equipped items have green highlighting and an indicator; upgrades remain in the
shop tab. The inventory occupies at most the upper half of the screen, scrolls
within that space, and collapses to its heading without an empty shaded area.
It starts collapsed on mobile.

One fullscreen control stays at the top right throughout the player area,
including Classic, Boss Rush and student learning reports. A persistent container
holds the player pages in a same-origin frame, so links, POST redirects and live
lobby-to-game redirects keep the fullscreen document intact. Page scripts and
Socket.IO connections still initialize normally for each destination. The address
bar and title follow the current page, including the Hub's AJAX selection URLs;
browser Back/Forward and refresh retain the current destination. Logout and
authentication redirects leave the container.

The page requests fullscreen on the first interaction by default. Browsers require
user activation for initial entry, so focus alone cannot force entry. Exit
fullscreen or Esc disables automatic entry for that browser-tab session until the
player enables it again. HTML responses vary by `Sec-Fetch-Dest` and use private,
no-store caching to keep container and frame responses separate. Frame requests
continue through the existing authentication and game-access checks.

Validation covered 52 focused checks against PostgreSQL, local avatar and asset
checks, Classic/Boss Rush regressions, and browser checks with cold caches,
delayed/failed image requests, avatar changes, fullscreen and mobile layouts.
Authenticated public Hub/Blacksmith checks passed. All 189 deployed file hashes
match the release manifest, and counts across all 47 existing tables were
unchanged. This release required no database migration or data reset.

Fresh game and examination backups were taken before deployment. The source
rollback snapshot, manifest and before/after counts are in
`/var/backups/korephysics-game/ui-polish-20261017-174848/`. Local release evidence
is under
`C:/Users/korol/AppData/Local/KorePhysics/game-deployment/ui-polish-20261017-174848/`.

The seven-file follow-up refinement is backed up separately at
`/var/backups/korephysics-game/ui-refinement-20261017-203247/`, with local evidence
under the matching `game-deployment/ui-refinement-20261017-203247/` directory.
Six focused local checks and browser checks cover delayed loading over a visible
layout, atomic avatar changes, equipped highlighting, a long scrollable inventory,
collapse, mobile/short desktop layouts, fullscreen restoration and explicit exit.

The persistent fullscreen release has a separate source rollback snapshot at
`/var/backups/korephysics-game/fullscreen-navigation-20261017-204624/` and local
evidence under the matching `game-deployment/fullscreen-navigation-20261017-204624/`
directory. Validation: eight focused UI/container checks, 35 multi-round checks,
nine Boss Rush UI checks, and browser checks of links, purchase redirects,
Back/Forward, refresh, mobile layout, initial fullscreen entry inside the frame,
logout, and a real Socket.IO lobby-to-game redirect. The older Boss Rush theme
checks were updated to recognize the optimized display URLs already in use.
Authenticated public checks cover both container and frame responses for the Hub,
Blacksmith and progress pages. No migration or data reset was required.

## Session reporting release — 17 October 2026

The first learning-report release is deployed at
https://game.korephysics.com/admin/analytics/sessions. See
[the test-run guide](learning-reports.md) for the teacher and student workflow.

It adds a complete-session matrix, student/round/context filters, question and
answer-sequence review, immutable question/image snapshots, alias-based AI ZIP
exports, teacher notes/feedback, publication/withdrawal, progress exclusions and
student report/progress views. Boss Rush attack/recovery summary mixing and the
PostgreSQL class subject-filter query were repaired. Questions in unfinished
rounds are protected from content edits/import replacement.

Migration head is now `e0f1a2b3c4d5`. Existing records were preserved; no sample
students, questions or sessions were added to production. New student learning
results remain private until the teacher finishes and publishes the session.
Historical records without content snapshots are explicitly labeled unavailable.

Validation: 181 focused local checks, 172 checks against the dedicated PostgreSQL
QA database, a record-preserving PostgreSQL migration rehearsal, and desktop/mobile
browser checks of the new teacher/student reports. Authenticated public checks
passed for Session Reports, round/class analytics, content import, Classic and
Boss Rush. This does not substitute for a real class rehearsal. A full Alembic
autogenerate check still detects pre-existing index/type differences in older
Boss Rush and steal models; the new reporting migration itself was verified.

Fresh game and examination backups were taken before deployment. The source
rollback snapshot, release checksums and before/after table counts are in
`/var/backups/korephysics-game/learning-release-20261017-170047/`. Local release
evidence is under
`C:/Users/korol/AppData/Local/KorePhysics/game-deployment/learning-20261017-170047/`.
Frozen report media is stored beneath the existing persistent media directory
in `learning-assets/` and is covered by game backups.

Automatic AI calls, plan import, per-student assignment tracking and delayed-check
automation remain subsequent phases. The current release exports evidence for
teacher-led AI analysis and publication of feedback.

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


Economy redesign deployed 19 October 2026: see docs/economy-release-20261019.md. Source recovery: /var/backups/korephysics-game/economy-20261019181514/. Local play and both local schemas were upgraded; historical balances and gear were preserved.


Boss Rush shared-bank rewards deployed 19 October 2026. See docs/boss-bank-release-20261019.md. Main recovery: /var/backups/korephysics-game/boss-bank-20261019202940/. Compact UI recovery: /var/backups/korephysics-game/boss-bank-ui-20261019-203355/. Both local databases upgraded; historical balances and rounds preserved.
