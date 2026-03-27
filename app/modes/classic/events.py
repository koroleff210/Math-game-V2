# app/modes/classic/events.py
#
# Socket.IO event handlers for Classic Mode.
#
# All handlers are registered via register_classic_handlers(socketio).
# Flask-Login's current_user is available inside handlers because Flask-SocketIO
# propagates the Flask HTTP session into the SocketIO event context.
#
# Room convention: 'classic_<session_id>'
#
# Event flow (per player, per problem):
#   1. classic_join              → join_ack (problem list + wallet + steal state)
#   2. classic_submit_answer     → answer_result (wrong) OR choose_action_prompt (correct)
#   3. classic_choose_action     → reward_applied + leaderboard_update (broadcast)
#                                  OR steal_targets (if action='steal')
#   4a. classic_steal_pick_target  → steal_mini_game_start OR steal_result
#   4b. classic_steal_mini_game_pick → steal_result + (steal_victim_notify to victim)
#
# Note on PlayerAnswer:
#   The existing PlayerAnswer model has UNIQUE(round_id, player_id) — one answer
#   per player per round.  Classic Mode allows multiple problems per round per player,
#   so PlayerAnswer CANNOT be used here without violating that constraint.
#   All answer tracking is done in PlayerProblemState (attempts_used, is_solved,
#   is_closed).  This deviation is documented in docs/dev_log.md.

import random

from flask import render_template
from flask_socketio import emit, join_room
from flask_login import current_user
from datetime import datetime, timezone

from app.extensions import db
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.problems import Problem
from app.models.classic import (
    ClassicRoundConfig, PlayerWallet, PlayerClassicState,
    PlayerProblemState, ProblemSolverCount, StealEvent,
    StoreItem, PlayerInventory,
)
from app.core.problem_engine import check_answer
from app.modes.classic import engine, state, store as classic_store
from app.modes.classic.routes import player_in_session_group
from app.services.problem_content import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    build_problem_body_view,
    build_problem_choice_view,
)
from app.modes.classic.admin_summary import render_admin_supervision_summary_payload
from app.services.progression import get_session_player_modifiers


def _manual_shield_base_duration(config) -> int:
    return getattr(config, 'active_shield_duration', None) or getattr(config, 'shield_duration', 60)


def _reactive_shield_base_duration(config) -> int:
    return getattr(config, 'reactive_shield_duration', None) or getattr(config, 'shield_duration', 60)


def _render_problem_body_html(problem) -> str:
    body_view = build_problem_body_view(problem)
    return render_template('shared/_problem_body_blocks.html', body_view=body_view)


def _build_problem_choice_payload(problem) -> dict:
    choice_view = build_problem_choice_view(problem)
    return {
        'answer_type': choice_view['answer_type'],
        'choice_options': choice_view['options'],
    }


def register_classic_handlers(socketio):
    """Bind all Classic Mode Socket.IO events to the socketio instance."""

    # ── classic_join ──────────────────────────────────────────────────────────

    @socketio.on('classic_join')
    def handle_join(data):
        """
        Player (or re-joining player) enters the Classic session.

        Payload: { session_id }

        Emits to caller:
          join_ack → { player_id, gold, round_status, problem_list }
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id = data.get('session_id')
        game_session = db.session.get(GameSession, session_id)

        if not game_session or game_session.mode != 'classic':
            emit('error', {'msg': 'session not found'})
            return

        player = current_user

        # Group access check (AD-32: double-guard — HTTP + socket)
        if not player_in_session_group(player, game_session):
            emit('access_denied', {
                'reason': 'not_in_group',
                'message': 'You are not in the group for this session.',
            })
            return

        # Enrollment guard — player must have joined explicitly via POST /classic/join.
        # classic_join is bootstrap-only; it no longer creates participation rows.
        existing_rp = RoundPlayer.query.filter_by(
            session_id=session_id, player_id=player.id
        ).first()
        if not existing_rp:
            emit('access_denied', {
                'reason': 'not_enrolled',
                'message': 'Join the session from your Hub first.',
            })
            return

        # Fetch wallet and classic state — must exist (created by explicit Join).
        wallet = PlayerWallet.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        if not wallet:
            emit('error', {'msg': 'participation state missing \u2014 please rejoin'})
            return

        # Get PlayerClassicState (steal shield state)
        pcs = PlayerClassicState.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        if not pcs:
            emit('error', {'msg': 'participation state missing \u2014 please rejoin'})
            return

        # Join the session room and the private player room (for victim notifications)
        room = f'classic_{session_id}'
        join_room(room)
        join_room(f'player_{player.id}')

        # Get the current (non-ended) round
        game_round = GameRound.query.filter_by(
            session_id=session_id, ended_at=None
        ).order_by(GameRound.round_number.desc()).first()

        # Build problem list from the session's problem set
        problem_list = []
        if game_round and game_session.problem_set:
            config = game_round.classic_config
            problems = game_session.problem_set.problems.all()

            for prob in problems:
                # Get or create PlayerProblemState for this player+round+problem.
                # Use merge-or-create pattern inside a savepoint to survive UNIQUE
                # constraint races (lobby socket and game socket can both fire here).
                pps = PlayerProblemState.query.filter_by(
                    player_id=player.id,
                    round_id=game_round.id,
                    problem_id=prob.id,
                ).first()
                if not pps:
                    # Use a savepoint so that a UNIQUE-constraint race on this
                    # problem does not roll back PlayerProblemState rows that
                    # were already flushed for earlier problems in this loop.
                    sp = db.session.begin_nested()
                    try:
                        pps = PlayerProblemState(
                            player_id=player.id,
                            round_id=game_round.id,
                            problem_id=prob.id,
                        )
                        db.session.add(pps)
                        db.session.flush()
                    except Exception:
                        sp.rollback()
                        pps = PlayerProblemState.query.filter_by(
                            player_id=player.id,
                            round_id=game_round.id,
                            problem_id=prob.id,
                        ).first()

                if not pps:
                    continue  # skip if row still unavailable

                atp = config.attempts_per_problem if config else 1
                if atp == -1:
                    attempts_left = -1  # unlimited — represented as -1
                else:
                    attempts_left = max(0, atp - pps.attempts_used)

                choice_payload = _build_problem_choice_payload(prob)
                problem_list.append({
                    'problem_id':  prob.id,
                    'title':       prob.title,
                    'prompt_text': prob.prompt_text,
                    'problem_body_html': _render_problem_body_html(prob),
                    'answer_type': choice_payload['answer_type'],
                    'choice_options': choice_payload['choice_options'],
                    'attempts_left': attempts_left,
                    'is_closed':   pps.is_closed,
                    'is_solved':   pps.is_solved,
                })

            db.session.commit()

        round_status = 'not_started'
        if game_session.status == 'active' and game_round and not game_round.ended_at:
            round_status = 'active'
        elif game_session.status == 'finished' or (game_round and game_round.ended_at):
            round_status = 'ended'

        # Build store data for this player
        store_items    = classic_store.store_items_for(session_id)
        active_bonuses = classic_store.get_active_counts(player.id, session_id)

        # Build current leaderboard so the game screen shows data immediately on join
        wallets_lb = (
            PlayerWallet.query
            .filter_by(session_id=session_id)
            .order_by(PlayerWallet.gold.desc())
            .all()
        )
        leaderboard = [
            {'username': w.player.username, 'gold': w.gold, 'gems': w.gems}
            for w in wallets_lb
        ]

        # Steal state for join_ack
        shield_active     = engine.is_steal_shield_active(pcs)
        # A1b: SQLite stores datetimes as naive (no tzinfo).  Always re-attach
        # UTC before serialising so JavaScript can parse the expiry correctly.
        _se = pcs.shield_expires_at
        if _se is not None and _se.tzinfo is None:
            _se = _se.replace(tzinfo=timezone.utc)
        shield_expires_iso = _se.isoformat() if _se else None
        recent_actions = state.get_action_log(player.id, session_id)

        # A1-4: include streak so page refresh doesn't reset the displayed counter.
        # A1-7: include frozen token cap so client shows current/max correctly.
        current_streak = state.get_streak(player.id, game_round.id) if game_round else 0
        steal_token_max_cap = 1
        if game_round:
            _join_mods = get_session_player_modifiers(session_id, player.id)
            steal_token_max_cap = _join_mods.effective_steal_token_cap

        # Notify the room that a player joined (updates lobby player lists)
        enrolled_now = RoundPlayer.query.filter_by(session_id=session_id).all()
        player_names = [rp.player.username for rp in enrolled_now]
        socketio.emit('player_joined', {'players': player_names}, room=room)

        emit('join_ack', {
            'player_id':          player.id,
            'username':           player.username,
            'gold':               wallet.gold,
            'gems':               wallet.gems,
            'steal_tokens':       wallet.steal_tokens,
            'steal_token_max_cap': steal_token_max_cap,
            'streak':             current_streak,
            'shield_active':      shield_active,
            'shield_expires_at':  shield_expires_iso,
            'recent_actions':     recent_actions,
            'round_status':       round_status,
            'problem_list':       problem_list,
            'store_items':        store_items,
            'active_bonuses':     active_bonuses,
            'leaderboard':        leaderboard,
        })

    # ── classic_submit_answer ─────────────────────────────────────────────────

    @socketio.on('classic_submit_answer')
    def handle_submit_answer(data):
        """
        Player submits an answer for a problem.

        Payload: { session_id, problem_id, answer_text }

        Emits to caller:
          answer_result        (if incorrect or last attempt exhausted)
          choose_action_prompt (if correct)
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id = int(data.get('session_id', 0))
        problem_id = int(data.get('problem_id', 0))
        answer_text = str(data.get('answer_text', '')).strip()
        selected_option_id_raw = data.get('selected_option_id')
        try:
            selected_option_id = int(selected_option_id_raw) if selected_option_id_raw not in (None, '') else None
        except (TypeError, ValueError):
            selected_option_id = None

        player = current_user

        # ── Guards ────────────────────────────────────────────────────────────

        game_session = db.session.get(GameSession, session_id)
        if not game_session or game_session.status != 'active':
            emit('error', {'msg': 'session not active'})
            return

        game_round = GameRound.query.filter_by(
            session_id=session_id,
            ended_at=None,
        ).order_by(GameRound.round_number.desc()).first()
        if not game_round:
            emit('error', {'msg': 'no active round'})
            return

        enrolled = RoundPlayer.query.filter_by(
            session_id=session_id, player_id=player.id
        ).first()
        if not enrolled:
            emit('error', {'msg': 'not enrolled in session'})
            return

        pps = PlayerProblemState.query.filter_by(
            player_id=player.id,
            round_id=game_round.id,
            problem_id=problem_id,
        ).first()
        if not pps or pps.is_closed:
            emit('error', {'msg': 'problem closed or not found'})
            return

        problem = db.session.get(Problem, problem_id)
        if not problem:
            emit('error', {'msg': 'problem not found'})
            return

        config = game_round.classic_config
        if not config:
            emit('error', {'msg': 'round config missing'})
            return

        # ── Evaluate answer ───────────────────────────────────────────────────

        if getattr(problem, 'answer_type', 'text_input') == PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE:
            is_correct = check_answer(problem, None, selected_option_id=selected_option_id)
        else:
            is_correct = check_answer(problem, answer_text)
        pps.attempts_used += 1

        atp = config.attempts_per_problem  # -1 = unlimited

        if is_correct:
            pps.is_solved = True
            pps.is_closed = True
        elif atp != -1 and pps.attempts_used >= atp:
            pps.is_closed = True

        db.session.commit()

        # ── Incorrect branch ──────────────────────────────────────────────────

        if not is_correct:
            wallet = PlayerWallet.query.filter_by(
                player_id=player.id, session_id=session_id
            ).first()

            second_chance_used = False

            # D2: Second Chance — consume one if available (unified path).
            # Benefits: no penalty AND attempt is preserved (player can retry).
            sc_inv = classic_store.consume_item(player.id, session_id, 'shield')
            if sc_inv:
                second_chance_used = True
                # Undo the attempt increment and re-open the problem
                pps.attempts_used -= 1
                pps.is_closed = False
                db.session.commit()
            else:
                # No Second Chance: apply penalty if configured
                if wallet and config.wrong_answer_penalty > 0:
                    wallet.gold = engine.apply_penalty(wallet.gold, config.wrong_answer_penalty)
                    db.session.commit()

            gold_now = wallet.gold if wallet else 0

            # Reset the consecutive-correct streak on any wrong answer
            state.reset_streak(player.id, game_round.id)

            if atp == -1:
                attempts_left = -1
            else:
                attempts_left = max(0, atp - pps.attempts_used)

            emit('answer_result', {
                'correct':           False,
                'attempts_left':     attempts_left,
                'problem_closed':    pps.is_closed,
                'gold_after_penalty': gold_now,
                'second_chance_used': second_chance_used,
                'streak_reset':      True,
            })
            return

        # ── Correct branch ─────────────────────────────────────────────────────
        # Increment solver count under the per-session lock to prevent duplicates
        # under concurrent submissions.

        lock = state.get_lock(session_id)
        with lock:
            psc = ProblemSolverCount.query.filter_by(
                round_id=game_round.id, problem_id=problem_id
            ).first()
            if not psc:
                psc = ProblemSolverCount(
                    round_id=game_round.id,
                    problem_id=problem_id,
                    solver_count=0,
                )
                db.session.add(psc)
            psc.solver_count += 1
            solver_rank = psc.solver_count
            db.session.commit()
        _emit_admin_summary_update(socketio, session_id)

        timer_active = state.is_timer_active(session_id, config.bonus_timer_duration)

        # Increment streak now that the answer is confirmed correct.
        # The streak is read back in classic_choose_action for gem calculation.
        state.increment_streak(player.id, game_round.id)

        # Record pending action so choose_action is only accepted after this event
        state.set_pending_action(player.id, game_round.id, problem_id)

        # Determine if steal is available (has token to spend)
        steal_wallet = PlayerWallet.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        steal_available = bool(steal_wallet and steal_wallet.steal_tokens >= 1)

        emit('choose_action_prompt', {
            'problem_id':      problem_id,
            'solver_rank':     solver_rank,
            'timer_active':    timer_active,
            'steal_available': steal_available,
        })

    # ── classic_choose_action ─────────────────────────────────────────────────

    @socketio.on('classic_choose_action')
    def handle_choose_action(data):
        """
        Player selects Mine or Treasure Search after a correct answer.

        Payload: { session_id, problem_id, action }
          action ∈ ['mine', 'treasure_search']

        Emits to caller:    reward_applied
        Emits to room:      leaderboard_update
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id = int(data.get('session_id', 0))
        problem_id = int(data.get('problem_id', 0))
        action = str(data.get('action', '')).strip().lower()

        if action not in ('mine', 'treasure_search', 'steal'):
            emit('error', {'msg': 'invalid action'})
            return

        player = current_user

        # ── Guards ────────────────────────────────────────────────────────────

        game_session = db.session.get(GameSession, session_id)
        if not game_session or game_session.status != 'active':
            emit('error', {'msg': 'session not active'})
            return

        game_round = GameRound.query.filter_by(
            session_id=session_id, ended_at=None
        ).order_by(GameRound.round_number.desc()).first()
        if not game_round:
            emit('error', {'msg': 'no active round'})
            return

        # Require a pending action for this specific problem
        if not state.has_pending_action(player.id, game_round.id, problem_id):
            emit('error', {'msg': 'no pending action for this problem'})
            return

        config = game_round.classic_config
        if not config:
            emit('error', {'msg': 'round config missing'})
            return

        # Contract #1: Mine/TS is blocked while a steal intent is open for this session.
        # (steal_targets has been sent but the player has not yet picked a target or cancelled)
        if action in ('mine', 'treasure_search'):
            existing_intent = state.get_steal_intent(player.id)
            if existing_intent and existing_intent.get('session_id') == session_id:
                emit('error', {'msg': 'steal in progress — cancel first'})
                return

        # ── Steal branch ──────────────────────────────────────────────────────
        # Consumes the action slot; token consumed later at pick_target (AD-28).
        # Exception: if no valid targets exist, token is consumed immediately.

        if action == 'steal':
            wallet = PlayerWallet.query.filter_by(
                player_id=player.id, session_id=session_id
            ).first()

            # Guard: must have at least one steal token
            if not wallet or wallet.steal_tokens < 1:
                emit('error', {'msg': 'no steal tokens'})
                return

            # Build valid target list
            all_wallets = PlayerWallet.query.filter_by(session_id=session_id).all()
            all_pcs     = PlayerClassicState.query.filter_by(session_id=session_id).all()
            states_map  = {p.player_id: p for p in all_pcs}

            targets = engine.build_steal_targets(all_wallets, states_map, player.id)

            if not targets:
                # No valid targets — consume token, forfeit action slot immediately
                state.clear_pending_action(player.id, game_round.id, problem_id)
                wallet.steal_tokens -= 1
                wallet.gold = max(0, wallet.gold + config.steal_fallback_gold)

                evt = StealEvent(
                    session_id=session_id,
                    round_id=game_round.id,
                    actor_id=player.id,
                    target_id=None,
                    outcome='no_targets_fallback',
                    gold_exchanged=config.steal_fallback_gold,
                    mini_game_pick=None,
                    created_at=datetime.now(timezone.utc),
                )
                db.session.add(evt)
                db.session.commit()

                log_entry = (
                    f'You received {config.steal_fallback_gold} gold from a stranger '
                    f'(no valid targets)'
                )
                state.append_action_log(player.id, session_id, log_entry)

                emit('steal_result', {
                    'outcome':    'no_targets_fallback',
                    'gold_gained': config.steal_fallback_gold,
                    'new_balance': wallet.gold,
                    'new_tokens':  wallet.steal_tokens,
                    'winning_chests': [],
                    'log_entry':  log_entry,
                })

                # Broadcast updated leaderboard
                _emit_leaderboard(socketio, session_id)
                _emit_admin_summary_update(socketio, session_id)
                return

            # Valid targets exist — register intent; action slot preserved for cancel
            state.set_steal_intent(player.id, session_id, game_round.id, problem_id)
            emit('steal_targets', {'targets': targets})
            return

        # ── Calculate reward (mine / treasure_search) ─────────────────────────

        # Re-read solver rank from DB (most accurate under concurrency)
        psc = ProblemSolverCount.query.filter_by(
            round_id=game_round.id, problem_id=problem_id
        ).first()
        solver_rank = psc.solver_count if psc else 1

        timer_active = state.is_timer_active(session_id, config.bonus_timer_duration)

        x2_active    = False
        treasure_roll = None   # only set for treasure_search actions
        if action == 'mine':
            result = engine.calc_mine_reward(config, solver_rank, timer_active)
            # Consume an x2_mine item if the player has one
            x2_inv = classic_store.consume_item(player.id, session_id, 'x2_mine')
            if x2_inv:
                result = engine.apply_x2_mine(result)
                x2_active = True
        else:
            result = engine.calc_treasure_search_reward(config, solver_rank, timer_active)
            treasure_roll = result['treasure_roll']  # raw roll before bonuses

        gold_gained = result['gold']
        breakdown   = result['breakdown']

        # D4: apply frozen upgrade bonus to the reward
        mods = get_session_player_modifiers(session_id, player.id)
        if action == 'mine':
            if mods.effective_mine_bonus != 0:
                gold_gained += mods.effective_mine_bonus
                breakdown.append(f'upgrade bonus: {mods.effective_mine_bonus:+d}')
            if mods.effective_gear_mine_gold_delta != 0:
                gold_gained += mods.effective_gear_mine_gold_delta
                breakdown.append(f'gear bonus: {mods.effective_gear_mine_gold_delta:+d}')
        elif action == 'treasure_search' and mods.effective_treasure_bonus > 0:
            gold_gained += mods.effective_treasure_bonus
            breakdown.append(f'upgrade bonus: +{mods.effective_treasure_bonus}')

        # ── Update wallet (gold + gems in one commit) ─────────────────────────

        wallet = PlayerWallet.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        if not wallet:
            wallet = PlayerWallet(player_id=player.id, session_id=session_id, gold=0, gems=0)
            db.session.add(wallet)

        wallet.gold += gold_gained

        # ── [D4] Treasure side reward (at most one, weighted selection) ────────
        token_found   = False
        token_awarded = False
        treasure_gem_won = False
        treasure_gem_gained = 0
        treasure_shield_token_granted = False
        treasure_second_chance_granted = False

        if action == 'treasure_search':
            side_reward = engine.pick_treasure_side_reward(
                getattr(config, 'gem_treasure_chance', 0.0),
                getattr(config, 'treasure_steal_token_chance', 0.0),
                getattr(config, 'treasure_active_shield_chance', 0.0),
                getattr(config, 'treasure_second_chance_chance', 0.0),
            )

            if side_reward == 'gem':
                treasure_gem_gained = 1
                treasure_gem_won = True

            elif side_reward == 'steal_token':
                token_found = True
                token_awarded = engine.try_award_steal_token(
                    wallet, max_cap=mods.effective_steal_token_cap
                )

            elif side_reward == 'active_shield':
                sys_item = classic_store.get_or_create_system_shield_token(session_id)
                inv = PlayerInventory(
                    player_id=player.id,
                    session_id=session_id,
                    item_id=sys_item.id,
                    purchased_at=datetime.now(timezone.utc),
                    used_at=None,
                )
                db.session.add(inv)
                db.session.flush()
                treasure_shield_token_granted = True

            elif side_reward == 'second_chance':
                # Capacity check: max 1 active Second Chance (any source)
                store_sc_active = (
                    PlayerInventory.query
                    .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
                    .filter(
                        PlayerInventory.player_id  == player.id,
                        PlayerInventory.session_id == session_id,
                        StoreItem.bonus_type       == 'shield',
                        PlayerInventory.used_at    == None,   # noqa: E711
                    )
                    .count()
                )
                if store_sc_active < 1:
                    sys_item = classic_store.get_or_create_system_sc(session_id)
                    inv = PlayerInventory(
                        player_id=player.id,
                        session_id=session_id,
                        item_id=sys_item.id,
                        purchased_at=datetime.now(timezone.utc),
                        used_at=None,
                    )
                    db.session.add(inv)
                    db.session.flush()
                    treasure_second_chance_granted = True
                # else: blocked by capacity → resolve to nothing

        # ── Gem awards (milestone + streak, both actions) ─────────────────────
        # Milestone: count solved problems for this player in this round (DB-authoritative).
        # Streak:    read the in-memory counter that was incremented in submit_answer.
        solved_count   = PlayerProblemState.query.filter_by(
            player_id=player.id, round_id=game_round.id, is_solved=True
        ).count()
        current_streak = state.get_streak(player.id, game_round.id)

        gem_result  = engine.calc_gem_award(
            solved_count, config.gem_milestone_count,
            current_streak, config.gem_streak_count,
        )
        gems_gained = gem_result['gems'] + treasure_gem_gained
        gem_reason  = gem_result['reason']

        wallet.gems += gems_gained

        new_balance = wallet.gold
        new_gems    = wallet.gems
        db.session.commit()

        # Consume the pending action
        state.clear_pending_action(player.id, game_round.id, problem_id)

        # ── Action log ────────────────────────────────────────────────────────
        if action == 'mine':
            state.append_action_log(player.id, session_id,
                                    f'You mined {gold_gained} gold')
        else:  # treasure_search
            side_parts = []
            if token_found and token_awarded:
                side_parts.append('a steal token')
            if treasure_shield_token_granted:
                side_parts.append('a shield token')
            if treasure_second_chance_granted:
                side_parts.append('a Second Chance')
            if treasure_gem_won:
                side_parts.append('a gem')
            if side_parts:
                side_str = ' and '.join(side_parts)
                state.append_action_log(player.id, session_id,
                    f'You found treasure: {gold_gained} gold and {side_str}')
            else:
                state.append_action_log(player.id, session_id,
                    f'You searched for treasure: {gold_gained} gold')

        # ── Emit reward to this player ────────────────────────────────────────

        emit('reward_applied', {
            'gold_gained':         gold_gained,
            'breakdown':           breakdown,
            'new_balance':         new_balance,
            'gems_gained':         gems_gained,
            'new_gems':            new_gems,
            'gem_reason':          gem_reason,
            'treasure_gem_won':    treasure_gem_won,
            'x2_active':           x2_active,
            'treasure_roll':       treasure_roll,
            'token_found':         token_found,
            'token_awarded':       token_awarded,
            'treasure_shield_token_granted': treasure_shield_token_granted,
            'treasure_second_chance_granted': treasure_second_chance_granted,
            'active_bonuses': classic_store.get_active_counts(player.id, session_id),
        })

        # ── Broadcast leaderboard to the room ────────────────────────────────

        wallets = (
            PlayerWallet.query
            .filter_by(session_id=session_id)
            .order_by(PlayerWallet.gold.desc())
            .all()
        )
        leaderboard = [
            {'username': w.player.username, 'gold': w.gold, 'gems': w.gems}
            for w in wallets
        ]
        room = f'classic_{session_id}'
        socketio.emit('leaderboard_update', {'leaderboard': leaderboard}, room=room)

    # ── classic_buy_item ──────────────────────────────────────────────────────

    @socketio.on('classic_buy_item')
    def handle_buy_item(data):
        """
        Player purchases a store item using gold.

        Payload: { session_id, item_id }

        Emits to caller:
          buy_result → { ok, msg, new_balance, store_items, active_bonuses }
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id = int(data.get('session_id', 0))
        item_id    = int(data.get('item_id', 0))
        player     = current_user

        game_session = db.session.get(GameSession, session_id)
        if not game_session or game_session.status != 'active':
            emit('error', {'msg': 'session not active'})
            return

        enrolled = RoundPlayer.query.filter_by(
            session_id=session_id, player_id=player.id
        ).first()
        if not enrolled:
            emit('error', {'msg': 'not enrolled in session'})
            return

        # A1-6/A1-7: get the frozen token cap so purchase_item can enforce it.
        _buy_cap = get_session_player_modifiers(session_id, player.id).effective_steal_token_cap

        ok, msg, new_balance = classic_store.purchase_item(
            player.id, session_id, item_id, steal_token_max_cap=_buy_cap,
        )

        # Re-read wallet after purchase; steal_token purchases update steal_tokens
        wallet_post = PlayerWallet.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        emit('buy_result', {
            'ok':            ok,
            'msg':           msg,
            'new_balance':   wallet_post.gold if wallet_post else new_balance,
            'new_gems':      wallet_post.gems if wallet_post else 0,
            'steal_tokens':  wallet_post.steal_tokens if wallet_post else 0,
            'store_items':   classic_store.store_items_for(session_id),
            'active_bonuses': classic_store.get_active_counts(player.id, session_id),
        })

    # ── classic_steal_pick_target ─────────────────────────────────────────────

    @socketio.on('classic_steal_pick_target')
    def handle_steal_pick_target(data):
        """
        Player confirms which target they want to steal from.

        Payload: { session_id, target_player_id }

        Token is consumed here (AD-28).

        Emits to caller:
          steal_mini_game_start  — if mini-game is enabled
          steal_result           — if mini-game is disabled (instant success/fail)
        Emits to victim (on success with no mini-game):
          steal_victim_notify
        Emits to room:
          leaderboard_update
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id       = int(data.get('session_id', 0))
        target_player_id = int(data.get('target_player_id', 0))
        player           = current_user

        # Guard: must have an active steal intent
        intent = state.get_steal_intent(player.id)
        if not intent or intent['session_id'] != session_id:
            emit('error', {'msg': 'no active steal intent'})
            return

        problem_id = intent['problem_id']   # preserved for clear_pending_action calls

        game_session = db.session.get(GameSession, session_id)
        if not game_session or game_session.status != 'active':
            state.clear_steal_intent(player.id)
            emit('error', {'msg': 'session not active'})
            return

        game_round = GameRound.query.filter_by(
            session_id=session_id, ended_at=None
        ).order_by(GameRound.round_number.desc()).first()
        if not game_round:
            state.clear_steal_intent(player.id)
            emit('error', {'msg': 'no active round'})
            return

        config = game_round.classic_config
        if not config:
            state.clear_steal_intent(player.id)
            emit('error', {'msg': 'round config missing'})
            return

        actor_wallet = PlayerWallet.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        actor_mods = get_session_player_modifiers(session_id, player.id)
        target_wallet = PlayerWallet.query.filter_by(
            player_id=target_player_id, session_id=session_id
        ).first()
        target_pcs = PlayerClassicState.query.filter_by(
            player_id=target_player_id, session_id=session_id
        ).first()

        # Re-validate target: must exist, have gold > 0, not shielded (OQ-4 guard point 1)
        target_valid = (
            target_wallet is not None
            and target_wallet.gold > 0
            and (target_pcs is None or not engine.is_steal_shield_active(target_pcs))
        )

        if not target_valid:
            # Target became invalid between intent and pick (e.g. spent gold or got shielded).
            # Per locked design: confirmation already happened — token is consumed and the
            # attempt is logged as mini_game_fail (AD-28).
            actor_wallet.steal_tokens -= 1
            state.clear_steal_intent(player.id)
            state.clear_pending_action(player.id, game_round.id, problem_id)

            evt = StealEvent(
                session_id=session_id,
                round_id=game_round.id,
                actor_id=player.id,
                target_id=target_player_id,
                outcome='target_invalid',
                gold_exchanged=0,
                mini_game_pick=None,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(evt)
            db.session.commit()
            _emit_admin_summary_update(socketio, session_id)

            log_entry = 'Your steal attempt failed (target no longer valid)'
            state.append_action_log(player.id, session_id, log_entry)

            emit('steal_result', {
                'outcome':        'target_invalid',
                'gold_gained':    0,
                'new_balance':    actor_wallet.gold,
                'new_tokens':     actor_wallet.steal_tokens,
                'winning_chests': [],
                'log_entry':      log_entry,
            })
            return

        # ── Consume token (AD-28) ─────────────────────────────────────────────
        actor_wallet.steal_tokens -= 1
        state.clear_steal_intent(player.id)
        state.clear_pending_action(player.id, game_round.id, problem_id)

        steal_amount = engine.calc_effective_steal_amount(
            target_wallet.gold,
            config.steal_percent,
            config.steal_min_cap,
            config.steal_max_cap,
            actor_mods.effective_gear_steal_gold_delta,
        )

        if config.steal_chest_count == 0:
            # Mini-game disabled — instant success
            # D4: compute target's effective shield duration from frozen modifiers
            _target_mods  = get_session_player_modifiers(session_id, target_player_id)
            _eff_shield_s = engine.calc_effective_shield_duration(
                _reactive_shield_base_duration(config),
                _target_mods.effective_shield_bonus_pct,
                _target_mods.effective_gear_shield_duration_delta,
            )
            _resolve_steal_success(
                socketio, session_id, game_round.id,
                player, actor_wallet,
                target_player_id, target_wallet, target_pcs,
                steal_amount, config,
                mini_game_pick=None,
                shield_duration_s=_eff_shield_s,
            )
        else:
            # Mini-game enabled — generate server-side winning chests and wait for pick
            winning_chests = engine.generate_winning_chests(
                config.steal_chest_count, config.steal_winning_chest_count
            )
            state.set_steal_minigame(
                player.id,
                target_id=target_player_id,
                winning_chests=winning_chests,
                steal_amount=steal_amount,
                session_id=session_id,
                round_id=game_round.id,
            )
            db.session.commit()   # commit token consumption before mini-game starts
            emit('steal_mini_game_start', {
                'chest_count':         config.steal_chest_count,
                'winning_chest_count': config.steal_winning_chest_count,
            })

    # ── classic_steal_cancel ──────────────────────────────────────────────────

    @socketio.on('classic_steal_cancel')
    def handle_steal_cancel(data):
        """
        Player cancels target selection during a steal attempt.

        Payload: { session_id }

        Effect:
          - steal_intent cleared; token NOT consumed (AD-28)
          - pending_action preserved (action slot returned to the player)

        Emits to caller:
          choose_action_prompt — player may now choose Mine / TS / Steal again
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id = int(data.get('session_id', 0))
        player     = current_user

        intent = state.get_steal_intent(player.id)
        if not intent or intent['session_id'] != session_id:
            emit('error', {'msg': 'no active steal intent'})
            return

        problem_id = intent['problem_id']
        round_id   = intent['round_id']
        state.clear_steal_intent(player.id)   # token NOT consumed

        game_session = db.session.get(GameSession, session_id)
        if not game_session or game_session.status != 'active':
            emit('error', {'msg': 'session not active'})
            return

        game_round = GameRound.query.filter_by(
            session_id=session_id, ended_at=None
        ).order_by(GameRound.round_number.desc()).first()
        if not game_round or game_round.id != round_id:
            emit('error', {'msg': 'round ended'})
            return

        config = game_round.classic_config

        if not state.has_pending_action(player.id, game_round.id, problem_id):
            emit('error', {'msg': 'no pending action'})
            return

        # Re-read solver rank and timer for a fresh choose_action_prompt
        psc = ProblemSolverCount.query.filter_by(
            round_id=game_round.id, problem_id=problem_id
        ).first()
        solver_rank  = psc.solver_count if psc else 1
        timer_active = state.is_timer_active(session_id, config.bonus_timer_duration)

        wallet = PlayerWallet.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        steal_available = bool(wallet and wallet.steal_tokens >= 1)

        emit('choose_action_prompt', {
            'problem_id':      problem_id,
            'solver_rank':     solver_rank,
            'timer_active':    timer_active,
            'steal_available': steal_available,
        })

    # ── classic_steal_mini_game_pick ──────────────────────────────────────────

    @socketio.on('classic_steal_mini_game_pick')
    def handle_steal_mini_game_pick(data):
        """
        Player picks a chest index during the steal mini-game.

        Payload: { session_id, chest_index }

        Emits to caller:    steal_result
        Emits to victim:    steal_victim_notify (on success)
        Emits to room:      leaderboard_update  (on success)
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id  = int(data.get('session_id', 0))
        chest_index = int(data.get('chest_index', 0))
        player      = current_user

        minigame = state.get_steal_minigame(player.id)
        if not minigame or minigame['session_id'] != session_id:
            emit('error', {'msg': 'no active steal mini-game'})
            return

        game_session = db.session.get(GameSession, session_id)
        if not game_session or game_session.status != 'active':
            state.clear_steal_minigame(player.id)
            emit('error', {'msg': 'session not active'})
            return

        game_round = GameRound.query.filter_by(
            session_id=session_id, ended_at=None
        ).order_by(GameRound.round_number.desc()).first()
        if not game_round:
            state.clear_steal_minigame(player.id)
            emit('error', {'msg': 'no active round'})
            return

        config = game_round.classic_config
        if not config:
            state.clear_steal_minigame(player.id)
            emit('error', {'msg': 'round config missing'})
            return

        target_player_id = minigame['target_id']
        winning_chests   = minigame['winning_chests']
        steal_amount     = minigame['steal_amount']

        actor_wallet  = PlayerWallet.query.filter_by(
            player_id=player.id, session_id=session_id
        ).first()
        target_wallet = PlayerWallet.query.filter_by(
            player_id=target_player_id, session_id=session_id
        ).first()
        target_pcs = PlayerClassicState.query.filter_by(
            player_id=target_player_id, session_id=session_id
        ).first()

        state.clear_steal_minigame(player.id)

        # OQ-4: re-validate target; if now shielded or broke → mini_game_fail
        target_still_valid = (
            target_wallet is not None
            and target_wallet.gold > 0
            and (target_pcs is None or not engine.is_steal_shield_active(target_pcs))
        )

        won_chest = chest_index in winning_chests

        # D4: compute target's effective shield duration from frozen modifiers
        _target_mods  = get_session_player_modifiers(session_id, target_player_id)
        _eff_shield_s = engine.calc_effective_shield_duration(
            _reactive_shield_base_duration(config),
            _target_mods.effective_shield_bonus_pct,
            _target_mods.effective_gear_shield_duration_delta,
        )

        if won_chest and target_still_valid:
            _resolve_steal_success(
                socketio, session_id, game_round.id,
                player, actor_wallet,
                target_player_id, target_wallet, target_pcs,
                steal_amount, config,
                mini_game_pick=chest_index,
                shield_duration_s=_eff_shield_s,
            )
        else:
            # Terminal failure — distinguish target_invalid from a wrong-chest mini_game_fail
            if not target_still_valid:
                outcome_str = 'target_invalid'
                log_entry   = 'Your steal attempt failed (target no longer valid)'
            else:
                outcome_str = 'mini_game_fail'
                log_entry   = 'Your steal attempt failed'

            evt = StealEvent(
                session_id=session_id,
                round_id=game_round.id,
                actor_id=player.id,
                target_id=target_player_id,
                outcome=outcome_str,
                gold_exchanged=0,
                mini_game_pick=chest_index,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(evt)
            db.session.commit()

            state.append_action_log(player.id, session_id, log_entry)

            emit('steal_result', {
                'outcome':        outcome_str,
                'gold_gained':    0,
                'new_balance':    actor_wallet.gold if actor_wallet else 0,
                'new_tokens':     actor_wallet.steal_tokens if actor_wallet else 0,
                'winning_chests': sorted(winning_chests),
                'log_entry':      log_entry,
            })

    # ── classic_activate_steal_shield ─────────────────────────────────────────

    @socketio.on('classic_activate_steal_shield')
    def handle_activate_steal_shield(data):
        """
        Player manually activates a steal_shield item from their inventory.

        Payload: { session_id }

        Requires an ACTIVE round (not just active session) — clarification E-1.
        Atomically consumes the oldest unused steal_shield inventory row and
        extends PlayerClassicState.shield_expires_at via grant_steal_shield().

        Emits to caller:
          shield_activated → { shield_active, shield_expires_at, active_bonuses, log_entry }
        """
        if not current_user.is_authenticated:
            emit('error', {'msg': 'not authenticated'})
            return

        session_id = int(data.get('session_id', 0))
        player     = current_user

        game_session = db.session.get(GameSession, session_id)
        if not game_session or game_session.status != 'active':
            emit('error', {'msg': 'session not active'})
            return

        # Clarification E-1: active ROUND required, not just active session
        game_round = GameRound.query.filter_by(
            session_id=session_id, ended_at=None
        ).order_by(GameRound.round_number.desc()).first()
        if not game_round:
            emit('error', {'msg': 'no active round'})
            return

        config = game_round.classic_config
        if not config:
            emit('error', {'msg': 'round config missing'})
            return

        enrolled = RoundPlayer.query.filter_by(
            session_id=session_id, player_id=player.id
        ).first()
        if not enrolled:
            emit('error', {'msg': 'not enrolled in session'})
            return

        # Clarification E-2: single atomic commit for consume + grant
        with state.get_lock(session_id):
            pcs = PlayerClassicState.query.filter_by(
                player_id=player.id, session_id=session_id
            ).first()
            if pcs and engine.is_steal_shield_active(pcs):
                emit('shield_activation_blocked', {
                    'msg': 'You are already protected. Wait for the current protection to expire before using a Shield Token.',
                    'active_bonuses': classic_store.get_active_counts(player.id, session_id),
                })
                return

            inv = (
                PlayerInventory.query
                .join(StoreItem, PlayerInventory.item_id == StoreItem.id)
                .filter(
                    PlayerInventory.player_id  == player.id,
                    PlayerInventory.session_id == session_id,
                    StoreItem.bonus_type       == 'steal_shield',
                    PlayerInventory.used_at    == None,  # noqa: E711
                )
                .order_by(PlayerInventory.purchased_at.asc())
                .first()
            )
            if not inv:
                emit('error', {'msg': 'no shield tokens available'})
                return

            if not pcs:
                pcs = PlayerClassicState(
                    player_id=player.id,
                    session_id=session_id,
                )
                db.session.add(pcs)
                db.session.flush()

            inv.used_at      = datetime.now(timezone.utc)
            # Shared modifier pipeline, manual/base duration path.
            _actor_mods    = get_session_player_modifiers(session_id, player.id)
            effective_shield_s = engine.calc_effective_shield_duration(
                _manual_shield_base_duration(config),
                _actor_mods.effective_shield_bonus_pct,
                _actor_mods.effective_gear_shield_duration_delta,
            )
            new_expiry       = engine.grant_steal_shield(pcs, effective_shield_s)
            db.session.commit()

        log_entry      = f'Shield Token activated ({effective_shield_s}s)'
        state.append_action_log(player.id, session_id, log_entry)
        active_bonuses = classic_store.get_active_counts(player.id, session_id)

        emit('shield_activated', {
            'shield_active':     True,
            'shield_expires_at': new_expiry.isoformat(),
            'active_bonuses':    active_bonuses,
            'log_entry':         log_entry,
        })

    # ── classic_admin_watch ───────────────────────────────────────────────────

    @socketio.on('classic_admin_watch')
    def handle_admin_watch(data):
        """
        Admin joins the classic session room to receive live broadcasts.

        Expects: { session_id: <int> }
        Joins room: classic_<session_id>

        No gameplay logic is executed here; all updates arrive via the
        existing leaderboard_update and player_joined room broadcasts.
        """
        if not current_user.is_authenticated or not current_user.is_admin:
            emit('error', {'message': 'Unauthorized'})
            return

        session_id = data.get('session_id')
        if not session_id:
            emit('error', {'message': 'session_id required'})
            return

        join_room(f'classic_{session_id}')
        emit('admin_watch_ack', {'session_id': session_id})

    # end register_classic_handlers


# ── Module-level helper (not a socket handler) ────────────────────────────────

def _emit_leaderboard(socketio, session_id: int) -> None:
    """Broadcast the current gold leaderboard to the classic session room."""
    wallets = (
        PlayerWallet.query
        .filter_by(session_id=session_id)
        .order_by(PlayerWallet.gold.desc())
        .all()
    )
    leaderboard = [
        {'username': w.player.username, 'gold': w.gold, 'gems': w.gems}
        for w in wallets
    ]
    socketio.emit('leaderboard_update', {'leaderboard': leaderboard},
                  room=f'classic_{session_id}')


def _emit_admin_summary_update(socketio, session_id: int) -> None:
    payload = render_admin_supervision_summary_payload(session_id)
    socketio.emit('admin_summary_update', payload, room=f'classic_{session_id}')


def _resolve_steal_success(
    socketio, session_id, round_id,
    actor_player, actor_wallet,
    target_player_id, target_wallet, target_pcs,
    steal_amount, config,
    mini_game_pick,
    *,
    shield_duration_s=None,  # effective reactive protection duration (including modifiers)
):
    """
    Apply a successful steal: transfer gold, grant reactive protection to victim,
    log StealEvent, emit events, update leaderboard.

    shield_duration_s: pre-computed effective reactive protection duration for the target.
    Falls back to config.reactive_shield_duration when not provided.
    Target's PlayerClassicState (target_pcs) may be None if the row doesn't
    exist yet; in that case one is created here.
    """
    _shield_s = shield_duration_s if shield_duration_s is not None else _reactive_shield_base_duration(config)
    # Transfer gold
    actual_stolen = min(steal_amount, target_wallet.gold)
    target_wallet.gold  -= actual_stolen
    actor_wallet.gold   += actual_stolen

    # Grant reactive anti-steal protection to the victim.
    if target_pcs is None:
        target_pcs = PlayerClassicState(
            player_id=target_player_id,
            session_id=session_id,
        )
        db.session.add(target_pcs)
        db.session.flush()   # get id before grant_steal_shield uses it

    new_expiry = engine.grant_steal_shield(target_pcs, _shield_s)

    # Log the event
    evt = StealEvent(
        session_id=session_id,
        round_id=round_id,
        actor_id=actor_player.id,
        target_id=target_player_id,
        outcome='success',
        gold_exchanged=actual_stolen,
        mini_game_pick=mini_game_pick,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(evt)
    db.session.commit()

    # Action log entries
    actor_log  = f'You stole {actual_stolen} gold from {target_wallet.player.username}'
    victim_log = (
        f'{actor_player.username} stole {actual_stolen} gold from you \u2014 '
        f'reactive protection granted ({_shield_s}s)'
    )
    state.append_action_log(actor_player.id, session_id, actor_log)
    state.append_action_log(target_player_id, session_id, victim_log)

    # Emit steal_result to actor
    emit('steal_result', {
        'outcome':        'success',
        'gold_gained':    actual_stolen,
        'new_balance':    actor_wallet.gold,
        'new_tokens':     actor_wallet.steal_tokens,
        'winning_chests': [] if mini_game_pick is None else [mini_game_pick],
        'log_entry':      actor_log,
    })

    # Notify victim in their own private room
    shield_iso = new_expiry.isoformat() if new_expiry else None
    socketio.emit(
        'steal_victim_notify',
        {
            'stolen_by':          actor_player.username,
            'amount':             actual_stolen,
            'new_balance':        target_wallet.gold,
            'shield_granted':     True,
            'shield_expires_at_iso': shield_iso,
            'log_entry':          victim_log,
        },
        room=f'player_{target_player_id}',
    )

    # Broadcast updated leaderboard
    _emit_leaderboard(socketio, session_id)
    _emit_admin_summary_update(socketio, session_id)
