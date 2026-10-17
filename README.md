# Game v2

The live game is at **https://game.korephysics.com/**. See [live operation and shared student login](docs/korephysics_live.md) for account linking, backups, deployment evidence and current limits.

Flask, SQLAlchemy, and Socket.IO classroom math/physics game. Local development uses SQLite; the first self-hosted Internet pilot uses Docker Compose, PostgreSQL, and Caddy. For the audited feature map and v4 bank assessment, read [Project State](docs/project_state.md).

## Run locally

```powershell
.venv\Scripts\python.exe run.py
```

Open `http://localhost:5000`. The seed scripts create demo credentials (`admin/admin123` and player accounts); these are for local development only. `run.py` currently enables debug mode and binds to the LAN.

## Implemented and planned

- Classic individual mode with Mine, Treasure, and Steal is implemented.
- Boss Rush has live battle, recovery, abilities, rounds, and rewards.
- Team mode is a stub.
- Expedition is a separate sibling prototype and is not part of this app.
- The admin problem editor and external IB Physics import exist. The current game database contains old-bank imports; Questionbank v4 is in the sibling IB Physics Question System and needs an explicit migration.

## Documentation

- [Current state and release roadmap](docs/project_state.md) — current source of truth for status.
- [Self-hosted deployment](docs/self_hosted_deployment.md) — current Ubuntu/Docker Compose pilot path with fresh accounts and an empty problem bank.
- [Earlier hosted pilot notes](docs/online_pilot.md) — superseded Render option, retained for reference.
- [Cleanup inventory](docs/cleanup_inventory.md) — preservation rules and candidates for later refactoring.
- [System architecture](docs/system_architecture.md) — implementation boundaries; review its March-era details against code when changing a subsystem.
- [Manual test guide](docs/manual_test_guide.md) — Classic-focused smoke guide that needs extension before release.
- [New chat bootstrap](docs/bootstrap_prompt.txt) — short onboarding note.
- [Fresh laptop setup](SETUP_NEW_LAPTOP.md) — local Windows setup, not production deployment.

`docs/dev_log.md`, `docs/checkpoints/`, `docs/archive/`, `classic_mode_description_v1_0.txt`, and `Diamonds_Upgrades_Roadmap_v1.txt` are historical references, not active plans.
