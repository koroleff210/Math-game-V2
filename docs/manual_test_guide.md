# Manual Test Guide

_Updated: 2026-03-30_

This guide stays intentionally current and practical.
It focuses on current admin authoring/config flows, Hub behavior, Classic gameplay smoke paths, Treasure/Steal overlays, reconnect safety, and asset/avatar sanity.

Use:
- [C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\project_state.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\project_state.md) for status
- [C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\system_architecture.md](C:\Users\korol\OneDrive\Desktop\Game\Game v2\docs\system_architecture.md) for architecture

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
- if you create Classic sessions during testing, end them when done
- do not leave `waiting` or `active` test sessions behind

## 2. Recommended Manual Order

1. admin shell sanity
2. subject/topic/problem/problem-set authoring
3. Hub / gear / avatar sanity
4. Classic session create/manage
5. Classic gameplay
6. Treasure / Steal overlays
7. refresh/reconnect safety
8. supervision / history sanity

## 3. Admin Shell and CRUD Sanity

### MT-01: Admin shell navigation
1. Log in as admin.
2. Verify sidebar links load without error:
   - Players
   - Classes
   - Subjects
   - Topics
   - Problems
   - Problem Sets
   - Gear Catalog
   - Classic Mode
   - History
   - Diamonds

Expected:
- admin shell routes load
- no broken nav links
- grouped admin pages render without template errors

### MT-02: Subjects / topics / players / groups quick sanity
1. Create or edit:
   - one Subject
   - one Topic under that Subject
   - one Player
   - one Group/Class
2. Add a player to a class.

Expected:
- CRUD pages submit and reload correctly
- Topic shows Subject correctly
- player/group pages remain usable

## 4. Problem Authoring

### MT-03: New Problem bootstrap -> full editor
1. Open `New Problem`.
2. Fill:
   - title
   - subject helper
   - topic
   - answer type
   - difficulty
   - seed prompt
3. Submit.

Expected:
- problem is created
- flow lands in the full content editor
- the new problem is editable immediately

### MT-04: Text-input problem authoring
1. In the content editor, keep answer type = `Text input`.
2. Add/update:
   - rich-text blocks
   - accepted answers
3. Save.

Expected:
- accepted answers persist
- preview reflects current body blocks

### MT-05: Multiple-choice problem authoring
1. Create or edit a problem with answer type = `Multiple choice`.
2. Add/update MC options.
3. Ensure exactly one option is correct.

Expected:
- MC options persist
- preview remains coherent
- gameplay later respects the stored correct option

### MT-06: Graph block authoring
1. Add a graph block.
2. Configure:
   - viewport
   - one or more equation rows
   - one or more points
3. Save.

Expected:
- graph preview renders
- Plotly interactions work
- graph remains part of the ordered problem body

## 5. Problem Set Builder

### MT-07: Filter, preview, membership
1. Open an existing problem set.
2. Filter by:
   - subject
   - topic
   - difficulty
   - answer type
3. Add one problem.
4. Remove one problem.

Expected:
- left list filters correctly
- middle preview updates
- right membership updates immediately

## 6. Hub / Gear / Avatar Sanity

### MT-08: Hub readiness and session control
1. Log in as a player and open Hub.
2. Verify session control behavior for:
   - no joinable session
   - joinable session
   - unfinished enrolled session

Expected:
- session control is integrated into the Hub status area
- no separate stale banner/placeholder flow appears

### MT-09: Face / gear refresh
1. Change face.
2. Equip an item.
3. Unequip an item.

Expected:
- no full page reload
- avatar preview updates
- equipped slots update
- inventory state updates

### MT-10: Asset sanity
1. Verify avatar renders use actual layered art.
2. Verify gameplay Treasure/Steal overlays can load their background/container/icon art.

Expected:
- no missing-image icons
- no obvious broken static paths

## 7. Classic Session Create / Manage

### MT-11: New session grouped config UX
1. Open `Classic Mode` -> new session.
2. Verify grouped sections:
   - Session
   - Core Round / Economy
   - Bonuses
   - Treasure
   - Steal & Protection
   - Review

Expected:
- grouped config page renders cleanly
- labels reflect current mechanics:
  - chest fill chance
  - Stranger steal gold
  - Shield Token / reactive protection wording

### MT-12: Between-round editor grouped UX
1. Create a Classic session.
2. End round 1 so the session is in `waiting`.
3. Open the between-round editor in manage page.

Expected:
- next-round editor uses the same grouped language as session creation
- fields still submit correctly

### MT-13: Broken-session recovery safety
1. If a dev session lands in:
   - session `active`
   - latest round already ended
2. Open manage page.

Expected:
- warning/recovery path is visible
- page is not a no-button dead end

## 8. Classic Gameplay Core

### MT-14: 3-column gameplay contract
1. Join a live Classic session as a player.
2. Open gameplay page on normal PC/iPad landscape-sized viewport.

Expected:
- left rail = Player / Status, Actions, This Round or Store
- center = tabs, problem window, workflow panel
- right rail = Leaderboard, Round Context, Action Log

### MT-15: Text-input answer flow
1. Open a text-input problem.
2. Submit a correct answer.

Expected:
- prompt stays in the problem window
- answer control stays in workflow panel
- solve advances into post-solve action choice

### MT-16: Multiple-choice answer flow
1. Open an MC problem.
2. Select one option.
3. Confirm on the selected option.

Expected:
- MC controls stay in workflow panel
- prompt remains in the problem window
- correctness matches stored option data

## 9. Treasure Overlay

### MT-17: Treasure center-stage overlay
1. Solve correctly.
2. Choose `Treasure Search`.
3. Trigger cases with:
   - no eligible chest rewards
   - 1 visible chest
   - multiple visible chests

Expected:
- Treasure no longer uses the cramped workflow mini-area
- center-stage overlay appears above problem area
- correct cave background loads for chest count
- one-chest case reveals immediately on tap
- multi-chest case uses select -> confirm -> reveal -> auto-close
- only the selected chest grants a reward
- unselected chests reveal only as missed outcomes

### MT-18: Treasure messaging sanity
1. Trigger Treasure outcomes that give:
   - Gem
   - Shield Token
   - Steal Token
   - Second Chance
   - empty chest

Expected:
- base gold is separate from chest reveal icons
- empty chest shows junk
- reward messages/logs reflect selected chest only

## 10. Steal Overlay

### MT-19: Steal center-stage overlay
1. Solve correctly.
2. Choose `Steal`.
3. Pick a valid target.

Expected:
- Steal target pick happens in workflow panel
- Steal mini-game itself opens as a center-stage overlay
- actual target avatar appears in scene
- bag/container slots render in the scene

### MT-20: Steal reveal semantics
1. Complete Steal with:
   - winning result
   - non-winning result

Expected:
- selected bag/container is emphasized
- only the selected container opens/reveals in current visual pass
- reveal icon is `gold` or `junk_01`
- overlay auto-closes and gameplay resumes cleanly

### MT-21: Stranger steal / no-target sanity
1. Test Steal when:
   - no valid targets exist
   - target becomes invalid before resolution if reproducible

Expected:
- spent steal token still leads to positive actor outcome
- target is unaffected on Stranger steal
- reactive protection only happens on true targeted steal success

## 11. Refresh / Reconnect Safety

### MT-22: Refresh during post-solve action choice
1. Solve correctly.
2. Stop at the action choice step.
3. Refresh.

Expected:
- problem remains solved
- pending action choice is restored
- reward opportunity is not lost

### MT-23: Refresh during steal target selection
1. Solve correctly.
2. Choose `Steal`.
3. Stop at target-selection step.
4. Refresh.

Expected:
- pending steal target selection restores
- player is not kicked back to normal selection flow

### MT-24: Refresh during Treasure overlay
1. Open Treasure overlay.
2. Refresh during selection or pending confirm.

Expected:
- same Treasure overlay restores
- chest outcome is not rerolled

### MT-25: Refresh during Steal overlay
1. Open Steal overlay.
2. Refresh during selection or pending confirm.

Expected:
- same Steal overlay restores
- slot assignment/outcome is not rerolled

## 12. Shield / Store / Status Clarity

### MT-26: Shield Token and Protected state
1. Ensure the player has a `Shield Token`.
2. Activate it.
3. Wait for expiry.

Expected:
- Shield Token count is visible in `Actions`
- `Protected` appears near avatar/identity
- countdown is visible
- layout does not jump when it appears/disappears

### MT-27: Blocked manual activation
1. While `Protected`, try activating again.

Expected:
- activation is blocked
- token is not consumed
- feedback is visible without expanding the Actions block permanently

### MT-28: Reactive protection after targeted steal
1. Complete a true targeted steal against another player.

Expected:
- victim gets `Protected`
- protected victim becomes an invalid steal target during protection window

## 13. Admin Supervision / History

### MT-29: Live supervision
1. Open Classic admin manage page during live play.
2. Solve problems and trigger steal events.

Expected:
- leaderboard updates live
- solve counts update live
- steal history updates live

### MT-30: Round history
1. End one or more rounds.
2. Open Classic history.

Expected:
- frozen round history renders
- results are read-only
- export/archive controls behave as expected

## 14. Optional Dev-Only Overlay Tuning

### MT-31: Overlay debug mode
1. Open gameplay with `?overlay_debug=1` or enable `classicOverlayDebug` in `localStorage`.
2. Trigger Treasure or Steal.

Expected:
- debug grid appears only in debug mode
- slot anchors are visible
- Treasure/Steal layout export tools work

This is optional and development-only, not a player-facing acceptance path.
