# System Architecture

_Updated: 2026-03-25_

This file documents the current architecture and boundaries.
Use [project_state.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\project_state.md) for implementation status and [manual_test_guide.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\manual_test_guide.md) for practical verification.

---

## Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3.x |
| ORM | SQLAlchemy 2.x via Flask-SQLAlchemy |
| Migrations | Alembic via Flask-Migrate |
| Auth | Flask-Login |
| Real-time | Flask-SocketIO (`threading`) |
| DB | SQLite (`instance/math_game.db`) |
| Templates | Jinja2 |
| Graph rendering | Plotly in browser |

Canonical startup:

```powershell
.venv\Scripts\python.exe run.py
```

Current Alembic head:
- `f1a2b3c4d5e6`

---

## Documentation Roles

Canonical current docs:
- `docs/project_state.md`
- `docs/system_architecture.md`
- `docs/manual_test_guide.md`
- `docs/bootstrap_prompt.txt`

Historical/reference docs:
- `docs/dev_log.md`
- `docs/checkpoints/*`
- `classic_mode_description_v1_0.txt`
- `Diamonds_Upgrades_Roadmap_v1.txt`

---

## Top-Level Product Boundaries

### Authored content boundary
Canonical authored-content entities:
- `Subject`
- `Topic`
- `Problem`
- `ProblemSet`

Rule:
- `Problem` remains the root authored-question entity

### Live session/runtime boundary
Canonical live-session entities:
- `GameSession`
- `GameRound`
- Classic runtime state tables / services

### Persistent progression boundary
Persistent progression remains outside live Classic runtime state:
- upgrades / diamonds
- gear catalog / ownership / loadout

### Frozen runtime boundary
`SessionParticipantSnapshot` is the frozen runtime read model for progression-derived gameplay values.

Rule:
- active gameplay must not read live progression/gear rows directly
- Join is the boundary where runtime values freeze

---

## Hub and Join Boundary

### Hub role
The Hub is the persistent player preparation space.

Current responsibilities:
- avatar / face changes
- equip / unequip gear
- resource / bonus visibility
- session readiness / Join entry point

### Join boundary
Join creates or confirms runtime participation and frozen snapshot usage.

Rules:
- Hub state is live and persistent
- Classic gameplay reads the frozen session snapshot and round/runtime state, not live Hub rows
- the Hub remains server-rendered and uses fragment refresh rather than SPA state

---

## Problem System V1

### Root model
- `Problem`

### Child models
- `ProblemBlock`
  - ordered body blocks
  - current block types:
    - `rich_text`
    - `image`
    - `graph`
- `ProblemAcceptedAnswer`
  - ordered accepted text-input variants
- `ProblemChoiceOption`
  - ordered MC options
  - exactly one correct option enforced by application/admin validation

### Legacy compatibility
Legacy fields still exist on `Problem`:
- `prompt_text`
- `answer_text`
- `image_path`
- `graph_config_json`

Compatibility rule:
- if structured child rows exist, they are authoritative
- otherwise content/answer fallback goes through compatibility helpers

### Answer types
Current supported `Problem.answer_type` values:
- `text_input`
- `multiple_choice`

Gameplay validation:
- `text_input` validates normalized text against accepted answers
- `multiple_choice` validates by stored option ID

---

## Problem Content Rendering Path

Canonical server-side interpretation lives in:
- `app/services/problem_content.py`

Key responsibilities:
- normalize authored problem body into gameplay/admin view structures
- normalize accepted answers
- normalize/build MC option view
- normalize graph config
- build graph render payloads

Current anti-drift rule:
- admin preview and Classic gameplay must keep sharing the same interpreted body/graph path
- do not fork a second problem renderer for Classic

---

## Unified Problem Editor

### Canonical editor
The unified problem editor is now the normal create/edit surface.

Current layout contract:
- full-width top:
  - metadata
  - answer type
- lower workspace:
  - left = body blocks + answer section
  - right = preview

### Authoring behavior
- `text_input`
  - accepted answers shown
- `multiple_choice`
  - MC options shown

### Block authoring
Current block types:
- rich text
- image
- graph

Preview rule:
- preview uses the same content interpretation path that Classic gameplay uses

---

## Graph Architecture

### Canonical storage
Canonical saved graph state remains:
- `ProblemBlock.graph_config_json`

Teacher-facing equation input is an authoring convenience layer, not a second canonical storage format.

### Normalized graph model
Current normalized graph config includes:
- viewport:
  - `x_min`
  - `x_max`
  - `y_min`
  - `y_max`
  - `x_label`
  - `y_label`
  - `show_grid`
- `elements`:
  - functions
  - points

Supported function families:
- `linear`
- `quadratic`
- `exponential`
- `sine`
- `cosine`

Optional per-function range:
- `x_min`
- `x_max`

### Authoring flow
Admin graph UI currently uses:
- graph settings
- equation rows
- point rows

Backend flow:
1. teacher-facing rows
2. parser/converter helpers
3. normalized graph config
4. Plotly payload builder
5. shared renderer in admin preview and Classic

### Legacy reconstruction rule
Existing saved graph elements are reconstructed into equation/point rows where practical.

If an element cannot round-trip through the narrow supported syntax:
- it is preserved
- it is surfaced as legacy-only in the editor
- it is not silently dropped

---

## Problem Set Builder

Current builder model:
- top filters
- left candidates
- middle preview
- right set membership

Current filters:
- subject
- topic
- difficulty
- answer type

Membership rule:
- add/remove is immediate and DB-backed
- there is no separate builder save step for membership changes

---

## Classic Runtime Architecture

### Main gameplay layers
Classic runtime combines:
- DB-backed session/round/player state
- in-memory per-session timing/state helpers
- Socket.IO event flow
- server-rendered player/admin templates

### Current player page contract
Current gameplay page structure:
- left rail
  - `Player / Status`
  - `Actions`
  - `This Round` or `Store`
- center
  - problem tabs
  - fixed problem window
  - fixed workflow panel
- right rail
  - `Leaderboard`
  - `Round Context`
  - `Action Log`

### Workflow-state contract
Center workflow panel supports:
- solve
- action choice
- steal target choice
- steal mini-game
- result/transition

Rule:
- keep prompt/content in the problem window
- keep answer/action controls in the workflow panel

### Runtime content use
Classic currently consumes Problem System V1 as follows:
- body display uses structured interpreted content
- legacy-only problems still work through compatibility fallback
- text-input and MC switch by `Problem.answer_type`
- graph blocks render in the same content body area

Not implemented:
- graph-as-answer
- draggable graph gameplay objects
- separate student graph-editing path

---

## Admin Live Supervision

Current live admin supervision uses one shared Classic admin watch path.

Current live-updated regions:
- leaderboard
- solve counts per problem
- steal history / stolen-gold summary

Rule:
- extend supervision through the existing Classic admin watch/socket path
- do not build a second competing admin live-update system

---

## Shield Runtime Model

### Canonical runtime state
Timed anti-steal protection is represented by:
- `PlayerClassicState.shield_expires_at`

### Trigger sources
Two trigger sources write into the same runtime protection state:
- manual `Shield Token`
- reactive post-steal protection

### Duration model
Separate configurable base durations exist for:
- active/manual shield duration
- reactive shield duration

Both still pass through the shared modifier pipeline.

### Current semantics
- `Second Chance` = wrong-answer absorber
- `Shield Token` = stored manual anti-steal token
- `Protected` = currently under timed anti-steal protection

Rule:
- do not reintroduce ambiguous generic `shield` wording in player-facing gameplay UI when the distinction matters

---

## Related Systems Still Present

These are implemented and active but not fully re-described here:
- diamonds progression
- upgrades
- persistent gear / avatar / ownership / loadout
- Blacksmith
- round history / archive

They remain part of the architecture; this document just keeps focus on current active boundaries rather than repeating every detail.
