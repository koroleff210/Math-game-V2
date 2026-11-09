# Local play with online content

Double-click **Launch Admin Login.bat**. This starts the current local source
with a dedicated database in `instance/local-play/math_game.db` and opens the
login page (normally http://127.0.0.1:5001/login).

Initial local accounts:

- Teacher: `local-admin` / `local-admin123`
- Player: `local-test` / `local-test123`

Create additional local players in the admin area if needed. Choose any imported
set when starting a Classic or Boss Rush session. Progress, diamonds, equipment
and learning reports persist in this database across sessions and restarts.
Online accounts and results are separate. The earlier `instance/math_game.db`
is preserved and is still used by a plain `python run.py` command.

After adding sets online, finish local sessions, run **Stop Local Game.bat**, and
double-click **Refresh Local Content.bat**. This reads online questions, sets,
gear, uploaded artwork and overlay layouts over pinned-key SSH. It updates the
dedicated local content while retaining local players and progress. It never
writes to the online game. Each refresh backs up the local database and layouts
under `instance/local-play/backups/`. Old media is retained for saved reports.

Author question sets online: local content IDs are reserved for online records,
and a refresh replaces their content and set membership. Removed online root
records are retained locally so historical results remain usable. Content
refresh requires matching local/server source and migration versions; it stops
with a list of differences when a code update needs review. Code is maintained
in this repository and deployed separately, rather than silently overwritten.

This is local testing with a manual content refresh, not automatic progress
sharing. Reopening the launcher reuses the saved local database. The sync report
records when content was last refreshed and how many source files matched.
