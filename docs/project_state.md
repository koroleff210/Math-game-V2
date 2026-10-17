# Project State

_Audited 2026-10-01 against the current working tree and a read-only inspection of the local database. Code is authoritative. Historical March plans and checkpoints are retained for reference._

## Product map

| Area | Current state | Main evidence / limit |
|---|---|---|
| Classic individual mode | Implemented: problem sets, answer flow, Mine, Treasure, Steal, store, rounds, leaderboard, reconnect UI | `app/modes/classic/`; some pending state and locks are process-local |
| Boss Rush | Implemented beyond its original setup shell: attacks, recovery, boss HP and abilities, multiple rounds, reward finalization | `app/modes/boss_rush/`; 26 lifecycle checks passed |
| Team mode | Not implemented | Only `app/modes/team/__init__.py` and `ProblemSet.usable_in_team`; no registered route, handler, or team model |
| Expedition | Separate prototype, not integrated | Sibling `../expedition_mode/` uses its own Flask app, JSON data, teacher and student pages |
| Problem system | Admin structured editor, text and multiple choice answers, rich text/image/graph blocks, problem set builder and filters | No student graph answer mechanic or general algorithmic problem generator |
| Admin and persistence | Players/classes, subjects/topics, problem bank, sets, gear, diamonds, analytics/history, Classic and Boss Rush supervision | `app/routes/admin.py`, mode routes, models |
| Player Hub | Avatar and gear preparation, Blacksmith, progress and session entry | `app/routes/player.py`, Hub template |

The main app's `app/core/problem_engine.py` selects a random stored problem. The separate IB Physics importer samples and imports existing bank questions. Neither creates new math/physics questions algorithmically. Expedition has separate expression and answer-checking services.

## Local data

Read-only inspection of `instance/math_game.db`:

- Alembic current/head: `a6b7c8d9e0f1`.
- 27 players, 1 subject, 24 topics, 1,708 problems, 2 problem sets.
- 1,570 imported multiple choice problems from `ib_physics_question_system`; 138 curated text-input definitions.
- 3 Classic sessions, all finished, and 4 saved rounds. No saved Boss Rush session here.
- The imported MCQ source path is `C:\Users\korol\OneDrive\Desktop\IB Physics Question System\data\complete_questionbank\questions.json`. This source JSON bank is distinct from the live game SQLite database.

## Questionbank v4

Located at `C:\Users\korol\OneDrive\Desktop\IB Physics Question System\data\questionbank_v4\`. Its active source is 2,966 per-question JSON records in `problems/` with content-addressed assets in `assets/`; `build/questionbank.sqlite` is a queryable export. The v4 teacher app uses this bank. The old Game v2 importer expects one `complete_questionbank/questions.json` payload and its old image layout, so it cannot directly import v4.

V4 uses `phys_...` IDs, while Game v2 stores old canonical IDs. Direct ID overlap is zero. The v4 `migration/migration_index.jsonl` crosswalk contains every one of Game v2's 1,570 imported IDs, mapping them to 1,566 distinct v4 IDs. Some old records merge into one v4 record. The source project's v4 migration note says 2,961 records have full approval; five are quarantined or need review. V4 includes Paper 1A, Paper 1B, and Paper 2; current game import covers multiple choice only. Map content, answers, image assets, topic/classification, difficulty, and saved history deliberately before replacing records.

The existing content-reset helper reports saved runtime, history, and analytics dependencies. Do not use a blanket reset against this database. Back up the SQLite file first, then plan a staged, reversible import that preserves student accounts, progress, and historical references.

## Verification and current test limitation

- `flask db heads` and `flask db current`: both `a6b7c8d9e0f1`.
- Direct script `tests/test_boss_rush_lifecycle.py`: 26/26 checks passed.
- Direct script `tests/test_admin_problems_board_filters.py`: 10/10 checks passed.
- Direct script `tests/test_ib_physics_importer.py`: 44/44 checks passed, with SQLAlchemy identity-map warnings.
- Running script-style tests via `pytest` bypasses their `__main__` setup; five collected cases failed with `no such table: player`. Convert setup to fixtures or run those files directly. This does not mean the live database lacks its tables.

These focused checks do not establish a clean full suite or a live multiplayer rehearsal. The working tree also contains substantial pre-existing uncommitted code, assets, tests, and scripts. Review and checkpoint them before release work.

## Remaining work, in dependency order

1. **Local stabilization:** check in or otherwise preserve the current work; run direct-script regression checks and manual two-player Classic/Boss Rush flows; fix observed issues.
2. **V4 migration:** compare schemas and content; use the ID crosswalk; decide how merges and retired questions affect saved results; validate assets and answer types; build a read-only migration report; back up data; then import and verify.
3. **Release scope:** implement Team and integrate Expedition if they are required at first release, or explicitly defer them. Add verification for included modes.
4. **Deployment hardening:** the self-hosted Compose/Caddy/PostgreSQL configuration now guards production secrets, applies migrations and first-admin bootstrap, provides `/healthz`, and limits login failures. Complete real-server verification and review persistence for authored media before public use.
5. **Online multiplayer:** the first pilot deliberately uses one web process for process-local Classic state and locks. Exercise auth, concurrent answers, reconnects, and data retention with real clients. A later multi-worker release would need persistent runtime state and a shared Socket.IO backend.

Game v2 is a functional local classroom prototype with an unverified self-hosted deployment path. See `docs/self_hosted_deployment.md` for deployment and `docs/manual_test_guide.md` for gameplay checks.

## Online pilot preparation added after this audit

The repository includes an earlier Render pilot Blueprint and a current
self-hosted Docker Compose/Caddy/PostgreSQL setup, production configuration
checks, a fresh-admin CLI command, a database health endpoint, and production
login throttling. A disposable SQLite database passed
fresh migration, first-admin creation, empty-library checks, player creation,
and admin page rendering. These changes have not been deployed. PostgreSQL
migrations, HTTPS and multi-client Socket.IO behavior still need live verification.
