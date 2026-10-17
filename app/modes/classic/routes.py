# app/modes/classic/routes.py
#
# HTTP routes for Classic Mode.
#
# Two blueprints:
#   classic_admin_bp  — all admin management routes under /admin/classic/
#   classic_player_bp — player-facing pages under /classic/
#
# Admin flow:
#   GET  /admin/classic/new          → create session form
#   POST /admin/classic/new          → create session + round + config
#   GET  /admin/classic/<id>/manage  → manage live session
#   POST /admin/classic/<id>/start   → start the round (sets started_at)
#   POST /admin/classic/<id>/end     → end the round and session
#
# Player flow:
#   POST /classic/join/<id>  → explicit Hub Join endpoint; creates participation and freezes session-scoped snapshot state
#   GET  /classic/play       → routing entry path into the current Classic waiting/active flow; does not create participation
#   GET  /classic/lobby/<id> → participant-only waiting room (before round starts)
#   GET  /classic/game/<id>  → participant-only game screen (real-time via Socket.IO)

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from flask import (
    Blueprint, render_template, redirect, url_for, current_app,
    flash, request, abort, make_response, jsonify,
)
from flask_login import login_required, current_user

from app.extensions import db, socketio
from app.decorators import admin_required
from app.models.problems import ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import ClassicRoundConfig, PlayerWallet, PlayerClassicState, PlayerInventory, ProblemSolverCount, StoreItem, StealEvent
from app.models.groups import PlayerGroup
from app.models.history import RoundHistory, RoundPlayerResult, build_history_csv
from app.models.analytics import AnalyticsRound
from app.modes.classic.forms import ClassicSessionForm, StoreItemForm, NextRoundForm
from app.modes.classic import state
from app.modes.classic import store as classic_store
from app.modes.classic.history_snapshot import freeze_round_history
from app.modes.classic.admin_summary import (
    build_admin_supervision_summary_context,
    render_admin_supervision_summary_payload,
)
from app.services.progression import ensure_session_participant_snapshot, ensure_all_session_participant_snapshots
from app.services.avatar import build_player_avatar_view
from app.models.gear import PlayerGearLoadout
from app.services.overlay_layouts import build_overlay_asset_payload, load_overlay_layouts, save_overlay_layouts
from app.services.analytics import (
    ensure_analytics_round,
    ensure_player_round,
    finalize_classic_round,
    snapshot_classic_round_problem_set,
)

# Config fields that map 1:1 between NextRoundForm and ClassicRoundConfig.
# Used to pre-fill the next-round form and to build a new config from submitted data.
_ROUND_CONFIG_FIELDS = (
    'mine_reward', 'treasure_search_reward', 'attempts_per_problem',
    'wrong_answer_penalty', 'bonus_timer_duration', 'bonus_timer_gold',
    'first_solver_count', 'first_solver_multiplier',
    'treasure_search_max_reward', 'gem_milestone_count', 'gem_streak_count',
    'gem_treasure_chance', 'steal_percent', 'steal_min_cap', 'steal_max_cap',
    'steal_fallback_gold', 'steal_chest_count', 'steal_winning_chest_count',
    'active_shield_duration', 'reactive_shield_duration', 'treasure_steal_token_chance',
    'treasure_active_shield_chance', 'treasure_second_chance_chance',
)

classic_admin_bp = Blueprint('classic_admin', __name__, url_prefix='/admin/classic')
classic_player_bp = Blueprint('classic_player', __name__, url_prefix='/classic')

_CLASSIC_ROUND_BACKGROUND_FILENAMES = (
    'background_002a.png',
)


def player_in_session_group(player, session):
    """Returns True if the session is open (no group_id) or the player is a member."""
    if session.group_id is None:
        return True
    group = db.session.get(PlayerGroup, session.group_id)
    if group is None:
        return True  # group deleted — treat as open
    return group.members.filter_by(id=player.id).first() is not None


def _emit_hub_session_available(game_session):
    """Push a session_available event to Hub-connected players.

    If the session is restricted to a group, emit to hub_group_<id>.
    Otherwise emit to hub_open (all Hub-connected players).
    """
    payload = {
        'session_id': game_session.id,
        'label': game_session.display_label or '',
        'mode': 'classic',
    }
    if game_session.group_id:
        socketio.emit('session_available', payload,
                      room=f'hub_group_{game_session.group_id}')
    else:
        socketio.emit('session_available', payload, room='hub_open')


def _list_round_background_urls() -> list[str]:
    player_ui_dir = Path(current_app.static_folder) / 'classic_ui' / 'player_ui'
    filenames = [
        filename
        for filename in _CLASSIC_ROUND_BACKGROUND_FILENAMES
        if (player_ui_dir / filename).is_file()
    ]
    return [
        url_for('static', filename=f'classic_ui/player_ui/{filename}')
        for filename in filenames
    ]


def _select_round_background_url(*, session_id: int, game_round, background_urls: list[str]) -> str | None:
    if not background_urls or not game_round:
        return None
    round_id = int(getattr(game_round, 'id', 0) or 0)
    round_number = int(getattr(game_round, 'round_number', 0) or 0)
    seed = (int(session_id) * 131) + (round_id * 17) + (round_number * 19)
    return background_urls[seed % len(background_urls)]


# ─────────────────────────────────────────────────────────────────────────────
# Admin routes
# ─────────────────────────────────────────────────────────────────────────────

@classic_admin_bp.route('/')
@login_required
@admin_required
def index():
    """Entry point for Classic Mode nav link.

    Exactly-one-live-session cases (normal):
      0 live → redirect to new-session form
      1 live → redirect to its manage page

    Multiple-live-session case (legacy data / admin error):
      > 1 live → flash an explicit warning listing all IDs, then redirect to
                 the newest one (highest id).  Admin is expected to manually
                 end any stale sessions.  This branch cannot arise for new
                 data because new_session() now blocks concurrent creation.
    """
    live_sessions = (
        GameSession.query
        .filter(
            GameSession.mode == 'classic',
            GameSession.status.in_(['waiting', 'active'])
        )
        .order_by(GameSession.id.desc())
        .all()
    )
    if not live_sessions:
        return redirect(url_for('classic_admin.new_session'))
    if len(live_sessions) > 1:
        ids = ', '.join(f'#{s.id}' for s in live_sessions)
        flash(
            f'Warning: {len(live_sessions)} live Classic sessions found ({ids}). '
            'Only one should be active at a time. '
            'Opening the newest — please end any stale sessions.',
            'warning',
        )
    return redirect(url_for('classic_admin.manage', session_id=live_sessions[0].id))

@classic_admin_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_session():
    """Create a new Classic Mode session and its initial round config."""
    form = ClassicSessionForm()

    # Populate the problem set choices from the DB
    all_sets = ProblemSet.query.filter_by(usable_in_classic=True).order_by(ProblemSet.name).all()
    form.problem_set_id.choices = [(s.id, s.name) for s in all_sets]

    # Populate group restriction choices (0 = no restriction)
    form.group_id.choices = [(0, 'Open — no class restriction')] + [
        (g.id, g.name) for g in PlayerGroup.query.order_by(PlayerGroup.name).all()
    ]

    if not all_sets:
        flash('No problem sets exist yet. Create one in the Problem Bank first.', 'error')

    if form.validate_on_submit():
        # Guard: only one live Classic session at a time.
        live = GameSession.query.filter(
            GameSession.mode == 'classic',
            GameSession.status.in_(['waiting', 'active'])
        ).order_by(GameSession.id.asc()).first()
        if live:
            flash(
                f'Session #{live.id} is already live ({live.status}). '
                'End it before creating a new one.',
                'warning',
            )
            return redirect(url_for('classic_admin.manage', session_id=live.id))

        # 1. Create the GameSession
        game_session = GameSession(
            mode='classic',
            status='waiting',
            problem_set_id=form.problem_set_id.data,
            group_id=form.group_id.data if form.group_id.data != 0 else None,
            label=(form.label.data or '').strip() or None,
        )
        db.session.add(game_session)
        db.session.flush()  # get game_session.id without full commit

        # 2. Create the GameRound (not started yet — started_at is None)
        #    Classic rounds cover a whole problem set, so problem_id is None.
        game_round = GameRound(
            session_id=game_session.id,
            problem_id=None,
            round_number=1,
            started_at=None,   # will be set when admin presses Start
        )
        db.session.add(game_round)
        db.session.flush()

        # 3. Create the ClassicRoundConfig
        config = ClassicRoundConfig(
            round_id=game_round.id,
            mine_reward=form.mine_reward.data,
            treasure_search_reward=form.treasure_search_reward.data,
            attempts_per_problem=form.attempts_per_problem.data,
            wrong_answer_penalty=form.wrong_answer_penalty.data,
            bonus_timer_duration=form.bonus_timer_duration.data,
            bonus_timer_gold=form.bonus_timer_gold.data,
            first_solver_count=form.first_solver_count.data,
            first_solver_multiplier=form.first_solver_multiplier.data,
            treasure_search_max_reward=form.treasure_search_max_reward.data,
            gem_milestone_count=form.gem_milestone_count.data,
            gem_streak_count=form.gem_streak_count.data,
            gem_treasure_chance=form.gem_treasure_chance.data,
            steal_percent=form.steal_percent.data,
            steal_min_cap=form.steal_min_cap.data,
            steal_max_cap=form.steal_max_cap.data,
            steal_fallback_gold=form.steal_fallback_gold.data,
            steal_chest_count=form.steal_chest_count.data,
            steal_winning_chest_count=form.steal_winning_chest_count.data,
            active_shield_duration=form.active_shield_duration.data,
            reactive_shield_duration=form.reactive_shield_duration.data,
            treasure_steal_token_chance=form.treasure_steal_token_chance.data,
            treasure_active_shield_chance=form.treasure_active_shield_chance.data,
            treasure_second_chance_chance=form.treasure_second_chance_chance.data,
        )
        db.session.add(config)
        ensure_analytics_round(game_round, 'classic', config=config)
        snapshot_classic_round_problem_set(game_round)
        db.session.commit()

        # Notify Hub-connected players that a session is available.
        _emit_hub_session_available(game_session)

        flash(f'Classic session #{game_session.id} created. Players can use the Hub Join flow when you are ready, then you can press Start.', 'success')
        return redirect(url_for('classic_admin.manage', session_id=game_session.id))

    return render_template('admin/classic/new.html', form=form)


@classic_admin_bp.route('/<int:session_id>/manage')
@login_required
@admin_required
def manage(session_id):
    """Show the live management page for a Classic session."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    game_round = GameRound.query.filter_by(
        session_id=session_id
    ).order_by(GameRound.round_number.desc()).first()
    broken_active_ended = bool(
        game_session.status == 'active'
        and game_round
        and game_round.ended_at is not None
    )

    config = game_round.classic_config if game_round else None

    # Leaderboard: all wallets for this session, sorted by gold desc
    wallets = (
        PlayerWallet.query
        .filter_by(session_id=session_id)
        .order_by(PlayerWallet.gold.desc())
        .all()
    )
    wallet_bonus_counts = {
        wallet.player_id: classic_store.get_active_counts(wallet.player_id, session_id)
        for wallet in wallets
    }

    # Enrolled players
    enrolled = RoundPlayer.query.filter_by(session_id=session_id).all()

    summary_context = build_admin_supervision_summary_context(session_id)

    # Count frozen history rows so the template can show/hide the View History link
    history_count = RoundHistory.query.filter_by(session_id=session_id).count()

    # Populate next-round form problem set choices
    all_sets = ProblemSet.query.filter_by(usable_in_classic=True).order_by(ProblemSet.name).all()
    next_round_form = NextRoundForm(formdata=None)
    next_round_form.problem_set_id.choices = [(s.id, s.name) for s in all_sets]
    if game_session.problem_set_id:
        next_round_form.problem_set_id.data = game_session.problem_set_id

    # Pre-fill round config fields from the previous round so admin sees
    # current values and can keep or tweak them.
    if config:
        for f in _ROUND_CONFIG_FIELDS:
            getattr(next_round_form, f).data = getattr(config, f)

    return render_template(
        'admin/classic/manage.html',
        game_session=game_session,
        game_round=game_round,
        config=config,
        wallets=wallets,
        wallet_bonus_counts=wallet_bonus_counts,
        enrolled=enrolled,
        solve_counts=summary_context['solve_counts'],
        steal_events=summary_context['steal_events'],
        next_round_form=next_round_form,
        history_count=history_count,
        broken_active_ended=broken_active_ended,
    )


@classic_admin_bp.route('/layout-lab')
@login_required
@admin_required
def layout_lab():
    """Dev-only stage-event overlay layout tuning page."""
    return render_template(
        'admin/classic/layout_lab.html',
        overlay_layouts=load_overlay_layouts(),
        overlay_assets=build_overlay_asset_payload(),
    )


@classic_admin_bp.route('/layout-lab/save', methods=['POST'])
@login_required
@admin_required
def layout_lab_save():
    """Persist stage-event overlay layout changes to the shared app-side JSON source."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'ok': False, 'error': 'Layout payload must be a JSON object.'}), 400
    saved = save_overlay_layouts(payload)
    return jsonify({'ok': True, 'overlay_layouts': saved})


@classic_admin_bp.route('/<int:session_id>/repair_waiting', methods=['POST'])
@login_required
@admin_required
def repair_waiting(session_id):
    """Recover a session stuck in active+ended-round state.

    This is a narrow admin/dev recovery path for stale test sessions where the
    session status never flipped back to waiting after the latest round ended.
    """
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    game_round = (
        GameRound.query
        .filter_by(session_id=session_id)
        .order_by(GameRound.round_number.desc())
        .first()
    )
    if not game_round or game_round.ended_at is None or game_session.status != 'active':
        flash('Session is not in the recoverable active + ended-round state.', 'warning')
        return redirect(url_for('classic_admin.manage', session_id=session_id))

    game_session.status = 'waiting'
    db.session.commit()
    state.clear_session(session_id)

    room = f'classic_{session_id}'
    socketio.emit('return_to_lobby', {'session_id': session_id}, room=room)
    socketio.emit('admin_summary_update', render_admin_supervision_summary_payload(session_id), room=room)

    flash('Session recovered to waiting state. You can start the next round or end the session.', 'success')
    return redirect(url_for('classic_admin.manage', session_id=session_id))


@classic_admin_bp.route('/<int:session_id>/start', methods=['POST'])
@login_required
@admin_required
def start_round(session_id):
    """Start the round: set started_at, activate the session, init in-memory state."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    if game_session.status != 'waiting':
        flash('Session is not in waiting state.', 'error')
        return redirect(url_for('classic_admin.manage', session_id=session_id))

    game_round = GameRound.query.filter_by(
        session_id=session_id, ended_at=None
    ).order_by(GameRound.round_number.desc()).first()

    if not game_round:
        flash('No round found for this session.', 'error')
        return redirect(url_for('classic_admin.manage', session_id=session_id))

    now = datetime.now(timezone.utc)
    game_round.started_at = now
    game_session.status = 'active'
    game_session.started_at = now
    # Ensure session-scoped participant snapshots exist for all enrolled players.
    # join_session() creates each player's snapshot at join time; this is a
    # safety net covering players enrolled before the explicit-join boundary.
    ensure_all_session_participant_snapshots(session_id)
    ensure_analytics_round(game_round, 'classic', config=game_round.classic_config)
    snapshot_classic_round_problem_set(game_round)
    for round_player in RoundPlayer.query.filter_by(session_id=session_id).all():
        wallet = PlayerWallet.query.filter_by(player_id=round_player.player_id, session_id=session_id).first()
        ensure_player_round(game_round, round_player.player, 'classic', wallet=wallet)
    db.session.commit()

    # Initialise in-memory timer state
    state.init_session(session_id, now)

    # Broadcast to all players in the room
    room = f'classic_{session_id}'
    socketio.emit('round_started', {
        'session_id': session_id,
        'round_id': game_round.id,
        'round_number': game_round.round_number,
    }, room=room)
    socketio.emit('admin_summary_update', render_admin_supervision_summary_payload(session_id), room=room)

    flash('Round started.', 'success')
    return redirect(url_for('classic_admin.manage', session_id=session_id))


@classic_admin_bp.route('/<int:session_id>/end', methods=['POST'])
@login_required
@admin_required
def end_round(session_id):
    """End the current round.  Session returns to 'waiting' (between-rounds lobby).
    Players are redirected back to the lobby. Admin can then start a new round
    (with carry-over controls) or call end_session to close the session entirely."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    game_round = GameRound.query.filter_by(
        session_id=session_id, ended_at=None
    ).order_by(GameRound.round_number.desc()).first()

    now = datetime.now(timezone.utc)

    if game_round:
        game_round.ended_at = now
        # Snapshot history BEFORE commit so wallet gold/gems reflect round-end values.
        # This must come after ended_at is set but before any next-round carry resets.
        freeze_round_history(game_round, game_session, now)
        finalize_classic_round(game_round)

    # Return to between-rounds waiting state — do NOT close the session.
    game_session.status = 'waiting'
    db.session.commit()

    # Clear in-memory state (round timer, steal intents, streaks, etc.)
    state.clear_session(session_id)

    # Send players back to the lobby.
    room = f'classic_{session_id}'
    socketio.emit('return_to_lobby', {'session_id': session_id}, room=room)
    socketio.emit('admin_summary_update', render_admin_supervision_summary_payload(session_id), room=room)

    flash('Round ended. Set carry-over options and start the next round, or end the session.', 'success')
    return redirect(url_for('classic_admin.manage', session_id=session_id))


@classic_admin_bp.route('/<int:session_id>/end_session', methods=['POST'])
@login_required
@admin_required
def end_session(session_id):
    """Permanently close the session (status → finished).
    Call this after end_round when no further rounds will be played."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    now = datetime.now(timezone.utc)
    game_session.status = 'finished'
    game_session.ended_at = now
    db.session.commit()

    # clear_session is idempotent — safe even if already called from end_round
    state.clear_session(session_id)

    room = f'classic_{session_id}'
    socketio.emit('round_ended', {'session_id': session_id}, room=room)
    socketio.emit('admin_summary_update', render_admin_supervision_summary_payload(session_id), room=room)

    flash('Session ended.', 'success')
    # Redirect to the new-session form rather than index() so that stale
    # legacy live sessions (which index() would silently open) don't make
    # it look like end_session failed.
    return redirect(url_for('classic_admin.new_session'))


@classic_admin_bp.route('/<int:session_id>/next_round', methods=['POST'])
@login_required
@admin_required
def next_round(session_id):
    """Start the next round in the same session.

    The admin can edit all round-config values via the expanded NextRoundForm.
    Fields are pre-filled from the previous round (in manage) and the submitted
    values populate the new ClassicRoundConfig.

    carry_over_gold / carry_over_gems control whether player wallets are reset.
    Round starts immediately (started_at = now, session.status = 'active').
    """
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    if game_session.status != 'waiting':
        flash('Session must be in waiting state to start a new round.', 'error')
        return redirect(url_for('classic_admin.manage', session_id=session_id))

    # Most recent round — must exist and be ended
    last_round = GameRound.query.filter_by(
        session_id=session_id
    ).order_by(GameRound.round_number.desc()).first()

    if not last_round or not last_round.ended_at:
        flash('No completed round found for this session.', 'error')
        return redirect(url_for('classic_admin.manage', session_id=session_id))

    old_config = last_round.classic_config
    if not old_config:
        flash('Previous round has no config — cannot derive defaults.', 'error')
        return redirect(url_for('classic_admin.manage', session_id=session_id))

    # Bind form to POST data and validate
    form = NextRoundForm()
    all_sets = ProblemSet.query.filter_by(usable_in_classic=True).order_by(ProblemSet.name).all()
    form.problem_set_id.choices = [(s.id, s.name) for s in all_sets]
    for field_name in _ROUND_CONFIG_FIELDS:
        field = getattr(form, field_name)
        if field.raw_data in (None, []):
            field.data = getattr(old_config, field_name)
    if form.problem_set_id.raw_data in (None, []):
        form.problem_set_id.data = game_session.problem_set_id

    if not form.validate():
        for field_name, errors in form.errors.items():
            if field_name == 'csrf_token':
                continue
            label = getattr(form, field_name).label.text
            for err in errors:
                flash(f'{label}: {err}', 'error')
        return redirect(url_for('classic_admin.manage', session_id=session_id))

    # Carry-over controls
    carry_over_gold = 'carry_over_gold' in request.form
    carry_over_gems = 'carry_over_gems' in request.form

    # Optional problem set switch for the new round.
    new_ps_id = form.problem_set_id.data
    if new_ps_id and new_ps_id != game_session.problem_set_id:
        ps = db.session.get(ProblemSet, new_ps_id)
        if ps:
            game_session.problem_set_id = new_ps_id

    now = datetime.now(timezone.utc)

    # Apply carry-over resets BEFORE the round becomes active
    if not carry_over_gold or not carry_over_gems:
        for wallet in PlayerWallet.query.filter_by(session_id=session_id).all():
            if not carry_over_gold:
                wallet.gold = 0
            if not carry_over_gems:
                wallet.gems = 0

    # Create new GameRound
    new_round = GameRound(
        session_id=session_id,
        problem_id=None,
        round_number=last_round.round_number + 1,
        started_at=now,
    )
    db.session.add(new_round)
    db.session.flush()  # get new_round.id

    # Build ClassicRoundConfig from submitted form values
    new_config = ClassicRoundConfig(
        round_id=new_round.id,
        **{f: getattr(form, f).data for f in _ROUND_CONFIG_FIELDS}
    )
    db.session.add(new_config)
    ensure_analytics_round(new_round, 'classic', config=new_config)
    snapshot_classic_round_problem_set(new_round)

    # Ensure session-scoped participant snapshots exist for all enrolled players.
    ensure_all_session_participant_snapshots(session_id)
    game_session.status = 'active'
    game_session.started_at = now  # update to current round start time
    db.session.commit()

    # Initialise in-memory session state for the new round
    state.init_session(session_id, now)

    room = f'classic_{session_id}'
    socketio.emit('round_started', {
        'session_id': session_id,
        'round_id': new_round.id,
        'round_number': new_round.round_number,
    }, room=room)
    socketio.emit('admin_summary_update', render_admin_supervision_summary_payload(session_id), room=room)

    gold_msg = 'carried over' if carry_over_gold else 'reset to 0'
    gems_msg = 'carried over' if carry_over_gems else 'reset to 0'
    ps_name  = game_session.problem_set.name if game_session.problem_set else '?'
    flash(
        f'Round {new_round.round_number} started. '
        f'Problem set: {ps_name}. '
        f'Gold: {gold_msg}. Gems: {gems_msg}.',
        'success',
    )
    return redirect(url_for('classic_admin.manage', session_id=session_id))


@classic_admin_bp.route('/<int:session_id>/store', methods=['GET', 'POST'])
@login_required
@admin_required
def store(session_id):
    """List store items for this session and allow adding a new one."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    form = StoreItemForm()
    if form.validate_on_submit():
        item = StoreItem(
            session_id=session_id,
            name=form.name.data.strip(),
            description=(form.description.data or '').strip() or None,
            cost=form.cost.data,
            currency=form.currency.data,
            bonus_type=form.bonus_type.data,
            session_stock=form.session_stock.data,
            per_player_limit=form.per_player_limit.data,
        )
        db.session.add(item)
        db.session.commit()
        flash(f'Item "{item.name}" added.', 'success')
        return redirect(url_for('classic_admin.store', session_id=session_id))

    items = StoreItem.query.filter_by(session_id=session_id, is_system=False).order_by(StoreItem.cost).all()

    # D3: compute sold count per item for stock clarity display
    sold_counts = {}
    for item in items:
        sold_counts[item.id] = PlayerInventory.query.filter_by(item_id=item.id).count()

    return render_template(
        'admin/classic/store.html',
        game_session=game_session,
        items=items,
        sold_counts=sold_counts,
        form=form,
    )


@classic_admin_bp.route('/<int:session_id>/store/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def store_edit(session_id, item_id):
    """Edit an existing store item."""
    game_session = db.session.get(GameSession, session_id)
    item = db.session.get(StoreItem, item_id)
    if not game_session or game_session.mode != 'classic' or not item or item.session_id != session_id:
        abort(404)

    form = StoreItemForm(obj=item)
    if form.validate_on_submit():
        item.name        = form.name.data.strip()
        item.description = (form.description.data or '').strip() or None
        item.cost        = form.cost.data
        item.currency    = form.currency.data
        item.bonus_type  = form.bonus_type.data
        item.session_stock    = form.session_stock.data
        item.per_player_limit = form.per_player_limit.data
        db.session.commit()
        flash(f'Item "{item.name}" updated.', 'success')
        return redirect(url_for('classic_admin.store', session_id=session_id))

    return render_template(
        'admin/classic/store_edit.html',
        game_session=game_session,
        item=item,
        form=form,
    )


@classic_admin_bp.route('/<int:session_id>/store/<int:item_id>/delete', methods=['POST'])
@login_required
@admin_required
def store_delete(session_id, item_id):
    """Delete a store item (only if no purchases have been made for it)."""
    game_session = db.session.get(GameSession, session_id)
    item = db.session.get(StoreItem, item_id)
    if not game_session or game_session.mode != 'classic' or not item or item.session_id != session_id:
        abort(404)

    if item.inventory.count() > 0:
        flash('Cannot delete: players have already purchased this item.', 'error')
    else:
        db.session.delete(item)
        db.session.commit()
        flash(f'Item "{item.name}" deleted.', 'success')

    return redirect(url_for('classic_admin.store', session_id=session_id))


@classic_admin_bp.route('/<int:session_id>/push_store', methods=['POST'])
@login_required
@admin_required
def push_store(session_id):
    """Push the current store item list to all connected players in this session.

    Emits 'store_updated' to the player room containing the refreshed store payload.
    Admin presses this explicitly after editing store items during a live session.
    """
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    from app.modes.classic import store as classic_store
    store_items = classic_store.store_items_for(session_id)
    room = f'classic_{session_id}'
    socketio.emit('store_updated', {'store_items': store_items}, room=room)

    flash('Store pushed to connected players.', 'success')
    return redirect(url_for('classic_admin.store', session_id=session_id))


@classic_admin_bp.route('/<int:session_id>/history')
@login_required
@admin_required
def history(session_id):
    """Show frozen round-history for a Classic session (read-only).

    Archived records are hidden by default.
    Pass ?include_archived=1 to reveal them.
    """
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    include_archived = request.args.get('include_archived') == '1'

    # All frozen rounds for this session, in chronological order
    q = RoundHistory.query.filter_by(session_id=session_id)
    if not include_archived:
        q = q.filter(RoundHistory.archived_at.is_(None))
    rounds = q.order_by(RoundHistory.round_number).all()
    round_ids = [rh.round_id for rh in rounds]
    analytics_by_round_id = {}
    if round_ids:
        analytics_by_round_id = {
            row.round_id: row
            for row in AnalyticsRound.query
            .filter(AnalyticsRound.round_id.in_(round_ids))
            .all()
        }

    # Pre-load player results for each round, ordered by place then name snapshot
    # so the template can iterate without extra queries.
    results_by_round = {}
    for rh in rounds:
        results_by_round[rh.id] = (
            RoundPlayerResult.query
            .filter_by(round_history_id=rh.id)
            .order_by(RoundPlayerResult.final_place, RoundPlayerResult.player_name_snapshot)
            .all()
        )

    return render_template(
        'admin/classic/history.html',
        game_session=game_session,
        rounds=rounds,
        results_by_round=results_by_round,
        include_archived=include_archived,
        analytics_by_round_id=analytics_by_round_id,
    )


@classic_admin_bp.route('/<int:session_id>/history/export')
@login_required
@admin_required
def history_export(session_id):
    """Download frozen round history for one Classic session as a flat CSV.

    Visibility rules match the H1 history page:
    - default: archived rounds excluded
    - ?include_archived=1: archived rounds included
    """
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    include_archived = request.args.get('include_archived') == '1'
    q = RoundHistory.query.filter_by(session_id=session_id)
    if not include_archived:
        q = q.filter(RoundHistory.archived_at.is_(None))
    rounds = q.order_by(RoundHistory.round_number).all()

    csv_data = build_history_csv(rounds)
    filename = f'session_{session_id}_history.csv'
    response = make_response(csv_data)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Player routes
# ─────────────────────────────────────────────────────────────────────────────

@classic_player_bp.route('/join', methods=['POST'])
@login_required
def join_session():
    """Explicit first-time Join — the only place participation rows are created.

    Creates RoundPlayer, PlayerWallet, and PlayerClassicState atomically.
    For active rounds, also freezes the player's real upgrade modifiers now
    so late joiners get correct effects, not _DefaultModifiers baseline.

    Lobby, game routes, and the classic_join socket handler no longer create
    participation; they assume it already exists.
    """
    session_id = request.form.get('session_id', type=int)
    if not session_id:
        flash('Invalid session.', 'error')
        return redirect(url_for('player.dashboard'))

    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        flash('Session not found.', 'error')
        return redirect(url_for('player.dashboard'))

    if game_session.status == 'finished':
        flash('That session has already ended.', 'info')
        return redirect(url_for('player.dashboard'))

    if not player_in_session_group(current_user, game_session):
        flash('You are not eligible for this session.', 'danger')
        return redirect(url_for('player.dashboard'))

    # --- Participation transaction ---
    # All three participation rows are created here and nowhere else.

    # 1. RoundPlayer (session enrollment)
    rp = RoundPlayer.query.filter_by(
        session_id=session_id, player_id=current_user.id
    ).first()
    if not rp:
        rp = RoundPlayer(session_id=session_id, player_id=current_user.id)
        db.session.add(rp)
        db.session.flush()

    # 2. PlayerWallet (session gold/gems/steal_tokens)
    wallet = PlayerWallet.query.filter_by(
        player_id=current_user.id, session_id=session_id
    ).first()
    if not wallet:
        wallet = PlayerWallet(player_id=current_user.id, session_id=session_id, gold=0, gems=0)
        db.session.add(wallet)
        db.session.flush()

    # 3. PlayerClassicState (steal-shield state)
    pcs = PlayerClassicState.query.filter_by(
        player_id=current_user.id, session_id=session_id
    ).first()
    if not pcs:
        pcs = PlayerClassicState(player_id=current_user.id, session_id=session_id)
        db.session.add(pcs)
        db.session.flush()

    # 4. Freeze session-scoped participant snapshot for this player.
    #    This is the Step 4 runtime source of truth for upgrade-derived gameplay effects.
    #    Idempotent — safe to call even if the player re-submits the join form.
    ensure_session_participant_snapshot(session_id, current_user.id)
    game_round = GameRound.query.filter_by(
        session_id=session_id, ended_at=None
    ).order_by(GameRound.round_number.desc()).first()
    if game_round:
        ensure_player_round(game_round, current_user, 'classic', wallet=wallet)

    db.session.commit()

    # Route to the correct in-session page.
    if game_session.status == 'active':
        return redirect(url_for('classic_player.game', session_id=session_id))
    # status == 'waiting'
    return redirect(url_for('classic_player.lobby', session_id=session_id))


@classic_player_bp.route('/play')
@login_required
def play():
    """Unified player routing entry point.

    This path does not create participation. It only routes an already eligible
    player into the current Classic waiting/active session flow.
    """
    active = GameSession.query.filter(
        GameSession.mode == 'classic',
        GameSession.status.in_(['waiting', 'active'])
    ).order_by(GameSession.id.desc()).first()

    if not active:
        flash('No active session right now. Ask your teacher when the next round starts.', 'info')
        return redirect(url_for('player.dashboard'))

    if not player_in_session_group(current_user, active):
        flash('You are not enrolled in the group for this session.', 'danger')
        return redirect(url_for('player.dashboard'))

    if active.status == 'active':
        return redirect(url_for('classic_player.game', session_id=active.id))
    return redirect(url_for('classic_player.lobby', session_id=active.id))


@classic_player_bp.route('/lobby/<int:session_id>')
@login_required
def lobby(session_id):
    """Player waiting room — shown before the round starts."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    # Deny unauthorized users before any status-based redirect.
    if not player_in_session_group(current_user, game_session):
        flash('You are not enrolled in the group for this session.', 'danger')
        return redirect(url_for('player.dashboard'))

    # Round already finished — show final results.
    if game_session.status == 'finished':
        return redirect(url_for('classic_player.round_over', session_id=session_id))

    # If the round is already active, skip the lobby entirely.
    if game_session.status == 'active':
        return redirect(url_for('classic_player.game', session_id=session_id))

    # Enrollment guard — player must have joined explicitly via POST /classic/join.
    # Lobby is a participant-only waiting room; it no longer implicitly enrolls.
    existing_rp = RoundPlayer.query.filter_by(
        session_id=session_id, player_id=current_user.id
    ).first()
    if not existing_rp:
        flash('Join the session from your Hub first.', 'info')
        return redirect(url_for('player.dashboard'))

    enrolled = RoundPlayer.query.filter_by(session_id=session_id).all()
    return render_template(
        'player/classic/lobby.html',
        game_session=game_session,
        enrolled=enrolled,
    )


@classic_player_bp.route('/game/<int:session_id>')
@login_required
def game(session_id):
    """Player game screen — initial shell loaded once; Socket.IO handles live updates."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    game_round = (
        GameRound.query
        .filter_by(session_id=session_id, ended_at=None)
        .order_by(GameRound.round_number.desc())
        .first()
    )

    # Deny unauthorized users before any status-based redirect.
    if not player_in_session_group(current_user, game_session):
        flash('You are not enrolled in the group for this session.', 'danger')
        return redirect(url_for('player.dashboard'))

    # Round hasn't started yet — keep player in the waiting room.
    if game_session.status == 'waiting':
        return redirect(url_for('classic_player.lobby', session_id=session_id))

    # Round is over — show final results.
    if game_session.status == 'finished':
        return redirect(url_for('classic_player.round_over', session_id=session_id))

    loadout = PlayerGearLoadout.query.filter_by(player_id=current_user.id).first()
    if loadout is None:
        loadout = SimpleNamespace(
            head_item_id=None,
            chest_item_id=None,
            boots_item_id=None,
            main_hand_item_id=None,
            off_hand_item_id=None,
            pocket1_item_id=None,
            pocket2_item_id=None,
        )

    round_background_urls = _list_round_background_urls()

    return render_template(
        'player/classic/game.html',
        game_session=game_session,
        player=current_user,
        round_config=(game_round.classic_config if game_round else None),
        game_round=game_round,
        gear_avatar=build_player_avatar_view(current_user, loadout),
        overlay_layouts=load_overlay_layouts(),
        overlay_assets=build_overlay_asset_payload(),
        round_background_urls=round_background_urls,
        current_round_background_url=_select_round_background_url(
            session_id=session_id,
            game_round=game_round,
            background_urls=round_background_urls,
        ),
    )


@classic_player_bp.route('/round_over/<int:session_id>')
@login_required
def round_over(session_id):
    """Final results page shown after the round ends."""
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != 'classic':
        abort(404)

    # If the round isn't finished yet, route correctly.
    if game_session.status == 'waiting':
        return redirect(url_for('classic_player.lobby', session_id=session_id))
    if game_session.status == 'active':
        return redirect(url_for('classic_player.game', session_id=session_id))

    wallets = (
        PlayerWallet.query
        .filter_by(session_id=session_id)
        .order_by(PlayerWallet.gold.desc())
        .all()
    )
    return render_template(
        'player/classic/round_over.html',
        game_session=game_session,
        wallets=wallets,
    )
