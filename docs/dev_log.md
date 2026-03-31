# Development Log

_Append-only. New entries added at the bottom of each checkpoint._

_Historical/progress reference only. For the current repo state, use `docs/project_state.md` and `docs/system_architecture.md`._

---

## Entry 001 — 2026-03-08 — Phases 1 & 2 Complete

### Architecture Decisions

**AD-01: Factory pattern with `flask_app` rename**  
The Flask app instance inside `create_app()` is named `flask_app`, not `app`. Reason: `import app.models` is executed inside the factory to ensure Alembic can detect all models. If the local variable were named `app`, Python would rebind it to the `app` package, causing `AttributeError: module 'app' has no attribute 'register_blueprint'`. This naming convention must be preserved in all future edits to `__init__.py`.

**AD-02: `threading` async mode, not gevent**  
`gevent` is not installed in the `.venv`. `simple-websocket` is used instead. `SOCKETIO_ASYNC_MODE = 'threading'` in config.py. Do not change this without installing gevent first.

**AD-03: Central SocketIO handler registry**  
`app/socketio_handlers/__init__.py` contains `register_all_handlers(socketio)`. All Socket.IO event bindings go through this function. Mode-specific events will be registered in `modes/<mode>/events.py` and called from `register_all_handlers`. This prevents event naming conflicts and gives a single place to audit all live events.

**AD-04: `models/__init__.py` re-exports all models**  
Flask-Migrate (Alembic) only detects model classes if they have been imported before the migration command runs. All models are imported in `app/models/__init__.py`. Every new model file must be added here.

**AD-05: Optional form fields use `(field.data or '').strip() or None`**  
WTForms sets empty optional text fields to `None`, not `''`. Calling `.strip()` directly on `None` raises `AttributeError`. The safe pattern for optional fields is: `value = (field.data or '').strip() or None`. Applied to: topic subject/description, problem image_path, problem set description.

**AD-06: CSRFProtect must be initialized to use `csrf_token()` in templates**  
`csrf_token()` is a template global injected by `CSRFProtect`. It is only available if `CSRFProtect` has been initialized via `csrf.init_app(flask_app)`. Without it, templates raise `UndefinedError: 'csrf_token' is undefined`.

**AD-07: SQLAlchemy 2.0 session API**  
Use `db.session.get(Model, pk)` instead of `Model.query.get(pk)`. The `.query` API is deprecated in SQLAlchemy 2.0.

**AD-08: Problem Bank filters deferred to Phase 7**  
Subject/topic filter, keyword search, and sorting for admin problem browser are deferred until after the Core Game Engine (Phase 3). Reason: problem query patterns will be clearer after `problem_engine.py` is built, avoiding duplicate query logic.

### Bug Fixes

**BF-01: `gevent` startup crash**  
Default config had `SOCKETIO_ASYNC_MODE = 'gevent'`. gevent not in venv → immediate crash on `socketio.init_app`. Fixed by changing to `'threading'`.

**BF-02: `flask.exe` blocked by Application Control**  
Windows Application Control policy blocked `flask.exe` from running. Fixed by using `python -m flask` instead of `flask` for all CLI commands.

**BF-03: `None.strip()` on optional form fields (3 locations)**  
Empty optional text fields from WTForms are `None`. Calling `.strip()` raised `AttributeError`. Fixed in: topics route (subject, description), problems route (image_path in both new and edit handlers), problem_sets route (description).

**BF-04: `csrf_token` undefined in login template**  
Template rendered `{{ csrf_token() }}` but `CSRFProtect` was not initialized. Fixed by adding `csrf = CSRFProtect()` to `extensions.py` and `csrf.init_app(flask_app)` to `create_app()` in `__init__.py`.

### Design Tradeoffs

**DT-01: SQLite for development**  
Using SQLite for simplicity during development. No connection pooling concerns at this scale. Can migrate to PostgreSQL later with no code changes (only config URI change).

**DT-02: Monolithic `admin.py` for Phase 2**  
All admin problem-bank routes are in a single `admin.py` file. Acceptable for Phase 2 scope. Will split into `admin/problem_bank.py`, `admin/sessions.py` etc. if the file grows beyond ~300 lines.

**DT-03: `graph_config_json` stored as plain text**  
Plotly graph configuration is stored as a raw JSON string in the `graph_config_json` column. Parsed to dict at render time. No separate graph model — keeps the schema flat for now.

### Test Results

All exit tests passed:
- Phase 1 Step 2 (Auth): 5/5 tests passed
- Phase 2 (Problem Bank): 7/7 tests passed
  - Login with CSRF → 200
  - Create topic → 200, topic ID confirmed
  - Create problem → 200, problem title confirmed
  - Create problem set → 200, set name confirmed
  - Add problem to set → 200, membership confirmed
  - View set detail → 200
  - Problem in set confirmed via API

---

_Next entry will be added at the "Phase 3 complete" checkpoint._

---

## Entry 002 — 2026-03-10 — Classic Mode Step A Complete

### Summary

Classic Mode Step A (first playable session) fully implemented and exit-tested.
All 32 exit tests passed (`test_classic_step_a.py`).

---

### New Files Created

| File | Purpose |
|---|---|
| `app/models/classic.py` | Four Classic Mode DB models (see AD-09) |
| `app/modes/classic/state.py` | In-memory per-session state (timers, locks, pending actions) |
| `app/modes/classic/engine.py` | Pure reward/penalty calculation functions |
| `app/modes/classic/forms.py` | `ClassicSessionForm` (WTForms) |
| `app/modes/classic/routes.py` | Two blueprints: `classic_admin_bp`, `classic_player_bp` |
| `app/modes/classic/events.py` | Socket.IO handlers: `classic_join`, `classic_submit_answer`, `classic_choose_action` |
| `app/templates/admin/classic/new.html` | Admin: create Classic session form |
| `app/templates/admin/classic/manage.html` | Admin: manage live session (start/end, leaderboard, solve counts) |
| `app/templates/player/classic/lobby.html` | Player: waiting room with Socket.IO auto-redirect |
| `app/templates/player/classic/game.html` | Player: live game UI with full Socket.IO JS |
| `test_classic_step_a.py` | 32-case exit test |

---

### Files Modified

| File | Change |
|---|---|
| `app/models/game.py` | `GameRound.problem_id` made `nullable=True` (Classic rounds cover a problem set, not one problem) |
| `app/models/__init__.py` | Added Classic model imports for Alembic detection |
| `app/core/session_manager.py` | `start_round(problem=None)` — made `problem` argument optional |
| `migrations/env.py` | Added `render_as_batch=True` to support SQLite `ALTER COLUMN` via Alembic |
| `app/__init__.py` | Registered `classic_admin_bp` and `classic_player_bp` |
| `app/socketio_handlers/__init__.py` | Wired `register_classic_handlers(socketio)` |
| `app/templates/admin/layout.html` | Added "Classic Mode" nav link |
| `app/modes/classic/routes.py` | Added `ProblemSolverCount` import and `solve_counts` to manage view |

---

### Migration Applied

`eb6a766ae410_classic_mode_models_game_round_nullable_.py`
- Four new tables: `classic_round_config`, `player_wallet`, `player_problem_state`, `problem_solver_count`
- `game_round.problem_id` changed from NOT NULL to nullable

Current migration head: `eb6a766ae410`  
Total tables in DB: 14

---

### Architecture Decisions

**AD-09: Classic Mode uses four dedicated models, not PlayerAnswer**  
`PlayerAnswer` has `UNIQUE(round_id, player_id)` — one answer per player per round. Classic Mode requires one answer per player per *problem* per round (each round covers a full problem set). Using `PlayerAnswer` here would violate the unique constraint. All answer tracking for Classic Mode goes through `PlayerProblemState` instead. `PlayerAnswer` remains for future modes (Team, Boss Rush) where one-answer-per-round semantics apply.

**AD-10: Round-active gate uses `game_session.status`, not `game_round.started_at`**  
SQLAlchemy evaluates Python-side `default=` expressions at object instantiation, not at commit time. If a `GameRound` is created with `started_at=None` but the model declares `started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))`, the default fires immediately on `GameRound(...)` unless `started_at=None` is explicitly passed. To avoid confusion and make the active-round guard robust, all event handlers check `game_session.status == 'active'` rather than `game_round.started_at is not None`.

**AD-11: Solver count incremented in DB under per-session lock**  
`ProblemSolverCount.solver_count` is incremented inside `state.get_lock(session_id)` using a DB write, not an in-memory counter. This is safe under `threading` async mode. In-memory counters would be lost on server restart; DB-backed counts survive. The lock prevents the classic TOCTOU race where two players solving simultaneously both get rank 1.

**AD-12: Timer bonus window tracked in memory, falls back gracefully**  
`state.is_timer_active(session_id, duration)` reads `_round_start_times[session_id]` set by `state.init_session()`. If the server restarts mid-session, `_round_start_times` is empty and `is_timer_active` returns `False` (no bonus). This is a known, accepted limitation for MVP. The cost is a missed timer bonus after a crash, not incorrect gold calculation.

**AD-13: Two-phase Socket.IO action flow (submit → choose)**  
Correct answers do NOT immediately award gold. The flow is:
1. `classic_submit_answer` → emits `choose_action_prompt` to the solver; records a pending action in `state._pending_actions`
2. `classic_choose_action` → consumes the pending action, calculates reward, updates `PlayerWallet`, emits `reward_applied` to the player and `leaderboard_update` to all room members
This prevents clients from calling `classic_choose_action` without first solving a problem, and ensures gold is only awarded once per correct answer.

**AD-14: Gold is session-scoped (not round-scoped)**  
`PlayerWallet` is created per `(player_id, session_id)` pair. Gold accumulates across rounds within a session. A new session always starts with 0 gold. This was an explicit design decision locked before implementation started.

---

### Bug Fixes

**BF-05: SQLAlchemy Cython `.pyd` incompatible with Python 3.14**  
After a Python update, the pre-built Cython extensions inside the SQLAlchemy wheel were compiled for an older Python ABI. This caused `ImportError` on startup. Fixed by: `pip install --force-reinstall sqlalchemy` (downloaded a fresh `cp314-cp314-win_amd64.whl`).

---

### Test Results

`test_classic_step_a.py` — 32/32 passed

| Range | What is tested |
|---|---|
| T01–T04 | Session, round, config creation; backref works |
| T05–T06 | Admin start round; timer active immediately |
| T07–T10 | Player join: wallets and problem state rows created |
| T11–T14 | Correct answer, first solver (rank 1), mine reward = 31 gold |
| T15–T17 | Second solver (rank 2), treasure_search reward = 14 gold |
| T18–T21 | Wrong answer closes problem (1-attempt config); penalty applied; submit blocked on closed problem |
| T22–T23 | Gold floor: `apply_penalty` never produces negative gold |
| T24–T25 | Admin end round: session finished, ended_at set |
| T26–T30 | DB row counts for all Classic models |
| T31–T32 | Engine unit: no fsb past rank threshold; no timer bonus when inactive |

---

_Next entry will be added at the "Classic Mode Step B complete" checkpoint._

---

## Entry 003 — 2026-03-10 — Classic Mode Step B Complete

### Summary

Classic Mode Step B (Store system, x2 mine bonus, shield token) fully implemented and exit-tested.
All 48 exit tests passed (`test_classic_step_b.py`). Step A regression: 32/32 still pass.

---

### New Files Created

| File | Purpose |
|---|---|
| `app/modes/classic/store.py` | `purchase_item()`, `consume_item()`, `get_active_counts()`, `store_items_for()` |
| `app/templates/admin/classic/store.html` | Admin: list + add store items for a session |
| `app/templates/admin/classic/store_edit.html` | Admin: edit an existing store item |
| `test_classic_step_b.py` | 48-case exit test |

---

### Files Modified

| File | Change |
|---|---|
| `app/models/classic.py` | Added `StoreItem` and `PlayerInventory` models |
| `app/models/__init__.py` | Added `StoreItem`, `PlayerInventory` imports |
| `app/modes/classic/engine.py` | Added `apply_x2_mine(reward_dict)` |
| `app/modes/classic/forms.py` | Added `StoreItemForm`; added `StringField`, `TextAreaField`, `Length` imports |
| `app/modes/classic/routes.py` | Added `store`, `store_edit`, `store_delete` admin routes; added `StoreItem`, `StoreItemForm` imports |
| `app/modes/classic/events.py` | Added `classic_buy_item` handler; shield check in incorrect branch; x2_mine check in mine branch; store data in `join_ack` and `reward_applied` |
| `app/templates/admin/classic/manage.html` | Added "🛒 Manage Store" link/button in action bar |
| `app/templates/player/classic/game.html` | Added store panel with toggle, item list, buy buttons, active bonus indicator, `buy_result` Socket.IO handler |

---

## Entry 015 — 2026-03-30 — Documentation Checkpoint / Source-of-Truth Sync

### Summary

Active docs were synchronized to the current repo reality after substantial Classic/Hub/admin/player-page changes.

Current source-of-truth docs are:
- `docs/project_state.md`
- `docs/system_architecture.md`
- `docs/manual_test_guide.md`
- `docs/bootstrap_prompt.txt`

Historical/reference-only docs remain:
- `docs/dev_log.md`
- `docs/checkpoints/*`
- `docs/archive/*`

### What changed

- updated active docs to reflect:
  - current Classic-centered gameplay state
  - center-stage Treasure overlay
  - center-stage Steal overlay
  - grouped Classic admin config UX
  - new-problem bootstrap -> full content editor flow
  - refresh/reconnect restoration for pending action and stage-event flows
  - current asset/render responsibilities
- archived outdated implementation prompts from active `docs/` root into:
  - `docs/archive/prompts/`
- added:
  - `docs/checkpoints/2026-03-30/DOCS_CHECKPOINT.md`
  - `docs/archive/README.md`

### Notes

- this was a docs-only checkpoint
- code remained the source of truth; docs were updated to match current code behavior rather than future design

---

### Migration Applied

`3b6e8c2b3f19_store_item_player_inventory.py`
- Two new tables: `store_item`, `player_inventory`

Current migration head: `3b6e8c2b3f19`  
Total tables in DB: 16

---

### Architecture Decisions

**AD-15: One PlayerInventory row per purchased item copy**  
Rather than `(player_id, item_id, count)`, each purchase creates a separate `PlayerInventory` row with `used_at=NULL`. Consuming an item sets `used_at` on the oldest unused row. Advantages: clean audit trail of each purchase; `consume_item()` is a simple `ORDER BY purchased_at LIMIT 1` query; no race condition on count decrement.

**AD-16: Item bonuses are one-time use, consumed at activation**  
Both `x2_mine` and `shield` are consumed when activated (not at purchase). This ensures items cannot be hoarded to apply to a future session or re-used: the row always records exactly when each purchased copy was consumed. `used_at=NULL` = still active; `used_at` set = spent.

**AD-17: Store item quantity enforced via purchase count, not a stock counter**  
`StoreItem.quantity` is a design intent field. Actual enforcement uses `PlayerInventory.query.filter_by(item_id=...).count()` at purchase time. Under threading async mode this is safe because purchase events execute serially per session (no async concurrency). If gevent is ever adopted, a `SELECT ... FOR UPDATE` pattern would be needed.

**AD-18: Store data sent in `join_ack`, refreshed in `buy_result` and `reward_applied`**  
The client receives `store_items` + `active_bonuses` on every `join_ack` (reconnect-safe). `buy_result` always replays the full updated store + active bonuses so the client never needs to maintain its own inventory state. `reward_applied` returns `active_bonuses` so the bonus indicator refreshes after an item is consumed.

---

### Test Results

`test_classic_step_b.py` — 48/48 passed

| Range | What is tested |
|---|---|
| T01–T04 | Setup: players, problem set, session |
| T05–T06 | StoreItem creation; quantity fields |
| T07 | `store_items_for()` returns correct item data & qty_left |
| T08–T09 | `purchase_item()` success: gold deducted, inventory created |
| T10–T11 | `PlayerInventory` rows created; `get_active_counts()` correct |
| T12 | `purchase_item()` rejects insufficient gold |
| T13 | `purchase_item()` rejects out-of-stock item (quantity=2 exhausted) |
| T14 | `store_items_for()` qty_left reflects actual purchases |
| T15–T16 | `consume_item()` marks shield used; second call returns None |
| T17 | `get_active_counts()` reflects consumed item |
| T18 | `engine.apply_x2_mine()` doubles gold; appends breakdown; original unchanged |
| T19 | `consume_item()` x2_mine flow; count decremented |
| T20 | `calc_mine_reward` + `apply_x2_mine` integration |
| T21 | DB row counts: 2 store items, 4 inventory rows |
| T22 | `store_items_for()` item dict has required keys |

---

_Next entry will be added at the "Classic Mode Step C complete" checkpoint._

---

## Entry 004 — 2026-03-10 — Classic Mode Step C-1 through C-5 Complete

### Summary

Classic Mode Step C (Random Rewards + Gems) substeps C-1 through C-5 implemented.
Step C-6 (exit tests — `test_classic_step_c.py`) is the only remaining substep.
Regressions throughout: Step A 32/32 ✓, Step B 48/48 ✓.

---

### Feature Overview

| Substep | What was delivered |
|---|---|
| C-1 | DB migration: 3 new columns on `ClassicRoundConfig`, `gems` column on `PlayerWallet`; `events.py` wired for gems |
| C-2 | Random Treasure Search gold: `calc_treasure_search_reward()` rolls `random.randint(ts_min, ts_max)`; `treasure_roll` key added to `reward_applied` payload |
| C-3 | Gem awarding: milestone (DB-backed solved count) + streak (in-memory); `calc_gem_award()` pure engine function; `state.py` gem streak API |
| C-4 | Admin forms + templates: 3 new fields in `ClassicSessionForm`; cross-field validator; `new.html` "Random Rewards & Gems" section; `manage.html` gems column + Round Config summary table |
| C-5 | Player UI: currency bar (💰 gold + 💎 gems + 🔥 streak), `join_ack` gems init, `reward_applied` treasure roll + gem gain display, leaderboard gems column |

---

### New Columns Added

**`ClassicRoundConfig`** (migration `bde9f2a62232`):

| Column | Type | Default | Purpose |
|---|---|---|---|
| `treasure_search_max_reward` | Integer | 5 | Upper bound of random TS gold roll; equal to min = fixed reward |
| `gem_milestone_count` | Integer | 5 | Award 1 gem every N problems solved (0 = disabled) |
| `gem_streak_count` | Integer | 3 | Award 1 gem every K consecutive correct answers (0 = disabled) |

**`PlayerWallet`** (same migration):

| Column | Type | Default | Purpose |
|---|---|---|---|
| `gems` | Integer | 0 | Session-scoped gem balance; separate from gold |

> Note: The migration required manual `server_default` values (`'5'`, `'5'`, `'3'`, `'0'`) — SQLite rejects `ADD COLUMN NOT NULL` without a server-level default.

---

### Files Modified

| File | Change |
|---|---|
| `app/models/classic.py` | 3 new columns on `ClassicRoundConfig`; `gems` column + `__repr__` update on `PlayerWallet` |
| `app/modes/classic/engine.py` | `import random`; `calc_treasure_search_reward()` now rolls random; `calc_gem_award()` added |
| `app/modes/classic/state.py` | `_player_streaks` dict; `increment_streak()`, `reset_streak()`, `get_streak()` functions |
| `app/modes/classic/events.py` | `gems=0` in wallet creation; `gems` in `join_ack` + leaderboard; `treasure_roll` in `reward_applied`; streak/gem logic in correct+wrong branches and `handle_choose_action` |
| `app/modes/classic/forms.py` | `ValidationError` import; 3 new fields with `NumberRange(min=0)`; `validate_treasure_search_max_reward` cross-field validator |
| `app/modes/classic/routes.py` | 3 new `ClassicRoundConfig` fields passed through in `new_session()` POST handler |
| `app/templates/admin/classic/new.html` | "Random Rewards & Gems" form section with 3 fields, help text, inline errors |
| `app/templates/admin/classic/manage.html` | Leaderboard Gems column; full Round Config summary table (11 fields incl. Step C) |
| `app/templates/player/classic/game.html` | Currency bar; gems display; streak indicator; treasure roll annotation; gem-gain lines in reward; leaderboard gems column |
| `migrations/versions/bde9f2a62232_step_c1_gems_random_ts.py` | Applied migration |

---

### Architecture Decisions

**AD-19: Gems are session-scoped (parallel to gold)**
`PlayerWallet.gems` lives on the existing wallet row. Gems do not carry between sessions (same scoping rule as AD-14 for gold). Diamonds are deferred to Step E — `PlayerWallet` intentionally does NOT have a `diamonds` column yet.

**AD-20: Gem milestone is DB-backed; gem streak is in-memory**
Milestone uses `db.session.query(PlayerProblemState).filter_by(..., is_solved=True).count()` — survives server restart. Streak uses `state._player_streaks[(player_id, round_id)]` — resets to 0 on restart (acceptable; streak is a bonus, not a balance).

**AD-21: `calc_gem_award()` is a pure function (no DB access)**
Signature: `calc_gem_award(solved_count, cfg_milestone, streak_count, cfg_streak) → {"gems": int, "reason": "milestone"|"streak"|"both"|None}`. Both milestone and streak can fire simultaneously (`reason="both"`, `gems_gained=2`). `cfg_milestone=0` or `cfg_streak=0` disables that feature (division-by-zero guard included).

**AD-22: Random TS gold uses `random.randint(ts_min, ts_max)`**
`ts_min = config.treasure_search_reward` (existing field). `ts_max = config.treasure_search_max_reward` (new field; clamped to `>= ts_min`). When min == max the result is deterministic (backward-compatible). The rolled value is returned in the `reward_applied` payload as `treasure_roll` (int or None for mine actions).

**AD-23: Streak keys are round-scoped: `(player_id, round_id)`**
Streak resets naturally when a new round starts because the new `round_id` produces a fresh key with no entry. No explicit streak-clear needed on `round_started`.

---

### Bug Fixes

**BF-06: SQLite `ADD COLUMN NOT NULL` without `server_default` rejected**
Alembic auto-generated migration omitted `server_default` on all 4 new columns. SQLite throws `OperationalError: Cannot add a NOT NULL column with default value NULL`. Fixed by manually editing the migration to add `server_default='5'` / `server_default='3'` / `server_default='0'` before running `flask db upgrade`.

---

### Migration Applied

`bde9f2a62232_step_c1_gems_random_ts.py`
- 3 new columns on `classic_round_config`
- 1 new column (`gems`) on `player_wallet`

Current migration head: `bde9f2a62232`
Total tables in DB: 16 (no new tables — columns added to existing tables)

---

### Test Results

| Suite | Result |
|---|---|
| Step A regression (`test_classic_step_a.py`) | 32/32 ✓ |
| Step B regression (`test_classic_step_b.py`) | 48/48 ✓ |
| Step C exit tests (`test_classic_step_c.py`) | **Not yet written — Step C-6** |

---

_Next entry will be added at the "Classic Mode Step C-6 complete" checkpoint._

---

## Entry 005 — 2026-03-10 — Classic Mode Step C Complete

### Summary

Classic Mode Step C (Random Rewards + Gems) fully complete.
`tests/test_classic_step_c.py` written and all 38 exit tests passed.
Full regression: Step A 32/32 ✓, Step B 48/48 ✓, Step C 38/38 ✓.

---

### Feature Completed

Step C-6 adds `tests/test_classic_step_c.py` — the exit test suite covering the entire Step C
feature layer. Tests drive the engine and ORM directly (no HTTP/WebSocket) from inside an
app context, following the same pattern as `test_classic_step_a.py` and `test_classic_step_b.py`.

---

### New Files Created

| File | Purpose |
|---|---|
| `tests/test_classic_step_c.py` | 38-case exit test for random TS + gem system |

---

### Test Coverage

| Range | What is tested |
|---|---|
| T01–T04 | Setup: test players, 6-problem set, session with Step C config (milestone=3, streak=2, ts_max=15) |
| T05–T06 | `PlayerWallet.gems=0` on creation; `ClassicRoundConfig` stores 3 new Step C fields |
| T07–T09 | Random TS gold: 200 rolls in [5, 15]; `min==max=10` always produces 10; ts_min floor enforced |
| T10–T12 | TS reward includes FSB + timer bonus on top of roll; `treasure_roll` in payload; Mine has `treasure_roll=None` |
| T13–T16 | Gem milestone: N solves → +1 gem; N+1 → still 1; 2N → +2; `gem_milestone_count=0` disables |
| T17–T20 | Gem streak: K consecutive correct → +1 gem; wrong resets; 2K → +2; `gem_streak_count=0` disables |
| T21 | Simultaneous milestone + streak → `gem_reason="both"`, `gems_gained=2` |
| T22–T23 | Wrong answer: `streak_reset=True` in `answer_result`; no gems awarded |
| T24–T25 | `reward_applied` payload has all required keys |
| T26–T27 | `join_ack` includes `gems`; leaderboard entries include `gems` |
| T28 | Gems do not carry between sessions |
| T29–T30 | Gold unchanged by gem award; gems unchanged by gold award |
| T31–T34 | DB wallet accounting via `calc_gem_award`; milestone uses DB query (repeatable after state clear) |
| T35–T36 | Multi-player wallet consistency: totals correct across 2 wallets |
| T37 | Step A regression: 32/32 |
| T38 | Step B regression: 48/48 |

---

### Architecture Decisions

No new architecture decisions. All Step C design decisions (AD-19 through AD-23) were locked in Entry 004.

---

### Bug Fixes

**BF-07: Windows subprocess UTF-8 encoding in test runner subprocesses**
When `tests/test_classic_step_c.py` spawns subprocesses for regression tests (T37, T38), the
inherited Windows console code page (`cp1251` / `cp1252`) causes emoji characters (💰 💎 🔥)
in test output to fail with `UnicodeDecodeError`. Fixed by passing `encoding='utf-8'` to
`subprocess.run()` and injecting `{'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}` into
the subprocess environment.

---

### Test Results

| Suite | Result |
|---|---|
| Step A regression (`test_classic_step_a.py`) | 32/32 ✓ |
| Step B regression (`test_classic_step_b.py`) | 48/48 ✓ |
| Step C exit tests (`tests/test_classic_step_c.py`) | 38/38 ✓ |

---

_Next entry will be added at the "Classic Mode Step D complete" checkpoint._

---

## Entry 006 — 2026-03-10 — Classic Mode Step D Planning Finalized

### Summary

Step D (Steal System) design fully locked and documented. No code written yet.
All open questions resolved. Architecture is ready for implementation in the next session.

---

### Design Decisions Locked

**OQ-1 resolved: Token earn sources (three paths)**
- Players automatically receive 1 steal token when their wallet is created at session join
- New store item `bonus_type='steal_token'` immediately credits a token at purchase
- New `steal_token_treasure_chance` config field (float 0.0–1.0); rolled during Treasure Search action
- Max capacity = 1 for Step D; extra tokens silently dropped regardless of source

**OQ-2 resolved: Manual anti-steal shield is a separate new store item type**
- `bonus_type='steal_shield'` — distinct from Step B `bonus_type='shield'` (penalty absorber)
- Activated immediately at purchase; sets `wallet.shield_expires_at`
- These two shield concepts never interact (documented as AD-27)

**OQ-3 resolved: No-cap UX uses a checkbox**
- `no_steal_max_cap` boolean field in `ClassicSessionForm`
- When checked → `steal_max_cap` saved as `-1` internally (consistent with `attempts_per_problem=-1` sentinel)
- Numeric `steal_max_cap` field hidden/disabled when checkbox is checked

**OQ-4 resolved: Target becomes shielded during mini-game**
- No timeout for Step D
- If the chosen target becomes shielded (or loses all gold) after the token is consumed but before the mini-game resolves → outcome is `mini_game_fail` regardless of chest chosen

**OQ-5 resolved: Victim notification + rolling action log**
- Victim receives a `steal_victim_notify` socket event when stolen from
- Each player has a lightweight rolling action log: `state._action_logs[(player_id, session_id)]` = `deque(maxlen=10)`
- Log sent to client in `join_ack` as `recent_actions: [str]`
- Each relevant server event includes a `log_entry: str` field appended client-side
- Example entries: "You mined 15 gold", "Player A stole 19 gold from you — reactive shield granted"
- In-memory only; lost on server restart (acceptable — cosmetic display only)

**OQ-6 resolved: No steal count on leaderboard**
- Leaderboard remains gold + gems only

**Additional locked: Steal is a post-solve action (not standalone)**
- Replaces Mine / Treasure Search for that correct-answer action slot
- `choose_action_prompt` gains `steal_available: bool`
- No Mine/TS gold awarded on the same solve when Steal is chosen

**Confirmed defaults:**
`steal_percent=0.10, steal_min_cap=10, steal_max_cap=50, steal_fallback_gold=5,`
`steal_chest_count=2, steal_winning_chest_count=1, shield_duration=60, steal_token_treasure_chance=0.0`

---

### Architecture Decisions

**AD-24: Steal is a third post-solve action, not a standalone mechanic**
Steal is offered in `choose_action_prompt` alongside Mine and Treasure Search, controlled by
`steal_available: bool`. Only one action per correct solve. This keeps the reward flow single-path
and prevents steal from being spammable outside problem-solving.

**AD-25: Token capacity = 1 for Step D; excess tokens silently dropped**
All three token grant paths check `wallet.steal_tokens < 1` before incrementing. No error shown.
The `token_awarded: bool` field in `reward_applied` indicates whether a found treasure token
was actually credited (false when at cap). Step D capacity expansion deferred.

**AD-26: `steal_token` and `steal_shield` store items have immediate effect at purchase**
Unlike `x2_mine` and `shield` (AD-16, which are activated later), these two new types are applied
immediately when purchased. `PlayerInventory.used_at` is set equal to `purchased_at` in the same
transaction. This is a documented deviation from AD-16 — add a comment in `store.py`.

**AD-27: Steal shield (wallet.shield_expires_at) is entirely separate from Step B penalty shield**
`wallet.shield_expires_at` is a time-based steal-protection mechanism.
`PlayerInventory` rows with `bonus_type='shield'` are wrong-answer penalty absorbers.
They have no interaction. The word "shield" in Step D always means `shield_expires_at`.

**AD-28: Token consumed at pick_target, not at choose_action='steal'**
If valid targets exist, the token is NOT consumed when the player initiates steal.
It is consumed when they confirm a specific target (`classic_steal_pick_target`).
Exception: if no valid targets exist, token is consumed immediately in the steal branch of
`handle_choose_action`. This allows players to see the target list before committing.

**AD-29: Action log is in-memory, rolling, cosmetic-only**
`state._action_logs[(player_id, session_id)] = deque(maxlen=10)`. Sent to client in
`join_ack`, updated via `log_entry` field in `reward_applied`, `steal_result`,
`steal_victim_notify`. Not persisted to DB. Lost on restart (acceptable — not a balance value).

---

### Planned DB Changes (not yet applied)

**`ClassicRoundConfig` — 8 new columns** (all need `server_default` in Alembic migration):
steal_percent (REAL 0.1), steal_min_cap (INTEGER 10), steal_max_cap (INTEGER 50),
steal_fallback_gold (INTEGER 5), steal_chest_count (INTEGER 2),
steal_winning_chest_count (INTEGER 1), shield_duration (INTEGER 60),
steal_token_treasure_chance (REAL 0.0)

**`PlayerWallet` — 2 new columns**:
steal_tokens (INTEGER DEFAULT 0), shield_expires_at (DATETIME NULLABLE)

**New table: `steal_event`**:
id, session_id (FK), round_id (FK), actor_id (FK), target_id (FK nullable),
outcome (VARCHAR 20: 'success'|'mini_game_fail'|'no_targets_fallback'),
gold_exchanged (INTEGER), mini_game_pick (INTEGER nullable), created_at (DATETIME)

Migration label: `step_d1_steal_system`

---

### Planned Substep Breakdown

| Substep | Scope |
|---|---|
| D-1 | DB migration + StealEvent model + admin form fields + new.html section |
| D-2 | Engine functions + state.py additions |
| D-3 | Socket event handlers + store.py new item types + extended join_ack/choose_action_prompt |
| D-4 | Player UI (game.html) |
| D-5 | Admin UI (manage.html steal history + config summary) |
| D-6 | Exit tests (tests/test_classic_step_d.py, ~46 tests) + full regression |

---

### Routing Changes Already Applied (prior session)

The following routes were already coded and are live (not part of Step D coding):
- `GET /classic/play` — unified player entry point
- `GET /classic/round_over/<id>` — final results page
- `GET /classic/lobby/<id>` — now guards for finished → round_over
- `GET /classic/game/<id>` — now guards for waiting → lobby and finished → round_over

---

_Next entry will be added at the "Classic Mode Step D complete" checkpoint._

---

## Entry 007 — 2026-03-10 — Classic Mode Step D Substeps D-1 through D-3 Complete

### Summary

Classic Mode Step D (Steal System) substeps D-1, D-1b (schema correction), D-2, D-3,
and a D-3 cleanup pass are all complete. All server-side steal logic is implemented and tested.
D-2: 39/39 tests. D-3: 43/43 tests.
D-4 (Player UI), D-5 (Admin UI), D-6 (exit tests) remain.

---

### Feature Overview

| Substep | What was delivered |
|---|---|
| D-1 | DB migration `c4f7e8d21a30`: 8 new `ClassicRoundConfig` steal cols, `PlayerWallet.steal_tokens`, `StealEvent` table |
| D-1b | Corrective migration `d2a91f3b5c07`: new `PlayerClassicState` table (shield state separated from wallet); field renamed to `treasure_steal_token_chance` |
| D-2 | 6 engine functions, 8 state API functions; `tests/test_classic_step_d2.py` 39/39 |
| D-3 | 4 new socket handlers; extended `handle_join`, `handle_submit_answer`, `handle_choose_action`; store.py steal types; treasure token wired; `tests/test_classic_step_d3.py` 43/43 |
| D-3 cleanup | Private room join; `steal_token`/`steal_shield` store effects; cancel returns action slot; `problem_id` stored in intent |

---

### New DB Tables

| Table | Migration | Purpose |
|---|---|---|
| `steal_event` | `c4f7e8d21a30` | Audit trail: every steal attempt with outcome, gold, chest pick |
| `player_classic_state` | `d2a91f3b5c07` | Time-based steal shield per (player, session) |

### New Columns (D-1 / D-1b)

**`ClassicRoundConfig`** — 8 steal columns (all with `server_default`):
`steal_percent`, `steal_min_cap`, `steal_max_cap`, `steal_fallback_gold`,
`steal_chest_count`, `steal_winning_chest_count`, `shield_duration`, `treasure_steal_token_chance`

**`PlayerWallet`** — `steal_tokens INTEGER DEFAULT 1`
(not 0, because token is granted at join; max capacity = 1 for Step D)

**`PlayerClassicState`** — `shield_expires_at DATETIME NULLABLE`
(IMPORTANT: shield is here, NOT in `PlayerWallet` — AD-27)

---

### New Engine Functions (`app/modes/classic/engine.py`)

| Function | Purpose |
|---|---|
| `calc_steal_amount(target_gold, steal_percent, min_cap, max_cap)` | Clamped steal formula; max_cap=-1 skips upper clamp |
| `is_steal_shield_active(player_classic_state)` | Normalises naive SQLite datetimes |
| `grant_steal_shield(player_classic_state, duration_s)` | Stacks on active shield if present |
| `build_steal_targets(wallets, states_dict, acting_player_id)` | Excludes self, broke, shielded |
| `generate_winning_chests(chest_count, winning_count)` | Server-side chest RNG; 1-based frozenset |
| `try_award_steal_token(wallet, max_cap=1)` | Returns False if already at cap |

---

### New State API (`app/modes/classic/state.py`)

- `_pending_steal_intents[player_id]` = `{session_id, round_id, problem_id}`
- `_pending_steal_minigames[player_id]` = mini-game state
- `_action_logs[(player_id, session_id)]` = `deque(maxlen=10)`
- `set_steal_intent(player_id, session_id, round_id, problem_id)` — signature change: `problem_id` added (required for cancel restore)
- Full set/get/clear for both steal structures; `clear_session()` extended to clean all three

---

### Socket Event Changes (`app/modes/classic/events.py`)

**New handlers:**

| Handler | Event | Notes |
|---|---|---|
| `handle_steal_pick_target` | `classic_steal_pick_target` | Consumes token; routes to mini-game or instant resolve; both invalid and valid paths consume token (AD-28) |
| `handle_steal_mini_game_pick` | `classic_steal_mini_game_pick` | Picks chest; OQ-4 re-validates target before resolving |
| `handle_steal_cancel` | `classic_steal_cancel` | Clears intent; token NOT consumed; action slot returned; re-emits `choose_action_prompt` |
| `handle_buy_item` | (extended) | `buy_result` now includes `steal_tokens` |

**Extended handlers:**
- `handle_join`: creates `PlayerClassicState` if absent; joins `player_<id>` private room; `join_ack` extended with `steal_tokens`, `shield_active`, `shield_expires_at`, `recent_actions`
- `handle_submit_answer`: `choose_action_prompt` now includes `steal_available: bool`
- `handle_choose_action` steal branch: no_targets_fallback path consumes token + emits immediately; valid-targets path preserves pending action; action log entries for mine/TS; treasure token chance rolled

---

### Store Changes (`app/modes/classic/store.py`)

- `purchase_item()` branches on `bonus_type` after commit:
  - `'steal_token'`: credits `wallet.steal_tokens` if under cap; `inv.used_at = inv.purchased_at`
  - `'steal_shield'`: `inv.used_at = None` — stored as manual token, not auto-activated (see AD-30)

---

### Architecture Decisions (new in this entry)

**AD-30 (REVISED from OQ-2): `steal_shield` store item is MANUAL, not auto-activate**
OQ-2 in Entry 006 said "activated immediately at purchase." After review, changed:
`steal_shield` items sit in inventory with `used_at=NULL` until player manually activates (D-4).
Players may hold multiple shield tokens. `get_active_counts()` reports `steal_shield: N`.

**AD-31: `classic_steal_cancel` returns action slot (not forfeit)**
Entry 006 implied the action slot would be forfeited. After review, changed:
cancel restores `choose_action_prompt` for the same problem using `problem_id` from the intent.
Token not consumed. Player can re-choose Mine, TS, or Steal.

**AD-32: Treasure token chance wired in D-3 (not deferred)**
`reward_applied` now emits live `token_found`/`token_awarded` based on `treasure_steal_token_chance`.
Originally planned for D-4+. Included in D-3 cleanup pass as a clean single-function addition.

---

### Bug Fixes

**BF-08: `set_steal_intent` — `problem_id` added as required 4th argument**
Needed so `classic_steal_cancel` can restore `choose_action_prompt` for the correct problem.
D-2 and D-3 tests updated (`problem_id=0` at all call sites).

**BF-09: Token not consumed on invalid target at `pick_target`**
Corrected: token consumed in both invalid and valid paths of `handle_steal_pick_target` (AD-28).

**BF-10: Player private room never joined**
`handle_join` now calls `join_room(f'player_{player.id}')`.
Without this, `steal_victim_notify` events were silently dropped.

---

### Migration History

| Revision | Label | Tables changed |
|---|---|---|
| `c4f7e8d21a30` | `step_d1_steal_system` | `classic_round_config` (+8 cols), `player_wallet` (+1 col), new `steal_event` |
| `d2a91f3b5c07` | `step_d1b_schema_corrections` | new `player_classic_state`; renamed col in `classic_round_config` |

Current HEAD: `d2a91f3b5c07` — total DB tables: 18

---

### Test Results

| Suite | Result |
|---|---|
| D-2 unit tests (`tests/test_classic_step_d2.py`) | 39/39 ✓ |
| D-3 integration tests (`tests/test_classic_step_d3.py`) | 43/43 ✓ |

---

_Next entry will be added at the "Classic Mode Step D complete" (D-6) checkpoint._

---

## Entry 008 — 2026-03-10 — Classic Mode Step D-4 Complete + Terminology Normalization

### Summary

Step D-4 (Player UI — game.html steal system) fully implemented.
D-3 test suite expanded from 43 to 53 tests during a post-D-3 audit pass.
Canonical steal outcome string `no_targets` renamed to `no_targets_fallback` across all runtime
files and documentation.
All 53 D-3 integration tests pass; 39 D-2 unit tests still pass.

---

### Feature Delivered: D-4 Player UI (game.html)

| UI element | Details |
|---|---|
| Currency bar (extend) | `🗡 ×N` steal-token count (green ≥1, grey at 0); `🛡 Protected` shield indicator |
| Action panel (extend) | Dark-red "🗡 Steal" button; hidden until `steal_available: true` in `choose_action_prompt` |
| `#steal-targets-panel` | Target list with player name + gold + "Pick" button; Cancel button emits `classic_steal_cancel` |
| `#steal-mini-game-panel` | N numbered chest buttons; header "Pick a chest — X of N are winners!" |
| `#steal-result-msg` | Outcome-styled banner: green=success, blue=no_targets_fallback, yellow=fail/target_invalid |
| `#steal-notification` | Victim alert div with stolen-by + amount + reactive shield message; auto-hides after 8 s |
| Action log panel | Loads `recent_actions` from `join_ack`; prepends entries from `reward_applied`, `steal_result`, `steal_victim_notify` |

**New JS handlers added:**
- `steal_targets` — populates and shows `#steal-targets-panel`
- `steal_mini_game_start` — populates and shows `#steal-mini-game-panel`
- `steal_result` — handles all four outcomes; animates chest reveal (1.8 s delay before showing winning indices); hides panels; updates currency bar
- `steal_victim_notify` — shows `#steal-notification`; updates gold from `new_balance`; updates shield display

**JS helper added:**
- `updateShieldDisplay(active, expiresIso)` — toggles `🛡 Protected` text and countdown

**Store rendering updated:**
- `renderStore()` handles all four `bonus_type` values: `x2_mine`, `shield`, `steal_token`, `steal_shield`
- `renderBonuses()` shows `steal_shield` unused-token count alongside existing bonuses
- `buy_result` handler now refreshes steal-token count in currency bar

**Manual steal_shield activation deferred to D-5** — `#steal-targets-panel` shows shield token count
for display only; activation button not yet wired (AD-30).

---

### Files Modified (D-4)

| File | Change |
|---|---|
| `app/templates/player/classic/game.html` | Full steal UI: panels, buttons, JS handlers, store/bonus rendering, action log |
| `app/modes/classic/events.py` | Added `new_balance: target_wallet.gold` to `steal_victim_notify` payload |

---

### D-3 Audit — Test Count Expansion (43 → 53)

During a post-D-3 audit, 10 additional tests were added to `tests/test_classic_step_d3.py`
to cover gaps identified in the audit:
- Victim's gold displayed correctly after steal (the `new_balance` field)
- Action log entries for all steal outcomes
- Leaderboard broadcast on `no_targets_fallback` and `success` paths; NOT on `mini_game_fail`
- Shield display in `join_ack` after reactive grant
- Cancel restoring action slot (AD-31 enforcement)

---

### Terminology Normalization

The canonical steal outcome for "no valid targets" was renamed from `no_targets` to
`no_targets_fallback` to match the locked contract spec. Changed in 8 files:

| File | Occurrences |
|---|---|
| `app/modes/classic/events.py` | 2 (DB write outcome + emit payload) |
| `app/models/classic.py` | 6 (column docstring/comment) |
| `app/templates/player/classic/game.html` | 2 (JS comment + outcome branch) |
| `tests/test_classic_step_d3.py` | 5 (assertion label, query filter, event name) |
| `docs/dev_log.md` | Entries 006 and 007 content |
| `docs/bootstrap_prompt.txt` | 8 (outcome string, test names, flow pseudo-code, AD-28) |
| `docs/project_state.md` | 1 (outcomes list) |
| `docs/system_architecture.md` | 2 (schema comment + flow diagram) |

---

### Architecture Decisions

**AD-30 (confirmed final): `steal_shield` store item is MANUAL — activation deferred to D-5**
`purchase_item()` creates the `PlayerInventory` row with `used_at=NULL`. No `shield_expires_at`
is set at purchase time. The player will activate the token manually via a UI button in D-5.
This is a revision of the original OQ-2 plan (which said "immediately at purchase"). D-4 displays
the unused token count but does not wire the activation; commented in `store.py`.

---

### Bug Fixes

**BF-11: `steal_victim_notify` missing `new_balance` field**
The victim's gold display was not updated after a steal because the payload lacked the new gold
value. Fixed by adding `'new_balance': target_wallet.gold` to the `steal_victim_notify` emit in
`_resolve_steal_success()` inside `events.py`.

---

### Test Results

| Suite | Result |
|---|---|
| D-2 unit tests (`tests/test_classic_step_d2.py`) | 39/39 ✓ |
| D-3 integration tests (`tests/test_classic_step_d3.py`) | 53/53 ✓ (expanded from 43 during audit) |

---

_Next entry will be added at the "Classic Mode Step D-5 complete" checkpoint._

---

## Entry 009 — 2026-03-10 — Classic Mode Step D Complete (D-5 + D-6)

### Summary

Classic Mode Step D (Steal System) fully complete. All 6 substeps (D-1 through D-6) done.
D-5 (Admin UI) implemented; D-6 exit test suite written — 131/131 tests pass.
Full regression: A 32/32 ✓, B 48/48 ✓, C 38/38 ✓.

---

### Feature Delivered: D-5 Admin UI (manage.html)

| Addition | Details |
|---|---|
| Round Config table | 8 new rows with "Steal System" sub-header; steal_max_cap shows "No max cap" when value is -1; treasure_steal_token_chance formatted as percentage |
| Steal History section | New table below solve counts: Time / Actor / Target / Outcome / Gold; color-coded outcomes (✓ green for success, ✗ red for fail, ↩ blue for no_targets_fallback); "stranger" shown for NULL target_id; empty-state fallback row |

**Files modified (D-5):**

| File | Change |
|---|---|
| `app/templates/admin/classic/manage.html` | Added steal config rows + Steal History section |
| `app/modes/classic/routes.py` | Added `StealEvent` import; `steal_events` query + pass in `manage()` render_template |

---

### Feature Delivered: D-6 Exit Tests (tests/test_classic_step_d.py)

**New file created:** `tests/test_classic_step_d.py` — 131 tests, all passing.

Pattern: app context, direct ORM + engine/state/store calls (no HTTP or WebSocket).
Follows same fixture conventions as D-2/D-3 test suites.

| Section | Range | What is tested |
|---|---|---|
| Engine: calc_steal_amount | T01–T05 | Clamping, min_cap, max_cap, target-gold cap, max_cap=-1 |
| Engine: shield | T06–T10 | is_steal_shield_active (None/past/future), grant_steal_shield (new + stacking) |
| Engine: targets/chests/token | T11–T15 | build_steal_targets exclusions, generate_winning_chests bounds, try_award_steal_token cap |
| State API | T16–T18 | steal_intent round-trip, steal_minigame round-trip, action_log maxlen |
| Integration: no_targets_fallback | T19–T21 | Token consumed, fallback_gold credited, StealEvent logged |
| Integration: mini-game disabled | T22–T25 | Gold transfer, reactive shield, StealEvent, victim shield in join_ack |
| Integration: mini-game success | T26–T29 | Token consumed at pick_target, winning chest, gold transfer, steal_victim_notify |
| Integration: mini-game fail | T30–T32 | Losing chest, no gold change, StealEvent outcome |
| Shield integration | T33–T35 | Target shielded after token → mini_game_fail; shield stacking; shielded excluded from targets |
| Store new types | T36–T39 | steal_token purchase (success + at-cap), steal_shield purchase (manual, AD-30) |
| Token from treasure | T40–T41 | chance=1.0 awards token; chance=0.0 does not |
| Action log | T42–T43 | Insertion order preserved; maxlen=10 enforced |
| Regression | T44–T46 | A 32/32, B 48/48, C 38/38 |
| Additional (SA/CA/MT/DC/AH/TK/SS/CS) | 85 tests | steal availability, no-targets, cancel flow, mine/TS block, duplicate guard, admin history, wallet default (flush needed), steal_shield inventory distinction, clear_session |

---

### Architecture Decisions (confirmed in this entry)

**AD-30 (FINAL): `steal_shield` store item is MANUAL — activation deferred**
Confirmed in D-5 and exit tests. `purchase_item()` creates `PlayerInventory` row with
`used_at=NULL`. No `shield_expires_at` is set at purchase time. Players can hold multiple
shield tokens. D-4 player UI activates the shield manually by consuming an inventory token.
The reactive shield (granted to victim after a successful steal) is auto-applied by the server.
This is the permanent design — do not change.

**AD-31 (FINAL): `classic_steal_cancel` returns action slot**
Confirmed by exit tests (CA section). `handle_steal_cancel` clears steal intent but does NOT
call `clear_pending_action`. The original `choose_action_prompt` is re-emitted to the player
using `problem_id` stored in the intent (requirement for this is why `set_steal_intent` takes
a 4th `problem_id` argument).

---

### Bug Fixes

No new bugs found in D-5 or D-6. BF-10 and BF-11 (from Entry 008) were validated by the
exit test suite's CA and integration sections.

**Test infrastructure note — BF-12 (exit test fixture):**
TK-01 test case ("new wallet steal_tokens default=1") initially failed because 
`PlayerWallet(...)` construction in Python does not apply `Column(default=1)` — that is a
Python-side default that fires at ORM INSERT, not at object instantiation. 
Fix: `db.session.add(dummy_wallet); db.session.flush()` before reading `wallet.steal_tokens`.
Then `db.session.delete(dummy_wallet); db.session.commit()` to clean up.
General rule: never check SQLAlchemy column defaults before flush/INSERT.

---

### Test Results

| Suite | Result |
|---|---|
| D-2 unit tests (`tests/test_classic_step_d2.py`) | 39/39 ✓ |
| D-3 integration tests (`tests/test_classic_step_d3.py`) | 53/53 ✓ |
| D exit tests (`tests/test_classic_step_d.py`) | **131/131 ✓** |
| Step A regression | 32/32 ✓ |
| Step B regression | 48/48 ✓ |
| Step C regression | 38/38 ✓ |

**Total Classic Mode tests passing: 32 + 48 + 38 + 131 = 249**

---

_Next entry will be added at the "Classic Mode Step E complete" checkpoint._

---

## Entry 009.5 — 2026-03-12 — Step D Admin Templates + G1 Planning Complete

### Summary

Session completed the outstanding admin template items for Step D, then ran an extended
planning series to lock the full G1→G2→H→I roadmap. All major design decisions are now
confirmed. G1 (Player/Group/Session Foundation) is ready to implement in a new chat.

---

### Admin Template Items Completed (this session)

| Item | File |
|---|---|
| 8 steal fields added to `ClassicSessionForm` | `app/modes/classic/forms.py` |
| Steal System section (8 form fields + no-max-cap checkbox) | `app/templates/admin/classic/new.html` |
| 8 steal kwargs passed to `ClassicRoundConfig` constructor | `app/modes/classic/routes.py` |
| `gem_treasure_chance` row in config table | `app/templates/admin/classic/manage.html` |
| Enrolled Players section (DOM ids: `enrolled-list`, `enrolled-count`, `enrolled-empty`) | `app/templates/admin/classic/manage.html` |
| `classic_admin_watch` socket handler (admin joins `classic_{id}` room) | `app/modes/classic/events.py` |
| Live monitoring JS (`leaderboard_update` + `player_joined` listeners) | `app/templates/admin/classic/manage.html` |

---

### Architecture Decisions (this session)

**AD-31 (E1): Route file structure — keep admin.py monolithic through G1**
New player CRUD routes and group CRUD routes go directly into `app/routes/admin.py`.
Do NOT split into sub-files during G1. Reconsider splitting during or after G2 if the
file becomes unwieldy.

**AD-32 (E2): Access restriction double-guard is correct and intentional**
Both guards will coexist:
- HTTP routes (`/classic/play`, `/classic/lobby/<id>`, `/classic/game/<id>`): redirect
  with flash message if player is not in the session's group.
- Socket handler (`classic_join`): emit `access_denied` event if player is not in the
  session's group.
This double-guard is defensive design. No open decision remains here.

**AD-33 (E3): `PlayerEditForm` — blank `new_password` = preserve existing hash**
- If `new_password` is blank on submit → leave `password_hash` unchanged.
- If `new_password` is non-empty → hash and store the new password.
- Never clear a password to blank; that code path must not exist.
Security-sensitive decision, confirmed explicitly by user.

---

### Planned Roadmap (locked)

| Phase | Scope | Status |
|---|---|---|
| **G1** | Player CRUD, Group CRUD + M2M membership, `GameSession.group_id` + `label` + `display_label`, session access restriction at 4 points, admin nav updates | Ready to code |
| **G2** | `Subject` model, `Topic.subject_id` FK migration, AJAX topic-by-subject endpoint, problem form two-step scoping, filter UI on problems list + set detail | After G1 |
| **H** | Session history (admin view, per-player history) | After G2 |
| **I** | Diamonds currency | After H |

---

### Test Results (no new tests this session — all prior passing)

| Suite | Count |
|---|---|
| Step D-2 engine tests | 39/39 ✓ |
| Step D-3 socket integration tests | 53/53 ✓ |
| Step D exit tests | 131/131 ✓ |
| Total Classic Mode | 249/249 ✓ |

---

_Next entry will be added at the "G1 complete" checkpoint._

---

## Entry 010 — 2026-03-12 — Phase 4 Step G1 Complete

### Summary

Phase 4 Step G1 (Player/Group/Session Foundation) fully implemented and approved.
All 271 tests pass (32 + 48 + 38 + 131 + 22).
Migration HEAD: `ba437f763581` — total DB tables: 20.

---

### Feature Overview

| Item | What was delivered |
|---|---|
| `PlayerGroup` model | `app/models/groups.py`: id, name (UNIQUE 64), description (256 nullable), created_at; `player_group_members` M2M table |
| `GameSession` additions | `group_id` FK→`player_group` (nullable), `label` VARCHAR(128 nullable), `display_label` property |
| Player CRUD forms | `PlayerCreateForm`, `PlayerEditForm`, `PlayerGroupForm` added to `app/routes/forms.py` |
| `ClassicSessionForm` additions | `group_id` SelectField, `label` StringField added to `app/modes/classic/forms.py` |
| Player CRUD routes (5) | `players_index`, `player_new`, `player_edit`, `player_delete` in `app/routes/admin.py` |
| Group CRUD routes (9) | `groups_index`, `group_new`, `group_detail`, `group_edit`, `group_add_player`, `group_remove_player`, `group_delete` in `app/routes/admin.py` |
| `player_in_session_group()` | Helper in `app/modes/classic/routes.py`; returns True if session is open or player is a member |
| HTTP route double-guard | `/classic/play`, `/classic/lobby/<id>`, `/classic/game/<id>` — redirect + flash if group check fails |
| Socket double-guard | `classic_join` handler emits `access_denied {reason: 'not_in_group'}` if group check fails |
| 5 new templates | `admin/players/index.html`, `admin/players/form.html`, `admin/groups/index.html`, `admin/groups/detail.html`, `admin/groups/form.html` |
| 3 modified templates | `admin/layout.html` (+Players/Groups nav), `admin/classic/new.html` (+group_id/label fields), `admin/classic/manage.html` (+display_label/group name) |
| Migration `ba437f763581` | Creates `player_group`, `player_group_members`; adds `group_id`, `label` to `game_session` via batch_alter (SQLite) |

---

### New Files Created

| File | Purpose |
|---|---|
| `app/models/groups.py` | `PlayerGroup` model + `player_group_members` M2M table |
| `app/templates/admin/players/index.html` | Player list: username, admin?, groups, created, actions |
| `app/templates/admin/players/form.html` | Create/edit player (conditional new_password field for edit) |
| `app/templates/admin/groups/index.html` | Group list: name, member count, description, created, actions |
| `app/templates/admin/groups/detail.html` | Group detail: members table + add/remove player form |
| `app/templates/admin/groups/form.html` | Create/edit group: name + description |
| `migrations/versions/ba437f763581_g1_player_groups_and_session_labels.py` | G1 migration (fixed FK name) |

---

### Files Modified

| File | Change |
|---|---|
| `app/models/__init__.py` | Added `PlayerGroup, player_group_members` import/re-export |
| `app/models/game.py` | Added `group_id`, `label` columns, `group` relationship, `display_label` property to `GameSession` |
| `app/models/classic.py` | `PlayerClassicState.session` backref now `cascade='all, delete-orphan'` (BF-12) |
| `app/routes/forms.py` | Added `BooleanField`, `PasswordField` imports; added `PlayerCreateForm`, `PlayerEditForm`, `PlayerGroupForm` |
| `app/modes/classic/forms.py` | Added `Optional` import; added `group_id` SelectField and `label` StringField to `ClassicSessionForm` |
| `app/routes/admin.py` | Added `from sqlalchemy import select`, `Player`, `PlayerGroup`, new form imports; 5 player routes + 9 group routes |
| `app/modes/classic/routes.py` | Added `PlayerGroup` import; added `player_in_session_group()` helper; group choices population in `new_session`; group_id/label save; group checks in `play`, `lobby`, `game` |
| `app/modes/classic/events.py` | Added `player_in_session_group` import; group check in `handle_join` with `access_denied` emit |
| `app/templates/admin/layout.html` | Added Players and Groups nav links |
| `app/templates/admin/classic/new.html` | Added "Session Setup" section with `group_id` SelectField + `label` StringField |
| `app/templates/admin/classic/manage.html` | Added `display_label` and `group.name`/`Open` in session info header |

---

### Migration Applied

**`ba437f763581_g1_player_groups_and_session_labels.py`**
- Creates `player_group` table
- Creates `player_group_members` M2M table
- Adds `group_id` (FK, nullable) and `label` (VARCHAR 128, nullable) to `game_session` via `batch_alter_table` (SQLite compatible)
- FK constraint explicitly named `'fk_game_session_group_id'` (unnamed FK causes `ValueError` in SQLite batch mode)

Current migration head: `ba437f763581`
Total tables in DB: **20**

| Table (new) | Notes |
|---|---|
| `player_group` | G1 — PlayerGroup model |
| `player_group_members` | G1 — M2M association; no ORM class |

---

### Architecture Decisions

**AD-34: `player_in_session_group()` — open-session logic**
If `session.group_id is None` → return True (session is open; no restriction).
If group record has since been deleted (orphaned FK) → return True (safe fallback; don't lock out players).
Check: `group.members.filter_by(id=player.id).first() is not None`.

**AD-35: Unnamed FK prohibition in SQLite batch migrations**
`create_foreign_key(None, ...)` causes `ValueError: Constraint must have a name` in SQLite batch
alter mode (Alembic limitation). Always give FK constraints an explicit name in Alembic migrations.
Affected migration used `'fk_game_session_group_id'`.

---

### Bug Fixes

**BF-12: Test isolation regression — `PlayerClassicState` orphaned rows after session delete**
`test_classic_step_c.py`'s `_clean()` helper deleted `GameSession` rows but not the associated
`PlayerClassicState` rows (written before PCS existed). Orphaned PCS rows later caused
`sqlite3.IntegrityError: NOT NULL constraint failed: player_classic_state.session_id` during
autoflush in Game v2's test runs (T46 of `test_classic_step_d.py`).

Fix: Changed `PlayerClassicState.session` relationship backref in `app/models/classic.py` to:
```python
backref=db.backref('classic_states', lazy='dynamic', cascade='all, delete-orphan')
```
This ensures that deleting a `GameSession` automatically deletes all related `PlayerClassicState`
rows via cascade. Confirmed by T46 passing (38/38 Step C regression).

---

### Test Results

| Suite | Result |
|---|---|
| Step A (`test_classic_step_a.py`) | 32/32 ✓ |
| Step B (`test_classic_step_b.py`) | 48/48 ✓ |
| Step C (`tests/test_classic_step_c.py`) | 38/38 ✓ |
| Step D (`tests/test_classic_step_d.py`) | 131/131 ✓ |
| Step E (`tests/test_classic_step_e.py`) | 22/22 ✓ |
| **Total** | **271/271 ✓** |

---

_Next entry will be added at the "G2 complete" checkpoint._

---

## Entry 011 — 2026-03-12 — Steps E, G2, QA Batch, Multi-round, H0 Complete (catch-up)

### Summary

Catch-up entry covering all work completed after G1 (documented in detail in project_state.md).
Migration HEAD advanced from `ba437f763581` → `a1b2c3d4e5f6`. Total tests: 416 across 12 suites.

---

### Features Completed

| Step | Description | Tests |
|---|---|---|
| **Step E** | Manual steal_shield activation wired in player UI | 22/22 ✓ |
| **G2a** | `Subject` model (`app/models/subjects.py`); admin Subject CRUD (6 routes) | 11/11 ✓ |
| **G2b** | `Topic.subject_id` FK; subject-first AJAX problem form; subject column on problem list | 16/16 ✓ |
| **G2c** | Subject filter on problem list + problem set detail | 28/28 ✓ |
| **Maintenance CLI** | `flask pilot-reset` — dry-run + apply --yes; timestamped SQLite backup; ASCII-safe output | pass ✓ |
| **QA R8_9** | `validate_steal_winning_chest_count()` cross-field validator | 7/7 ✓ |
| **QA R10_7** | Group auth check moved before status redirects in `lobby()` and `game()` | 9/9 ✓ |
| **QA R1_1** | `allow_unsafe_werkzeug=True` added to `socketio.run()` in `run.py` | — |
| **QA R0_1** | All non-ASCII chars replaced in `click.echo()` — Windows console safe | — |
| **Multi-round** | Session lifecycle: `end_round` → status='waiting'; `next_round` + carry-over; `end_session` | 35/35 ✓ |
| **H0** | `RoundHistory` + `RoundPlayerResult` tables; frozen snapshot at `end_round`; idempotent | 39/39 ✓ |

---

### New Migrations Applied (after ba437f763581)

| Revision | Description |
|---|---|
| `e1f2a3b4c5d6` | G2a: Subject table |
| `f2a3b4c5d6e7` | G2a: Topic.subject_id FK |
| `a1b2c3d4e5f6` | H0: round_history + round_player_result ← HEAD |

_(Note: `f3a1c7e92b84` — gem_treasure_chance on ClassicRoundConfig — falls between `d2a91f3b5c07`
and `ba437f763581` in the chain and was applied during the D/G1 era.)_

---

### New files created (G2 era onward)

| File | Purpose |
|---|---|
| `app/models/subjects.py` | `Subject` model |
| `app/cli/maintenance.py` | `flask pilot-reset` command |
| `app/modes/classic/history_snapshot.py` | `freeze_round_history()` |
| `app/models/history.py` | `RoundHistory`, `RoundPlayerResult` models |
| `tests/test_classic_step_e.py` | 22-case Step E exit test |
| `tests/test_g2a_subject_foundation.py` | 11-case G2a test |
| `tests/test_g2b_subject_first_form.py` | 16-case G2b test |
| `tests/test_regression_g2c.py` | 28-case G2c regression test |
| `tests/test_regression_8_9.py` | 7-case R8_9 regression test |
| `tests/test_regression_10_7.py` | 9-case R10_7 regression test |
| `tests/test_regression_multi_round.py` | 35-case multi-round regression test |
| `tests/test_regression_history.py` | 39-case H0 regression test |
| `tests/test_pilot_sanity.py` | Pilot-reset sanity check |

---

### Architecture Decisions (new in this era)

**AD-carry-over:** Carry-over checkboxes in next_round form read via `'field_name' in request.form`
(raw checkbox pattern) rather than WTForms `.data`. WTForms `BooleanField(default=True)` returns
`True` when POST body is completely empty, making it unusable for optional checkbox semantics.

**AD-history:** `freeze_round_history()` is called from `end_round` BEFORE `db.session.commit()`,
after `game_round.ended_at` is set. Wallets still reflect round-end values at that point.
Carry-over resets (if any) happen in `next_round`, not in `end_round`.

---

### Bug Fixes (this era)

**BF-R8_9:** `ClassicSessionForm.validate_steal_winning_chest_count()` added — rejects
`winning_chests > chest_count`. Previously accepted invalid config; now 7/7 tests enforce it.

**BF-R10_7:** Group membership check in `lobby()` and `game()` moved before the
status-based redirect. Previously a non-member could reach the `game()` route on an active session
because the group check ran after the active-status branch. Now denied early regardless of status.

**BF-R1_1:** `allow_unsafe_werkzeug=True` added to `socketio.run()` in `run.py` to prevent
DeprecationWarning from blocking startup on newer Werkzeug versions.

**BF-R0_1:** All non-ASCII chars (checkmarks, arrows, emoji) replaced with ASCII equivalents
in `app/cli/maintenance.py` `click.echo()` calls to prevent `UnicodeEncodeError` on Windows
default console code page (`cp1252`).

---

### Test Results

| Suite | Result |
|---|---|
| Step E (`tests/test_classic_step_e.py`) | 22/22 ✓ |
| G2a (`tests/test_g2a_subject_foundation.py`) | 11/11 ✓ |
| G2b (`tests/test_g2b_subject_first_form.py`) | 16/16 ✓ |
| G2c (`tests/test_regression_g2c.py`) | 28/28 ✓ |
| R8_9 (`tests/test_regression_8_9.py`) | 7/7 ✓ |
| R10_7 (`tests/test_regression_10_7.py`) | 9/9 ✓ |
| Multi-round (`tests/test_regression_multi_round.py`) | 35/35 ✓ |
| H0 history (`tests/test_regression_history.py`) | 39/39 ✓ |
| **Cumulative total** | **416 across 12 suites** |

---

_Next entry will be added at the "H1 complete" checkpoint._

---

## Entry 012 — 2026-03-18 — Post-H0 Catch-up: H1 through D5 Complete

### Summary

Catch-up entry covering all work completed after Entry 011 (H0). This spans
H1/H2a/H2b/H2c (history UI + archive + export), A1 (gameplay fixes), B1 (yeargroup),
Diamonds Phase 1 MVP (D0 foundation through D5 store purchase limits), stabilization
fixes, next-round expansion, end-session redirect, and a 15-file test suite repair.

Migration HEAD advanced from `a1b2c3d4e5f6` → `d5a1b2c3d4e5` (7 new migrations).
Total test files: 36, all passing.

---

### Features Completed

| Step | Description | Tests | Migration |
|---|---|---|---|
| **H1** | Admin history UI — per-session round history view | 16 | — |
| **H2a** | Global admin round-history index (newest-first) | 13 | — |
| **H2b** | Safe delete/archive controls (archived_at on RoundHistory) | 20 | `b2c3d4e5f6a7` |
| **H2c** | History CSV export (session + global endpoints) | 19 | — |
| **A1** | 9 core gameplay/UX fixes (penalty floor, SC max-1, token cap, streak) | 19 | — |
| **B1** | Player yeargroup field + admin nav flow fixes + between-round problem_set edit | 20 | `b1a2c3d4e5f6` |
| **D0** | Diamonds progression foundation (4 new tables) | — | `d0e1f2a3b4c5` |
| **D1** | Admin diamond awards + store currency field (gold/gems) | 23+15 | `d1a2b3c4e5f6` |
| **D2** | Player Blacksmith / upgrade purchase flow (4 types, leveled costs) | 28 | — |
| **D2 SC** | Second Chance redesign (wrong-answer retry, max-1 capacity) | 13 | — |
| **D2b** | Catalog corrections + Blacksmith session gating | 8 | — |
| **D3** | Round-start RoundPlayerModifiers snapshot | 9 | — |
| **D3 Stock** | Stock clarity display in admin store | 19 | — |
| **D4** | Wiring frozen modifiers into gameplay (mine/treasure bonus, shield pct, steal cap) | 20 | — |
| **D4 Treasure** | Weighted single-roll side rewards (shield, SC, token) | 11+ | `d4a1b2c3e4f5` |
| **D4b** | Unified Treasure SC via inventory (is_system on StoreItem) | 9 | `d4b1a2b3c4d5` |
| **D5** | Store purchase limits (session_stock + per_player_limit replace quantity) | 10 | `d5a1b2c3d4e5` |
| **Stabilization** | StoreItemForm all 4 types, pilot-reset history tables, join savepoint | ~22 | — |
| **Next-round expansion** | Full config editable between rounds; carry-over toggles + validation | 33 | — |
| **End-session redirect** | Redirect to classic index after end_session | 3 | — |
| **Test suite repair** | FK cascade cleanup, encoding fixes, quantity→session_stock rename | 15 files | — |

---

### New DB Tables (D0)

| Table | Purpose |
|---|---|
| `player_progression` | 1 per player; persistent diamonds balance |
| `diamond_transaction` | Immutable audit ledger for all diamond changes |
| `player_upgrade` | 1 per player per upgrade_type; 4 types with leveled costs/effects |
| `round_player_modifiers` | Frozen snapshot per player per round; effective upgrade values |

### New/Modified Columns

| Table | Column | Migration |
|---|---|---|
| `round_history` | `archived_at` (DATETIME nullable) | `b2c3d4e5f6a7` |
| `player` | `yeargroup` (VARCHAR 32 nullable) | `b1a2c3d4e5f6` |
| `store_item` | `currency` (VARCHAR 10 default 'gold') | `d1a2b3c4e5f6` |
| `classic_round_config` | `treasure_active_shield_chance`, `treasure_second_chance_chance` (REAL) | `d4a1b2c3e4f5` |
| `store_item` | `is_system` (BOOLEAN default FALSE) | `d4b1a2b3c4d5` |
| `store_item` | `quantity` → `session_stock` (renamed); `per_player_limit` (INTEGER) | `d5a1b2c3d4e5` |

Current migration HEAD: `d5a1b2c3d4e5`

---

### Architecture Decisions (new in this era)

- **Second Chance** replaces "shield" semantics: wrong answer consumes SC, prevents penalty, rolls back attempt, reopens problem. Max capacity 1.
- **Blacksmith** blocked during active/waiting sessions (session gating).
- **Treasure side rewards** use weighted single-roll: at most one of shield/SC/token per treasure action. Sum of probabilities ≤ 1.
- **Unified Treasure SC** via hidden system StoreItem (is_system=True) instead of PlayerClassicState flag. Shares max-1 capacity with store SC.
- **Store purchase limits**: session_stock (session-wide cap) + per_player_limit (per-player cap); both -1 = unlimited.

---

### Test Suite Repair (separate session)

15 test files were repaired (zero production code changes):
- FK cascade cleanup in `_clean()` functions: explicit deletion order for models with cascade dependencies
- Windows encoding fixes: `PYTHONIOENCODING=utf-8` in subprocess environments
- `quantity` → `session_stock` field rename in Step B tests
- All 36 test files now pass cleanly.

---

## Entry 013 — 2026-03-20 — Player-Flow Migration + Legacy Modifier Retirement

### Summary

Completed the player-flow migration and retired the legacy round-scoped
`RoundPlayerModifiers` infrastructure. `SessionParticipantSnapshot` is now the
sole runtime frozen gameplay source. Two new migrations added. All tests
rewritten and passing.

Migration HEAD advanced from `d5a1b2c3d4e5` → `a1b2c3d4e5f7` (2 new migrations).

---

### Architecture Changes

**Player-flow migration (Steps 1–4):**
- Hub/dashboard is now the persistent player home
- Explicit Join is required for session participation
- Lobby no longer implicitly enrolls players
- `classic_join` no longer creates participation/session-init rows
- Joined unfinished players are routed back into session flow
- `SessionParticipantSnapshot` created at Join time, session-scoped

**Legacy modifier retirement:**
- `RoundPlayerModifiers` model class removed from codebase
- `snapshot_round_player_modifiers()`, `snapshot_single_player_modifiers()`,
  `get_round_player_modifiers()` functions removed from `app/services/progression.py`
- All production call sites in `routes.py` removed
- `round_player_modifiers` table dropped via migration `a1b2c3d4e5f7`

**Runtime read path:**
- All 6 event consumers in `events.py` use `get_session_player_modifiers()`
- Session-scoped snapshot is the sole frozen source for upgrade-derived effects
- `_DefaultModifiers` sentinel used when snapshot is absent (safety fallback)

---

### New Migrations

| Revision | Description |
|---|---|
| `0a38914b8e02` | Add `session_participant_snapshot` table |
| `a1b2c3d4e5f7` | Drop `round_player_modifiers` table (retired) |

---

### Test Changes

| Suite | Before | After | Change |
|---|---|---|---|
| D3 (`tests/test_regression_d3.py`) | 9 tests | 20 tests | Rewritten for SessionParticipantSnapshot |
| D4 (`tests/test_regression_d4.py`) | 20 tests | 35 tests | Rewritten for session-scoped modifiers |
| A1 (`tests/test_regression_a1.py`) | 19 tests | 25 tests | A1-11 updated to use `get_session_player_modifiers` |

All test suites pass: D3 20/20, D4 35/35, A1 25/25 (including Step E regression gate).

---

### Documentation Alignment

Updated to reflect current architecture:
- `docs/project_state.md` — milestone descriptions, DB models table, working features, test counts, migration history
- `docs/system_architecture.md` — folder structure, DB schema, migration history
- `docs/manual_test_guide.md` — progression model list, snapshot description
- `docs/bootstrap_prompt.txt` — AD-snap invariant updated
- `docs/dev_log.md` — this entry

---

### Cleanup

- Deleted `tmp_migration_verify.py` (temporary migration verification script)
- Replaced `round_player_modifiers` with `session_participant_snapshot` in cleanup SQL of `test_classic_step_a.py` and `test_classic_step_b.py`
- Removed stale references to `snapshot_round_player_modifiers` and "Step 4" from progression service docstrings

---

_Next entry will be added at the next feature checkpoint._

---

## Entry 014 — 2026-03-25 — Hub / Classic UI Stabilization + Shield Alignment + Docs Sync

### Summary

Recent work moved the repo beyond authored-content foundation work and into
playable-surface stabilization, supervision visibility, and documentation
synchronization.

This checkpoint groups the recent work that landed after the player-flow migration:
- Hub partial-refresh stabilization and session-control placement cleanup
- Classic player gameplay page cleanup and structure/fit polish
- Classic admin live supervision extension beyond leaderboard-only updates
- shield-mechanics alignment and player-facing visibility cleanup
- source-of-truth documentation synchronization

Migration head advanced from `c1d2e3f4a5b6` to `f1a2b3c4d5e6`.

---

### Architecture / Product-State Alignment

**Hub**
- Hub remains the persistent preparation space
- Join remains the runtime freeze boundary
- equip / unequip / face changes use server-rendered fragment refresh rather than full page reload or SPA state
- session readiness / Join control now lives inside the Hub status surface rather than a separate banner/status placeholder

**Classic gameplay page**
- player gameplay page now follows a stable 3-column contract:
  - left support rail
  - center gameplay workspace
  - right context rail
- center workflow panel uses explicit state modes instead of loose competing controls
- store now replaces the lower left-rail slot instead of stacking additional height
- right rail is the single location for leaderboard, round context, and action log

**Classic admin supervision**
- the existing admin live-update path now also updates:
  - solve counts per problem
  - steal-history / stolen-gold summary

**Shield model**
- one runtime anti-steal protection state remains authoritative:
  - `PlayerClassicState.shield_expires_at`
- manual `Shield Token` and reactive post-steal protection feed that same runtime state with separate base durations
- treasure “active shield” now grants a token instead of immediate runtime protection

---

### UI / Usability Outcomes

**Hub outcomes**
- no top session banner
- no standalone Session Status placeholder card
- async face/equip/unequip flow stabilized

**Classic gameplay outcomes**
- center problem/workflow contract is explicit and stable
- multiple choice fits the workflow area more efficiently
- left/right rails are consolidated and readable
- shield/protection status is clearer to players

---

### Documentation Alignment

Synchronized current docs:
- `docs/project_state.md`
- `docs/system_architecture.md`
- `docs/manual_test_guide.md`
- `docs/bootstrap_prompt.txt`

Historical hygiene:
- `docs/dev_log.md` remains append-only and historical
- checkpoint docs remain historical/reference-only rather than current source-of-truth

---

### Testing / Process Notes

Recent focused green areas include:
- Hub polish suites
- Classic admin live supervision
- shield alignment
- problem-system/editor slices still used as regression gates while UI work continued

Process rule carried forward:
- if tests or manual validation create Classic sessions, end them before closing the task
