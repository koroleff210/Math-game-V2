# Session reports: first test run

The teacher entry point is **Session Reports** in the admin sidebar:
https://game.korephysics.com/admin/analytics/sessions

## Prepare and run

1. Import your selected approved Questionbank V4 ZIP through **Content Import**, then create a small problem set. The fresh-start game has no questions or students until these are added.
2. Create or link two student profiles and optionally put them in a class. Existing test-site students can sign in with their shared credentials to create game profiles.
3. Start a normal Classic or Boss Rush session with a recognizable label. For a short reporting check, use a few questions and allow retries. In Boss Rush, using the same question in attack and recovery also checks that those contexts stay separate.
4. Have one student submit an incorrect answer and then a correct retry; have the other answer correctly on the first try. Leave one presented question unanswered. A second round lets you check session aggregation.
5. Open **Session Reports**, select the session, and reload while it is running. The report is provisional until all rounds are finalized. Questions captured in an unfinished round cannot be edited or replaced by an import; finish that round before editing them.
6. Finish the session using the normal game controls. Review the matrix and click a result to see the saved question, answer key, diagrams and answer sequence. Filter by student, round or Classic/attack/recovery context.

The teacher can select a student in the session report and follow **View this student's progress across sessions**. This shows first-response bars and counts for the selected page of sessions. Sets, contexts and difficulty can differ, so the chart is evidence to inspect, not a calibrated mastery score.

## Share with students

Save session feedback under **Teacher controls**, then choose **Publish results to students**. Publishing releases each student's own answers, correct answers and available explanations together. The **Student preview** link lets you inspect that view first. Private teacher notes remain private.

Students open **My Progress** in their Hub, select the published session, and review their own questions. New sessions remain absent from their learning statistics until published. **Withdraw student report** removes access again. An excluded session remains available for review if published, but is omitted from learning-progress totals; excluding requires a reason. Legacy analytics without publication settings retain their previous aggregate behavior.

## Analyze with AI

Choose the desired student/round/context filters, then **Export selected evidence for AI (.zip)**. The package contains:

- `report.json`: versioned, alias-based evidence, definitions, scope and frozen question content/keys;
- rectangular student, question, attempt, outcome and summary CSVs;
- frozen question/option diagrams in `assets/`, with missing/changed files identified in the manifest;
- `ANALYSIS_PROMPT.txt`: a starting prompt requiring evidence-linked findings and a teacher-reviewable practice plan.

Aliases such as `S000002` are displayed next to student names in the teacher matrix. Names, emails, private notes, credentials and source-server paths are omitted from the structured export. Student-authored answer text is preserved as evidence and can itself contain personal information.

Ask AI to separate demonstrated errors from hypotheses, and to suggest targeted skills and follow-up questions. Review its suggestions before giving students more work. This release supports evidence export and published feedback; automatic AI calls, AI-plan import, individual assignment tracking and delayed-check automation remain later phases.

## Interpret the results

First-try correctness is the first response to a question **within a round/context**, not the student's lifetime first encounter. Eventually solved means at least one correct answer, including retries. Attempt accuracy counts every submission. Questions not presented and unanswered questions are shown separately and excluded from correctness-rate denominators.

Each student/question/round/context counts as an occurrence; a repeated question in another round counts again. Recovery cycles within a round are represented by their answer sequence, without independent presentation timings. Timestamps are UTC and do not measure active solving time. Missing historical content is labeled unavailable rather than replaced with current bank content. Explanations are included only when available at capture; future V4 imports preserve markscheme text for this purpose.
