# Classic mode live playtest

**6 November 2026 · KorePhysics online deployment**

The test used ten synthetic student accounts in a class-restricted room. Two players were scripted as strong, five as average, and three as weak. Each profile had a fixed accuracy sequence and a different answer pace. Every balance run used a fresh session wallet, the same question order per player, one attempt per question, zero wrong-answer penalty, and standardized competition with permanent bonuses disabled. Players used separate authenticated sessions and the production Socket.IO WebSocket. Selected admin and player flows also ran in Chromium at desktop and mobile sizes.

The test class and both banks were created with the live admin forms. Each bank has 20 questions, with 2 multiple-choice questions, 4 graph questions, and a mix of numeric, formula, and short-text answers. The 10 student profiles use synthetic addresses on the shared student sign-in system.

- [QA class](https://game.korephysics.com/admin/groups/2)
- [Main bank](https://game.korephysics.com/admin/sets/7)
- [Recovery bank](https://game.korephysics.com/admin/sets/8)

## Balance runs

The score columns show mean final session gold per player by profile. In each complete run, the seeded sequence produced 39/40 correct answers for strong players, 80/100 for average players, and 31/60 for weak players. The scripted delays were centered at 0.65, 1.18, and 1.95 seconds before each answer. These are accelerated simulations. The observed timers show the relative speed advantage in this test.

| Run | Settings varied | Submissions | Strong | Average | Weak | Class gold |
|---|---|---:|---:|---:|---:|---:|
| [R01](https://game.korephysics.com/admin/classic/6/history) | 8 answer + 4 Mine | 200 | 232.0 | 192.0 | 124.0 | 1,796 |
| [R02](https://game.korephysics.com/admin/classic/7/history) | 5 answer + 7 Mine | 200 | 234.0 | 192.0 | 124.0 | 1,800 |
| [R03](https://game.korephysics.com/admin/classic/8/history) | 8 + 4, timer +2 for 28 s | 200 | 273.0 | 215.6 | 135.3 | 2,030 |
| [R04](https://game.korephysics.com/admin/classic/9/history) | 8 + 4, timer +4 for 12 s, Double Mine in Store | 200 | 264.0 | 209.6 | 134.7 | 1,980 |
| [R05](https://game.korephysics.com/admin/classic/10/history) | 1–2 treasure gold, 30% Double Mine | 200 | 221.5 | 184.6 | 117.0 | 1,717 |
| [R06](https://game.korephysics.com/admin/classic/11/history) | 2–3 treasure gold, 30% Double Mine | 200 | 231.5 | 192.4 | 122.7 | 1,793 |
| [R07](https://game.korephysics.com/admin/classic/12/history) | 3–4 treasure gold, 30% Double Mine | 200 | 245.5 | 199.4 | 129.3 | 1,876 |
| [R08](https://game.korephysics.com/admin/classic/13/history) | 2–3 treasure gold, 55% Double Mine | 200 | 238.0 | 194.2 | 126.3 | 1,826 |
| [R09](https://game.korephysics.com/admin/classic/14/history) | 10% theft, cap 12, 35 s manual and 20 s reactive | 173 | 144.0 | 155.0 | 116.0 | 1,411 |
| [R10](https://game.korephysics.com/admin/classic/15/history) | 18% theft, cap 22, 18 s manual and 8 s reactive | 117 | 61.5 | 87.2 | 89.3 | 827 |

R01–R08 completed all 1,600 planned submissions. The theft error cut short two players in R09 and six in R10, leaving 173 and 117 submissions. Their scores reflect incomplete rounds. Across all ten configurations, the server graded 1,890 submissions with 1,405 correct answers and no disagreement with the scripted answer key.

Gold per solve and the action split matter separately. Moving from **8 correct + 4 mine** to **5 correct + 7 mine** still yields 12 for an ordinary successful Mine. The 8+4 split protects more of the learning reward when a player searches, steals, or leaves the action unfinished. The 4-gold Mine bonus also limits the value of each Double Mine to 4 extra gold. The 4-gold timer in R4 and 2-gem Double Mine purchase were intentionally tested together, so R4's total combines their effects.

The **+2 gold, 28-second** timer reached 39/39 strong, 59/80 average and 17/31 weak correct answers. The **+4 gold, 12-second** timer reached 13/39 strong, 17/80 average and 5/31 weak. Double Mine was purchased and used 10 times in R4 and applied 4 extra gold each time. Seven purchase attempts were correctly refused for insufficient gems. A timer applies from round start, which compounds differences in solving pace. The presets below use a zero timer.

The Easy candidate is **2–3 treasure gold**, or 50–75% of the ordinary Mine reward, plus a **30% base Double Mine chance**. With 75 searches, R06 granted 30 Double Mine charges and 27 were used. The base search gold averaged 2.53. Adding the 108 gold later earned from those consumed charges puts the realized contribution at about **3.97 per search** against 4 per plain Mine. The class finished with 1,793 gold versus 1,796 in the mining baseline. R05 came in at about 2.99 per search after the same attribution. R07 and R08 came in at about 5.04 and 4.41, respectively, making sustained search more attractive for these scripted players.

The Regular trial transferred **63 gold across 10 successful steals** of 3–12 each. Greedy transferred **110 gold across 8 successes** of 8–22 each. Victim notifications matched the credited gold in both cases. The proposed Regular preset lowers the tested cap from 12 to **6 gold**. At a blind 3-in-5 win chance, that caps expected direct earnings at **3.6 gold** against 4 for a guaranteed Mine. A steal can still change the gap between two players. Greedy keeps the tested cap of 22 and gives targets a shorter protection window. Both presets need a rerun after the theft bug is fixed. The two bundled comparisons and incomplete rounds leave the best shield durations and steal percentage unresolved.

## Presets to enter in Classic setup

Shared settings for all four presets are **8 correct-answer gold**, **4 Mine gold**, **1 attempt**, **0 wrong-answer penalty**, **0 combo gold**, **0 speed bonus**, **0 first-solver bonus**, and **Standardized competition on**. Use a **0.10 pity increment**, **0.75 chance cap**, **3 held temporary bonuses**, **0 gem streak**, and **0 Gem chest chance** in the treasure presets.

| Setting | Intro | Easy | Regular | Greedy |
|---|---:|---:|---:|---:|
| Treasure base gold range | 0–0 | 2–3 | 2–3 | 2–4 |
| Double Mine chest chance | 0% | 30% | 30% | 40% |
| Steal Token chest chance | 0% | 0% | 35% | 55% |
| Shield Token chest chance | 0% | 0% | 35% | 40% |
| Second Chance chest chance | 0% | 0% | 20% | 20% |
| Gem milestone | Off | Off | 1 per 3 correct | 1 per 3 correct |
| Steal attempts per session | 0 | 0 | 2 | 3 |
| Successful steal | Off | Off | 10%, cap 6 gold | 18%, cap 22 gold |
| Manual shield | Off | Off | 35 s | 18 s |
| Reactive protection after theft | Off | Off | 20 s | 8 s |
| Steal minigame | Off | Off | 3 winning spots of 5 | 3 winning spots of 5 |

Use a zero theft minimum and zero stranger payout in Regular and Greedy. Keep the default store in those two presets. Remove all four seeded store items in Intro and Easy. Easy obtains Double Mine through Treasure. Intro currently needs a facilitator to direct players to Mine because the zero-value Treasure button and disabled-mechanic indicators remain visible.

Chest percentages are **base fill probabilities for eligible rewards**. Eligibility and held bonuses determine which chests appear. The failure counter can raise the next chosen chest's chance. Players choose one chest, so a 35% Shield setting does not mean 35% of all Treasure Searches award a shield.

## Admin and player findings

| Priority | Area | Observation and reproduction | Change worth making |
|---|---|---|---|
| Blocker | Steal stalls when the target becomes protected | In sessions 14 and 15, a target gained protection after the target list was issued. One pick then received no minigame start or result, and seven chest confirmations received no result. The eight timed-out players stopped submitting in those runs. Server logs recorded eight PostgreSQL `StringDataRightTruncation` errors in the fallback path. The outcome `stranger_target_invalid` has 23 characters and the live `steal_event.outcome` column allows 20. | Add a migration to match the model's 32-character column, and exercise the protected-target fallback at both target selection and chest resolution on PostgreSQL. Return a recoverable response if resolution fails. |
| High | Admin event scope | In session 11, a signed-in student was denied `classic_admin_watch`, then received `admin_summary_update` on the ordinary game socket. In session 14, a student received a populated admin theft log with actor, target, outcome, and gold. | Deliver supervision events to a separately authorized admin room. Keep the public leaderboard and private victim notification in their own channels. |
| High | Restricted final results | Remove a synthetic former participant from the QA class after session 16. The lobby route redirected the player to the dashboard, while the direct final-results route still returned the names and scores. Class membership was restored afterward. | Apply the class and enrollment guards to the final-results route. |
| High | Treasure refresh | Solve a problem, choose Treasure, select a chest, and refresh before confirming. In sessions 18 and 19 the Confirm control stayed invisible. In session 19 the game restored `selected_pending_confirm`, but the entire problem detail panel was hidden, leaving the restored overlay inaccessible from the normal flow. | Restore the associated problem and reveal the workspace before opening a pending chest overlay. Verify refresh before selection, before confirmation and after reveal. |
| High | Intro and Easy controls | Set treasure gold and every chest chance to zero, set steal attempts to zero, and remove seeded items. Players still see Treasure Search, the shield area, the Store control, and a starting steal token. In session 6, selecting Treasure consumed the action and paid 0. Easy also displayed an unused starting token. | Add switches for Treasure, Steal, Shield and Store. Apply the switches to wallet initialization, store seeding, UI and server validation. |
| Medium | Shield feedback | Four in-round manual activations were refused because the player already had protection. The token stayed in inventory. The player page has a protection countdown, but button eligibility uses the token count and round status. | Tie the Activate button to the existing countdown so it becomes available at expiry. |
| Medium | Admin graph authoring | Add a Graph and an Equation, enter `y = 3`, and save. The editor says “Unsupported graph equation syntax.” A slope, a quadratic and labelled points saved. | Accept horizontal constant functions and show the exact supported syntax beside each graph row. |
| Medium | Live admin progress | The live roster and leaderboard updated, and the solver table matched the correct-answer totals. The solver table displayed internal problem IDs such as 1789. It exposes aggregate solves without a per-player view of attempts, correct answers or connection status. | Add a progress grid with player, attempts, correct answers, last activity, connection state and a drill-down. Use problem number and title in the solver list. |
| Medium | Problem numbering | The same set opened with different player-visible problem numbers after edits to prompts and titles. Problem 5 originally showed the line-gradient graph, then showed the momentum formula with the same set membership. | Persist an explicit set order and use it for gameplay, the live solver view and history. |
| Medium | End of session | One browser stayed on the lobby's waiting message when the admin ended the session immediately after returning players to the lobby. A later test with time for the lobby to connect opened Final Results automatically. The between-rounds lobby showed the same message as the initial waiting lobby. | Send distinct initial-waiting, between-rounds and finished states on join or reconnect. A finished state should open results even if the browser missed the end event. |
| Medium | Admin session setup | Every new session began with four seeded store entries. Creating the mining and treasure-only configurations required separate store deletions. Classic's one-active-session rule also means a restricted class uses the same Classic slot as a real class. | Save and reuse named presets including the store inventory. Add an isolated rehearsal mode or separate test room slot. |
| Medium | Player grading | Text answers use accepted strings with basic normalization. On the same conversion problem, the listed `2.0` passed and the equivalent unlisted `2.00` consumed the only attempt. A plotted prompt can ask for a typed graph reading. | Add optional numeric tolerance, unit-aware grading, symbolic equivalence, and graph or multi-step response types where the question requires them. |
| Low | Formula authoring | HTML tags typed into the rich-text block rendered as literal text. The mobile test displayed `<strong>F = ma</strong>` in the question. | Show supported bold and TeX syntax beside the editor, with the same formula preview as the player sees. |
| Product decision | Recovery | The bank was saved with the recovery flag. Classic setup accepts one main bank. Classic's Second Chance preserves an attempt through a consumable rather than serving a recovery question. | Add a Classic recovery-bank selector and trigger rules if recovery questions are intended for Classic. |

## Verified flows and scope

- The admin saw all ten players enroll, start and submit. Across the ten balance runs, the live solver table counted all 1,405 correct answers. All 100 final player leaderboard snapshots agreed with the admin snapshot, and all 100 player connections received the session-end event.
- Desktop Chromium exercised the admin Start and End controls, MCQ selection and confirmation, mining, formula rendering with MathJax, and the Plotly graph. At 390 px, the browser could sign in, page through questions, render the graph and reload without horizontal page overflow. The test-bank formulas were revised to supported TeX after the initial formatting check.
- Two players reconnected while a correct answer was waiting for an action and got the same pending action back. Five wrong answers used Second Chance and kept their attempt.
- In a focused Greedy replay, a manual shield excluded its holder from the target list until the 18-second protection expired. A successful 6-gold steal notified the victim with the same amount. A separate attacker could target that victim again after the 8-second reactive protection expired.

The scored matrix covers sessions 6–15. Session 5 was a setup retry closed before any player joined. Sessions 16 onward were focused browser and protection replays using the same settings, separate from the balance totals. The QA class, accounts, banks, and finished history remain available for review. The recovery bank was authored and saved through admin controls. The balance runs used the Classic main bank.

The player policies used fixed speeds and a scripted mix of actions. That supports comparison under controlled inputs. Real classroom pacing, repeated treasure rolls under other policies, and a broader sweep of shield and theft settings remain open. Intro and Easy have the cleanest live evidence. Regular and Greedy need a full ten-player rerun after the fallback defect is repaired.

Evidence is in [the run summary](../instance/classic-live-qa-1106/summary.json), [the admin live screenshot](../instance/classic-live-qa-1106/admin-live.png), [the mobile graph screenshot](../instance/classic-live-qa-1106/mobile-graph.png), [the protection replay](../instance/classic-live-qa-1106/ui-replay.json), and [the Treasure refresh trace](../instance/classic-live-qa-1106/ui-treasure-refresh.json).
