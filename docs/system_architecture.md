# System Architecture

_Updated: 2026-03-30_

This file documents current architectural boundaries and runtime/data-flow rules.
Use [C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\project_state.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\project_state.md) for status and [C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\manual_test_guide.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\manual_test_guide.md) for manual verification.

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

## Documentation Roles

Canonical active docs:
- `docs/project_state.md`
- `docs/system_architecture.md`
- `docs/manual_test_guide.md`
- `docs/bootstrap_prompt.txt`

Historical/reference docs:
- `docs/dev_log.md`
- `docs/checkpoints/*`
- `docs/archive/*`

## Top-Level Boundaries

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
- Classic runtime state tables/services
- in-memory Classic runtime helpers in `app/modes/classic/state.py`

### Persistent progression boundary
Persistent progression remains outside live Classic runtime state:
- diamonds
- upgrades
- gear catalog
- gear ownership
- loadout
- cosmetic face selection

### Frozen runtime boundary
`SessionParticipantSnapshot` is the frozen runtime read model for progression-derived gameplay values.

Rule:
- active gameplay should not read live persistent progression/gear rows directly for gameplay math
- Join is the boundary where session-scoped runtime values freeze

## Hub and Join Boundary

### Hub role
Hub is the persistent player preparation/dashboard surface.

Current Hub responsibilities:
- gear equip/unequip
- face selection
- avatar preview
- persistent bonus visibility
- join/return session entry

### Join role
Hub Join creates or confirms runtime participation and frozen snapshot availability.

Join currently creates/confirms:
- `RoundPlayer`
- `PlayerWallet`
- `PlayerClassicState`
- `SessionParticipantSnapshot`

Rules:
- Hub state is live and persistent
- Classic gameplay uses frozen session/runtime state after Join
- Hub remains server-rendered with fragment refresh, not SPA state

## Problem System Architecture

### Root model
- `Problem`

### Child models
- `ProblemBlock`
  - ordered body blocks
  - current types:
    - `rich_text`
    - `image`
    - `graph`
- `ProblemAcceptedAnswer`
  - text-input accepted answer variants
- `ProblemChoiceOption`
  - multiple-choice options with one correct option

### Legacy compatibility
Legacy fields still exist on `Problem`:
- `prompt_text`
- `answer_text`
- `image_path`
- `graph_config_json`

Compatibility rule:
- structured child rows are authoritative when present
- legacy fields remain fallback only

### Answer types
Current supported `Problem.answer_type` values:
- `text_input`
- `multiple_choice`

Validation rules:
- text input validates against normalized accepted answers
- MC validates by stored option ID

## Content Interpretation Path

Canonical server-side interpretation lives in:
- `app/services/problem_content.py`

Responsibilities:
- build normalized problem body view
- build accepted-answer view
- build MC option view
- normalize graph payloads

Rule:
- admin preview and Classic gameplay should keep sharing this interpretation path
- do not fork a separate Classic-only problem renderer

## Problem Authoring Flow

### Bootstrap creation flow
Current create flow is two-step in practice:
1. `New Problem` bootstrap form captures:
   - title
   - subject helper
   - topic
   - answer type
   - difficulty
   - seed prompt/answer data
2. creation redirects into the full problem content editor

### Canonical editor
The full structured editor is the authoritative edit surface.

Current responsibilities:
- metadata updates
- ordered body blocks
- accepted answers
- MC options
- preview

### Subject/topic authoring boundary
- `Subject` is a separate model
- `Topic.subject_id` is the subject relationship
- `Problem` still belongs to `Topic`, not directly to `Subject`
- problem create/edit uses a subject helper to scope topic selection, but `Subject` is not stored directly on `Problem`

## Graph Architecture

### Canonical storage
Canonical graph storage remains:
- `ProblemBlock.graph_config_json`

Teacher-facing equation rows and point rows are authoring helpers, not a second persistence model.

### Current normalized graph model
Viewport:
- `x_min`
- `x_max`
- `y_min`
- `y_max`
- `x_label`
- `y_label`
- `show_grid`

Elements:
- function traces
- points

Supported function families:
- linear
- quadratic
- exponential
- sine
- cosine

Optional per-function range:
- `x_min`
- `x_max`

### Render rule
- Plotly is the shared renderer in admin preview and Classic gameplay

## Problem Set Builder

Current builder model:
- top filters
- left candidate list
- middle preview
- right set membership

Filters:
- subject
- topic
- difficulty
- answer type

Membership rule:
- add/remove is immediate and DB-backed
- no separate save step for membership changes

## Classic Runtime Architecture

### Main layers
Classic runtime combines:
- DB-backed session/round/player state
- in-memory per-session timing and pending-flow helpers
- Socket.IO event flow
- server-rendered player/admin templates

### Core DB-backed Classic state
Examples:
- `ClassicRoundConfig`
- `PlayerWallet`
- `PlayerClassicState`
- `PlayerProblemState`
- `ProblemSolverCount`
- `StealEvent`
- `StoreItem`
- `PlayerInventory`

### In-memory Classic runtime state
`app/modes/classic/state.py` currently tracks:
- round start times
- session locks
- pending post-solve actions
- pending steal intents
- pending steal mini-games
- pending treasure chest phases
- rolling per-player action log
- streak counters

Important boundary:
- these resumable stage/pending states survive page refresh and reconnect
- they do not survive server restart

## Classic Player Page Contract

Current gameplay page structure:
- left rail
  - `Player / Status`
  - `Actions`
  - `This Round` or `Store`
- center
  - problem tabs
  - fixed problem window
  - fixed workflow panel
  - center-stage overlay layer
- right rail
  - `Leaderboard`
  - `Round Context`
  - `Action Log`

Rule:
- prompt/content stays in the problem window
- answer/action controls stay in the workflow panel
- center-stage stage events sit above the problem area without redesigning the whole page

## Classic Event Flow

### Normal solve/action flow
1. `classic_join`
2. `join_ack`
3. `classic_submit_answer`
4. `answer_result` or `choose_action_prompt`
5. `classic_choose_action`
6. Mine/Treasure/Steal branch resolution

### Post-solve action resumability
After a correct solve:
- the problem is marked solved/closed in DB
- pending post-solve action context is stored in runtime state
- `join_ack` can now restore:
  - pending action choice
  - pending steal target choice
  - pending Treasure overlay
  - pending Steal overlay

This prevents refresh/reconnect from unfairly discarding the earned action opportunity.

### Treasure flow
Treasure runtime uses:
- base gold first
- optional chest phase second

Treasure chest phase:
- one chest per eligible reward type
- each visible chest rolls filled/empty independently
- player selects one chest
- only the selected chest can grant a reward

Treasure stage-event state:
- pending chest payload is stored server-side in runtime memory
- selection/reveal phase is serializable into `join_ack`
- resolved reveal can replay safely without duplicate grant

### Steal flow
Steal outcomes are:
- targeted steal
- Stranger steal

Steal target/minigame state:
- target-pick intent is stored in runtime memory
- mini-game container payload and reveal state are stored in runtime memory
- reconnect can restore:
  - target selection
  - container selection
  - reveal state

Reactive protection rule:
- only true targeted steal success applies reactive protection

## Overlay / Stage-Event Presentation Boundary

### Treasure overlay
- rendered in the gameplay template
- uses explicit slot layout maps by chest count
- uses static assets from `app/static/classic_ui/treasure/`
- base gold is not part of the reveal icon layer

### Steal overlay
- rendered in the gameplay template
- uses explicit seven-slot layout
- target avatar is rendered from the same avatar-layer payload system used elsewhere
- uses static assets from `app/static/classic_ui/steal/`

### Shared stage-event rule
- mechanics are resolved server-side
- presentation/layout is currently template/JS-driven
- layout geometry is explicit in the template, not hidden in DB/admin config

## Avatar and Asset Responsibilities

### Avatar rendering
`app/services/avatar.py` is the avatar-layer builder.

Current responsibilities:
- enumerate valid face/gear asset keys
- build ordered avatar layer view payload
- serve Hub and Classic avatar rendering paths

Asset root:
- `app/static/gear/`

### Stage-event visual assets
Treasure/Steal presentation assets currently live under:
- `app/static/classic_ui/treasure/`
- `app/static/classic_ui/steal/`
- `app/static/classic_ui/icons/`

Rule:
- these are presentation assets, not gameplay logic
- chest/container positions are explicit layout config in the page template

## Dev-Only Overlay Tuning Tooling

Current dev-only tuning exists in the gameplay template for Treasure and Steal:
- grid overlay
- anchor markers
- draggable slot tuning
- copy/export of layout config

Boundary:
- this is development-only tooling
- it should not affect normal player UX when debug mode is off

## Admin Supervision Boundary

Current live admin supervision uses one shared Classic admin watch path.

Live-updated regions:
- leaderboard
- solve counts
- steal history / stolen-gold summary

Rule:
- extend supervision through the existing admin live path
- do not build a competing second live-update system

## Shield Runtime Model

### Canonical runtime state
Timed anti-steal protection is represented by:
- `PlayerClassicState.shield_expires_at`

### Trigger sources
Two trigger sources write to the same runtime protection field:
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
- `Protected` = active timed anti-steal protection

## Systems Present But Not Re-described Fully Here

These remain implemented and active:
- diamonds progression
- upgrades
- gear ownership/catalog/loadout
- Blacksmith
- round history/archive

This document keeps focus on the architecture boundaries most likely to matter for current work.
