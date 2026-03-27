# Setup Guide — New Windows Laptop

Follow these steps in order to get math_game_v2 running on a fresh Windows machine
from a backup copy of the project folder.

---

## Prerequisites

### 1. Python 3.14.3

The project was developed and tested with **Python 3.14.3 exactly**.

- Download from https://www.python.org/downloads/release/python-3143/
- At the installer: check **"Add python.exe to PATH"**
- Verify after install:
  ```
  python --version
  ```
  Expected: `Python 3.14.3`

> Other Python 3.x versions may work, but 3.14.3 is the only confirmed-working version.
> Do not use Python 3.12 or below — the venv will need to be recreated regardless.

---

## Steps

### 2. Get the project folder

Copy the `Game v2\` folder to your machine. Place it anywhere convenient, e.g.:
```
C:\Users\<you>\Desktop\Game\Game v2\
```

The folder should contain:
```
Game v2/
  app/
  config.py
  docs/
  instance/         ← contains math_game.db (the database)
  migrations/
  requirements.txt
  run.py
  seed.py
  tests/
```

### 3. Create a virtual environment

Open a PowerShell or CMD window. Navigate to the `Game v2\` folder:

```powershell
cd "C:\Users\<you>\Desktop\Game\Game v2"
python -m venv .venv
```

This creates a `.venv\` folder. Do NOT copy a venv from another machine — always create fresh.

### 4. Activate the virtual environment

```powershell
.venv\Scripts\Activate.ps1
```

If you get an execution policy error, run this first (once, as admin):
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate again. Your prompt should show `(.venv)`.

### 5. Install dependencies

```powershell
pip install -r requirements.txt
```

This installs all pinned versions. Expected output ends with "Successfully installed ...".

### 6. Optional — create a .env file for config overrides

Copy `.env.example` to `.env` and edit as needed:
```powershell
copy .env.example .env
```

For local development, the defaults in `.env.example` are fine.
The app works without a `.env` file — environment variables in `.env.example` all have
safe defaults built into `config.py`.

### 7. Set up the database

#### Restore path (recommended — preserves all data)

If you have a backup of `instance\math_game.db`, copy it to:
```
Game v2\instance\math_game.db
```

Then verify the DB is at the correct schema version (the app does this automatically
on startup — no manual migration needed for a restored DB from the same checkpoint).

#### Fresh setup (no backup DB)

If starting with no database at all:
```powershell
python -m flask db upgrade
```

Then seed initial users:
```powershell
python seed.py
```

Seeded credentials:
- Admin: `admin` / `admin123`
- Player 1: `player1` / `player123`
- Player 2: `player2` / `player123`

### 8. Start the app

```powershell
python run.py
```

Expected output (approximately):
```
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://<your-LAN-ip>:5000
```

### 9. Open in browser

- **This machine:** http://localhost:5000
- **Another device on same LAN:** http://\<your-ip\>:5000  (use the IP shown in startup output)

### 10. Verify it works

1. Open http://localhost:5000 — should show the login page
2. Log in as `admin` / `admin123`
3. You should see the admin dashboard
4. Navigate to Topics, Problems, Problem Sets — confirm data is present if restoring from backup

---

## Trouble-shooting

| Problem | Fix |
|---------|-----|
| `python` not found | Add Python to PATH, or use full path `C:\Users\...\AppData\Local\Programs\Python\Python314\python.exe` |
| `Activate.ps1` blocked | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| Port 5000 already in use | Kill the other process or change port in `run.py` |
| DB not found / empty tables | Confirm `instance\math_game.db` is present; if not, run `flask db upgrade` then `seed.py` |
| Packages wrong version | Delete `.venv`, create fresh, run `pip install -r requirements.txt` again |

---

## Summary of canonical commands

| Purpose | Command |
|---------|---------|
| Create venv | `python -m venv .venv` |
| Activate venv | `.venv\Scripts\Activate.ps1` |
| Install packages | `pip install -r requirements.txt` |
| Apply DB migrations (fresh only) | `python -m flask db upgrade` |
| Seed users (fresh only) | `python seed.py` |
| **Start the app** | **`python run.py`** |
| Run tests | `python -m pytest tests\` |
