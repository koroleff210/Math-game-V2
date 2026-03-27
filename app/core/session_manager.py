# app/core/session_manager.py
#
# Mode-agnostic session lifecycle functions.
# These handle database operations only — no Socket.IO events are emitted here.
# Mode-specific engines call these functions and then emit events as needed.
#
# Lifecycle:
#   create_session() → add_player() × N → start_round() → submit_answer() × N
#   → end_round() → [repeat start_round/end_round] → end_session()

from datetime import datetime, timezone
from app.extensions import db
from app.models.game import GameSession, GameRound, RoundPlayer, PlayerAnswer
from app.core.problem_engine import check_answer


def create_session(mode, problem_set_id=None):
    """
    Create a new GameSession in 'waiting' status.

    Args:
        mode           (str): 'classic', 'team', or 'boss_rush'
        problem_set_id (int | None): Optional link to a ProblemSet.

    Returns:
        GameSession: The newly created (and committed) session.
    """
    session = GameSession(
        mode=mode,
        status='waiting',
        problem_set_id=problem_set_id,
    )
    db.session.add(session)
    db.session.commit()
    return session


def add_player(game_session, player):
    """
    Enroll a player in a session lobby.
    Safe to call more than once for the same player — will not create duplicates
    because of the unique constraint on (session_id, player_id).

    Args:
        game_session (GameSession): The session to join.
        player       (Player):      The player joining.

    Returns:
        RoundPlayer: The enrollment record (existing or newly created).
    """
    # Check for existing enrollment to avoid hitting the unique constraint
    existing = db.session.query(RoundPlayer).filter_by(
        session_id=game_session.id,
        player_id=player.id,
    ).first()

    if existing:
        return existing

    rp = RoundPlayer(session_id=game_session.id, player_id=player.id)
    db.session.add(rp)
    db.session.commit()
    return rp


def start_round(game_session, problem=None, time_limit_seconds=None):
    """
    Create a new GameRound and mark the session as 'active'.

    Args:
        game_session        (GameSession): The owning session.
        problem             (Problem | None): The problem for this round.
                            Pass None for Classic mode (problem set covers the whole round).
        time_limit_seconds  (int | None):  Optional countdown timer.

    Returns:
        GameRound: The newly started round.
    """
    # Count existing rounds to determine the next round number
    round_count = db.session.query(GameRound).filter_by(session_id=game_session.id).count()

    game_round = GameRound(
        session_id=game_session.id,
        problem_id=problem.id if problem is not None else None,
        round_number=round_count + 1,
        time_limit_seconds=time_limit_seconds,
        started_at=datetime.now(timezone.utc),
    )
    db.session.add(game_round)

    # Move session to active on the first round
    if game_session.status == 'waiting':
        game_session.status    = 'active'
        game_session.started_at = datetime.now(timezone.utc)

    db.session.commit()
    return game_round


def submit_answer(game_round, player, answer_text):
    """
    Record a player's answer and immediately evaluate it.

    If the player has already answered this round, the existing answer is returned
    unchanged (first-answer-only policy).

    Args:
        game_round  (GameRound): The active round.
        player      (Player):    The answering player.
        answer_text (str):       The raw answer submitted by the player.

    Returns:
        PlayerAnswer: The saved answer record (is_correct is already set).
    """
    # Enforce one answer per player per round
    existing = db.session.query(PlayerAnswer).filter_by(
        round_id=game_round.id,
        player_id=player.id,
    ).first()

    if existing:
        return existing

    correct = check_answer(game_round.problem, answer_text)

    answer = PlayerAnswer(
        round_id=game_round.id,
        player_id=player.id,
        answer_text=answer_text,
        is_correct=correct,
    )
    db.session.add(answer)
    db.session.commit()
    return answer


def end_round(game_round):
    """
    Mark a round as finished by setting ended_at.

    Args:
        game_round (GameRound): The round to close.
    """
    game_round.ended_at = datetime.now(timezone.utc)
    db.session.commit()


def end_session(game_session):
    """
    Mark a session as finished.

    Args:
        game_session (GameSession): The session to close.
    """
    game_session.status   = 'finished'
    game_session.ended_at = datetime.now(timezone.utc)
    db.session.commit()
