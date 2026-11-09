# Economy redesign — 19 October 2026

Boss Rush has since received the shared-bank redesign described in
[the Boss Rush release notes](boss-bank-release-20261019.md). Its new-round
rewards supersede the Boss Rush defaults documented below.

Applied to the online game and both local databases. Local play is running on
http://127.0.0.1:5001/. Create a **new session** to use the redesigned economy.
Historical sessions retain version 1. No historical gold was credited, as
requested. Existing diamonds, owned gear, upgrades and game results survive.

## Rules delivered

Classic defaults: correct answer +5 gold immediately; Mine +5 additional;
Treasure +2 additional plus a selected chest; combo +2 on each correct answer
starting with the third consecutive correct answer. Timer and first-solver
bonuses default to disabled. The administrator can configure these values.

Gold and gems carry across rounds. One gem is awarded every five correct answers
in the session, including answers followed by Steal. Correct counts and streaks
are persisted. Wrong answers reset the streak. Additional streak gems are an
optional admin rule, disabled by default.

At session completion, remaining gold is added to saved gold exactly once and
gems expire. The final session gold remains available as the historical score;
finished-session guards prevent spending it. A settlement marker and unique
per-player ledger keys are committed with the balances. Saved gold cannot be
stolen. Repeated completion requests and reconnects do not duplicate credit.

Treasure preserves the chest selection/reveal interaction. Shield Token and
Second Chance start at 35%, Steal Token and Double Mine at 30%, and Gem at 10%.
Each unsuccessful selected reward increments a persisted session failure count.
Only the selected chest receives +10 percentage points per failure, capped at
75%; a granted reward resets the count. Unselected chest reveals retain their
base rolls and remain shaded. Eligibility and capacity are checked again when
granting the selected reward.

Steal defaults to 12% of current target session gold, maximum 15 gold, with three
winning containers out of seven. A player can attempt two steals per session;
extra tokens do not bypass this limit. Failed/no-target steals default to zero
additional gold. Reactive protection remains. Transfers cannot overdraw a target.

New-session stores are seeded with editable defaults: Shield Token, Second
Chance and Steal Token cost one gem; Double Mine costs two. Each has a two-copy
purchase limit. The player may hold one charge of each effect and three total
temporary bonus charges by default. Double Mine doubles only the mining base,
not the correct-answer reward, combo, permanent bonus or other multipliers.

Blacksmith equipment uses saved gold. Existing catalogue prices become 300–500
gold; the administrator can edit each saved-gold price. Existing cosmetics and
ownership are preserved. Combined permanent earning bonuses are additive and
capped at 10%, with fractional carry so low base rewards do not round every
bonus down to zero. Standardized competition disables permanent modifiers while
retaining appearance. Legacy diamonds remain available for existing upgrades;
new accounts no longer receive a diamond grant.

Boss Rush: correct attack +10 gold, defeat participation +25, **recovery +0**, per
the user's clarification. Recovery still restores health. Defeat participation
requires at least one submitted attack or recovery answer. Defeat rewards are
credited once when finalized or when the administrator ends the defeated round
or session. An unsuccessful session retains earned attack gold. Both modes bank
into the same saved-gold account. Existing version-1 Boss Rush diamond rewards
retain their legacy behavior.

## Validation

- 52 targeted pytest checks passed locally and in server staging.
- Existing Treasure/Steal, Boss Rush lifecycle/UI/legacy rewards and account-reset
  regression scripts passed in staging.
- Migration rehearsed on a local SQLite copy and an isolated PostgreSQL copy.
- Real concurrent PostgreSQL transactions verified one settlement credit and
  rejection of a second unaffordable simultaneous gear purchase.
- A disposable 30-player Socket.IO classroom completed 600 submissions across
  20 questions. At mean 15.03 correct answers, mean gold was 165.67 and mean gems
  2.60. The gold range was 114–206. All 30 wallets banked once and gems expired.
  This academic-work simulation used Mine; it is not a mixed-action load test
  or a substitute for a real classroom balancing trial.
- A separate 5,000-transfer arithmetic simulation preserved total gold and
  nonnegative balances with the 15-gold cap.
- Browser check verified immediate +5 answer credit and the updated action
  labels. The deployed online form exposes the new balancing controls.
- Public health, Classic/Boss creation forms, gear catalogue, deployed checksums
  and all four services passed. No test player or session was created online.

Both local database migrations preserved old table counts and diamond balances.
Online migration preserved all 47 old table counts and a fingerprint of existing
diamonds, session wallets and owned gear. Saved gold begins at zero.

## Deployment and recovery

Online release: 39 checksummed files, no unfinished sessions at restart.
Archive SHA-256:
`e6ec77796b639bf4895428c6799131445bf875046220f3affe1d451d2c079527`.

Fresh game and examination backups completed before migration. Source recovery
and verification: `/var/backups/korephysics-game/economy-20261019181514/`.
The migration is additive. A source rollback should retain the migration file
and schema lineage; do not restore an old database over new player progress.

Local database backups: `instance/economy-local-backups/20261019-181555/`.
Private release diff, manifest packaging scripts and simulation evidence are
under `instance/`.

## Manual acceptance checklist

1. Reload and create a new Classic session with defaults. A correct answer gives
   +5 before action selection; Mine adds +5. The third consecutive correct answer
   adds the +2 combo bonus. Check one gem at the fifth correct answer.
2. End the round and start another. Gold, gems, streak/correct counters and steal
   attempt counts carry across. Refresh during play and verify the counters.
3. Try Treasure and its selected/unselected reveal states. Double Mine should
   apply to one Mine action only. Buying another held copy should be refused.
   Probability increases are statistical, not a guarantee on an individual try.
4. Test Steal with two players: the configured percentage/cap, victim protection,
   failure outcome, and refusal after two attempts. A token purchase cannot
   reopen a spent session attempt allowance.
5. End the session. Check saved gold in Hub and zero unspent session gems.
   Refresh the result page; saved gold must not increase again. A new session
   starts at zero session gold/gems. Buy equipment using saved gold.
6. Enable standardized competition in a new test session. Equipped appearance
   remains, while permanent modifiers provide no advantage.
7. Test Boss Rush: correct attack +10, recovery +0, defeat participation +25 once.
   End an unsuccessful attempt and verify attack gold reaches saved gold.

Gem prices and gear prices are initial defaults. Use actual classroom spending,
Treasure choices and session length to decide further balancing changes.
