from flask import render_template

from app.models.game import GameRound
from app.models.classic import ProblemSolverCount, StealEvent


def build_admin_supervision_summary_context(session_id: int) -> dict:
    game_round = (
        GameRound.query
        .filter_by(session_id=session_id)
        .order_by(GameRound.round_number.desc())
        .first()
    )

    solve_counts = []
    if game_round:
        solve_counts = (
            ProblemSolverCount.query
            .filter_by(round_id=game_round.id)
            .order_by(ProblemSolverCount.problem_id.asc())
            .all()
        )

    steal_events = (
        StealEvent.query
        .filter_by(session_id=session_id)
        .order_by(StealEvent.created_at.desc())
        .all()
    )

    return {
        'game_round': game_round,
        'solve_counts': solve_counts,
        'steal_events': steal_events,
    }


def render_admin_supervision_summary_payload(session_id: int) -> dict:
    context = build_admin_supervision_summary_context(session_id)
    return {
        'solve_counts_html': render_template(
            'admin/classic/_solve_counts.html',
            solve_counts=context['solve_counts'],
        ),
        'steal_history_html': render_template(
            'admin/classic/_steal_history.html',
            steal_events=context['steal_events'],
        ),
    }
