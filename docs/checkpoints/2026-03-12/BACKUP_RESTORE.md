# Backup and Restore Guide

This guide explains exactly what to back up, what to skip, and how to restore
math_game_v2 on another Windows laptop from the checkpoint backup.

---

## What to back up

### Essential — must include

| Path | Why |
|------|-----|
| `app\` | All source code (models, routes, templates, static, socket handlers) |
| `config.py` | App configuration |
| `run.py` | Entry point |
| `seed.py` | User seeder |
| `requirements.txt` | Pinned dependencies |
| `migrations\` | All Alembic migration scripts (schema history) |
| `instance\math_game.db` | **The database** — all players, sessions, problem bank, groups |
| `docs\` | Project documentation and bootstrap prompts |
| `tests\` | Regression and exit test suites |
| `.env` (if created) | Local config overrides (if any non-default values were set) |

### Back up only if modified

| Path | Why |
|------|-----|
| `instance\backups\` | SQLite snapshots created by `flask pilot-reset`; only needed if you want them |
| `app\static\` | CSS/JS/images; already in source, but include if any custom assets were added |

### Skip — do NOT copy

| Path | Why |
|------|-----|
| `.venv\` | Python virtual environment — recreate fresh on the new machine |
| `__pycache__\` (anywhere) | Compiled bytecode — regenerated automatically |
| `.pytest_cache\` | Test runner cache — regenerated automatically |
| `instance\app.db` | Empty artifact (0 bytes) — ignore |
| `server_out.log`, `server_err.log` | Runtime log files — not needed |
| `deep_gameplay_results.json`, `deep_ids.json`, `regression_results.json` | Old test artifact files — not needed |
| `tmp_run_server.py` | Temporary test helper — not needed |

---

## Quick backup (Windows PowerShell)

Simplest approach: copy the whole `Game v2\` folder, then delete the exclusions on the destination.

Or use `robocopy` to skip `.venv` and pycaches automatically:

```powershell
robocopy "C:\Users\<you>\Desktop\Game\Game v2" "D:\Backup\Game v2" /E /XD .venv __pycache__ .pytest_cache /XF *.pyc server_out.log server_err.log
```

Replace `D:\Backup\` with your backup destination (USB drive, cloud folder, etc.).

---

## Database backup

The database is the single most important file. Back it up separately before any large changes:

1. Stop the app (Ctrl+C in the terminal running `run.py`)
2. Copy `instance\math_game.db` to a safe location

Or use the built-in backup command (while app is running):
```powershell
python -m flask pilot-reset --dry-run
```
To actually create a backup snapshot:
```powershell
python -m flask pilot-reset --apply --yes
```
This creates a timestamped copy in `instance\backups\` before any changes.

---

## Restore procedure (step by step)

### On the new Windows laptop:

**Step 1 — Copy files**

Copy the backed-up `Game v2\` folder to the new machine. Example destination:
```
C:\Users\<you>\Desktop\Game\Game v2\
```

**Step 2 — Install Python 3.14.3**

Download from https://www.python.org/downloads/release/python-3143/  
Check "Add python.exe to PATH" during install.

Verify:
```powershell
python --version
# Expected: Python 3.14.3
```

**Step 3 — Create a fresh virtual environment**

```powershell
cd "C:\Users\<you>\Desktop\Game\Game v2"
python -m venv .venv
```

**Step 4 — Activate the venv**

```powershell
.venv\Scripts\Activate.ps1
```
(If blocked: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`)

**Step 5 — Install dependencies**

```powershell
pip install -r requirements.txt
```

**Step 6 — Verify the database is in place**

Check that this file exists and is NOT empty:
```
instance\math_game.db
```

If it is missing or 0 bytes, you need to restore from your backup copy.

**Step 7 — Do NOT run flask db upgrade on a restored DB**

The restored `math_game.db` is already at the correct migration HEAD (`f2a3b4c5d6e7`).
Running extra migrations on a known-good backup could cause drift.

> **Rule:** Copy DB from backup → start app directly.  
> Only run `flask db upgrade` if you are setting up with a completely fresh (empty) DB.

**Step 8 — Start the app**

```powershell
python run.py
```

**Step 9 — Verify**

1. Open http://localhost:5000
2. Log in as `admin` / `admin123`
3. Check admin dashboard — navigate to Topics, Problems, Problem Sets
4. Confirm players and groups are present under Admin → Players / Groups

---

## Fresh setup (no backup DB)

If you have no DB backup and need to start fresh:

```powershell
# After creating venv and installing requirements:
python -m flask db upgrade     # creates empty DB at correct schema
python seed.py                 # creates default admin + 2 players
python run.py                  # start
```

Note: A fresh setup will have an empty problem bank and no sessions.
You will need to create Topics, Problems, Problem Sets, and Groups from the admin UI.

---

## Migration HEAD reference

Current checkpoint migration HEAD: `f2a3b4c5d6e7` (g2a_topic_subject_fk)

To check the current DB version:
```powershell
python -m flask db current
```
Expected output (on a correctly restored DB): `f2a3b4c5d6e7 (head)`

If you see a different revision, do NOT run `flask db upgrade` blindly — investigate first.

---

## Checklist before moving to another laptop

- [ ] App starts cleanly with `python run.py`
- [ ] `instance\math_game.db` is present and non-empty (200 KB+)
- [ ] Login page works at http://localhost:5000
- [ ] Admin dashboard is reachable
- [ ] At least one topic/problem/problem set exists in the DB (if using populated checkpoint)
- [ ] `requirements.txt` is up to date (compare with `pip list`)
- [ ] No secrets or passwords are hardcoded in `.env` if copying that file
