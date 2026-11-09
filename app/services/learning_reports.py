"""Session learning metrics derived from answer evidence, never game scores."""
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.extensions import db
from app.models.analytics import (AnalyticsAnswerAttempt, AnalyticsPlayerProblem, AnalyticsPlayerRound,
                                  AnalyticsRound, AnalyticsRoundProblem, AnalyticsSessionSettings)
from app.models.game import GameRound, RoundPlayer

STATE_LABELS = {
    'first_correct': 'First try correct', 'retry_correct': 'Correct after retry',
    'incorrect': 'Unresolved incorrect', 'unanswered': 'Presented, no answer',
    'unseen': 'Not presented', 'incomplete': 'Incomplete answer evidence',
}


def iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def ensure_session_settings(session):
    settings = db.session.get(AnalyticsSessionSettings, session.id)
    if settings is None:
        roster = session.group.members.order_by('id').all() if session.group else []
        settings = AnalyticsSessionSettings(session_id=session.id, roster_snapshot_json=[
            {'player_id': p.id, 'name': p.username} for p in roster if not p.is_admin
        ])
        db.session.add(settings)
        db.session.flush()
    elif session.status != 'finished' and settings.published_at is not None:
        settings.published_at = None
    return settings


def eligible_round_query(player_id=None, *, student=False):
    q = db.session.query(AnalyticsRound.round_id).outerjoin(
        AnalyticsSessionSettings, AnalyticsSessionSettings.session_id == AnalyticsRound.session_id)
    q = q.filter(or_(AnalyticsSessionSettings.session_id.is_(None), AnalyticsSessionSettings.include_in_progress.is_(True)))
    if student:
        q = q.filter(or_(AnalyticsSessionSettings.session_id.is_(None), AnalyticsSessionSettings.published_at.isnot(None)))
    if player_id is not None:
        q = q.join(AnalyticsPlayerRound, AnalyticsPlayerRound.round_id == AnalyticsRound.round_id).filter(AnalyticsPlayerRound.player_id == player_id)
    return q


def _metrics(cells):
    attempted = [c for c in cells if c['attempted']]
    known = [c for c in attempted if c['first_correct'] is not None]
    first = sum(c['first_correct'] is True for c in known)
    solved = sum(c['solved'] for c in attempted)
    submissions = sum(len(c['attempts']) for c in cells)
    correct = sum(a['is_correct'] for c in cells for a in c['attempts'])
    return dict(presented=sum(c['seen'] for c in cells), attempted=len(attempted), first_correct=first,
                first_known=len(known), solved=solved, submissions=submissions, correct_submissions=correct,
                first_accuracy=first/len(known) if known else None,
                eventual_accuracy=solved/len(attempted) if attempted else None,
                attempt_accuracy=correct/submissions if submissions else None,
                incomplete=sum(c['state'] == 'incomplete' for c in cells))


def build_session_report(session, *, player_id=None, round_id=None, mode_context=None):
    rounds = AnalyticsRound.query.filter_by(session_id=session.id).order_by(AnalyticsRound.round_number, AnalyticsRound.id).all()
    all_ids = [r.round_id for r in rounds]
    selected = [r for r in rounds if round_id is None or r.round_id == round_id]
    ids = [r.round_id for r in selected]
    settings = db.session.get(AnalyticsSessionSettings, session.id)
    enrolled = RoundPlayer.query.filter_by(session_id=session.id).all()
    names = {e.player_id: e.player.username for e in enrolled}
    joined = {e.player_id: iso(e.joined_at) for e in enrolled}
    for r in AnalyticsPlayerRound.query.filter(AnalyticsPlayerRound.round_id.in_(all_ids)).all():
        names[r.player_id] = r.player_name_snapshot or names.get(r.player_id, f'Player {r.player_id}')
    if settings:
        for member in settings.roster_snapshot_json or []:
            names.setdefault(member['player_id'], member['name'])
    attempts_query = AnalyticsAnswerAttempt.query.filter(AnalyticsAnswerAttempt.round_id.in_(ids))
    pp_query = AnalyticsPlayerProblem.query.filter(AnalyticsPlayerProblem.round_id.in_(ids))
    if player_id is not None:
        attempts_query = attempts_query.filter_by(player_id=player_id)
        pp_query = pp_query.filter_by(player_id=player_id)
        names = {k: v for k, v in names.items() if k == player_id}
    attempts = attempts_query.order_by(AnalyticsAnswerAttempt.submitted_at, AnalyticsAnswerAttempt.id).all()
    pps = pp_query.all()
    snapshots = AnalyticsRoundProblem.query.filter(AnalyticsRoundProblem.round_id.in_(ids)).order_by(
        AnalyticsRoundProblem.round_id, AnalyticsRoundProblem.mode_context, AnalyticsRoundProblem.problem_id).all()
    if mode_context:
        snapshots = [q for q in snapshots if q.mode_context == mode_context]
    round_numbers = {r.round_id: r.round_number for r in rounds}
    grouped = defaultdict(list)
    for a in attempts:
        names.setdefault(a.player_id, a.player.username)
        grouped[(a.player_id, a.round_id, a.problem_id, a.mode_context)].append({
            'id': a.id, 'number': a.attempt_number, 'submitted_at': iso(a.submitted_at),
            'answer_text': a.submitted_answer_text, 'option_id': a.selected_option_id,
            'option_label': a.selected_option_label_snapshot, 'option_text': a.selected_option_text_snapshot,
            'is_correct': a.is_correct, 'action_context': a.action_context,
        })
    by_pp = {(p.player_id, p.round_id, p.problem_id, p.mode_context): p for p in pps}
    for p in pps:
        names.setdefault(p.player_id, p.player.username)
    questions = []
    for q in snapshots:
        questions.append(dict(id=q.id, round_id=q.round_id, round_number=round_numbers[q.round_id],
                              problem_id=q.problem_id, context=q.mode_context, title=q.problem_title_snapshot,
                              topic=q.topic_name_snapshot or 'Unassigned', subject=q.subject_name_snapshot,
                              content=q.content_snapshot_json, content_available=bool(q.content_snapshot_json),
                              canonical_id=(q.source_metadata_json or {}).get('canonical_id')))
    rows = []
    for pid, name in sorted(names.items(), key=lambda pair: (pair[1].casefold(), pair[0])):
        cells = []
        for q in questions:
            key = (pid, q['round_id'], q['problem_id'], q['context'])
            pp, answers = by_pp.get(key), grouped[key]
            tried = bool(answers or (pp and pp.attempt_count))
            seen = bool(tried or (pp and pp.first_seen_at))
            first = answers[0]['is_correct'] if answers and answers[0]['number'] == 1 else (pp.first_attempt_correct if pp else None)
            solved = any(a['is_correct'] for a in answers) or bool(pp and pp.eventual_correct)
            incomplete = bool(tried and (not answers or (pp and pp.attempt_count > len(answers))))
            state = ('incomplete' if incomplete else 'first_correct' if first is True else 'retry_correct' if solved
                     else 'incorrect' if tried else 'unanswered' if seen else 'unseen')
            cells.append(dict(question_id=q['id'], state=state, label=STATE_LABELS[state], seen=seen,
                              attempted=tried, first_correct=first, solved=solved,
                              first_seen_at=iso(pp.first_seen_at) if pp else None,
                              attempts=answers))
        rows.append(dict(player_id=pid, name=name, joined_at=joined.get(pid), cells=cells, metrics=_metrics(cells)))
    topics = []
    for topic in sorted({q['topic'] for q in questions}):
        indexes = [i for i, q in enumerate(questions) if q['topic'] == topic]
        topics.append(dict(topic=topic, metrics=_metrics([r['cells'][i] for r in rows for i in indexes])))
    for index, q in enumerate(questions):
        cells = [r['cells'][index] for r in rows]
        q['metrics'] = _metrics(cells)
        distribution = defaultdict(int)
        for c in cells:
            if c['attempts'] and c['attempts'][0]['number'] == 1:
                a = c['attempts'][0]
                distribution[a['option_label'] or a['answer_text'] or '(empty)'] += 1
        q['first_answer_distribution'] = dict(distribution)
    game_rounds = GameRound.query.filter_by(session_id=session.id).all()
    finalized = bool(game_rounds) and all(r.ended_at for r in game_rounds) and all(r.finalized_at for r in rounds) and len(game_rounds) == len(rounds)
    return dict(session=session, settings=settings, rounds=rounds, questions=questions, students=rows, topics=topics,
                metrics=_metrics([c for r in rows for c in r['cells']]), finalized=finalized,
                filters=dict(player_id=player_id, round_id=round_id, mode_context=mode_context),
                feedback=settings.student_feedback if settings else None)


def student_session_ids(player_id):
    from app.models.game import GameSession
    participation = select(RoundPlayer.session_id).where(RoundPlayer.player_id == player_id)
    analytics = select(AnalyticsRound.session_id).join(AnalyticsPlayerRound, AnalyticsPlayerRound.round_id == AnalyticsRound.round_id).where(AnalyticsPlayerRound.player_id == player_id)
    return select(AnalyticsSessionSettings.session_id).where(
        AnalyticsSessionSettings.published_at.isnot(None),
        AnalyticsSessionSettings.session_id.in_(select(GameSession.id).where(GameSession.status == 'finished')),
        or_(AnalyticsSessionSettings.session_id.in_(participation), AnalyticsSessionSettings.session_id.in_(analytics)))


def student_learning_sessions(player_id):
    from app.models.game import GameSession
    sessions = GameSession.query.filter(GameSession.id.in_(student_session_ids(player_id))).order_by(GameSession.created_at.desc()).limit(30).all()
    return [build_session_report(s, player_id=player_id) for s in sessions]


def report_payload(report):
    """Explicit allowlist: no identities, private notes or server/source paths."""
    session = report['session']
    return {
        'schema_version': 'learning_report.v1', 'metric_version': 'first_response.v1',
        'generated_at': iso(datetime.now(timezone.utc)), 'timezone': 'UTC',
        'session': dict(id=session.id, mode=session.mode, status=session.status,
                        started_at=iso(session.started_at), ended_at=iso(session.ended_at)),
        'scope': report['filters'], 'finalized': report['finalized'],
        'included_in_progress': report['settings'].include_in_progress if report['settings'] else True,
        'metric_definitions': {
            'first_accuracy': 'First responses correct / student-question-round-context occurrences with known first response; not lifetime first exposure.',
            'eventual_accuracy': 'Occurrences solved at least once / attempted occurrences; not retention.',
            'attempt_accuracy': 'Correct submissions / all submissions.',
            'timing': 'Timestamps are UTC; active solving time is not measured.',
        },
        'metrics': report['metrics'], 'topics': report['topics'], 'questions': report['questions'],
        'students': [dict(alias=f"S{r['player_id']:06d}", joined_at=r['joined_at'], cells=r['cells'], metrics=r['metrics']) for r in report['students']],
        'warnings': ['Question content is unavailable for legacy records without a frozen snapshot. They are never replaced with current bank content.',
                     'Repeated presentations within the same round/context are not separately timed; use attempt sequences.',
                     'Question difficulty is authored, not calibrated. A wrong choice does not establish a misconception.'],
    }
