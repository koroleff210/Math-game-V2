from collections import Counter
from datetime import datetime, time, timezone

from app.models.analytics import (
    AnalyticsAnswerAttempt,
    AnalyticsBossRushBattleEvent,
    AnalyticsClassicEconomyEvent,
    AnalyticsPlayerProblem,
    AnalyticsPlayerRound,
    AnalyticsRound,
    AnalyticsRoundProblem,
)


def _percent(numerator, denominator):
    return (numerator / denominator) if denominator else None


def parse_date_filter(value, *, end=False):
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None
    boundary_time = time.max if end else time.min
    return datetime.combine(parsed, boundary_time, tzinfo=timezone.utc)


def _filtered_round_query(group_id, *, subject_id=None, mode=None, date_from=None, date_to=None):
    q = AnalyticsRound.query.filter_by(group_id=group_id)
    if mode in ('classic', 'boss_rush'):
        q = q.filter_by(mode=mode)
    if date_from is not None:
        q = q.filter(
            (AnalyticsRound.ended_at >= date_from)
            | ((AnalyticsRound.ended_at.is_(None)) & (AnalyticsRound.started_at >= date_from))
        )
    if date_to is not None:
        q = q.filter(
            (AnalyticsRound.ended_at <= date_to)
            | ((AnalyticsRound.ended_at.is_(None)) & (AnalyticsRound.started_at <= date_to))
        )
    if subject_id:
        q = q.join(AnalyticsRoundProblem, AnalyticsRoundProblem.analytics_round_id == AnalyticsRound.id)
        q = q.filter(AnalyticsRoundProblem.subject_id == subject_id).distinct()
    return q


def recent_groups_with_analytics(limit=12):
    rows = (
        AnalyticsRound.query
        .filter(AnalyticsRound.group_id.isnot(None))
        .order_by(AnalyticsRound.ended_at.desc().nullslast(), AnalyticsRound.started_at.desc().nullslast(), AnalyticsRound.id.desc())
        .all()
    )
    seen = set()
    groups = []
    for row in rows:
        if row.group_id in seen:
            continue
        seen.add(row.group_id)
        groups.append({
            'group_id': row.group_id,
            'group_name': row.group_name_snapshot or f'Class #{row.group_id}',
            'latest_round': row,
        })
        if len(groups) >= limit:
            break
    return groups


def _topic_key_from_round_problem(row):
    return (
        row.topic_id or 0,
        row.topic_name_snapshot or 'Unassigned',
        row.subject_id,
        row.subject_name_snapshot or 'n/a',
    )


def _round_problem_maps(round_ids, *, subject_id=None):
    rows = AnalyticsRoundProblem.query.filter(AnalyticsRoundProblem.round_id.in_(round_ids)).all() if round_ids else []
    if subject_id:
        rows = [row for row in rows if row.subject_id == subject_id]
    by_context = {
        (row.round_id, row.problem_id, row.mode_context): row
        for row in rows
    }
    fallback = {}
    for row in rows:
        fallback.setdefault((row.round_id, row.problem_id), row)
    return rows, by_context, fallback


def _round_problem_for(row, by_context, fallback):
    return by_context.get((row.round_id, row.problem_id, row.mode_context)) or fallback.get((row.round_id, row.problem_id))


def _round_links(round_id_set, analytics_round_by_round):
    return [
        analytics_round_by_round[round_id]
        for round_id in sorted(round_id_set, reverse=True)
        if round_id in analytics_round_by_round
    ]


def _selected_rounds(group_id, *, subject_id=None, mode=None, date_from=None, date_to=None):
    return (
        _filtered_round_query(group_id, subject_id=subject_id, mode=mode, date_from=date_from, date_to=date_to)
        .order_by(AnalyticsRound.ended_at.desc().nullslast(), AnalyticsRound.started_at.desc().nullslast(), AnalyticsRound.id.desc())
        .all()
    )


def build_class_dashboard(group_id, *, subject_id=None, mode=None, date_from=None, date_to=None):
    analytics_rounds = _selected_rounds(
        group_id,
        subject_id=subject_id,
        mode=mode,
        date_from=date_from,
        date_to=date_to,
    )
    round_ids = [row.round_id for row in analytics_rounds]
    analytics_round_by_round = {row.round_id: row for row in analytics_rounds}
    if not round_ids:
        return {
            'overview': {
                'round_count': 0,
                'player_count': 0,
                'attempts': 0,
                'correct': 0,
                'incorrect': 0,
                'accuracy': None,
                'first_try_accuracy': None,
            },
            'rounds': [],
            'topic_rows': [],
            'player_rows': [],
            'missed_problem_rows': [],
            'recent_rounds': [],
        }

    round_problem_rows, problem_context, problem_fallback = _round_problem_maps(round_ids, subject_id=subject_id)
    allowed_problem_contexts = set(problem_context)
    subject_filter_active = bool(subject_id)

    topic_stats = {}
    player_stats = {}
    problem_stats = {}
    player_ids = set()

    attempts_query = AnalyticsAnswerAttempt.query.filter(AnalyticsAnswerAttempt.round_id.in_(round_ids))
    attempts = []
    for attempt in attempts_query.all():
        round_problem = _round_problem_for(attempt, problem_context, problem_fallback)
        if subject_filter_active and (attempt.round_id, attempt.problem_id, attempt.mode_context) not in allowed_problem_contexts and round_problem is None:
            continue
        if subject_filter_active and round_problem is None:
            continue
        attempts.append((attempt, round_problem))

    for attempt, round_problem in attempts:
        topic_key = _topic_key_from_round_problem(round_problem) if round_problem else (0, 'Unassigned', None, 'n/a')
        topic = topic_stats.setdefault(topic_key, {
            'topic_id': topic_key[0],
            'topic_name': topic_key[1],
            'subject_id': topic_key[2],
            'subject_name': topic_key[3],
            'player_ids': set(),
            'problem_ids': set(),
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'round_ids': set(),
            'first_try_attempted': 0,
            'first_try_correct': 0,
            'eventual_attempted': 0,
            'eventual_correct': 0,
        })
        topic['player_ids'].add(attempt.player_id)
        topic['problem_ids'].add(attempt.problem_id)
        topic['attempts'] += 1
        topic['correct'] += 1 if attempt.is_correct else 0
        topic['incorrect'] += 0 if attempt.is_correct else 1
        topic['round_ids'].add(attempt.round_id)

        player_ids.add(attempt.player_id)
        player = player_stats.setdefault(attempt.player_id, {
            'player_id': attempt.player_id,
            'player_name': getattr(attempt.player, 'username', None) or f'Player #{attempt.player_id}',
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'first_try_correct': 0,
            'first_try_attempted': 0,
            'round_ids': set(),
            'problems_seen': 0,
            'problems_attempted': 0,
            'problems_solved': 0,
            'classic_gold_net': 0,
            'boss_rush_damage': 0,
            'boss_rush_max_combo': 0,
        })
        player['attempts'] += 1
        player['correct'] += 1 if attempt.is_correct else 0
        player['incorrect'] += 0 if attempt.is_correct else 1
        player['round_ids'].add(attempt.round_id)

        problem_key = (attempt.problem_id, attempt.mode_context)
        problem = problem_stats.setdefault(problem_key, {
            'problem_id': attempt.problem_id,
            'problem_title': getattr(round_problem, 'problem_title_snapshot', None) if round_problem else f'Problem #{attempt.problem_id}',
            'mode_context': attempt.mode_context,
            'topic_name': topic_key[1],
            'players_seen_ids': set(),
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'wrong_options': Counter(),
            'round_ids': set(),
        })
        problem['attempts'] += 1
        problem['correct'] += 1 if attempt.is_correct else 0
        problem['incorrect'] += 0 if attempt.is_correct else 1
        if not attempt.is_correct and attempt.selected_option_id:
            label = attempt.selected_option_label_snapshot or f'option #{attempt.selected_option_id}'
            text = attempt.selected_option_text_snapshot or ''
            problem['wrong_options'][(attempt.selected_option_id, label, text)] += 1
        problem['round_ids'].add(attempt.round_id)

    player_problem_query = AnalyticsPlayerProblem.query.filter(AnalyticsPlayerProblem.round_id.in_(round_ids))
    for pp in player_problem_query.all():
        round_problem = _round_problem_for(pp, problem_context, problem_fallback)
        if subject_filter_active and round_problem is None:
            continue
        topic_key = _topic_key_from_round_problem(round_problem) if round_problem else (0, 'Unassigned', None, 'n/a')
        topic = topic_stats.setdefault(topic_key, {
            'topic_id': topic_key[0],
            'topic_name': topic_key[1],
            'subject_id': topic_key[2],
            'subject_name': topic_key[3],
            'player_ids': set(),
            'problem_ids': set(),
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'round_ids': set(),
            'first_try_attempted': 0,
            'first_try_correct': 0,
            'eventual_attempted': 0,
            'eventual_correct': 0,
        })
        topic['player_ids'].add(pp.player_id)
        topic['problem_ids'].add(pp.problem_id)
        topic['round_ids'].add(pp.round_id)
        if (pp.attempt_count or 0) > 0:
            topic['first_try_attempted'] += 1
            topic['first_try_correct'] += 1 if pp.first_attempt_correct is True else 0
            topic['eventual_attempted'] += 1
            topic['eventual_correct'] += 1 if pp.eventual_correct is True else 0

        player_ids.add(pp.player_id)
        player = player_stats.setdefault(pp.player_id, {
            'player_id': pp.player_id,
            'player_name': getattr(pp.player, 'username', None) or f'Player #{pp.player_id}',
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'first_try_correct': 0,
            'first_try_attempted': 0,
            'round_ids': set(),
            'problems_seen': 0,
            'problems_attempted': 0,
            'problems_solved': 0,
            'classic_gold_net': 0,
            'boss_rush_damage': 0,
            'boss_rush_max_combo': 0,
        })
        player['round_ids'].add(pp.round_id)
        player['problems_seen'] += 1 if pp.first_seen_at is not None else 0
        player['problems_attempted'] += 1 if (pp.attempt_count or 0) > 0 else 0
        player['problems_solved'] += 1 if pp.eventual_correct is True else 0
        if (pp.attempt_count or 0) > 0:
            player['first_try_attempted'] += 1
            player['first_try_correct'] += 1 if pp.first_attempt_correct is True else 0

        problem_key = (pp.problem_id, pp.mode_context)
        problem = problem_stats.setdefault(problem_key, {
            'problem_id': pp.problem_id,
            'problem_title': getattr(round_problem, 'problem_title_snapshot', None) if round_problem else pp.problem_title_snapshot or f'Problem #{pp.problem_id}',
            'mode_context': pp.mode_context,
            'topic_name': topic_key[1],
            'players_seen_ids': set(),
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'wrong_options': Counter(),
            'round_ids': set(),
        })
        if pp.first_seen_at is not None:
            problem['players_seen_ids'].add(pp.player_id)
        problem['round_ids'].add(pp.round_id)

    for pr in AnalyticsPlayerRound.query.filter(AnalyticsPlayerRound.round_id.in_(round_ids)).all():
        if pr.player_id not in player_stats:
            player_stats[pr.player_id] = {
                'player_id': pr.player_id,
                'player_name': pr.player_name_snapshot or f'Player #{pr.player_id}',
                'attempts': 0,
                'correct': 0,
                'incorrect': 0,
                'first_try_correct': 0,
                'first_try_attempted': 0,
                'round_ids': set(),
                'problems_seen': 0,
                'problems_attempted': 0,
                'problems_solved': 0,
                'classic_gold_net': 0,
                'boss_rush_damage': 0,
                'boss_rush_max_combo': 0,
            }
        player = player_stats[pr.player_id]
        player['round_ids'].add(pr.round_id)
        if pr.gold_net is not None:
            player['classic_gold_net'] += pr.gold_net
        elif pr.gold_start is not None and pr.gold_end is not None:
            player['classic_gold_net'] += pr.gold_end - pr.gold_start
        player['boss_rush_damage'] += pr.damage_dealt or 0
        player['boss_rush_max_combo'] = max(player['boss_rush_max_combo'], pr.max_combo or 0)

    total_attempts = len(attempts)
    total_correct = sum(1 for attempt, _ in attempts if attempt.is_correct)
    first_try_attempted = sum(row.get('first_try_attempted', 0) for row in topic_stats.values())
    first_try_correct = sum(row.get('first_try_correct', 0) for row in topic_stats.values())
    overview = {
        'round_count': len(analytics_rounds),
        'player_count': len(player_ids),
        'attempts': total_attempts,
        'correct': total_correct,
        'incorrect': total_attempts - total_correct,
        'accuracy': _percent(total_correct, total_attempts),
        'first_try_accuracy': _percent(first_try_correct, first_try_attempted),
    }

    topic_rows = []
    for row in topic_stats.values():
        row['players'] = len(row['player_ids'])
        row['problems'] = len(row['problem_ids'])
        row['accuracy'] = _percent(row['correct'], row['attempts'])
        row['first_try_accuracy'] = _percent(row['first_try_correct'], row['first_try_attempted'])
        row['eventual_correct_pct'] = _percent(row['eventual_correct'], row['eventual_attempted'])
        row['rounds'] = _round_links(row['round_ids'], analytics_round_by_round)
        row['round_count'] = len(row['round_ids'])
        topic_rows.append(row)
    topic_rows.sort(key=lambda row: (row['accuracy'] is None, row['accuracy'] if row['accuracy'] is not None else 1, row['topic_name']))

    player_rows = []
    for row in player_stats.values():
        row['rounds_played'] = len(row['round_ids'])
        row['accuracy'] = _percent(row['correct'], row['attempts'])
        row['first_try_accuracy'] = _percent(row['first_try_correct'], row['first_try_attempted'])
        row['rounds'] = _round_links(row['round_ids'], analytics_round_by_round)
        player_rows.append(row)
    player_rows.sort(key=lambda row: row['player_name'])

    missed_candidates = []
    fallback_candidates = []
    for row in problem_stats.values():
        if row['incorrect'] <= 0:
            continue
        top_wrong = row['wrong_options'].most_common(1)
        row['most_common_wrong_option'] = None
        if top_wrong:
            (option_id, label, text), count = top_wrong[0]
            row['most_common_wrong_option'] = {
                'option_id': option_id,
                'label': label,
                'text': text,
                'count': count,
            }
        row['players_seen'] = len(row['players_seen_ids'])
        row['accuracy'] = _percent(row['correct'], row['attempts'])
        row['miss_rate'] = _percent(row['incorrect'], row['attempts'])
        row['rounds'] = _round_links(row['round_ids'], analytics_round_by_round)
        fallback_candidates.append(row)
        if row['attempts'] >= 2:
            missed_candidates.append(row)
    missed_source = missed_candidates if missed_candidates else fallback_candidates
    missed_problem_rows = sorted(
        missed_source,
        key=lambda row: (row['accuracy'] if row['accuracy'] is not None else 1, -row['attempts'], row['problem_title'] or ''),
    )[:20]

    recent_rounds = []
    for row in analytics_rounds[:12]:
        round_attempts = [attempt for attempt, _ in attempts if attempt.round_id == row.round_id]
        correct = sum(1 for attempt in round_attempts if attempt.is_correct)
        recent_rounds.append({
            'round': row,
            'attempts': len(round_attempts),
            'correct': correct,
            'incorrect': len(round_attempts) - correct,
            'accuracy': _percent(correct, len(round_attempts)),
        })

    return {
        'overview': overview,
        'rounds': analytics_rounds,
        'topic_rows': topic_rows,
        'player_rows': player_rows,
        'missed_problem_rows': missed_problem_rows,
        'recent_rounds': recent_rounds,
    }


def build_player_dashboard(player_id, *, limit_recent_rounds=10, limit_missed=8):
    player_rounds = (
        AnalyticsPlayerRound.query
        .filter_by(player_id=player_id)
        .join(AnalyticsRound, AnalyticsRound.id == AnalyticsPlayerRound.analytics_round_id)
        .order_by(AnalyticsRound.ended_at.desc().nullslast(), AnalyticsRound.started_at.desc().nullslast(), AnalyticsPlayerRound.id.desc())
        .all()
    )
    round_ids = [row.round_id for row in player_rounds]
    analytics_round_by_round = {row.round_id: row.analytics_round for row in player_rounds}

    attempts = (
        AnalyticsAnswerAttempt.query
        .filter_by(player_id=player_id)
        .order_by(AnalyticsAnswerAttempt.submitted_at.desc(), AnalyticsAnswerAttempt.id.desc())
        .all()
    )
    player_problems = (
        AnalyticsPlayerProblem.query
        .filter_by(player_id=player_id)
        .order_by(AnalyticsPlayerProblem.completed_at.desc().nullslast(), AnalyticsPlayerProblem.first_seen_at.desc().nullslast(), AnalyticsPlayerProblem.id.desc())
        .all()
    )

    total_attempts = len(attempts)
    total_correct = sum(1 for attempt in attempts if attempt.is_correct)
    attempted_problem_rows = [row for row in player_problems if (row.attempt_count or 0) > 0]
    first_try_attempted = len(attempted_problem_rows)
    first_try_correct = sum(1 for row in attempted_problem_rows if row.first_attempt_correct is True)
    eventually_solved = sum(1 for row in attempted_problem_rows if row.eventual_correct is True)
    overview = {
        'rounds_played': len(player_rounds),
        'problems_tried': first_try_attempted,
        'correct': total_correct,
        'incorrect': total_attempts - total_correct,
        'accuracy': _percent(total_correct, total_attempts),
        'first_try_accuracy': _percent(first_try_correct, first_try_attempted),
        'eventually_solved': eventually_solved,
    }

    attempts_by_round = {}
    for attempt in attempts:
        attempts_by_round.setdefault(attempt.round_id, []).append(attempt)

    recent_rounds = []
    for row in player_rounds[:limit_recent_rounds]:
        analytics_round = analytics_round_by_round.get(row.round_id)
        round_attempts = attempts_by_round.get(row.round_id, [])
        correct = sum(1 for attempt in round_attempts if attempt.is_correct)
        recent_rounds.append({
            'player_round': row,
            'round': analytics_round,
            'date': (analytics_round.ended_at or analytics_round.started_at) if analytics_round else row.completed_at,
            'mode': analytics_round.mode if analytics_round else '',
            'problem_set': analytics_round.problem_set_name_snapshot if analytics_round else '',
            'problems_attempted': row.problems_attempted,
            'correct': correct,
            'incorrect': len(round_attempts) - correct,
            'accuracy': _percent(correct, len(round_attempts)),
            'classic_gold_net': row.gold_net if row.gold_net is not None else ((row.gold_end - row.gold_start) if row.gold_start is not None and row.gold_end is not None else None),
            'boss_damage': row.damage_dealt or 0,
            'boss_max_combo': row.max_combo or 0,
        })

    topic_stats = {}
    for attempt in attempts:
        key = (attempt.problem_id, attempt.mode_context)
        pp = next((row for row in player_problems if row.problem_id == attempt.problem_id and row.mode_context == attempt.mode_context and row.round_id == attempt.round_id), None)
        topic_key = (
            getattr(pp, 'topic_id', None) or 0,
            getattr(pp, 'topic_name_snapshot', None) or 'Unassigned',
            getattr(pp, 'subject_name_snapshot', None) or 'n/a',
        )
        row = topic_stats.setdefault(topic_key, {
            'topic_id': topic_key[0],
            'topic_name': topic_key[1],
            'subject_name': topic_key[2],
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'first_try_attempted': 0,
            'first_try_correct': 0,
            'eventual_attempted': 0,
            'eventual_correct': 0,
            '_problem_keys': set(),
        })
        row['attempts'] += 1
        row['correct'] += 1 if attempt.is_correct else 0
        row['incorrect'] += 0 if attempt.is_correct else 1
        row['_problem_keys'].add(key)

    for pp in attempted_problem_rows:
        topic_key = (
            pp.topic_id or 0,
            pp.topic_name_snapshot or 'Unassigned',
            pp.subject_name_snapshot or 'n/a',
        )
        row = topic_stats.setdefault(topic_key, {
            'topic_id': topic_key[0],
            'topic_name': topic_key[1],
            'subject_name': topic_key[2],
            'attempts': 0,
            'correct': 0,
            'incorrect': 0,
            'first_try_attempted': 0,
            'first_try_correct': 0,
            'eventual_attempted': 0,
            'eventual_correct': 0,
            '_problem_keys': set(),
        })
        row['first_try_attempted'] += 1
        row['first_try_correct'] += 1 if pp.first_attempt_correct is True else 0
        row['eventual_attempted'] += 1
        row['eventual_correct'] += 1 if pp.eventual_correct is True else 0

    topic_rows = []
    for row in topic_stats.values():
        row['accuracy'] = _percent(row['correct'], row['attempts'])
        row['first_try_accuracy'] = _percent(row['first_try_correct'], row['first_try_attempted'])
        row['eventual_correct_pct'] = _percent(row['eventual_correct'], row['eventual_attempted'])
        row.pop('_problem_keys', None)
        topic_rows.append(row)
    topic_rows.sort(key=lambda row: (row['topic_name'], row['subject_name']))

    review_candidates = [
        row for row in topic_rows
        if row['attempts'] >= 2 or row['first_try_attempted'] >= 2
    ]
    topics_to_review = sorted(
        review_candidates,
        key=lambda row: (
            row['accuracy'] if row['accuracy'] is not None else 1,
            row['first_try_accuracy'] if row['first_try_accuracy'] is not None else 1,
            -row['attempts'],
            row['topic_name'],
        ),
    )[:5]

    problem_by_key = {
        (row.round_id, row.problem_id, row.mode_context): row
        for row in player_problems
    }
    recent_missed = []
    for attempt in attempts:
        if attempt.is_correct:
            continue
        pp = problem_by_key.get((attempt.round_id, attempt.problem_id, attempt.mode_context))
        analytics_round = analytics_round_by_round.get(attempt.round_id) or attempt.analytics_round
        recent_missed.append({
            'attempt': attempt,
            'problem_title': (pp.problem_title_snapshot if pp else None) or f'Problem #{attempt.problem_id}',
            'topic_name': (pp.topic_name_snapshot if pp else None) or 'Unassigned',
            'date': attempt.submitted_at,
            'round': analytics_round,
            'selected_answer': (
                f'{attempt.selected_option_label_snapshot or ""}: {attempt.selected_option_text_snapshot or ""}'.strip()
                if attempt.selected_option_id else None
            ),
            'submitted_text': attempt.submitted_answer_text or '',
        })
        if len(recent_missed) >= limit_missed:
            break

    classic_events = AnalyticsClassicEconomyEvent.query.filter_by(actor_player_id=player_id).all()
    target_classic_events = AnalyticsClassicEconomyEvent.query.filter_by(target_player_id=player_id).all()
    classic_records = {
        'total_gold_net': sum((row.gold_net if row.gold_net is not None else ((row.gold_end - row.gold_start) if row.gold_start is not None and row.gold_end is not None else 0)) for row in player_rounds if (row.analytics_round and row.analytics_round.mode == 'classic')),
        'best_final_gold': max([row.gold_end for row in player_rounds if row.analytics_round and row.analytics_round.mode == 'classic' and row.gold_end is not None] or [None]),
        'total_mined_gold': sum(event.gold_delta_actor or 0 for event in classic_events if event.event_type == 'mine_success'),
        'total_stolen_gold': sum(event.gold_delta_actor or 0 for event in classic_events if event.event_type == 'steal_success'),
        'gold_lost_to_steals': abs(sum(event.gold_delta_target or 0 for event in target_classic_events if event.event_type == 'steal_success')),
        'successful_steals': sum(1 for event in classic_events if event.event_type == 'steal_success'),
        'failed_steals': sum(1 for event in classic_events if event.event_type == 'steal_failed'),
    }

    boss_rows = [row for row in player_rounds if row.analytics_round and row.analytics_round.mode == 'boss_rush']
    boss_events = AnalyticsBossRushBattleEvent.query.filter_by(player_id=player_id).all()
    bosses_fought = sorted({event.boss_type for event in boss_events if event.boss_type})
    boss_records = {
        'total_damage': sum(row.damage_dealt or 0 for row in boss_rows),
        'best_damage': max([row.damage_dealt or 0 for row in boss_rows] or [0]),
        'best_combo': max([row.max_combo or 0 for row in boss_rows] or [0]),
        'bosses_fought': bosses_fought,
        'diamonds_earned': sum(row.diamonds_awarded or 0 for row in boss_rows),
        'recovery_successes': sum(1 for event in boss_events if event.event_type == 'player_recovery_success'),
    }

    return {
        'overview': overview,
        'recent_rounds': recent_rounds,
        'topic_rows': topic_rows,
        'topics_to_review': topics_to_review,
        'recent_missed': recent_missed,
        'classic_records': classic_records,
        'boss_records': boss_records,
    }
