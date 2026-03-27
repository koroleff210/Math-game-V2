# math_game_v2

Flask + SQLAlchemy + Socket.IO classroom multiplayer game with:
- Classic live session gameplay
- admin-authored problem bank
- unified structured problem editor
- problem-set builder workspace
- persistent progression, diamonds, and gear

## Quick Start

```powershell
cd "C:\Users\korol\OneDrive\Desktop\Game\Game v2"
.venv\Scripts\python.exe run.py
```

Open: [http://localhost:5000](http://localhost:5000)

Default admin:
- `admin` / `admin123`

## Canonical Docs

Use these as the current source of truth:
- [docs/project_state.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\project_state.md) — current implemented status, roadmap, migration head, and known limits
- [docs/system_architecture.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\system_architecture.md) — architecture boundaries, core models, and problem-system structure
- [docs/manual_test_guide.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\manual_test_guide.md) — current manual test flows for admin authoring and Classic smoke testing
- [docs/bootstrap_prompt.txt](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\bootstrap_prompt.txt) — short new-chat bootstrap

## Current Snapshot

As of 2026-03-24:
- current Alembic head: `c1d2e3f4a5b6`
- repo test folder contains 56 Python test files
- Problem System V1 is implemented through:
  - structured body blocks
  - multiple accepted answers
  - multiple choice
  - graph blocks
  - unified create/edit problem editor
  - equation-based graph authoring UI
  - Classic structured problem rendering
  - problem-set builder workspace

## Historical / Reference Docs

These are retained for context, not as current source-of-truth docs:
- [classic_mode_description_v1_0.txt](C:\Users\korol\OneDrive\Desktop\Game\Game v2\classic_mode_description_v1_0.txt)
- [Diamonds_Upgrades_Roadmap_v1.txt](C:\Users\korol\OneDrive\Desktop\Game\Game v2\Diamonds_Upgrades_Roadmap_v1.txt)
- [docs/checkpoints/2026-03-12/README.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\checkpoints\2026-03-12\README.md)

## Setup / Restore

- fresh-machine setup: [SETUP_NEW_LAPTOP.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\SETUP_NEW_LAPTOP.md)
- checkpoint restore reference: [docs/checkpoints/2026-03-12/BACKUP_RESTORE.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\checkpoints\2026-03-12\BACKUP_RESTORE.md)
