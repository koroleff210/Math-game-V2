from datetime import datetime, timezone

from app.extensions import db
from app.models.analytics import (
    ANALYTICS_CONTEXT_BOSS_RUSH_ATTACK,
    ANALYTICS_CONTEXT_BOSS_RUSH_RECOVERY,
    ANALYTICS_CONTEXT_CLASSIC,
    ANALYTICS_MODE_BOSS_RUSH,
    ANALYTICS_MODE_CLASSIC,
    ANALYTICS_STATUS_CLOSED,
    ANALYTICS_STATUS_COMPLETED,
    ANALYTICS_STATUS_INCORRECT,
    ANALYTICS_STATUS_SEEN,
    ANALYTICS_STATUS_SOLVED,
    ANALYTICS_STATUS_UNSEEN,
    AnalyticsAnswerAttempt,
    AnalyticsBossRushBattleEvent,
    AnalyticsClassicEconomyEvent,
    AnalyticsPlayerProblem,
    AnalyticsPlayerRound,
    AnalyticsRound,
    AnalyticsRoundProblem,
)
from app.models.game import RoundPlayer
from app.models.problems import Problem, ProblemChoiceOption


def _utcnow():
    return datetime.now(timezone.utc)


def _option_label(position):
    if position is None:
        return None
    try:
        value = int(position)
    except (TypeError, ValueError):
        return None
    if value < 1 or value > 26:
        return str(value)
    return chr(ord('A') + value - 1)


def _merge_json(existing, updates):
    merged = dict(existing or {})
    merged.update(updates or {})
    return merged or None


def _model_snapshot(obj, exclude=()):
    if obj is None:
        return None
    excluded = set(exclude)
    payload = {}
    for column in obj.__table__.columns:
        key = column.name
        if key in excluded:
            continue
        value = getattr(obj, key)
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        else:
            payload[key] = value
    return payload


def _subject_topic_snapshot(problem):
    topic = getattr(problem, 'topic', None)
    subject = getattr(topic, 'subject_obj', None) if topic else None
    subject_id = getattr(subject, 'id', None)
    subject_name = getattr(subject, 'name', None)
    if subject_name is None and topic is not None:
        subject_name = getattr(topic, 'subject', None)
    return {
        'topic_id': getattr(topic, 'id', None),
        'topic_name': getattr(topic, 'name', None),
        'subject_id': subject_id,
        'subject_name': subject_name,
    }


def _problem_source_metadata_snapshot(problem):
    metadata = getattr(problem, 'source_metadata', None)
    if metadata is None:
        return None
    return {
        'source_system': metadata.source_system,
        'source_bank_path': metadata.source_bank_path,
        'source_id': metadata.source_id,
        'canonical_id': metadata.canonical_id,
        'content_hash': metadata.content_hash,
        'answer_hash': metadata.answer_hash,
        'import_batch_id': metadata.import_batch_id,
        'raw_metadata_json': metadata.raw_metadata_json,
    }


def _problem_set_subject_snapshot(problem_set):
    if problem_set is None:
        return None, None
    subject_ids = set()
    subject_names = set()
    for problem in problem_set.problems.all():
        snap = _subject_topic_snapshot(problem)
        if snap['subject_id'] is not None:
            subject_ids.add(snap['subject_id'])
        if snap['subject_name']:
            subject_names.add(snap['subject_name'])
    if len(subject_ids) == 1:
        return next(iter(subject_ids)), next(iter(subject_names), None)
    if not subject_ids and len(subject_names) == 1:
        return None, next(iter(subject_names))
    return None, None


def _round_problem_set(game_round, mode, config=None):
    session = game_round.session
    if mode == ANALYTICS_MODE_BOSS_RUSH and config is not None:
        return getattr(config, 'attack_problem_set', None)
    return getattr(session, 'problem_set', None)


def _joined_at(game_round, player):
    round_player = RoundPlayer.query.filter_by(
        session_id=game_round.session_id,
        player_id=player.id,
    ).first()
    return getattr(round_player, 'joined_at', None) if round_player else None


def ensure_analytics_round(game_round, mode=None, *, config=None):
    mode = mode or getattr(game_round.session, 'mode', None) or ANALYTICS_MODE_CLASSIC
    row = AnalyticsRound.query.filter_by(round_id=game_round.id).first()
    session = game_round.session
    problem_set = _round_problem_set(game_round, mode, config=config)
    subject_id, subject_name = _problem_set_subject_snapshot(problem_set)
    if row is None:
        row = AnalyticsRound(
            session_id=session.id,
            round_id=game_round.id,
            mode=mode,
            round_number=game_round.round_number,
            session_label_snapshot=getattr(session, 'label', None),
            group_id=session.group_id,
            group_name_snapshot=session.group.name if getattr(session, 'group', None) else None,
            subject_id=subject_id,
            subject_name_snapshot=subject_name,
            problem_set_id=problem_set.id if problem_set else None,
            problem_set_name_snapshot=problem_set.name if problem_set else None,
            started_at=game_round.started_at,
            ended_at=game_round.ended_at,
            round_settings_json={
                'round_number': game_round.round_number,
                'session_status': session.status,
            },
            mode_settings_json=_model_snapshot(config, exclude={'id', 'round_id', 'created_at'}) if config else None,
        )
        db.session.add(row)
        db.session.flush()
        return row

    row.session_label_snapshot = row.session_label_snapshot or getattr(session, 'label', None)
    row.group_id = row.group_id if row.group_id is not None else session.group_id
    row.group_name_snapshot = row.group_name_snapshot or (session.group.name if getattr(session, 'group', None) else None)
    row.subject_id = row.subject_id if row.subject_id is not None else subject_id
    row.subject_name_snapshot = row.subject_name_snapshot or subject_name
    row.problem_set_id = row.problem_set_id if row.problem_set_id is not None else (problem_set.id if problem_set else None)
    row.problem_set_name_snapshot = row.problem_set_name_snapshot or (problem_set.name if problem_set else None)
    row.started_at = row.started_at or game_round.started_at
    row.ended_at = row.ended_at or game_round.ended_at
    if row.mode_settings_json is None and config is not None:
        row.mode_settings_json = _model_snapshot(config, exclude={'id', 'round_id', 'created_at'})
    return row


def snapshot_round_problem(game_round, problem, mode_context, problem_set_context=None):
    analytics_round = ensure_analytics_round(game_round)
    row = AnalyticsRoundProblem.query.filter_by(
        round_id=game_round.id,
        problem_id=problem.id,
        mode_context=mode_context,
    ).first()
    if row is not None:
        return row
    snap = _subject_topic_snapshot(problem)
    row = AnalyticsRoundProblem(
        analytics_round_id=analytics_round.id,
        round_id=game_round.id,
        problem_id=problem.id,
        problem_title_snapshot=problem.title,
        answer_type_snapshot=getattr(problem, 'answer_type', None),
        subject_id=snap['subject_id'],
        subject_name_snapshot=snap['subject_name'],
        topic_id=snap['topic_id'],
        topic_name_snapshot=snap['topic_name'],
        mode_context=mode_context,
        problem_set_context=problem_set_context,
        source_metadata_json=_problem_source_metadata_snapshot(problem),
        answer_key_snapshot_json=None,
    )
    db.session.add(row)
    db.session.flush()
    return row


def snapshot_round_problem_set(game_round, problem_set, mode_context, *, role=None):
    if problem_set is None:
        return []
    context = {'problem_set_id': problem_set.id, 'problem_set_name': problem_set.name}
    if role:
        context['role'] = role
    return [
        snapshot_round_problem(game_round, problem, mode_context, problem_set_context=context)
        for problem in problem_set.problems.order_by(Problem.id).all()
    ]


def snapshot_classic_round_problem_set(game_round):
    ensure_analytics_round(game_round, ANALYTICS_MODE_CLASSIC, config=getattr(game_round, 'classic_config', None))
    return snapshot_round_problem_set(game_round, game_round.session.problem_set, ANALYTICS_CONTEXT_CLASSIC, role='classic')


def snapshot_boss_rush_round_problem_sets(game_round, config=None):
    config = config or getattr(game_round, 'boss_rush_config', None)
    ensure_analytics_round(game_round, ANALYTICS_MODE_BOSS_RUSH, config=config)
    rows = []
    if config:
        rows.extend(snapshot_round_problem_set(game_round, config.attack_problem_set, ANALYTICS_CONTEXT_BOSS_RUSH_ATTACK, role='attack'))
        rows.extend(snapshot_round_problem_set(game_round, config.recovery_problem_set, ANALYTICS_CONTEXT_BOSS_RUSH_RECOVERY, role='recovery'))
    return rows


def ensure_player_round(game_round, player, mode=None, *, wallet=None, state=None):
    analytics_round = ensure_analytics_round(game_round, mode)
    row = AnalyticsPlayerRound.query.filter_by(round_id=game_round.id, player_id=player.id).first()
    joined_at = _joined_at(game_round, player)
    if row is None:
        row = AnalyticsPlayerRound(
            analytics_round_id=analytics_round.id,
            round_id=game_round.id,
            player_id=player.id,
            player_name_snapshot=getattr(player, 'username', None),
            group_id=getattr(game_round.session, 'group_id', None),
            group_name_snapshot=game_round.session.group.name if getattr(game_round.session, 'group', None) else None,
            joined_at=joined_at,
            gold_start=getattr(wallet, 'gold', None) if wallet is not None else None,
            gems_start=getattr(wallet, 'gems', None) if wallet is not None else None,
        )
        db.session.add(row)
        db.session.flush()
    else:
        row.player_name_snapshot = row.player_name_snapshot or getattr(player, 'username', None)
        row.joined_at = row.joined_at or joined_at
        if wallet is not None:
            row.gold_start = row.gold_start if row.gold_start is not None else wallet.gold
            row.gems_start = row.gems_start if row.gems_start is not None else wallet.gems
    if state is not None:
        row.damage_dealt = getattr(state, 'damage_dealt', 0) or 0
        row.max_combo = getattr(state, 'max_combo', 0) or 0
        row.final_combo = getattr(state, 'current_combo', 0) or 0
        row.hp_final = getattr(state, 'hp', None)
    return row


def ensure_player_problem(game_round, player, problem, mode_context, *, mark_seen=False, extra_json=None):
    analytics_round = ensure_analytics_round(game_round)
    snapshot_round_problem(game_round, problem, mode_context)
    row = AnalyticsPlayerProblem.query.filter_by(
        round_id=game_round.id,
        player_id=player.id,
        problem_id=problem.id,
        mode_context=mode_context,
    ).first()
    snap = _subject_topic_snapshot(problem)
    if row is None:
        row = AnalyticsPlayerProblem(
            analytics_round_id=analytics_round.id,
            round_id=game_round.id,
            player_id=player.id,
            problem_id=problem.id,
            mode_context=mode_context,
            status=ANALYTICS_STATUS_SEEN if mark_seen else ANALYTICS_STATUS_UNSEEN,
            first_seen_at=_utcnow() if mark_seen else None,
            problem_title_snapshot=problem.title,
            subject_id=snap['subject_id'],
            subject_name_snapshot=snap['subject_name'],
            topic_id=snap['topic_id'],
            topic_name_snapshot=snap['topic_name'],
            source_metadata_json=_problem_source_metadata_snapshot(problem),
            extra_json=extra_json,
        )
        db.session.add(row)
        db.session.flush()
        return row
    if mark_seen and row.first_seen_at is None:
        row.first_seen_at = _utcnow()
        if row.status == ANALYTICS_STATUS_UNSEEN:
            row.status = ANALYTICS_STATUS_SEEN
    if extra_json:
        row.extra_json = _merge_json(row.extra_json, extra_json)
    return row


def record_answer_attempt(
    game_round,
    player,
    problem,
    *,
    is_correct,
    submitted_answer_text=None,
    selected_option_id=None,
    mode_context,
    action_context=None,
    extra_json=None,
    submitted_at=None,
):
    analytics_round = ensure_analytics_round(game_round)
    player_problem = ensure_player_problem(game_round, player, problem, mode_context, mark_seen=True)
    last_attempt = (
        AnalyticsAnswerAttempt.query
        .filter_by(
            round_id=game_round.id,
            player_id=player.id,
            problem_id=problem.id,
            mode_context=mode_context,
        )
        .order_by(AnalyticsAnswerAttempt.attempt_number.desc())
        .first()
    )
    attempt_number = (last_attempt.attempt_number if last_attempt else 0) + 1
    selected_option = None
    if selected_option_id is not None:
        selected_option = ProblemChoiceOption.query.filter_by(id=selected_option_id, problem_id=problem.id).first()

    attempt = AnalyticsAnswerAttempt(
        analytics_player_problem_id=player_problem.id,
        analytics_round_id=analytics_round.id,
        round_id=game_round.id,
        player_id=player.id,
        problem_id=problem.id,
        attempt_number=attempt_number,
        submitted_at=submitted_at or _utcnow(),
        submitted_answer_text=submitted_answer_text,
        selected_option_id=selected_option_id,
        selected_option_label_snapshot=_option_label(selected_option.position) if selected_option else None,
        selected_option_text_snapshot=selected_option.option_text if selected_option else None,
        is_correct=bool(is_correct),
        mode_context=mode_context,
        action_context=action_context,
        extra_json=extra_json,
    )
    db.session.add(attempt)

    player_problem.attempt_count = (player_problem.attempt_count or 0) + 1
    if player_problem.first_attempt_correct is None:
        player_problem.first_attempt_correct = bool(is_correct)
    if is_correct:
        player_problem.eventual_correct = True
        player_problem.status = ANALYTICS_STATUS_SOLVED
        player_problem.completed_at = player_problem.completed_at or attempt.submitted_at
    elif player_problem.status not in (ANALYTICS_STATUS_SOLVED, ANALYTICS_STATUS_COMPLETED):
        player_problem.status = ANALYTICS_STATUS_INCORRECT
        if player_problem.eventual_correct is None:
            player_problem.eventual_correct = False
    db.session.flush()
    return attempt


def latest_answer_attempt_for_action(game_round, player, problem_id, mode_context=ANALYTICS_CONTEXT_CLASSIC):
    if not problem_id:
        return None
    return (
        AnalyticsAnswerAttempt.query
        .filter_by(
            round_id=game_round.id,
            player_id=player.id,
            problem_id=problem_id,
            mode_context=mode_context,
        )
        .order_by(AnalyticsAnswerAttempt.attempt_number.desc(), AnalyticsAnswerAttempt.id.desc())
        .first()
    )


def classic_economy_event_key(game_round, player_id, problem_id, event_type, suffix=None):
    parts = ['classic', str(game_round.id), str(player_id), str(problem_id or 0), event_type]
    if suffix is not None:
        parts.append(str(suffix))
    return ':'.join(parts)


def record_classic_economy_event(
    game_round,
    *,
    event_type,
    actor_player,
    target_player=None,
    linked_answer_attempt=None,
    linked_problem_id=None,
    action_context=None,
    gold_delta_actor=0,
    gold_delta_target=0,
    gems_delta_actor=0,
    gems_delta_target=0,
    actor_gold_after=None,
    target_gold_after=None,
    item_key=None,
    bonus_key=None,
    problem_id=None,
    details_json=None,
    event_key=None,
    occurred_at=None,
):
    if event_key:
        existing = AnalyticsClassicEconomyEvent.query.filter_by(event_key=event_key).first()
        if existing is not None:
            return existing
    analytics_round = ensure_analytics_round(game_round, ANALYTICS_MODE_CLASSIC, config=getattr(game_round, 'classic_config', None))
    row = AnalyticsClassicEconomyEvent(
        analytics_round_id=analytics_round.id,
        round_id=game_round.id,
        session_id=game_round.session_id,
        event_type=event_type,
        event_key=event_key,
        occurred_at=occurred_at or _utcnow(),
        actor_player_id=actor_player.id,
        actor_name_snapshot=getattr(actor_player, 'username', None),
        target_player_id=getattr(target_player, 'id', None) if target_player is not None else None,
        target_name_snapshot=getattr(target_player, 'username', None) if target_player is not None else None,
        linked_answer_attempt_id=getattr(linked_answer_attempt, 'id', None),
        linked_problem_id=linked_problem_id,
        action_context=action_context,
        gold_delta_actor=gold_delta_actor or 0,
        gold_delta_target=gold_delta_target or 0,
        gems_delta_actor=gems_delta_actor or 0,
        gems_delta_target=gems_delta_target or 0,
        actor_gold_after=actor_gold_after,
        target_gold_after=target_gold_after,
        item_key=item_key,
        bonus_key=bonus_key,
        problem_id=problem_id,
        details_json=details_json,
    )
    db.session.add(row)
    db.session.flush()
    return row


def latest_boss_rush_answer_attempt(game_round, player, boss_rush_attempt):
    if not boss_rush_attempt:
        return None
    context = (
        ANALYTICS_CONTEXT_BOSS_RUSH_ATTACK
        if boss_rush_attempt.attempt_type == 'attack'
        else ANALYTICS_CONTEXT_BOSS_RUSH_RECOVERY
    )
    return (
        AnalyticsAnswerAttempt.query
        .filter_by(
            round_id=game_round.id,
            player_id=player.id,
            problem_id=boss_rush_attempt.problem_id,
            mode_context=context,
        )
        .order_by(AnalyticsAnswerAttempt.attempt_number.desc(), AnalyticsAnswerAttempt.id.desc())
        .first()
    )


def boss_rush_battle_event_key(game_round, event_type, suffix):
    return ':'.join(['boss_rush', str(game_round.id), event_type, str(suffix)])


def record_boss_rush_battle_event(
    game_round,
    *,
    event_type,
    player=None,
    target_player=None,
    linked_answer_attempt=None,
    linked_boss_rush_attempt=None,
    linked_problem_id=None,
    boss_type=None,
    boss_hp_before=None,
    boss_hp_after=None,
    player_hp_before=None,
    player_hp_after=None,
    combo_before=None,
    combo_after=None,
    damage_intended=0,
    damage_applied=0,
    shield_or_guard_absorbed=0,
    ability_key=None,
    ability_count=None,
    details_json=None,
    event_key=None,
    occurred_at=None,
):
    if event_key:
        existing = AnalyticsBossRushBattleEvent.query.filter_by(event_key=event_key).first()
        if existing is not None:
            return existing
    analytics_round = ensure_analytics_round(game_round, ANALYTICS_MODE_BOSS_RUSH, config=getattr(game_round, 'boss_rush_config', None))
    row = AnalyticsBossRushBattleEvent(
        analytics_round_id=analytics_round.id,
        round_id=game_round.id,
        session_id=game_round.session_id,
        event_type=event_type,
        occurred_at=occurred_at or _utcnow(),
        player_id=getattr(player, 'id', None) if player is not None else None,
        player_name_snapshot=getattr(player, 'username', None) if player is not None else None,
        target_player_id=getattr(target_player, 'id', None) if target_player is not None else None,
        target_player_name_snapshot=getattr(target_player, 'username', None) if target_player is not None else None,
        linked_answer_attempt_id=getattr(linked_answer_attempt, 'id', None),
        linked_boss_rush_attempt_id=getattr(linked_boss_rush_attempt, 'id', None),
        linked_problem_id=linked_problem_id,
        boss_type=boss_type,
        boss_hp_before=boss_hp_before,
        boss_hp_after=boss_hp_after,
        player_hp_before=player_hp_before,
        player_hp_after=player_hp_after,
        combo_before=combo_before,
        combo_after=combo_after,
        damage_intended=damage_intended or 0,
        damage_applied=damage_applied or 0,
        shield_or_guard_absorbed=shield_or_guard_absorbed or 0,
        ability_key=ability_key,
        ability_count=ability_count,
        details_json=details_json,
        event_key=event_key,
    )
    db.session.add(row)
    db.session.flush()
    return row


def finalize_player_problem(
    game_round,
    player,
    problem,
    mode_context,
    *,
    status=None,
    eventual_correct=None,
    completed_at=None,
    extra_json=None,
):
    row = ensure_player_problem(game_round, player, problem, mode_context)
    if status:
        row.status = status
    if eventual_correct is not None:
        row.eventual_correct = eventual_correct
    if completed_at:
        row.completed_at = completed_at
    if extra_json:
        row.extra_json = _merge_json(row.extra_json, extra_json)
    return row


def finalize_player_round_summary(
    game_round,
    player,
    mode=None,
    *,
    wallet=None,
    boss_state=None,
    completed_at=None,
    boss_rank=None,
    diamonds_awarded=None,
    summary_json=None,
):
    row = ensure_player_round(game_round, player, mode, wallet=wallet, state=boss_state)
    player_problems = AnalyticsPlayerProblem.query.filter_by(round_id=game_round.id, player_id=player.id).all()
    attempts = AnalyticsAnswerAttempt.query.filter_by(round_id=game_round.id, player_id=player.id).all()
    row.problems_seen = sum(1 for item in player_problems if item.first_seen_at is not None)
    row.problems_attempted = sum(1 for item in player_problems if (item.attempt_count or 0) > 0)
    row.problems_solved = sum(1 for item in player_problems if item.eventual_correct is True or item.status in (ANALYTICS_STATUS_SOLVED, ANALYTICS_STATUS_COMPLETED))
    row.correct_attempts = sum(1 for item in attempts if item.is_correct)
    row.incorrect_attempts = sum(1 for item in attempts if not item.is_correct)
    row.first_try_correct_count = sum(1 for item in player_problems if item.first_attempt_correct is True)
    total_attempts = row.correct_attempts + row.incorrect_attempts
    row.accuracy = (row.correct_attempts / total_attempts) if total_attempts else None
    if wallet is not None:
        row.gold_end = wallet.gold
        row.gems_end = wallet.gems
        row.gold_net = wallet.gold - row.gold_start if row.gold_start is not None else None
        row.gems_net = wallet.gems - row.gems_start if row.gems_start is not None else None
    if boss_state is not None:
        row.damage_dealt = boss_state.damage_dealt or 0
        row.max_combo = boss_state.max_combo or 0
        row.final_combo = boss_state.current_combo or 0
        row.hp_final = boss_state.hp
        row.attack_correct = boss_state.correct_count or 0
        row.attack_incorrect = boss_state.incorrect_count or 0
        row.recovery_correct = boss_state.recovery_correct_count or 0
        row.recovery_incorrect = boss_state.recovery_incorrect_count or 0
    if boss_rank is not None:
        row.boss_rank = boss_rank
    if diamonds_awarded is not None:
        row.diamonds_awarded = diamonds_awarded
    if summary_json:
        row.summary_json = _merge_json(row.summary_json, summary_json)
    now = _utcnow()
    row.completed_at = completed_at or row.completed_at
    row.finalized_at = now
    return row


def finalize_round_summary(game_round, mode=None, *, ended_at=None):
    row = ensure_analytics_round(game_round, mode)
    row.started_at = row.started_at or game_round.started_at
    row.ended_at = ended_at or row.ended_at or game_round.ended_at
    row.finalized_at = row.finalized_at or _utcnow()
    return row


def finalize_classic_round(game_round):
    from app.models.classic import PlayerProblemState, PlayerWallet

    snapshot_classic_round_problem_set(game_round)
    completed_at = game_round.ended_at or _utcnow()
    for round_player in RoundPlayer.query.filter_by(session_id=game_round.session_id).all():
        player = round_player.player
        wallet = PlayerWallet.query.filter_by(player_id=player.id, session_id=game_round.session_id).first()
        ensure_player_round(game_round, player, ANALYTICS_MODE_CLASSIC, wallet=wallet)
        for pps in PlayerProblemState.query.filter_by(player_id=player.id, round_id=game_round.id).all():
            status = ANALYTICS_STATUS_SOLVED if pps.is_solved else (ANALYTICS_STATUS_CLOSED if pps.is_closed else ANALYTICS_STATUS_SEEN)
            row = finalize_player_problem(
                game_round,
                player,
                pps.problem,
                ANALYTICS_CONTEXT_CLASSIC,
                status=status,
                eventual_correct=bool(pps.is_solved),
                completed_at=completed_at if pps.is_closed or pps.is_solved else None,
                extra_json={'classic_attempts_used': pps.attempts_used},
            )
            row.attempt_count = max(row.attempt_count or 0, pps.attempts_used or 0)
        player_summary = finalize_player_round_summary(
            game_round,
            player,
            ANALYTICS_MODE_CLASSIC,
            wallet=wallet,
            completed_at=completed_at,
        )
        events_as_actor = AnalyticsClassicEconomyEvent.query.filter_by(round_id=game_round.id, actor_player_id=player.id).all()
        events_as_target = AnalyticsClassicEconomyEvent.query.filter_by(round_id=game_round.id, target_player_id=player.id).all()
        economy_summary = {
            'gold_mined': sum(event.gold_delta_actor for event in events_as_actor if event.event_type == 'mine_success'),
            'gold_stolen_from_others': sum(event.gold_delta_actor for event in events_as_actor if event.event_type == 'steal_success'),
            'gold_lost_to_steals': -sum(event.gold_delta_target for event in events_as_target if event.event_type == 'steal_success'),
            'gold_earned_from_treasure': sum(event.gold_delta_actor for event in events_as_actor if event.event_type == 'treasure_gold'),
            'gold_spent_in_store': -sum(event.gold_delta_actor for event in events_as_actor if event.event_type == 'store_purchase'),
            'gems_spent_in_store': -sum(event.gems_delta_actor for event in events_as_actor if event.event_type == 'store_purchase'),
            'successful_steals': sum(1 for event in events_as_actor if event.event_type == 'steal_success'),
            'failed_steals': sum(1 for event in events_as_actor if event.event_type == 'steal_failed'),
            'blocked_steals': sum(1 for event in events_as_actor if event.event_type == 'steal_blocked'),
            'treasure_gold_events': sum(1 for event in events_as_actor if event.event_type == 'treasure_gold'),
            'treasure_picks': sum(1 for event in events_as_actor if event.event_type == 'treasure_pick'),
            'treasure_bonus_events': sum(1 for event in events_as_actor if event.event_type == 'treasure_bonus'),
            'store_purchases': sum(1 for event in events_as_actor if event.event_type == 'store_purchase'),
            'shield_activations': sum(1 for event in events_as_actor if event.event_type == 'shield_activated'),
        }
        player_summary.summary_json = _merge_json(player_summary.summary_json, {'classic_economy': economy_summary})
    return finalize_round_summary(game_round, ANALYTICS_MODE_CLASSIC, ended_at=completed_at)


def _reward_entry_map(reward_snapshot):
    entries = {}
    if not reward_snapshot:
        return entries
    for entry in reward_snapshot.get('players', []) or []:
        player_id = entry.get('player_id')
        if player_id is not None:
            entries[int(player_id)] = entry
    return entries


def finalize_boss_rush_round(game_round, *, reward_snapshot=None):
    from app.models.boss_rush import BossRushPlayerState

    config = getattr(game_round, 'boss_rush_config', None)
    snapshot_boss_rush_round_problem_sets(game_round, config=config)
    reward_entries = _reward_entry_map(reward_snapshot or getattr(getattr(game_round, 'boss_rush_battle_state', None), 'final_rewards_json', None))
    completed_at = game_round.ended_at or _utcnow()
    for state in BossRushPlayerState.query.filter_by(round_id=game_round.id).all():
        entry = reward_entries.get(state.player_id, {})
        ensure_player_round(game_round, state.player, ANALYTICS_MODE_BOSS_RUSH, state=state)
        finalize_player_round_summary(
            game_round,
            state.player,
            ANALYTICS_MODE_BOSS_RUSH,
            boss_state=state,
            completed_at=completed_at,
            boss_rank=entry.get('rank') or entry.get('place'),
            diamonds_awarded=entry.get('diamonds_awarded') or entry.get('diamonds') or 0,
            summary_json={'reward_entry': entry} if entry else None,
        )
    return finalize_round_summary(game_round, ANALYTICS_MODE_BOSS_RUSH, ended_at=completed_at)
