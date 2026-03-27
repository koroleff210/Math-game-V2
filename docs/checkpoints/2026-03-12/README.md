# Checkpoint Archive — 2026-03-12

This folder contains snapshot docs taken when the project was packaged for backup/restore
onto a new laptop on **2026-03-12**.

## Contents

| File | What it captured |
|------|-----------------|
| `CHECKPOINT_STATUS.md` | Feature status, test counts, migration HEAD at snapshot time |
| `BACKUP_RESTORE.md` | Step-by-step backup/restore procedure for the project |

## Important — these are NOT the current source of truth

- The code, tests, and `docs/project_state.md` are always the authoritative source of truth.
- `CHECKPOINT_STATUS.md` reflects the state as of 2026-03-12 (migration HEAD `f2a3b4c5d6e7`,
  287 tests). Subsequent work (G2c, multi-round/carry-over, H0…) is NOT reflected here.
- `BACKUP_RESTORE.md` is still a useful procedural reference but the migration HEAD listed
  inside it is outdated — always check `flask db heads` for the current head.
- Do not use this folder as a spec for ongoing feature development.
