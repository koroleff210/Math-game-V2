# Boss Rush shared bank — 19 October 2026

Deployed online and locally. Applies to newly created Boss Rush rounds; existing
rounds retain their previous reward contract. Saved gold, diamonds, owned gear,
session wallets and historical results were preserved.

## Defaults

| Consecutive correct attacks | Gold secured | Added to team bank |
|---|---:|---:|
| 1–2 | 3 | 7 |
| 3–5 | 4 | 8 |
| 6+ | 5 | 9 |

These are flat tiers, not multiplying bonuses. Wrong answers reset the combo.
Recovery restores health and awards zero gold or bank contribution. Existing
damage-combo rules remain: with default settings, attack damage rises from one
to two at the sixth consecutive correct attack. Correct answers blocked by a
boss shield still earn academic rewards and count toward bank shares.

Gold secured is never removed on failure. Ending an unbeaten round/session
permanently expires that fight's team bank. A new round starts an empty bank,
while secured session gold carries forward. The bank expiry timestamp prevents
later finalization. Late player submissions are rejected after the fight ends.

Victory automatically unlocks the bank, without waiting for an admin reward
button. Half is shared equally and half follows each player's number of correct
attack answers. Only players with at least one correct attack qualify. This
prevents idle/recovery-only participation from collecting victory payouts.
Exact fractions and largest-remainder rounding distribute every coin; ties use
player ID for reproducibility. The admin can adjust the equal-share percentage.

The victory bonus defaults to 25 gold per eligible player. Optional victory
diamonds default to zero. The admin may select active catalogue gear and set its
drop chance per eligible player; no gear is enabled by default. A successful
gear roll gives the item once. Duplicate, unavailable or incompatible gear gives
an editable gold alternative, default 150, instead. A failed loot roll grants
neither gear nor compensation. The gold alternative enters secured session gold
and is saved with the rest when the session ends. Gear and diamonds are granted
persistently on victory.

All reward amounts, tier thresholds, bank split, victory bonus and loot settings
are available on the Boss Rush creation/next-round form. Appearance and frozen
gear modifiers remain separate from new loot earned during a fight.

## Player and admin experience

The battle panel shows Gold secured and Team bank with gold icons. HP and combo
remain visible above optional explanations. Expand “Victory & combo rewards”
for next-attack amounts, combo thresholds and the bank condition. Live updates
carry both balances. All connected players refresh into their victory receipt
when the boss falls, showing bank share, victory bonus and any gear/diamond loot.

The lobby explains bank expiry after failure and shows retained gold. Admin
supervision shows the bank status and final share/bonus/loot breakdown.

## Verification

- 64 targeted pytest checks passed in server staging, including the shared-bank
  integration suite, previous economy checks, Classic delivery/design, Gear
  Studio and player-loading regressions.
- Boss Rush battle-loop, legacy diamond rewards, lifecycle, player layout and
  account-reset regression scripts also passed in staging.
- A separate 13-check follow-up verified the compact template and legacy HP/
  combo rendering before its deployment.
- The new suite covers flat combo tiers, zero recovery rewards, automatic
  victory payout, failure expiry, late-answer rejection, next-round reset,
  eligibility, gear/diamond grants, duplicate compensation, failed loot rolls,
  repeated finalization, permanent settlement and admin access control.
- 1,000 randomized integer bank distributions conserved every coin.
- Migration rehearsed on an isolated SQLite copy and a PostgreSQL clone.
- Two concurrent PostgreSQL victory requests produced exactly one bank/gold
  payout, one gear item and one diamond award per eligible player.
- Browser check confirmed an attack at combo four changes personal gold from
  10 to 14 and the team bank from 29 to 37. The compact fullscreen layout was
  visually checked. A victory receipt with gear and diamonds rendered correctly;
  its rendered JavaScript passed Node syntax checks.
- Both local databases and all 48 existing online table counts were preserved.
  Existing wallet, diamond, saved-gold and gear ownership fingerprints matched.
  No test account or session was created online.
- Public health and admin creation/catalogue checks passed; game, exam,
  identity and Nginx services remained active. Local play is healthy on port 5001.

## Deployment and recovery

Initial 12-file release archive SHA-256:
`bf85ead139f5f4428f5040cde906a71ff72a1a34b7e33d65a914796138623f56`.
Fresh backups/source recovery:
`/var/backups/korephysics-game/boss-bank-20261019202940/`.

Compact UI follow-up (two files):
`/var/backups/korephysics-game/boss-bank-ui-20261019-203355/`.

Migration: `b82d01f3c753`, following `a71c90e2b642`. It is additive; source rollback
can retain the schema and migration lineage rather than restoring an older
database over newer player progress.

Local database backups:
`instance/boss-bank-local-backups/20261019-203013/`.
Private diffs, deployment manifests and rehearsal scripts are under `instance/`.

## Manual acceptance checklist

1. Create a **new** Boss Rush session. Correct attacks should add 3 secured/7
   team, then 4/8 from combo three and 5/9 from combo six. A wrong answer resets
   the tier. Recovery should add nothing.
2. End a fight while the boss is alive. Verify that secured gold is retained,
   the bank expires and no victory loot is awarded. A next round has a fresh
   bank; ending the whole session saves retained gold to the Hub once.
3. Win with two players contributing different numbers of correct attacks.
   Verify automatic bank distribution, the configured victory bonus, both
   player receipts and the admin breakdown. Refresh/re-finalize; balances must
   remain unchanged.
4. Configure one victory diamond and a gear item at 100% chance in a test round.
   Verify receipt and Hub ownership. Win again with the same gear and verify
   the configured gold alternative instead of duplicate ownership.
5. Inspect fullscreen at your classroom display size. Gold, bank, HP and combo
   should be easy to find; the reward details are expandable. Choose boss HP
   appropriate for your player count and intended fight length during balancing.
