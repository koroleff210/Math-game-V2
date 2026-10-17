# Cleanup inventory for the online pilot

_2026-10-01. Inventory only; no gameplay function has been removed._

## Safe maintenance already done

- Replaced outdated March status/roadmap text with a current project map.
- Corrected Boss Rush labels and comments that still described implemented
  battle mechanics as deferred.
- Replaced one SQLite-only backfill statement in an older migration with
  portable SQLAlchemy execution. Existing migrated databases are unaffected.
- Added separate production setup. Local development startup and seed scripts
  still work as before.

## Candidates for later cleanup

| Area | Evidence | Condition before removal or rewrite |
|---|---|---|
| Team package stub | No registered route or live handler | Decide whether Team is in release scope; preserve flag and data compatibility until then |
| Root-level scratch verification files and old JSON results | `tmp_classic_core_verify.py`, `deep_*results.json`, `regression_results.json` | Confirm no current runner or reference uses them; archive useful results |
| Legacy `Problem` fields | Structured content is canonical, but fallback still reads old fields | Migrate all old rows and remove fallback only after importer and gameplay verification |
| Hard-coded old IB Physics source path | Importer defaults to a Windows desktop path and old bank layout | Build the v4 importer first; keep old import tooling for reproducibility |
| Classic process-local state | Pending actions and locks in `app/modes/classic/state.py` | Replace with persistent/shared state before multi-instance hosting; do not simply delete |
| Maintenance reset commands and local seed data | Useful for local testing; destructive on a real database | Keep registered but document/admin-gate them; never call them in the deployment path |
| Historical plans and logs | March checkpoints and append-only log describe past phases | Keep as historical references rather than deleting provenance |

## Cleanup rule

Make each cleanup change in a small diff. First identify every caller (including
Jinja templates, Socket.IO event names, CLI registrations, and migrations),
then run the affected direct-script checks and a manual two-player flow.
Preserve all user-visible capabilities and saved data. Do not delete migration
history from a database that has applied it.
