# Classic interface release — 18 October 2026

Deployed to https://game.korephysics.com/ after the user explicitly authorized
restarting active Classic session #4. No migration, economy change, round-rule
change, database replacement, or production test content was required.

## Changes and findings

- The leaderboard's non-wrapping four-column row exceeded its narrow rail. Rows
  now place the player's name above icon counters. Names truncate with a full-name
  tooltip; amounts wrap as whole counters and the list scrolls vertically.
- Resource cards use gold, gem, steal-token and flame icons beside larger values.
  Streak displays the consecutive-correct count without implying a multiplier.
- Shield icon and inventory count share one horizontal row with Activate.
- Round instructions explain rewards in short sentences. Mine reward, treasure
  minimum/maximum, attempts and wrong-answer penalty remain admin-configured.
  Fixed treasure rewards show one number. Only reward types with nonzero configured
  chances are advertised. This describes possible rewards, not guaranteed drops.
- The timer uses the existing round start/deadline and disappears entirely on
  expiry or when disabled. It does not restart on refresh.
- Bonus inventory details are collapsible; active bonuses remain visible near
  actions. Removed the repeated session note and shortened Mine result messaging.
- Larger question, answer, rule and resource text; fewer redundant headings.
- Desktop problem selection uses up to eight columns. The current-problem pager
  remains. Existing mobile Player/Round Info drawers remain available.
- Translucent materials, subtle text shadows and the existing scene preserve the
  background atmosphere. The question's stacked panel fills were lightened.
- The persistent fullscreen frame fills its container. A small fullscreen icon
  replaces the empty 46px toolbar, with accessible label/title and existing exit
  preference behavior. On phones the control sits at the lower right.

## Loading changes

The existing background WebP mapping, immutable image caching and idle warmup
were retained. They were already deployed before this task.

- Added WebP derivatives for 35 icons, chest states and bag states previously
  omitted from conversion: 10,829,730 original bytes to 2,418,584 display bytes,
  approximately 78% smaller. Originals remain intact; no avatar canvas changes.
- The lobby now warms game backgrounds and overlay artwork. The game warmup
  includes nested chest/bag/reward assets, not just backgrounds. Warmup remains
  low priority, bounded to two requests at a time, and respects Save-Data.
- Plotly loads on the first graph question rather than blocking every Classic
  document. Concurrent requests share the loader; failed loads have a Retry
  control. Other pages using the shared renderer retain their existing support.
- Page-wide image preparation is bounded to 1.2 seconds, while individual artwork
  continues loading/decoding and existing image error handling remains available.
- Added browser performance marks `player-ui-ready` and `player-artwork-ready`
  for subsequent measurement.

The 78% figure applies to the added derivatives, not total page weight or measured
loading time. A controlled before/after timing study on school Wi-Fi remains to
be done. First-time downloads of graph/math libraries and server response time
can still contribute to loading.

## Verification

- 14 focused pytest checks: admin-driven instructions, disabled rewards, token
  icons, image caching/alpha alignment and persistent player container behavior.
- Graph block suite: 11 passed. Boss Rush UI suite: 9 passed. Separate shield and
  Treasure/Steal regression scripts passed, including pending-action reconnect
  and duplicate-reward protection. These scripts also passed on staged server
  source against disposable SQLite fixtures.
- Browser QA with disposable local data: desktop/laptop layouts, a 390×844 phone
  viewport, long player names, seven-digit gold amounts, fourteen leaderboard
  entries, internal scrolling, question display, answer submission, Mine reward,
  Treasure chest selection/reveal, lazy graph rendering and hidden expired timer.
- At 1366×768, game layout, both rails and leaderboard had no horizontal overflow;
  the leaderboard scrolled internally.
- Public authenticated checks: Classic container and inner document, Hub,
  Blacksmith, progress, and four admin routes. Public Engine.IO polling handshake
  and TLS WebSocket upgrade both passed. Health endpoint passed; game, identity,
  examination and Nginx services remained active.
- All 49 deployed file checksums matched. All database table counts matched
  before/after file replacement while the game was stopped.

Three preliminary deployment attempts rolled source back after verification-tool
issues: shared-account version missing from a synthetic check cookie, then absent
optional Python WebSocket/HTTP client packages. The final checks use the proper
shared-account version and Python standard-library transport handshakes. No
production dependencies were added for verification.

## Deployment evidence

- Final source rollback, manifest and counts:
  `/var/backups/korephysics-game/classic-design-20261018-095725/`.
- Fresh game and examination backups completed before replacement.
- Local reviewed archive, diff and manifest:
  `C:/Users/korol/AppData/Local/KorePhysics/game-deployment/classic-design-20261018-095231/`.
- Archive SHA-256:
  `9b7a115aa0d0232ed796cd18cc7e426cbb372d76774d77bfcc71fc869e6f4290`.

## User test checklist

1. Hard-refresh the online game with Ctrl+F5. Enter fullscreen at your usual
   laptop resolution. Check readable question text, background atmosphere,
   visible resource amounts, the inline shield count and all action controls.
2. Use several players or long display names. Verify leaderboard names/amounts
   fit, updates arrive and the player list scrolls without moving the other panels.
3. For a new round, set distinctive Mine/treasure amounts, attempts and penalty
   in admin. Confirm the player's instructions reflect those values, including
   equal treasure bounds and disabled reward types.
4. Start a short timer bonus. Confirm the countdown, bonus award on an eligible
   correct answer, complete disappearance at expiry, and correct state on refresh.
5. Solve problems with Mine, Treasure and Steal. Check results, wallet changes,
   streak, chest/bag artwork, Store, and shield activation when a token is owned.
6. Compare a fresh/private-window visit with a repeat visit. Spend a little time
   in the lobby, then open Treasure/Steal for the first time. Note the screen and
   duration if a noticeable wait remains. Open a graph question as well.

Physical mobile/Safari testing and a full classroom network rehearsal remain
manual follow-ups. The saved preview uses disposable local values, not live
student data.
