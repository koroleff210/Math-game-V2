# Manual Test Guide

_Updated: 2026-03-25_

This guide is intentionally current and concise.
It focuses on the repo's current admin authoring flows, Hub behavior, Classic gameplay smoke paths, supervision visibility, and shield clarity.

Use [project_state.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\project_state.md) for status and [system_architecture.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\system_architecture.md) for structure.

---

## 1. Environment

Start the app:

```powershell
cd "C:\Users\korol\OneDrive\Desktop\Game\Game v2"
.venv\Scripts\python.exe run.py
```

Open:
- [http://localhost:5000](http://localhost:5000)

Default admin:
- `admin` / `admin123`

Recommended player accounts:
- `player1`
- `player2`
- `player3`

Session hygiene:
- if you create Classic sessions during testing, end them when the test is complete
- do not leave `waiting` or `active` test sessions in the database

---

## 2. Recommended Manual Test Order

1. subject/topic setup
2. unified problem editor
3. graph authoring
4. problem-set builder
5. Hub flow
6. Classic session smoke
7. admin supervision / shield checks

---

## 3. Subject / Topic Setup

### MT-01: Create subjects and topics
1. Log in as admin.
2. Create at least 2 subjects.
3. Under each subject, create at least 2 topics.

Expected:
- subjects save cleanly
- topics belong to the selected subject
- topic lists load correctly in problem authoring

---

## 4. Unified Problem Editor

### MT-02: Create a text-input problem
1. Open `New Problem`.
2. Fill:
   - title
   - subject
   - topic
   - difficulty
   - answer type = `Text input`
3. Enter:
   - question seed
   - first accepted answer
4. Create the problem.

Expected:
- creation happens on the unified editor surface
- redirect lands on the same canonical editor in edit mode
- first rich-text block exists
- accepted-answer section is active
- preview shows the saved text block

### MT-03: Create a multiple-choice problem
1. Open `New Problem`.
2. Fill metadata.
3. Set answer type = `Multiple choice`.
4. Enter question seed.
5. Fill option rows and mark exactly one as correct.
6. Create the problem.

Expected:
- redirect lands on the same canonical editor
- MC options are active
- accepted answers are not the visible answer editor
- Classic-compatible option rows are saved

### MT-04: Edit metadata / answer type
1. Open an existing problem.
2. Edit title/topic/difficulty.
3. Change answer type if needed.
4. Save.

Expected:
- metadata changes persist
- answer-type-specific section remains coherent
- no accidental write-on-GET behavior

---

## 5. Body Block Authoring

### MT-05: Rich text / image / graph body flow
1. Open a problem in the editor.
2. Add a rich-text block below an existing block.
3. Add an image block below that.
4. Add a graph block below that.

Expected:
- add-below actions return to the edited block area
- block ordering stays top-to-bottom
- preview reflects the saved order

### MT-06: Rich text preview
1. Edit a rich-text block with:
   - paragraphs
   - line breaks
   - `**bold**`
   - inline LaTeX delimiters
2. Save.

Expected:
- preview updates
- text block remains visible and readable

### MT-07: Image preview
1. Set a valid image path.
2. Adjust width percent.
3. Save.

Expected:
- preview shows the image
- width percent affects preview size

---

## 6. Graph Authoring

### MT-08: Create a graph from equations and points
1. Add a graph block.
2. Set viewport:
   - x min / max
   - y min / max
   - x label / y label
   - show grid
3. Add one or more equation rows.
4. Add one or more point rows.
5. Save.

Expected:
- graph preview renders
- Plotly zoom/pan/hover works in admin preview
- graph block remains in body order with other blocks

### MT-09: Accepted equation forms
Try examples such as:
- `y = 2x + 1`
- `y = x^2`
- `y = 2*3^x`
- `y = sin(x)`
- `y = cos(x)`

Expected:
- accepted forms save and render

### MT-10: Equation range
1. On an equation row, set optional `x min` / `x max`.
2. Save.

Expected:
- only that function trace uses the narrowed x-range

### MT-11: Points
Try point formats:
- `2,3`
- `2;3`
- `(2, 3)`
- `(2; 3)`

Expected:
- accepted formats save as point markers

---

## 7. Problem Set Builder

### MT-12: Filter and preview
1. Open an existing problem set.
2. Choose a subject.
3. Tick one or more topics.
4. Optionally choose difficulty.
5. Choose one answer type.
6. Click `Filter`.

Expected:
- left column shows only matching available problems
- middle preview shows the clicked problem
- right column shows current set membership

### MT-13: Immediate add/remove
1. Add a left-column problem.
2. Remove a right-column problem.

Expected:
- membership changes immediately
- page returns to the builder workspace rather than the top of the page
- active filters remain intact

---

## 8. Hub / Preparation Flow

### MT-14: Hub readiness and session control
1. Log in as a player and open the Hub.
2. Observe the `Active Gear Bonuses` area.
3. Verify Join/Return behavior for:
   - no joinable session
   - joinable session
   - unfinished enrolled session

Expected:
- no top session banner
- no standalone Session Status placeholder block
- session control lives inside the Hub status/bonus area

### MT-15: Face / equip async refresh
1. Change face.
2. Equip gear.
3. Unequip gear.

Expected:
- no full page reload
- avatar preview updates
- equipped slots update
- inventory state updates
- selected item stays correct

---

## 9. Classic Gameplay Smoke

### MT-16: Structured problem rendering in Classic
1. Create a problem set containing:
   - text-input problem
   - multiple-choice problem
   - graph problem
2. Create a Classic session with that set.
3. Join as a player.
4. Start the round.

Expected:
- body blocks render in Classic
- legacy-only problems still display if present
- graph blocks render in the gameplay body area

### MT-17: Text-input answer flow
1. Solve a text-input problem with an accepted variant.

Expected:
- validation uses accepted answers
- existing text-input flow still works

### MT-18: Multiple-choice answer flow
1. Open a multiple-choice problem.
2. Select an option.
3. Confirm on the selected option.

Expected:
- prompt stays in the problem window
- MC controls stay in the workflow panel
- submission uses option ID
- correctness matches the stored correct option

### MT-19: Gameplay-page fit / rail structure
1. Open the gameplay page on a normal PC or iPad landscape-sized viewport.
2. Verify:
   - left rail groups remain stable
   - center problem window + workflow panel remain visible
   - right rail contains leaderboard, round context, action log

Expected:
- page keeps the current 3-column contract
- action log remains fixed-height
- store replaces the lower left-rail slot rather than stacking height

---

## 10. Shield / Store / Steal Clarity

### MT-20: Shield Token and Protected state
1. Ensure a player has a `Shield Token`.
2. Activate it while not protected.
3. Wait for protection to expire.

Expected:
- `Shield Token` count is visible in the Actions area
- `Protected` appears near identity/avatar with remaining time
- activation while inactive consumes one token
- indicator disappears when protection expires

### MT-21: Blocked manual activation
1. While already `Protected`, try to activate a `Shield Token` again.

Expected:
- activation is blocked
- token count does not change
- blocked feedback is visible

### MT-22: Reactive protection after successful steal
1. Use two players in an active round.
2. Complete a successful steal against a victim.

Expected:
- victim receives automatic `Protected` state
- victim stop being a valid steal target during the runtime protection window
- wording stays distinct from token gain

### MT-23: Treasure token reward messaging
1. Trigger a treasure result that grants anti-steal protection inventory.

Expected:
- message/log says `Shield Token` gained
- it does not imply immediate protection

---

## 11. Admin Live Supervision

### MT-24: Leaderboard / solve counts / steal history
1. Open the Classic admin manage page for a live session.
2. During live play:
   - solve problems
   - trigger steal events

Expected:
- leaderboard updates live
- solve counts update live
- steal-history / stolen-gold summary updates live
- no manual refresh is required

### MT-25: Broken-session recovery safety
1. If a dev/test session lands in the state:
   - session `active`
   - latest round already ended
2. Open the admin manage page.

Expected:
- the page does not become a no-action dead end
- recovery path or warning is visible

---

## 12. Optional Reset / Seed Prep

For a fresh manual pass, you can:
- clear sessions
- clear authored subjects/topics/problems/problem sets
- keep only admin + a few player accounts
- reseed a small content bank for UI verification

This is useful when testing Hub/gameplay polish so the visible content remains small and predictable.

---

## 13. Not Covered Here

This guide does not try to exhaustively re-document:
- every historical Classic regression edge case
- older checkpoint-only milestones
- non-current planned UI redesign work

Those still exist as reference material, but this manual guide stays focused on the current supported flows.
