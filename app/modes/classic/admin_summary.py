from flask import render_template
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.analytics import ANALYTICS_CONTEXT_CLASSIC, AnalyticsAnswerAttempt, AnalyticsRoundProblem
from app.models.game import GameRound, RoundPlayer
from app.models.classic import ProblemSolverCount, StealEvent


def supervision_room(session_id):
    return f"classic_admin_{session_id}"


def build_admin_supervision_summary_context(session_id: int) -> dict:
    game_round = (
        GameRound.query
        .filter_by(session_id=session_id)
        .order_by(GameRound.round_number.desc())
        .first()
    )

    solve_counts = []
    problem_labels = {}
    attempts = {}
    if game_round:
        solve_counts = (
            ProblemSolverCount.query
            .filter_by(round_id=game_round.id)
            .order_by(ProblemSolverCount.problem_id.asc())
            .all()
        )
        problems = AnalyticsRoundProblem.query.filter_by(
            round_id=game_round.id, mode_context=ANALYTICS_CONTEXT_CLASSIC,
        ).order_by(AnalyticsRoundProblem.problem_id).all()
        problem_labels = {
            row.problem_id: f'{index}. {row.problem_title_snapshot or "Problem"}'
            for index, row in enumerate(problems, 1)
        }
        answers = AnalyticsAnswerAttempt
        attempts = {
            row.player_id: row for row in db.session.query(
                answers.player_id, func.count().label('attempts'),
                func.sum(case((answers.is_correct, 1), else_=0)).label('correct'),
                func.max(answers.submitted_at).label('latest'),
            ).filter_by(round_id=game_round.id, mode_context=ANALYTICS_CONTEXT_CLASSIC)
            .group_by(answers.player_id)
        }

    enrolled = RoundPlayer.query.filter_by(session_id=session_id).options(joinedload(RoundPlayer.player)).all()
    steal_events = (
        StealEvent.query
        .filter_by(session_id=session_id)
        .order_by(StealEvent.created_at.desc())
        .all()
    )

    return {
        'game_round': game_round,
        'solve_counts': solve_counts,
        'problem_labels': problem_labels,
        'progress_rows': [(row.player.username, attempts.get(row.player_id)) for row in enrolled],
        'steal_events': steal_events,
    }


def render_admin_supervision_summary_payload(session_id: int) -> dict:
    context = build_admin_supervision_summary_context(session_id)
    return {
        'solve_counts_html': render_template(
            'admin/classic/_solve_counts.html',
            **context,
        ),
        'progress_html': render_template('admin/classic/_live_progress.html', **context),
        'steal_history_html': render_template(
            'admin/classic/_steal_history.html',
            steal_events=context['steal_events'],
        ),
    }
