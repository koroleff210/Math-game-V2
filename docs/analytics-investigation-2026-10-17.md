# Game results and learning analytics: investigation and proposal

Investigated 17 October 2026. Scope: the deployed game at https://game.korephysics.com/. The separate test application was checked briefly for reusable ideas; changes to that application are outside this proposal. This is a proposal, not an implementation or deployment.

## Recommendation

Keep the existing answer capture and build a learning report around each session. Give the teacher a student-by-question matrix, individual session reports, topic trends, and a complete evidence export for AI. Give students a simpler view of their own progress, feedback, and next practice. Connect follow-up assignments to the original evidence and check learning again later on different questions.

Do this before adding an opaque mastery score or automatic AI assignment. The first useful release can work without an AI API: download a structured evidence package, analyze it with AI, and review a proposed practice list before assigning it.

## What I verified

- Read-only SSH inspection of the actual deployed game and its PostgreSQL database. At inspection: **0 game sessions, 0 analytics rounds, 0 answer attempts, and 0 non-admin player profiles**. This agrees with today's documented V4 fresh start. Empty reports currently do not indicate broken tracking. Earlier local/backup results must not be presented as current online results.
- SHA-256 equality between local and deployed versions of all ten inspected reporting files: analytics models, capture service, reporting service, export service, admin/player routes, three teacher analytics templates, and the student progress template.
- Existing analytics tests H1–H7 run directly using their in-memory SQLite configurations: **82 passed, 0 failed**. These cover capture, mode events, teacher reports, exports, student reports, and access restrictions. They are not a full production class rehearsal or a PostgreSQL regression run.
- A separate in-memory reproduction confirmed the Boss Rush context-mixing defect described below. No production records or application code were changed.
- Browser screenshots of populated production reports were not available: the live game has no results. UI conclusions below come from deployed templates and report code, with isolated test evidence.

## What exists now

| Area | Current behavior | Main limit |
|---|---|---|
| Teacher: Analytics → rounds | Latest 100 analytics rounds; Classic/Boss Rush filter; individual round detail | No session-level learning overview, student search/filter, or pagination |
| Teacher: Class Dashboard | Class, subject, mode and date filters; topic results, player summaries, most-missed questions and recent rounds | No student-by-topic heatmap, trend chart, exact session selector or individual learning profile |
| Round detail | Metadata, player summaries, problem summaries, player/question states, ordered answer attempts and mode events | Long tables; no question matrix or consolidated session analysis |
| History | Frozen round/player summaries, CSV export, archive/unarchive/delete; Classic has per-session history | Distinct from detailed analytics; game-oriented frozen summaries are not a complete learning report |
| Student: Hub → My Progress | Lifetime overview; last 10 rounds; topic table; up to five review topics; last eight incorrect attempts; Classic/Boss Rush records | No selectable session report, timeline chart, question review flow or assigned next practice |
| Student: Performance / History | Placeholder pages | Navigation suggests features that do not yet exist |
| Exports | Class-summary CSV and detailed round CSV with attempts and mode events; legacy history CSV | No complete session bundle or versioned AI format |

Teacher entry points:

- `/admin/analytics/`
- `/admin/analytics/class-dashboard`
- `/admin/analytics/rounds/<analytics_round_id>`
- `/admin/history/rounds`

Student entry point: `/player/progress`, restricted to the signed-in student's data.

### Recorded evidence

The model hierarchy is session → round → student/question/context → answer attempt. A session can contain multiple rounds. An analytics student/question row is unique within a round and context; it is not a record of every presentation of that question.

Already captured:

- Session/round IDs, mode, class, set, dates, labels and settings snapshots.
- Question ID, title, answer type, subject/topic and available source metadata snapshots. Imported V4 metadata includes the canonical `phys_…` ID, content/answer hashes and selected source classifications.
- Student ID, name snapshot, join/completion information and finalized round summaries.
- First-seen timestamp, attempt count, first-attempt correctness, eventual correctness and question status.
- Each submitted answer: time, attempt number, text or selected option, selected-option label/text, correctness, mode and action context.
- Classic economy and Boss Rush battle events linked to answers where applicable: rewards, theft, purchases, damage, recovery and related state.

This is a substantial foundation. We do not need to replace it to produce better reports.

### What the numbers actually mean

Current “accuracy” is correct submissions ÷ all submissions. First-try correctness is measured per student/question/round/context, not the first time the student has ever encountered that question. “Problems tried” similarly counts those occurrences across rounds, not necessarily different questions. Eventual correctness means the question was solved at least once in that round/context; it does not establish durable learning.

Example: eight questions, four right immediately, four right on their second attempt. First-try correctness = 4/8 = 50%; eventually solved = 8/8 = 100%; attempt accuracy = 8/12 ≈ 67%. All three are valid, but answer different questions.

## Issues to resolve before trusting stronger analysis

1. **Confirmed context-mixing defect.** `_build_analytics_problem_summaries` calculates counts by round and problem, without `mode_context`. If the same question appears in Boss Rush attack and recovery, both rows receive combined totals. Reproduction: one correct attack answer plus one incorrect recovery answer produced two attempts and 50% accuracy on each row; each should have one attempt, with 100% and 0% respectively. The detailed round CSV inherits these summaries. Raw answer rows retain context and can be recalculated correctly.
2. **Historical question reconstruction is incomplete.** Capture explicitly leaves `answer_key_snapshot_json` empty. Titles, selected option text, provenance and hashes are retained, but the complete prompt, all options, diagrams, correct answer and explanation are not frozen together. A later edit/import can therefore prevent faithful review of what a student saw. Store immutable question versions and durable asset references, with the grading rule/key used at the time.
3. **Timing cannot yet mean solving time.** First-seen and submission timestamps exist, but do not separate thinking from disconnections, shopping, waiting, combat animations or revisits. Display any derived interval as elapsed time only. Add question presentation/leave/resume events and carefully defined active time before using speed in learning analysis. The test app already distinguishes several timing states; reuse the definitions where useful without importing its entire monitoring system.
4. **Repeated presentations are collapsed.** Boss Rush recovery can repeat indefinitely, while its student/question summary keeps one first-seen time and an eventual-correct flag. Add a presentation/encounter ID and sequence to separate repeats, retries, and later independent evidence. Preserve the existing raw attempts.
5. **Mixed learning contexts obscure trends.** Class and student summaries can combine Classic, attack and recovery. Recovery questions and repeated familiar items can inflate apparent success. Expose these contexts separately, including in AI exports.
6. **History visibility differs from analytics inclusion.** Archiving or deleting a frozen `RoundHistory` record does not automatically exclude detailed analytics from class/student aggregates. Add an explicit “include in learning progress” setting with a reason, consistently applied by charts and exports. Keep this separate from archiving and student visibility.
7. **“Topics to review” is a simple heuristic.** It sorts low lifetime accuracy after a small amount of activity; it does not measure recent improvement, skills, retention or meaningful sample size. The recent-missed list can also repeat errors from the same question and show a question later solved. Show unresolved and resolved errors distinctly.
8. **Open sessions lack a class-dashboard path.** The dashboard requires a class, although a game session can be open. A direct session report must work regardless of class assignment.
9. **Question classification needs improvement.** V4 import uses the first class code as the primary topic and preserves all classes in metadata. Difficulty defaults to 1 when the incoming value is not an integer. Preserve raw difficulty and mark missing/uninterpretable values as unknown; add curated skill tags and misconception labels where reliable. Do not interpret a fallback value as calibrated difficulty.
10. **Scaling and reconciliation need attention.** Report services load full filtered histories and contain repeated per-question queries; the student topic lookup scans question rows per attempt. Use grouped SQL queries, indexes and pagination as data grows. Label active reports provisional and show finalization/data-quality status so raw attempts and cached round summaries are not mistaken for identical live views.

## Proposed teacher experience

### A. Sessions: the main reporting entry point

Each session row shows date, label, class/open status, mode, round count, participation, first-try correctness and follow-up state. Filter by student, class, date, set, topic, mode and whether the session counts toward progress. Open a session to see all its rounds together, with round drill-down preserved.

At the top, show who joined, who answered, late joins and participants with no answers. For class sessions, store the intended roster at session start so future membership changes do not rewrite attendance. For open sessions, use participants and avoid inventing an expected class roster. Random question selection means a student should not be penalized for questions never offered.

### B. Session overview and student-by-question matrix

- Columns: canonical question identities within their round/context; rows: students. Group or filter by round, topic and context.
- Cell labels: not presented, presented/no answer, first-try correct, correct after retry, unresolved incorrect. Keep absence separate from performance.
- Each cell opens the actual version of the question, answers in order, explanation, timing quality and teacher feedback.
- Summary: first-try correctness, eventual solve rate, retry burden, exposure/coverage and sample size. Keep gold, damage and ranking in a separate game-results section.
- Question analysis: first-response option distribution, common wrong answers, students affected and exposure count. Also offer all-attempt distribution, clearly labeled, so repeated guesses do not masquerade as a class misconception.

### C. Individual student learning profile

From any student row, open a profile with their selected session, prior sessions, question history, teacher notes and practice assignments. Compare a session with the student's previous comparable evidence, and compare selected sessions explicitly.

Teacher actions should include: annotate a result; mark a technical interruption; exclude a whole session or a specific result from learning trends with a reason; create a review group; export selected students; draft a practice assignment; preview the student's report; publish or withdraw feedback. Corrections should preserve original evidence and a revision trail rather than silently rewriting answers.

### D. Visual progress

Start with three views:

1. **Session timeline:** first-try correctness over time, attempted/unique-question counts and repeated-question share. Click a point to open the supporting session. Separate contexts and flag changes of question difficulty or set.
2. **Student × topic heatmap:** show percentage and evidence count together, with an explicit “insufficient evidence” state. Select a cell to inspect the underlying questions and recent trend.
3. **Practice outcome:** initial gap → assigned practice → completion → later check on different questions. Show immediate correction and delayed retention separately.

Use familiar labels such as “needs more evidence”, “needs practice”, “improving” and “secure on recent checks”, with visible evidence rules. Start with transparent rules rather than a mathematically elaborate mastery number. Never show 100% from one easy or repeated question as established mastery.

## Proposed student experience

Make one clear **My Learning** destination and connect or replace the current placeholder pages.

- After a session: what they attempted, first-try results, improvements after retries, topics to practise and a short teacher/AI-assisted explanation reviewed by the teacher.
- Over time: their own session trend, topic progress with evidence counts, and practice/check completion.
- Review: full question and their answer sequence; show correct answers and explanations according to teacher release settings.
- Next practice: a small assigned set, the reason for each selection, a due date if needed, and a visible completion/check stage.

Add separate controls for releasing scores, correct answers/explanations and feedback. Private teacher notes and other students' results remain outside the student payload. Provide a teacher “view as student” preview. These are actual server-side access rules, not just hidden UI elements.

## AI analysis and follow-up practice

### First release: export → analyze → review → assign

1. Teacher selects a session or recent window, students and contexts.
2. Download a ZIP containing a versioned JSON report, simple rectangular CSVs, question versions and diagrams needed to interpret them. Include a reusable analysis prompt.
3. AI returns an evidence-linked diagnosis and a proposed practice plan. Each claim cites actual student/question/attempt IDs, distinguishes observations from hypotheses, and states insufficient evidence where appropriate. A wrong MCQ choice alone cannot prove the reasoning error.
4. Teacher reviews recommendations, adjusts skill labels and question selections, then creates/publishes assignments. Merely importing AI output creates a draft.
5. Student completes practice; a later check uses fresh questions targeting the same skill. Results link back to the initial gap and assignment.

Existing problem sets select content, but do not provide this full per-student assignment and completion workflow. That requires explicit assignment, assignment-item, learner-progress and follow-up-check records.

### Evidence package requirements

Include schema/metric versions; timezone and generated-at; source and report scope; stable student aliases; session/round/context; roster/participation; canonical question/version IDs; full prompts/options/assets; correct answers and explanations for the teacher package; subject/topic/skill/difficulty including unknown values; complete attempt sequences; first/repeat exposure information; timing quality; exclusions and reasons; comparable earlier results; and the IDs/metadata of available follow-up candidates.

Default to aliases rather than names/emails, with a local teacher mapping. Exclude credentials, server paths and unrelated operational metadata. Current source snapshots include local bank paths, so do not blindly serialize the ORM records. Teacher exports may contain answer keys; student exports need a different, release-aware schema.

Current CSVs are useful for exploration, but they omit complete question versions, canonical IDs in the main attempt table, diagrams and explanations. They also concatenate sections with different columns. Add separate `students.csv`, `questions.csv`, `attempts.csv`, `summary.csv` and a JSON manifest for dependable AI/software use. Escape formula-leading free text in CSVs, including student answer text.

### Suggested AI response contract

```json
{
  "schema_version": "practice_plan.v1",
  "source_report_id": "report-id",
  "students": [{
    "student_alias": "S014",
    "findings": [{
      "skill_id": "forces.vector_components",
      "observation": "Incorrect on two first exposures",
      "evidence_attempt_ids": [101, 116],
      "hypothesis": "May be confusing components with magnitudes",
      "confidence": "limited"
    }],
    "suggested_items": [{
      "canonical_question_id": "existing-bank-question-id",
      "purpose": "prerequisite_check",
      "reason": "Check vector components before a mixed forces problem"
    }],
    "delayed_check_skill_ids": ["forces.vector_components"]
  }]
}
```

This is a proposed format, with fictional identifiers. Validate report/student/question IDs, duplicates, eligibility and supported answer types on import. Prefer questions from the reviewed bank first. New AI-generated questions should be saved separately as drafts with a checked answer/solution before students receive them.

Use a short progression tailored to the evidence: prerequisite check when needed, accessible practice, a fresh transfer question and a delayed retention check. Avoid simply assigning the questions already missed. Persist the plan, teacher edits, publication state and resulting evidence so the next analysis can determine whether it helped.

## Implementation order and completion criteria

| Phase | Deliverable | Completion criterion |
|---|---|---|
| Foundation | Fix context counts; define metrics; version/freeze questions and keys; define inclusion, provisional/final and unknown-data rules | Same-question attack/recovery reproduction passes; edits/imports preserve historical review; raw and finalized totals reconcile |
| Teacher session reports + AI export | Session list/detail, matrix, student drill-down, attendance/coverage, filters and complete export | Teacher can trace one session → one student → one question → every answer and export the same scope |
| Student progress + publication | Learning home, session reports, topic evidence/trends, teacher release controls | Student sees only their own permitted data; before/after release and teacher preview are verified |
| Practice and learning loop | Reviewed AI-plan import, personal/group assignments, fresh follow-up checks | An initial gap can be traced through assignment completion to later evidence of improvement |

The first meaningful product increment should be **Foundation + Teacher session reports + AI export**. It makes the next real class session inspectable and immediately supports AI-assisted planning. Add basic presentation tracking before that class if solving-time or repeat-exposure analysis is a priority; those observations cannot be reconstructed precisely afterward.

Do not make automated model calls, cross-application unification, population-calibrated difficulty or a predictive mastery model prerequisites for this release.

### Verification for the implementation

Exercise Classic and Boss Rush, multiple rounds, the same question in both contexts, repeated recovery, exhausted retries, no answers, zero attempts, open sessions, late joins, reconnects and unfinished rounds. Check class-membership changes, question/answer edits, re-imports, archived/excluded records, local date boundaries, large classes, filters and stable pagination. Assert metric denominators with small known examples and compare screen/export totals. Test students requesting another student's or unreleased report. Validate AI imports against stale or foreign IDs and unsupported questions. Rehearse a small live class after isolated SQLite/PostgreSQL checks.

## Code evidence / starting points

- [Analytics data model](../app/models/analytics.py): contexts, round snapshots, player/question lifecycle and raw attempts.
- [Capture/finalization](../app/services/analytics.py): `snapshot_round_problem`, `record_answer_attempt`, `finalize_player_round_summary`.
- [Teacher/student aggregation](../app/services/analytics_reports.py): `build_class_dashboard`, `build_player_dashboard`, date handling and review-topic heuristic.
- [Teacher routes](../app/routes/admin.py): `_build_analytics_problem_summaries`, round/class pages, exports and history controls.
- [Exports](../app/services/analytics_exports.py): detailed round and class multi-section CSVs.
- [Frozen history](../app/models/history.py): separate round-level aggregates and archive state.
- [Student routes](../app/routes/player.py): implemented progress page and performance/history placeholders.
- [Boss Rush engine](../app/modes/boss_rush/engine.py): repeated recovery presentations and answer capture.
- [V4 import](../app/services/v4_import.py): canonical IDs, primary topic, source metadata and difficulty handling.
- [Live deployment record](korephysics_live.md): fresh start, retained backup and production verification boundaries.

The accompanying preview uses fictional students, sessions and results. It illustrates the proposed report interactions and does not represent current live data.
