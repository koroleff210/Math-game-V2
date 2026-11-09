# Workshop, Hub and loading measurements — 18 October 2026

Deployed to https://game.korephysics.com/ with 14 checksummed runtime/test files.
No migration, shop seeding, progression change or production artwork editing
was required. There were no unfinished sessions when the game restarted.

## Interface changes

- Treasure reveals mark every unselected chest as unclaimed. Its reward icon is
  dimmed/desaturated and chest art is shaded; the selected reward stays bright.
  Accessible chest labels distinguish the chosen reward from items not received.
- Removed the extra drawn pickaxe, chest, checkmark and cross from the round-rule
  rows. Kept currency/reward icons and the timer clock.
- Hub uses the actual Diamond artwork instead of an emoji. Selected-item effects,
  active gear bonuses and current/next upgrade effects use existing gold, shield
  and steal-token artwork with short text for context. Backgrounds stay translucent.
- Gear Studio has Move/resize and Eraser tools, a 1–80 px brush, preview cursor,
  100–400% zoom and pixel-aware Undo/Redo. Only the editable artwork is erased.
  Inverse transform mapping handles translated/scaled/rotated artwork. References
  and the avatar never enter the saved PNG.
- Source-frame metadata preserves holes and erased edges across save/reopen.
  Legacy editable sources retain their old interpretation. No data migration.
- Reference selectors include all 35 bundled/catalog gear appearances across
  head, chest, boots/legs, main hand and off hand. All existing nine male/six
  female faces are available for compatibility previews. Body incompatibilities
  are labeled. Bundled previews do not create shop items; there are still eight
  registered catalog items immediately after deployment.

## Loading measurements before feature deployment

An opt-in `?ui_measure=1` panel reads navigation/resource/paint timings, existing
player readiness marks and long main-thread tasks. It does not send or persist
metrics. It is absent from normal screens. The diagnostics were enabled before
the feature release; no caching, bundling or renderer optimization was applied
on the basis of these preliminary measurements.

Three measured Chrome navigations used the existing online admin login, on the
user's laptop and connection, without bandwidth throttling. Initial assets were
partly cached; these are not clean-cache or classroom-load benchmarks. Hub timings
below start at the inner player document's navigation. Its persistent fullscreen
container has a separate initial request/clock.

| Observation | Initial measured visit | Repeat visits |
|---|---:|---:|
| Hub inner document first byte | 394 ms | 397–402 ms |
| Hub inner document HTML transfer | 3 ms | 3 ms |
| Hub first contentful paint | 1,376 ms | 628–732 ms |
| Hub UI/artwork ready | 1,694/1,695 ms | 799–917 ms |
| Hub long tasks over 50 ms | None observed | None observed |
| Gear Studio first byte | 471 ms | 187–499 ms |
| Gear Studio ready mark | 1,424 ms | 906–1,383 ms |
| Studio catalog request | 329 ms total | About 312 ms total |

The Hub's initial measured background request transferred 223 KB, took 735 ms
overall and spent 430 ms receiving its body. A body layer transferred 137 KB
with 283 ms body transfer. Total observed resources transferred about 1.15 MB
within the capture, including idle prefetches after the screen was ready. On a
repeat visit resource transfers fell to about 1.8 KB, mostly cache validations;
many images came from cache in 0–5 ms. Script/stylesheet validations still cost
roughly 145–150 ms waiting per request, even when their bodies were cached.

Studio recorded one 505–604 ms main-thread task in these samples. A quiet
navigation without an explicit AX inspection during loading still recorded it.
This establishes browser-side work, but does not identify a particular function
or prove all of that time is canvas rendering. A CPU trace is the next step
before changing rendering/import code.

Four requests per endpoint from server loopback isolated application processing
from the Internet/browser path:

| Endpoint | Before release median | After release median |
|---|---:|---:|
| Hub document | 40.4 ms | 33.8 ms |
| Studio document | 5.5 ms | 3.9 ms |
| Studio catalog | 167.6 ms | 163.1 ms |

Those small differences are normal sample variation, not a speed-up claim. The
larger reference library did not cause an observed server-time regression.

### Interpretation and next performance work

1. Hub waits are primarily network/request sequencing and initial artwork,
   rather than slow HTML generation or observed long rendering tasks. The initial
   fullscreen wrapper adds another navigation; retain its fullscreen behavior
   when considering any future navigation work.
2. Cache content-versioned JS/CSS and versioned uploaded images more effectively
   to remove repeat validation round trips, while preserving HTML privacy and
   correct invalidation. Do not simply cache every authenticated response.
3. Studio's catalog generation is a real application-side contributor. A future
   pass should reuse per-request asset/layer lookups instead of repeated avatar
   resolution, with tests for changed uploads and body variants.
4. Profile the Studio main-thread task before changing canvas drawing. The
   current data cannot attribute the full task to decoding, drawing or scripting.
5. Measure a real student Classic session and graph/first-overlay transitions
   separately. This run's live timing samples cover Hub and Studio under the
   admin login; Classic functional visual QA used isolated test data.

## Verification and preservation

- 38 focused pytest checks passed locally and against staged source on the
  server, including preserved erased-edge coordinates, PNG holes across save /
  reopen, bundled references without database additions, authorization/conflicts,
  existing image/cache and Classic rule behavior.
- Hub polish: 6 checks passed. Treasure/Steal regression script passed, including
  selected-only awards, refresh/reconnect and duplicate-award protection.
- Browser eraser test used a disposable local 200×200 image. A stroke, Undo,
  Redo and Save produced 88 fully transparent pixels with the source frame still
  200×200; its center alpha was zero. No production artwork was saved during QA.
- Hub visual QA used disposable owned gear and verified actual resource icons.
  Online Studio opens existing hand gear and offers all face/bundled selectors.
- Isolated Classic reveal produced two unclaimed chest classes for the two
  unselected rewards. CSS keeps the selected reward unshaded.
- Public authenticated admin/Studio checks passed. Both Socket.IO polling and
  TLS WebSocket upgrade handshakes passed. Game, identity, exam and Nginx services
  were active after deployment. All 14 source checksums matched.
- Fresh game and exam backups completed. Database table counts were equal before
  and after file replacement while the service was stopped. Persistent media and
  uploaded assets were not synchronized or replaced by the release.

Rollback evidence:
`/var/backups/korephysics-game/workshop-hub-20261018-153621/`.
Local release manifest, reviewed diff, measurements and screenshots:
`C:/Users/korol/AppData/Local/KorePhysics/game-deployment/workshop-hub-20261018-153459/`.

## User checks

1. Ctrl+F5 the online Hub and Studio. Check icon meanings, text fit and background
   atmosphere. Diamonds should look distinct from Classic gems.
2. In Studio, import a new PNG or open existing artwork. Erase a small detail,
   Undo/Redo, change zoom, then save and reopen. Check that erased edges do not
   move the artwork and that reference gear remains intact.
3. While editing a face, cycle head/chest/boots/main/off-hand references. While
   editing gear, cycle faces. Repeat for both bodies; missing-body art is labeled.
4. Open Treasure in a real game. Only the selected reward should remain bright;
   the other revealed rewards should be visibly shaded.
5. If a wait remains, report its screen and trigger (initial entry, refresh,
   changing gear, importing a PNG, first graph, or first overlay). Opt-in timing
   capture is available by adding `?ui_measure=1` to Hub or Studio and expanding
   the Loading measurements panel.
