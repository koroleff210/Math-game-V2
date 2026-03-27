# Checkpoint Status — math_game_v2

**Checkpoint date:** 2026-03-12  
**Migration HEAD:** `f2a3b4c5d6e7` (g2a_topic_subject_fk)  
**Canonical startup:** `python run.py` (from `Game v2\` directory)  
**DB backend:** SQLite at `instance\math_game.db`  
**Python version:** 3.14.3  
**Total passing tests:** 287

---

## What is working at this checkpoint

### Core infrastructure
- Flask factory app (`create_app()`) with SQLite + Flask-Migrate
- Session-based auth (Flask-Login); admin flag on Player model
- CSRF protection on all forms (Flask-WTF)
- Flask-SocketIO with `async_mode='threading'` + `simple-websocket`

### Problem bank (admin)
- Subject CRUD (create, edit, delete) — 6 routes at `/admin/subjects/`
- Topic CRUD with subject FK (Topic.subject_id links to Subject)
- Problem CRUD — subject-first form with AJAX topic dropdown
- Problem list includes Subject column
- Problem Set CRUD + add/remove problems (many-to-many)

### Player and group management (admin)
- Player CRUD: create, edit (blank password = preserve hash), delete
- Group CRUD + many-to-many membership (add/remove players)
- Session group restriction (HTTP guard + Socket.IO guard)

### Classic Mode — full feature set
- Session lifecycle: create → waiting → active → finished
- Admin: create session (full config form), manage live session, store management
- Player: `/classic/play` → lobby → game → round_over routing
- Real-time Socket.IO events (join, answer, mine/treasure/steal/buy)
- Reward engine: Mine, Treasure Search (random range), First-solver bonus, Timer bonus
- Store: x2_mine, shield (wrong-answer absorber), steal_token, steal_shield items
- Gems: milestone (every N correct) + streak (K consecutive correct)
- Steal system: token-based, mini-game, no-targets fallback, reactive shield, manual shield
- Group restriction on sessions: unauthorized players blocked at HTTP + socket layers

### Maintenance CLI
- `flask pilot-reset --dry-run` — preview what would be deleted
- `flask pilot-reset --apply --yes` — backup + delete session/problem-bank data; preserve players/groups
- Output is ASCII-safe (Windows console compatible)

---

## Known deferred items (not part of this checkpoint)

| Item | Notes |
|------|-------|
| G2c: problem list subject filter | Filter dropdown on problem list and problem set detail |
| Step H: Session history | Admin view + per-player history |
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
| R8_9 | `tests/test_regression_8_9.py` | 7/7 |
| Pilot sanity | `tests/test_pilot_sanity.py` | pass |
| **Total** | | **287** |

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
| f2a3b4c5d6e7 | G2a: Topic.subject_id FK ← **HEAD** |

---

## Seeded credentials (default)

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Admin |
| player1 | player123 | Player |
| player2 | player123 | Player |

---

## Startup verification checklist

After restore or fresh setup, confirm:

1. `python run.py` starts without error
2. http://localhost:5000 shows the login page
3. Login as `admin` / `admin123` succeeds
4. Admin dashboard is visible
5. Topics and Problems pages load without error
6. (If restored from populated DB) Topics, Problems, Problem Sets, Players, Groups show existing data

---

## Architecture notes

- Flask instance variable inside `create_app()` is named `flask_app` — this is intentional
  (prevents name collision with the `app` package). Never rename it.
- DB uses Flask-SQLAlchemy 2.0 API (`db.session.get()`, not `.query.get()`)
- Lazy `'dynamic'` on `PlayerGroup.members` — call `.filter_by(...).first()` not `.all()` in templates
- Socket.IO uses `async_mode='threading'` — do NOT switch to gevent without testing
