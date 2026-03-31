# app/core/problem_engine.py
#
# Stateless helpers for selecting problems and checking answers.
# These functions are called by session_manager.py and eventually by
# mode-specific engines (Classic, Team, Boss Rush).
#
# No Flask request context is required — these work with model objects directly.

import random
from app.extensions import db
from app.models.problems import Problem
from app.services.problem_content import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    PROBLEM_ANSWER_TYPE_TEXT_INPUT,
    check_problem_multiple_choice_answer,
    check_problem_text_input_answer,
    get_legacy_problem_answer_text,
)


def select_problem(topic_id=None, difficulty=None, exclude_ids=None):
    """
    Pick a random Problem from the database.

    Args:
        topic_id    (int | None): Restrict to this topic. None = any topic.
        difficulty  (int | None): Restrict to this difficulty (1–5). None = any.
        exclude_ids (list[int]): Problem IDs already used this session — skip them.

    Returns:
        Problem | None: A randomly selected Problem, or None if no match found.
    """
    if exclude_ids is None:
        exclude_ids = []

    # Build the query with optional filters
    query = db.session.query(Problem)

    if topic_id is not None:
        query = query.filter(Problem.topic_id == topic_id)

    if difficulty is not None:
        query = query.filter(Problem.difficulty == difficulty)

    if exclude_ids:
        query = query.filter(Problem.id.notin_(exclude_ids))

    candidates = query.all()

    if not candidates:
        return None

    return random.choice(candidates)


def check_answer(problem, submitted_text=None, *, selected_option_id=None):
    """
    Compare a player's submitted answer to the current canonical answer model.

    Current answer resolution is:
    - text_input: canonical structured accepted answers, with legacy
      problem.answer_text fallback only for compatibility
    - multiple_choice: canonical structured ProblemChoiceOption correctness
    - final direct problem.answer_text check: compatibility-only guard for older
      callers / records outside the structured answer flow

    Args:
        problem        (Problem): The problem being answered.
        submitted_text (str):     The player's raw answer string.

    Returns:
        bool: True if the answer is correct.
    """
    if getattr(problem, 'answer_type', PROBLEM_ANSWER_TYPE_TEXT_INPUT) == PROBLEM_ANSWER_TYPE_TEXT_INPUT:
        return check_problem_text_input_answer(problem, submitted_text)
    if getattr(problem, 'answer_type', PROBLEM_ANSWER_TYPE_TEXT_INPUT) == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE:
        return check_problem_multiple_choice_answer(problem, selected_option_id)

    # Legacy-only compatibility fallback for callers/records that do not expose
    # a structured answer type but still rely on root Problem.answer_text.
    correct = get_legacy_problem_answer_text(problem).lower()
    submitted = submitted_text.strip().lower()
    return submitted == correct
