# Checkpoint Status — math_game_v2

**Checkpoint date:** 2026-03-12
**Migration HEAD:** `a1b2c3d4e5f6` (h0_round_history)
**Canonical startup:** `python run.py` (from `Game v2\` directory)
**DB backend:** SQLite at `instance\math_game.db`
**Python version:** 3.14.3
**Total passing tests:** ~361 (322 prior + 39 history)

---

## What is working at this checkpoint

### Core infrastructure
- Flask factory app (`create_app()`) with SQLite + Flask-Migrate
- Session-based auth (Flask-Login); admin flag on Player model
- CSRF protection on all forms (Flask-WTF)
- Flask-SocketIO with `async_mode='threading'` + `simple-websocket`

### Problem bank (admin)
- Subject CRUD (6 routes at `/admin/subjects/`)
- Topic CRUD with subject FK (`Topic.subject_id`)
- Problem CRUD — subject-first form with AJAX topic dropdown; subject column on list
- Subject filter on problems list + problem set detail pages (G2c)
- Problem Set CRUD + add/remove problems (many-to-many)

### Player and group management (admin)
- Player CRUD: create, edit (blank password = preserve hash), delete
- Group CRUD + many-to-many membership (add/remove players)
- Session group restriction (HTTP guard + Socket.IO guard)

### Classic Mode — full feature set
- Session lifecycle: create → waiting → active → waiting (between rounds) → finished
- **Multi-round sessions**: end_round returns to `waiting`; next_round starts a new GameRound
  with carry-over gold/gems checkboxes; end_session closes permanently
- Admin: create session (full config form), manage live session, store management
- Player: `/classic/play` → lobby → game → round_over routing
- Real-time Socket.IO events (join, answer, mine/treasure/steal/buy)
- Reward engine: Mine, Treasure Search (random range), First-solver bonus, Timer bonus
- Store: x2_mine, shield (wrong-answer absorber), steal_token, steal_shield items
- Gems: milestone (every N correct) + streak (K consecutive correct)
- Steal system: token-based, mini-game, no-targets fallback, reactive shield, manual shield

### Round History persistence (Step H0)
- `RoundHistory` table: one frozen row per finished round
- `RoundPlayerResult` table: one frozen row per player per finished round
- Snapshot captured at `end_round` before any wallet carry-over resets
- Frozen fields: final gold, gems, place, per-player answer stats, round aggregates,
  player name snapshot, problem set name snapshot, group name snapshot
- Idempotent: double end_round call does not create duplicate rows
- 39/39 history regression tests pass

### Maintenance CLI
- `flask pilot-reset --dry-run` — preview what would be deleted
- `flask pilot-reset --apply --yes` — backup + delete session/problem-bank data; preserve players/groups

---

## Known deferred items (not part of this checkpoint)

| Item | Notes |
|------|-------|
| H1: admin history UI | Read past round history (view by session) |
| Step I: Diamonds currency | PlayerWallet.diamonds + earn/spend |
| Team Mode | Not started |
| Boss Rush Mode | Not started |
| Image upload | image_path is a free-text field only |
| Plotly graph rendering | graph_config_json stored but not rendered |
| Problem search / keyword filter | No search in admin UI yet |

---

## Test suites and counts

| Suite | File | Count |
|-------|------|-------|
| Step A | `test_classic_step_a.py` | 32/32 |
| Step B | `test_classic_step_b.py` | 48/48 |
| Step C | `tests/test_classic_step_c.py` | 38/38 |
| Step D | `tests/test_classic_step_d.py` | 131/131 |
| Step E | `tests/test_classic_step_e.py` | 22/22 |
| G2a | `tests/test_g2a_subject_foundation.py` | 11/11 |
| G2b | `tests/test_g2b_subject_first_form.py` | 16/16 |
| G2c | `tests/test_regression_g2c.py` | 28/28 |
| R8_9 | `tests/test_regression_8_9.py` | 7/7 |
| Multi-round | `tests/test_regression_multi_round.py` | 35/35 |
| Round history | `tests/test_regression_history.py` | 39/39 |
| Pilot sanity | `tests/test_pilot_sanity.py` | pass |
| **Total** | | **~361** |

---

## Migration history

| Revision | Description |
|----------|-------------|
| 98928f854543 | player table |
| 61de12ce8104 | topic, problem, problem_set tables |
| 1a869402f090 | GameSession, GameRound, RoundPlayer, PlayerAnswer |
| eb6a766ae410 | Classic Mode models + GameRound.problem_id nullable |
| 3b6e8c2b3f19 | StoreItem + PlayerInventory |
| f3a1c7e92b84 | Step C: gem_treasure_chance |
| bde9f2a62232 | Step C columns: ClassicRoundConfig (3) + PlayerWallet.gems |
| c4f7e8d21a30 | Step D-1: StealEvent, ClassicRoundConfig +8 steal cols, PlayerWallet +steal_tokens |
| d2a91f3b5c07 | Step D-1b: PlayerClassicState table; col rename |
| ba437f763581 | G1: PlayerGroup, player_group_members M2M, GameSession.group_id + label |
| e1f2a3b4c5d6 | G2a: Subject model |
| f2a3b4c5d6e7 | G2a: Topic.subject_id FK |
| a1b2c3d4e5f6 | H0: round_history + round_player_result tables ← **HEAD** |
