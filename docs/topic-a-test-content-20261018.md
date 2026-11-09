# Topic A test content — 18 October 2026

Added to the live game under **DP Physics**, with the V4 taxonomy:
A.1 Kinematics; A.2 Forces and momentum; A.3 Work, energy and power;
A.4 Rigid body mechanics; A.5 Galilean and special relativity.
Topic descriptions identify the parent family A — Space, time and motion.

| Set | Online ID | Scope | Content |
|---|---:|---|---|
| Mechanics 20 | 3 | SL A.1–A.3, excluding circular motion | 15 V4 MCQs + 5 legacy definitions |
| Relativity 20 | 4 | HL A.5, Galilean and special relativity | 15 V4 MCQs + 5 new definitions |
| Rotational 20 | 5 | SL circular motion from A.1–A.3 | 15 V4 MCQs + 5 new definitions |
| Rigid body 20 | 6 | 3 SL circular-motion MCQs + 12 HL A.4 MCQs | 15 V4 MCQs + 5 new HL definitions |

All 80 question IDs and prompt texts are distinct across sets. Difficulty was
assigned on the game's 1–5 scale: definitions 1–2, MCQs 1–4. Sets are enabled for
Classic, Boss Rush, and recovery. Definitions use text input with accepted term
variants; case and surrounding whitespace are ignored by the existing grader.
Neutral definition titles prevent answer disclosure in Boss Rush.

V4 JSON records and the old local database were read without modification.
Source IDs, raw level/classification, original content/answer hashes, and package
provenance are stored in ProblemSourceMetadata. The imported display copies retain
paragraphs, expand table options into labeled value pairs, normalize unit/trig
commands, and match a conical-pendulum question's angle symbol to its diagram.
No application release, database migration, restart, player, or game session was
needed. Existing accounts/history were preserved.

The new circular-motion definitions were checked against
[OpenStax](https://openstax.org/books/physics/pages/6-2-uniform-circular-motion);
relativity terminology was checked against
[University of Maryland relativity notes](https://physics.umd.edu/grt/taj/410b/410notes.pdf).

Validation: isolated import rehearsal; all MCQ choices and accepted definition
answers checked through the existing graders; live import; repeat-import check
with zero row additions; 80 authenticated browser previews with no MathJax errors
or horizontal overflow, all 14 diagrams loaded; screenshots of all 80 previews
and 12 mobile samples; visual review of every desktop preview.
Manual gameplay is left for the user's requested test.

Local package, reports, and screenshot evidence:
`instance/topic-a-20261018/`. Final package JSON SHA-256:
`73f430d37c8147dcca91a29b80a9983ab2678caea8c37e1ea427fb414237af35`.
Pre-import backup: `/var/backups/korephysics-game/game-20261017-221711.zip`.
Initial import and final verification reports are saved alongside server backups
as `topic-a-import-20261018.json` and `topic-a-final-20261018.json`.
