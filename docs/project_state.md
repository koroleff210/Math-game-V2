# Project State

_Updated: 2026-03-30_

This is the current product-status document for `math_game_v2`.
Code is the real source of truth. This file describes what is implemented now, what is stable enough to build on, and what is intentionally still deferred.

Use:
- [C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\system_architecture.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\system_architecture.md) for boundaries and runtime/data-flow rules
- [C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\manual_test_guide.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\manual_test_guide.md) for practical verification paths
- [C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\bootstrap_prompt.txt](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\bootstrap_prompt.txt) for fresh-thread onboarding

Historical/reference docs:
- `docs/dev_log.md`
- `docs/checkpoints/*`
- `docs/archive/*`

Those are not active specs.

## Current Snapshot

Current date:
- `2026-03-30`

Current Alembic head:
- `f1a2b3c4d5e6`

Current repo posture:
- Classic Mode is the gameplay center and is playable end-to-end
- the authored-content stack is live and no longer in bootstrap-only status
- Hub is the persistent prep surface before Join
- recent work has focused on stabilization, clarity, reconnect safety, and stage-event presentation rather than foundational rewrites

## Major Implemented Pillars

### Admin shell and CRUD
- admin shell includes:
  - players
  - classes/groups
  - subjects
  - topics
  - problems
  - problem sets
  - gear catalog
  - Classic Mode
  - history
  - diamonds
- subject/topic/problem/problem-set CRUD are active
- player/class/group CRUD is active
- diamonds and gear admin surfaces are active

### Problem authoring
- `Problem` remains the root authored entity
- canonical answer types:
  - `text_input`
  - `multiple_choice`
- body blocks under `ProblemBlock` support:
  - `rich_text`
  - `image`
  - `graph`
- accepted text answers live under `ProblemAcceptedAnswer`
- MC options live under `ProblemChoiceOption`
- legacy problem fields still exist for compatibility fallback

### New Problem bootstrap -> full editor flow
- `New Problem` is a lightweight bootstrap form
- creating a problem redirects into the full content editor
- the editor is the canonical structured-authoring surface for:
  - body blocks
  - accepted answers
  - multiple-choice options
  - preview
- admin preview and gameplay both use the shared interpreted-content path

### Graph authoring and rendering
- canonical graph storage remains `ProblemBlock.graph_config_json`
- admin graph authoring supports:
  - graph settings
  - equation rows
  - point rows
- current supported function families:
  - linear
  - quadratic
  - exponential
  - sine
  - cosine
- Plotly remains the renderer for admin preview and Classic gameplay

### Problem-set builder
- current builder is server-rendered
- filters include:
  - subject
  - topic
  - difficulty
  - answer type
- workspace remains:
  - left = available filtered problems
  - middle = preview
  - right = set membership
- add/remove is immediate and DB-backed

### Hub and persistent preparation
- Hub is the persistent player dashboard/prep page
- face/equip/unequip updates use fragment refresh, not full SPA state
- Join/Return session control is integrated into the Hub status surface
- Join is the runtime freeze boundary for progression-derived values

### Persistent progression, gear, and avatar
- diamonds progression is active
- persistent gear catalog / ownership / equip / loadout is active
- runtime avatar rendering uses layered assets from `static/gear`
- target/player avatar rendering is reused in Hub and Classic gameplay
- current runtime gameplay should read frozen session snapshot values, not live progression rows

### Classic admin experience
- new-session config page uses grouped sections:
  - Session
  - Core Round / Economy
  - Bonuses
  - Treasure
  - Steal & Protection
  - Review
- between-round settings editor now uses the same grouped config language
- manage page also supports:
  - live leaderboard
  - solve counts
  - steal history
  - store management
  - next-round transition
  - broken active+ended-round recovery

### Classic player gameplay page
- current page uses a stable 3-column contract
- left rail:
  - `Player / Status`
  - `Actions`
  - `This Round` or `Store` lower-slot swap
- center:
  - problem tabs
  - fixed problem window
  - fixed workflow panel
  - center-stage overlay layer above the problem area
- right rail:
  - `Leaderboard`
  - `Round Context`
  - `Action Log`

### Classic answer/action flow
- solving a problem correctly advances into a post-solve action state
- action choices:
  - Mine
  - Treasure Search
  - Steal
- text-input and MC both keep prompt content in the problem window and controls in the workflow panel
- MC uses compact select + confirm-on-option behavior

### Treasure system
- Treasure Search always grants base gold first
- optional bonus phase uses independent chest-fill logic
- one visible chest per eligible reward type
- each visible chest fills independently
- only the selected chest can grant a reward
- current center-stage Treasure overlay is implemented
- overlay uses:
  - cave backgrounds by chest count
  - randomized chest skins
  - reward/junk reveal icons
  - select -> confirm -> reveal -> auto-close flow
- one-chest Treasure skips confirm and reveals immediately on tap

### Steal system
- Steal no longer has a zero-value spent-token outcome
- outcomes are:
  - targeted steal
  - Stranger steal
- current center-stage Steal overlay is implemented
- overlay uses:
  - `steal_bg_main`
  - target avatar in scene
  - active bag/container slots
  - filler overlays for inactive slots
  - select -> confirm -> reveal -> auto-close flow
- current first-pass visual reveal only distinguishes:
  - `gold`
  - `junk_01`
- targeted vs Stranger visuals are not fully separated yet

### Shield model and player-facing terms
- runtime anti-steal protection state:
  - `PlayerClassicState.shield_expires_at`
- player-facing vocabulary is now:
  - `Second Chance`
  - `Shield Token`
  - `Protected`
- manual and reactive protection use separate base durations
- treasure shield rewards grant `Shield Token`, not immediate protection

### Refresh/reconnect safety
- pending Treasure and Steal stage events are resumable on refresh/reconnect
- post-solve action choice is now resumable on refresh/reconnect
- pending steal target selection is also restored
- resolved stage events replay safely without duplicate grants

## Current Asset/UI Reality

### Stage-event asset pipeline
- Treasure stage-event assets live under:
  - `app/static/classic_ui/treasure/`
- Steal stage-event assets live under:
  - `app/static/classic_ui/steal/`
- shared reward/junk icons live under:
  - `app/static/classic_ui/icons/`
- asset placement/layout data is currently explicit in the gameplay template

### Debug/tuning tooling
- Treasure and Steal overlays support dev-only debug/tuning mode
- debug mode can show:
  - grid
  - slot anchors
  - avatar anchor
  - confirm anchor
- draggable anchor tuning exists for:
  - Steal
  - Treasure
- this is development-only and should not be treated as player UX

## Implemented vs Deferred

### Implemented now
- full Classic solve -> action -> reward loop
- center-stage Treasure overlay
- center-stage Steal overlay
- resumable pending action / Treasure / Steal reconnect behavior
- grouped Classic admin config UX for session creation and between-round editing
- Hub fragment-refresh prep flow
- subject-first problem bootstrap and full structured editor flow
- avatar layering in Hub and gameplay
- shield semantics alignment and current player HUD clarity

### Still deferred / intentionally not finished
- final art/theme pass for Hub or Classic gameplay
- final animation polish for Treasure/Steal overlays
- stronger visual distinction between targeted steal and Stranger steal in the overlay reveal
- mobile portrait redesign
- drag/drop problem-body block ordering
- drag/drop problem-set ordering
- graph-as-answer gameplay
- student graph interaction mechanics
- media library / image upload workflow
- broad admin shell visual overhaul
- full cleanup removal of all legacy problem fallback fields

## Current Testing Reality

Current `tests/` inventory:
- 59 Python test files

Recent focused green areas include:
- problem system slices
- graph block authoring/rendering
- problem-set builder
- Classic admin live supervision
- shield alignment
- treasure/steal rework
- refresh/reconnect restoration for Treasure, Steal, and pending post-solve action

Testing policy:
- do not assume the entire suite runs on every task
- run targeted suites for the touched area
- when manual or automated testing creates Classic sessions, end them before closing the task

## Near-Term Roadmap

Near-term work should stay incremental.

### 1. Classic stage-event polish
- visual timing and readability polish for Treasure/Steal overlays
- clearer targeted vs Stranger steal presentation
- keep current mechanics stable while polishing presentation

### 2. Classic player UX polish
- continue compactness/readability improvements on the stable gameplay shell
- preserve the current 3-column contract

### 3. Hub/progression quality-of-life
- continue local QoL improvements using the current server-rendered fragment model
- avoid unnecessary SPA expansion

### 4. Admin supervision and operations
- refine session hygiene and live supervision clarity through the existing admin watch path
- keep recovery tooling pragmatic for local testing

### 5. Authored-content quality-of-life
- incremental editor/builder polish remains reasonable
- larger authoring redesigns are still deferred
