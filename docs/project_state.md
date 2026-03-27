# Project State

_Updated: 2026-03-25_

This is the current product-status document.
Use [system_architecture.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\system_architecture.md) for boundaries/data flow and [manual_test_guide.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\manual_test_guide.md) for practical verification.

Historical/progress docs:
- `docs/dev_log.md`
- `docs/checkpoints/*`

Those are reference-only and should not be treated as the current source of truth.

---

## Current Snapshot

Current date:
- `2026-03-25`

Current Alembic head:
- `f1a2b3c4d5e6`

Current repo posture:
- Problem System V1 is live and is now the normal authored-content path
- Classic Mode is playable end-to-end and includes the current session/store/steal/history stack
- Hub is the persistent player preparation space before Join
- recent work has shifted from core architecture building into stabilization, UI fit/polish, and supervision visibility

Current documentation split:
- `project_state.md` = current implemented state and current deferred items
- `system_architecture.md` = architectural boundaries and data flow
- `manual_test_guide.md` = current manual verification paths
- `bootstrap_prompt.txt` = compact fresh-chat bootstrap
- `dev_log.md` / `docs/checkpoints/*` = historical context only

---

## Implemented Systems

### Core Admin / Auth
- Flask auth via Flask-Login
- admin and player roles
- player CRUD
- class/group CRUD
- subject CRUD
- topic CRUD

### Problem System V1
- `Problem` remains the root authored-question entity
- structured body content under `ProblemBlock`
- supported block types:
  - `rich_text`
  - `image`
  - `graph`
- text-input accepted answers under `ProblemAcceptedAnswer`
- multiple-choice options under `ProblemChoiceOption`
- legacy compatibility remains in place for older `Problem` fields

### Unified Problem Editor
- one canonical create/edit page
- full-width metadata and answer-type controls
- lower workspace:
  - left = body blocks + answer section
  - right = preview
- answer-mode-specific authoring:
  - `text_input`
  - `multiple_choice`
- preview and gameplay share the same problem-content interpretation path

### Graph Authoring / Rendering
- canonical saved graph state remains `ProblemBlock.graph_config_json`
- admin graph authoring uses:
  - graph settings
  - equation rows
  - point rows
- parser/converter supports:
  - linear
  - quadratic
  - exponential
  - sine
  - cosine
- optional per-equation `x_min` / `x_max`
- Plotly remains the shared rendering layer for admin preview and Classic gameplay

### Problem Set Builder
- current builder is a server-rendered 3-column workspace
- top filters:
  - subject
  - topic
  - difficulty
  - answer type
- workspace:
  - left = filtered candidates
  - middle = preview
  - right = set membership
- add/remove is immediate and DB-backed

### Classic Mode Runtime
- session create/manage flow
- multi-round lifecycle:
  - create
  - waiting
  - active
  - waiting between rounds
  - finished
- player flow:
  - `/classic/play`
  - lobby
  - gameplay page
  - round-over / return routing
- live Socket.IO gameplay events
- current gameplay supports:
  - text-input answers
  - multiple-choice answers by option ID
  - graph block rendering
  - mine / treasure / steal / store actions
  - gems and streaks
  - round history

### Classic Player Gameplay Page
- current page uses a stable 3-column structure
- left rail:
  - `Player / Status`
  - `Actions`
  - `This Round` or `Store` lower-slot swap
- center:
  - problem tabs
  - fixed problem window
  - fixed workflow panel
- right rail:
  - `Leaderboard`
  - `Round Context`
  - `Action Log`
- workflow panel uses explicit state modes:
  - solve
  - action choice
  - steal target
  - steal mini-game
  - result

### Hub / Persistent Preparation
- Hub is the persistent player preparation/dashboard page
- Join is the runtime boundary where session values freeze
- no full document reload on face/equip/unequip actions
- current Hub uses server-rendered fragment refresh, not SPA state
- session readiness/join controls now live inside the Hub gear/status surface rather than a separate banner/placeholder card

### Persistent Progression / Gear
- diamonds progression
- upgrades
- persistent gear catalog
- ownership / equip / loadout
- avatar preview layering
- frozen runtime read path through `SessionParticipantSnapshot`

### Admin Live Supervision
- admin leaderboard already updates live
- solve-count summary also updates live
- steal-history / stolen-gold summary also updates live
- same Classic admin Socket.IO watch path is reused for supervision updates

### Shield Model Alignment
- one runtime timed anti-steal protection state:
  - `PlayerClassicState.shield_expires_at`
- two trigger paths:
  - manual `Shield Token`
  - reactive post-steal protection
- separate base durations for:
  - active/manual shield duration
  - reactive shield duration
- treasure "active shield" now grants a `Shield Token`, not immediate runtime protection
- current player-facing terms are:
  - `Second Chance`
  - `Shield Token`
  - `Protected`

---

## Current UX / UI Reality

### Admin authored-content area
- unified problem editor is functional and structured
- graph editor is teacher-facing and practical, but not a final polished graphing tool
- problem-set builder is stable and server-rendered; not a SPA

### Player areas
- Hub is stable enough for gameplay prep testing
- Classic gameplay page has completed a cleanup sequence:
  - center workspace hardened
  - left rail consolidated
  - store lower-slot replacement behavior implemented
  - right rail consolidated
  - naming normalized
  - fit/spacing polished
- current work in this area is polish/stabilization, not architecture rebuild

---

## Implemented vs Deferred

### Implemented now
- structured authored problems in admin and Classic
- MC authoring and gameplay
- graph blocks in admin preview and Classic
- equation/point graph authoring UI
- problem-set builder workspace
- Hub partial-refresh UX
- Classic player-page cleanup and stable 3-column structure
- admin live supervision for leaderboard, solve counts, and steal history
- aligned shield semantics and player shield-status visibility

### Still deferred / intentionally not built
- problem-bank keyword search
- drag/drop block ordering
- drag/drop problem-set ordering
- graph-as-answer mechanics
- draggable graph objects
- arbitrary symbolic graph parser
- media library / image upload workflow
- final art/theme pass for Hub or Classic gameplay page
- mobile portrait redesign
- broad admin styling overhaul
- cleanup/migration pass removing all legacy problem fields

---

## Current Testing State

Current `tests/` inventory:
- 59 Python test files

Recent focused green areas include:
- problem system slices 1-3
- unified problem editor workflow
- graph equation parser/converter and graph UI pass
- problem-set builder
- Hub polish / avatar / gear refresh behavior
- Classic admin live supervision
- shield alignment

Testing policy note:
- this document does not claim the entire suite runs on every change
- use targeted suites relevant to the touched area
- when manual or automated testing creates Classic sessions, end them before closing the task

---

## Recommended Near-Term Roadmap

Near-term work should be treated as incremental polish/stabilization, not foundational redesign.

### 1. Classic player UX polish
- continue fit/readability improvements on the stable gameplay page
- improve small status/feedback visibility issues without changing the page contract

### 2. Hub / progression usability
- continue local Hub quality-of-life polish using the existing server-rendered fragment model
- avoid SPA/frontend-state expansion unless clearly necessary

### 3. Admin supervision / operational clarity
- extend or refine live supervision only through the existing Classic admin watch path
- keep stale-session recovery and session hygiene practical for local testing

### 4. Authored-content quality-of-life
- small editor/builder polish is still reasonable
- larger editor redesigns remain deferred

---

## Historical Docs

These remain useful background/reference docs but are not current specs:
- `docs/dev_log.md`
- `docs/checkpoints/2026-03-12/*`
- `docs/checkpoints/2026-03-12-h0/*`
- `classic_mode_description_v1_0.txt`
- `Diamonds_Upgrades_Roadmap_v1.txt`
