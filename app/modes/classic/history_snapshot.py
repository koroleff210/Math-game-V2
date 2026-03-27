# app/modes/classic/history_snapshot.py
#
# Creates frozen round-history snapshots at Classic round end.
#
# Public API:
#   freeze_round_history(game_round, game_session, frozen_at)
#     → RoundHistory  (already added to db.session; caller commits)
#
# Design notes:
#   - Called from end_round BEFORE db.session.commit() so that wallet gold/gems
#     still reflect the end-of-round state (before any next-round carry resets).
#   - Idempotent: if a RoundHistory row already exists for this round_id, the
#     existing record is returned unchanged.  This prevents duplicate snapshots
#     if end_round is somehow invoked twice.
#   - All db.session.add() calls stay in the caller's transaction; no commit here.

from app.extensions import db
from app.models.classic import PlayerWallet, PlayerProblemState
from app.models.player  import Player
from app.models.history import RoundHistory, RoundPlayerResult


def freeze_round_history(game_round, game_session, frozen_at):
    """Build and persist a RoundHistory + RoundPlayerResult set for a just-ended round.

    Args:
        game_round   (GameRound):   The round that just ended (ended_at already set).
        game_session (GameSession): The containing session.
        frozen_at    (datetime):    The exact timestamp to store as ended_at on the snapshot.

    Returns:
        RoundHistory: The (newly created or pre-existing) history record.

    The function adds new rows to db.session but does NOT commit.
    The caller (end_round route) is responsible for the final commit.
    """
    # ── Idempotency guard ─────────────────────────────────────────────────────
    existing = RoundHistory.query.filter_by(round_id=game_round.id).first()
    if existing:
        return existing

    # ── Gather enrolled players ordered by gold desc (leaderboard order) ─────
    wallets = (
        PlayerWallet.query
        .filter_by(session_id=game_session.id)
        .order_by(PlayerWallet.gold.desc(), PlayerWallet.player_id.asc())
        .all()
    )

    # ── Frozen context snapshots ──────────────────────────────────────────────
    problem_set_name = None
    if game_session.problem_set_id and game_session.problem_set:
        problem_set_name = game_session.problem_set.name

    group_name = None
    if game_session.group_id and game_session.group:
        group_name = game_session.group.name

    session_label = game_session.display_label  # computed property; snapshot it now

    # ── Bulk-load player usernames in one query ───────────────────────────────
    player_ids = [w.player_id for w in wallets]
    if player_ids:
        players_map = {
            p.id: p.username
            for p in Player.query.filter(Player.id.in_(player_ids)).all()
        }
    else:
        players_map = {}

    # ── Per-player stats + competition ranking ────────────────────────────────
    round_total_answers = 0
    round_total_correct = 0
    player_data_list    = []
    prev_gold           = None
    current_place       = 1

    for idx, wallet in enumerate(wallets):
        # Competition ranking: first entry = place 1; same gold = same place;
        # next different gold = idx+1 (standard competition / 1-2-2-4 ranks).
        if prev_gold is None:
            current_place = 1
        elif wallet.gold < prev_gold:
            current_place = idx + 1
        # else: gold == prev_gold → keep same place as previous

        # Per-player answer stats from PlayerProblemState (round-scoped by round_id)
        pps_rows = (
            PlayerProblemState.query
            .filter_by(player_id=wallet.player_id, round_id=game_round.id)
            .all()
        )
        p_total     = sum(pps.attempts_used for pps in pps_rows)
        p_correct   = sum(1 for pps in pps_rows if pps.is_solved)
        p_incorrect = p_total - p_correct
        p_accuracy  = p_correct / p_total if p_total > 0 else 0.0

        round_total_answers += p_total
        round_total_correct += p_correct

        prev_gold = wallet.gold
        player_data_list.append({
            'player_id':    wallet.player_id,
            'player_name':  players_map.get(wallet.player_id, 'Unknown'),
            'final_place':  current_place,
            'final_gold':   wallet.gold,
            'final_gems':   wallet.gems,
            'total_answers': p_total,
            'correct':       p_correct,
            'incorrect':     p_incorrect,
            'accuracy':      p_accuracy,
        })

    round_total_incorrect = round_total_answers - round_total_correct
    overall_accuracy = (
        round_total_correct / round_total_answers
        if round_total_answers > 0 else 0.0
    )

    # ── Create RoundHistory record ────────────────────────────────────────────
    history = RoundHistory(
        round_id                  = game_round.id,
        session_id                = game_session.id,
        mode_type                 = game_session.mode,
        round_number              = game_round.round_number,
        session_label_snapshot    = session_label,
        problem_set_id            = game_session.problem_set_id,
        problem_set_name_snapshot = problem_set_name,
        group_id                  = game_session.group_id,
        group_name_snapshot       = group_name,
        started_at                = game_round.started_at,
        ended_at                  = frozen_at,
        player_count              = len(wallets),
        total_answers             = round_total_answers,
        total_correct             = round_total_correct,
        total_incorrect           = round_total_incorrect,
        overall_accuracy          = overall_accuracy,
    )
    db.session.add(history)
    db.session.flush()  # materialise history.id for the FK in player results

    # ── Create one RoundPlayerResult per enrolled player ──────────────────────
    for data in player_data_list:
        result = RoundPlayerResult(
            round_history_id     = history.id,
            player_id            = data['player_id'],
            player_name_snapshot = data['player_name'],
            final_place          = data['final_place'],
            final_gold           = data['final_gold'],
            final_gems           = data['final_gems'],
            total_answers        = data['total_answers'],
            correct              = data['correct'],
            incorrect            = data['incorrect'],
            accuracy             = data['accuracy'],
        )
        db.session.add(result)

    return history
