# app/modes/boss_rush/routes.py
#
# Phase 1 HTTP shell for Boss Rush. Admin can create/manage/start/end a
# Boss Rush session; players can join a placeholder lobby/game route. Live
# answer submission, boss damage, recovery, and reward finalization are deferred.

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.decorators import admin_required
from app.extensions import db, socketio
from app.models.boss_rush import (
    BOSS_RUSH_ATTEMPT_ATTACK,
    BOSS_RUSH_ATTEMPT_RECOVERY,
    BOSS_RUSH_STATUS_ACTIVE,
    BOSS_RUSH_STATUS_ENDED,
    BOSS_RUSH_STATUS_WAITING,
    BossRushBattleState,
    BossRushPlayerState,
    BossRushRoundConfig,
)
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.groups import PlayerGroup
from app.models.problems import ProblemSet
from app.modes.boss_rush.engine import (
    BOSS_RUSH_MODE,
    BOSS_ABILITY_CATALOG,
    boss_catalog_entry,
    build_admin_state_payload,
    build_live_state_payload,
    build_player_state_payload,
    finalize_boss_rush_rewards,
    get_final_reward_snapshot,
    get_reward_entry_for_player,
    get_current_problem,
    initialize_battle_state,
    initialize_player_state,
    process_due_ability,
    schedule_next_ability,
    submit_current_answer,
)
from app.modes.boss_rush.events import emit_boss_rush_state
from app.modes.boss_rush.forms import BossRushSessionForm
from app.services.problem_content import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    build_problem_body_view,
    build_problem_choice_view,
)
from app.services.progression import ensure_session_participant_snapshot
from app.services.analytics import (
    finalize_boss_rush_round,
    snapshot_boss_rush_round_problem_sets,
)


boss_rush_admin_bp = Blueprint('boss_rush_admin', __name__, url_prefix='/admin/boss-rush')
boss_rush_player_bp = Blueprint('boss_rush_player', __name__, url_prefix='/boss-rush')


_BOSS_RUSH_CONFIG_COPY_FIELDS = (
    'boss_type',
    'boss_name',
    'boss_image_path',
    'boss_max_hp',
    'player_max_hp',
    'attack_problem_set_id',
    'recovery_problem_set_id',
    'first_place_diamonds',
    'second_place_diamonds',
    'third_place_diamonds',
    'other_participant_diamonds',
    'highest_combo_diamonds',
    'combo_bonus_threshold',
    'combo_bonus_damage',
    'ability_enabled',
    'ability_interval_seconds',
    'fire_burn_damage',
    'fire_shield_max_stacks',
    'swamp_regen_amount',
    'stone_guard_combo_required',
    'time_drain_damage',
)


def _player_in_session_group(player, session):
    if session.group_id is None:
        return True
    group = db.session.get(PlayerGroup, session.group_id)
    if group is None:
        return True
    return group.members.filter_by(id=player.id).first() is not None


def _latest_round(session_id):
    return (
        GameRound.query
        .filter_by(session_id=session_id)
        .order_by(GameRound.round_number.desc())
        .first()
    )


def _emit_hub_session_available(game_session):
    payload = {
        'session_id': game_session.id,
        'label': game_session.display_label or '',
        'mode': BOSS_RUSH_MODE,
    }
    if game_session.group_id:
        socketio.emit('session_available', payload, room=f'hub_group_{game_session.group_id}')
    else:
        socketio.emit('session_available', payload, room='hub_open')


def _populate_session_form_choices(form):
    attack_sets = (
        ProblemSet.query
        .filter_by(usable_in_boss_rush=True)
        .order_by(ProblemSet.name)
        .all()
    )
    recovery_sets = (
        ProblemSet.query
        .filter_by(usable_as_recovery=True)
        .order_by(ProblemSet.name)
        .all()
    )
    form.attack_problem_set_id.choices = [(s.id, s.name) for s in attack_sets]
    form.recovery_problem_set_id.choices = [(s.id, s.name) for s in recovery_sets]
    form.group_id.choices = [(0, 'Open - no class restriction')] + [
        (g.id, g.name) for g in PlayerGroup.query.order_by(PlayerGroup.name).all()
    ]
    return attack_sets, recovery_sets


def _flash_form_errors(form):
    for field_name, errors in form.errors.items():
        if field_name == 'csrf_token':
            continue
        label = getattr(form, field_name).label.text
        for err in errors:
            flash(f'{label}: {err}', 'error')


def _boss_ability_ui_payload():
    field_groups = {
        'fire_giant': ['fire_burn_damage', 'fire_shield_max_stacks'],
        'stone_golem': ['stone_guard_combo_required'],
        'swamp_monster': ['swamp_regen_amount'],
        'time_wraith': ['time_drain_damage'],
        'air_elemental': [],
        'mirror_phantom': [],
    }
    return {
        boss_type: {
            'name': entry['name'],
            'summary': entry['summary'],
            'fields': field_groups.get(boss_type, []),
        }
        for boss_type, entry in BOSS_ABILITY_CATALOG.items()
    }


def _prefill_boss_rush_form_from_config(form, config, game_session=None):
    for field in _BOSS_RUSH_CONFIG_COPY_FIELDS:
        if hasattr(form, field):
            getattr(form, field).data = getattr(config, field)
    if game_session is not None:
        form.group_id.data = game_session.group_id or 0
        form.label.data = game_session.label or ''


def _build_boss_rush_config_from_form(form, *, round_id):
    boss_entry = boss_catalog_entry(form.boss_type.data)
    return BossRushRoundConfig(
        round_id=round_id,
        boss_type=form.boss_type.data,
        boss_name=boss_entry['label'],
        boss_image_path=boss_entry['image_path'],
        boss_max_hp=form.boss_max_hp.data,
        player_max_hp=form.player_max_hp.data,
        attack_problem_set_id=form.attack_problem_set_id.data,
        recovery_problem_set_id=form.recovery_problem_set_id.data,
        first_place_diamonds=form.first_place_diamonds.data,
        second_place_diamonds=form.second_place_diamonds.data,
        third_place_diamonds=form.third_place_diamonds.data,
        other_participant_diamonds=form.other_participant_diamonds.data,
        highest_combo_diamonds=form.highest_combo_diamonds.data,
        combo_bonus_threshold=form.combo_bonus_threshold.data,
        combo_bonus_damage=form.combo_bonus_damage.data,
        ability_enabled=form.ability_enabled.data,
        ability_interval_seconds=form.ability_interval_seconds.data,
        fire_burn_damage=form.fire_burn_damage.data,
        fire_shield_max_stacks=form.fire_shield_max_stacks.data,
        swamp_regen_amount=form.swamp_regen_amount.data,
        stone_guard_combo_required=form.stone_guard_combo_required.data,
        time_drain_damage=form.time_drain_damage.data,
    )


def _emit_live_state(session_id):
    return emit_boss_rush_state(socketio, session_id)


def _boss_rush_answer_feedback(result):
    if not result.get('ok'):
        return result.get('message') or 'No answer was submitted.', 'error'

    attempt_type = result.get('attempt_type')
    if attempt_type == BOSS_RUSH_ATTEMPT_RECOVERY:
        if result.get('is_correct'):
            return 'Recovered! HP restored to 1.', 'success'
        return 'Not quite. Your combo reset.', 'error'

    if not result.get('is_correct'):
        return 'Not quite. Your combo reset.', 'error'

    damage = int(result.get('damage_dealt') or 0)
    if damage > 0:
        if result.get('boss_defeated_after'):
            return f'Correct. You dealt {damage} damage and defeated the boss!', 'success'
        return f'Correct. You dealt {damage} damage.', 'success'

    if result.get('no_damage_reason') == 'stone_guard':
        return 'Correct - combo increased, but Stone Guard blocked the damage.', 'success'
    if result.get('boss_already_defeated') or int(result.get('boss_hp_before') or 0) <= 0:
        return 'Correct. The boss is already defeated.', 'success'
    return 'Correct - combo increased, but no damage was dealt.', 'success'


def _ensure_player_state(session, game_round, config):
    round_player = RoundPlayer.query.filter_by(
        session_id=session.id,
        player_id=current_user.id,
    ).first()
    if round_player is None:
        db.session.add(RoundPlayer(session_id=session.id, player_id=current_user.id))

    ensure_session_participant_snapshot(session.id, current_user.id)

    return initialize_player_state(game_round, current_user.id, config)


@boss_rush_admin_bp.route('/')
@login_required
@admin_required
def index():
    live_sessions = (
        GameSession.query
        .filter(
            GameSession.mode == BOSS_RUSH_MODE,
            GameSession.status.in_(['waiting', 'active']),
        )
        .order_by(GameSession.id.desc())
        .all()
    )
    if live_sessions:
        if len(live_sessions) > 1:
            ids = ', '.join(f'#{s.id}' for s in live_sessions)
            flash(
                f'Warning: {len(live_sessions)} live Boss Rush sessions found ({ids}). '
                'Only one should be active at a time. Opening the newest.',
                'warning',
            )
        return redirect(url_for('boss_rush_admin.manage', session_id=live_sessions[0].id))

    recent_sessions = (
        GameSession.query
        .filter(GameSession.mode == BOSS_RUSH_MODE)
        .order_by(GameSession.id.desc())
        .limit(12)
        .all()
    )
    return render_template(
        'admin/boss_rush/index.html',
        live_sessions=live_sessions,
        recent_sessions=recent_sessions,
    )


@boss_rush_admin_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_session():
    form = BossRushSessionForm()
    attack_sets, recovery_sets = _populate_session_form_choices(form)

    if not attack_sets:
        flash('No Boss Rush attack problem sets exist yet. Mark a problem set as Boss Rush attack in Problem Sets.', 'error')
    if not recovery_sets:
        flash('No Recovery problem sets exist yet. Mark a problem set as Boss Rush recovery in Problem Sets.', 'error')

    if form.validate_on_submit():
        live = (
            GameSession.query
            .filter(
                GameSession.mode == BOSS_RUSH_MODE,
                GameSession.status.in_(['waiting', 'active']),
            )
            .order_by(GameSession.id.asc())
            .first()
        )
        if live:
            flash(f'Boss Rush session #{live.id} is already live ({live.status}). End it before creating another.', 'warning')
            return redirect(url_for('boss_rush_admin.manage', session_id=live.id))

        game_session = GameSession(
            mode=BOSS_RUSH_MODE,
            status='waiting',
            problem_set_id=form.attack_problem_set_id.data,
            group_id=form.group_id.data if form.group_id.data != 0 else None,
            label=(form.label.data or '').strip() or None,
        )
        db.session.add(game_session)
        db.session.flush()

        game_round = GameRound(
            session_id=game_session.id,
            problem_id=None,
            round_number=1,
            started_at=None,
        )
        db.session.add(game_round)
        db.session.flush()

        config = _build_boss_rush_config_from_form(form, round_id=game_round.id)
        battle_state = BossRushBattleState(
            round_id=game_round.id,
            current_boss_hp=form.boss_max_hp.data,
            status=BOSS_RUSH_STATUS_WAITING,
        )
        db.session.add_all([config, battle_state])
        snapshot_boss_rush_round_problem_sets(game_round, config)
        db.session.commit()
        _emit_hub_session_available(game_session)

        flash(f'Boss Rush session #{game_session.id} created. Battle mechanics are still deferred for Phase 2.', 'success')
        return redirect(url_for('boss_rush_admin.manage', session_id=game_session.id))

    return render_template(
        'admin/boss_rush/new.html',
        form=form,
        form_action=url_for('boss_rush_admin.new_session'),
        page_title='New Boss Rush',
        page_eyebrow='Launch',
        page_description='Create the Boss Rush setup shell: boss, class scope, attack/recovery problem sets, and reward defaults.',
        submit_title='Create Shell',
        submit_button_label='Create Boss Rush',
        submit_description='This creates the session, round config, and boss state rows.',
        ability_ui=_boss_ability_ui_payload(),
    )


@boss_rush_admin_bp.route('/<int:session_id>/manage')
@login_required
@admin_required
def manage(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    game_round = _latest_round(session_id)
    config = game_round.boss_rush_config if game_round else None
    battle_state = initialize_battle_state(game_round, config) if game_round and config else None
    if game_round and config and battle_state:
        ability_result = process_due_ability(game_round, config, battle_state)
        if ability_result.get('triggered'):
            db.session.commit()
            _emit_live_state(session_id)
    admin_state = build_admin_state_payload(game_round, config, battle_state) if game_round and config and battle_state else None
    reward_snapshot = None
    if game_round and config and battle_state and battle_state.is_defeated:
        reward_snapshot = battle_state.final_rewards_json or get_final_reward_snapshot(game_round, config)
    live_state_payload = build_live_state_payload(game_session, game_round, config, battle_state) if game_round and config and battle_state else None
    return render_template(
        'admin/boss_rush/manage.html',
        game_session=game_session,
        game_round=game_round,
        config=config,
        battle_state=battle_state,
        player_states=admin_state['players'] if admin_state else [],
        admin_state=admin_state,
        reward_snapshot=reward_snapshot,
        live_state_payload=live_state_payload,
    )


@boss_rush_admin_bp.route('/<int:session_id>/start', methods=['POST'])
@login_required
@admin_required
def start_round(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    if game_session.status != 'waiting':
        flash('Boss Rush session is not in waiting state.', 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))
    game_round = _latest_round(session_id)
    if not game_round or not game_round.boss_rush_config or not game_round.boss_rush_battle_state:
        flash('Boss Rush round is missing its Phase 1 config/state rows.', 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))
    if game_round.ended_at:
        flash('The latest Boss Rush round is already ended. Start the next round instead.', 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))
    if not game_round.started_at:
        now = datetime.now(timezone.utc)
        game_round.started_at = now
        game_session.started_at = game_session.started_at or now
    else:
        now = datetime.now(timezone.utc)
    game_session.status = 'active'
    initialize_battle_state(game_round, game_round.boss_rush_config)
    game_round.boss_rush_battle_state.status = BOSS_RUSH_STATUS_ACTIVE
    schedule_next_ability(game_round.boss_rush_battle_state, game_round.boss_rush_config, now=now)
    snapshot_boss_rush_round_problem_sets(game_round, game_round.boss_rush_config)
    db.session.commit()
    _emit_live_state(session_id)
    flash('Boss Rush battle started.', 'success')
    return redirect(url_for('boss_rush_admin.manage', session_id=session_id))


@boss_rush_admin_bp.route('/<int:session_id>/end', methods=['POST'])
@login_required
@admin_required
def end_round(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    game_round = _latest_round(session_id)
    now = datetime.now(timezone.utc)
    if game_round and not game_round.ended_at:
        game_round.ended_at = now
    if game_round and game_round.boss_rush_battle_state:
        game_round.boss_rush_battle_state.status = BOSS_RUSH_STATUS_ENDED
        game_round.boss_rush_battle_state.next_ability_at = None
    if game_round:
        finalize_boss_rush_round(game_round)
    game_session.status = 'waiting'
    db.session.commit()
    _emit_live_state(session_id)
    flash('Boss Rush round ended. Players returned to the lobby. Start the next round or end the session.', 'success')
    return redirect(url_for('boss_rush_admin.manage', session_id=session_id))


@boss_rush_admin_bp.route('/<int:session_id>/ability/<string:action>', methods=['POST'])
@login_required
@admin_required
def toggle_ability_freeze(session_id, action):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    game_round = _latest_round(session_id)
    if not game_round or not game_round.boss_rush_config or not game_round.boss_rush_battle_state:
        flash('Boss Rush round is missing ability state.', 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))
    battle_state = game_round.boss_rush_battle_state
    config = game_round.boss_rush_config
    if battle_state.status != BOSS_RUSH_STATUS_ACTIVE or game_session.status != 'active':
        flash('Ability control is available only during an active Boss Rush round.', 'warning')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))
    if action == 'freeze':
        battle_state.ability_frozen = True
        battle_state.next_ability_at = None
        battle_state.last_ability_summary_json = {
            'boss_type': config.boss_type,
            'ability_name': BOSS_ABILITY_CATALOG.get(config.boss_type, {}).get('name', 'Boss Ability'),
            'message': 'Ability frozen.',
            'affected_count': 0,
            'immune_count': 0,
            'triggered_at': datetime.now(timezone.utc).isoformat(),
            'problem_refresh_player_ids': [],
        }
        flash('Boss ability frozen.', 'success')
    elif action == 'resume':
        battle_state.ability_frozen = False
        schedule_next_ability(battle_state, config, now=datetime.now(timezone.utc))
        battle_state.last_ability_summary_json = {
            'boss_type': config.boss_type,
            'ability_name': BOSS_ABILITY_CATALOG.get(config.boss_type, {}).get('name', 'Boss Ability'),
            'message': 'Ability resumed.',
            'affected_count': 0,
            'immune_count': 0,
            'triggered_at': datetime.now(timezone.utc).isoformat(),
            'problem_refresh_player_ids': [],
        }
        flash('Boss ability resumed.', 'success')
    else:
        abort(404)
    db.session.commit()
    _emit_live_state(session_id)
    return redirect(url_for('boss_rush_admin.manage', session_id=session_id))


@boss_rush_admin_bp.route('/<int:session_id>/next_round', methods=['GET', 'POST'])
@login_required
@admin_required
def next_round(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    if game_session.status != 'waiting':
        flash('Session must be waiting to start the next Boss Rush round.', 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))

    last_round = _latest_round(session_id)
    if not last_round or not last_round.ended_at or not last_round.boss_rush_config:
        flash('No completed Boss Rush round found to configure from.', 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))

    old_config = last_round.boss_rush_config
    form = BossRushSessionForm()
    attack_sets, recovery_sets = _populate_session_form_choices(form)

    if request.method == 'GET':
        _prefill_boss_rush_form_from_config(form, old_config, game_session)
        form.submit.label.text = 'Start Configured Boss Rush Round'
        return render_template(
            'admin/boss_rush/new.html',
            form=form,
            form_action=url_for('boss_rush_admin.next_round', session_id=session_id),
            page_title=f'Configure Boss Rush Round {last_round.round_number + 1}',
            page_eyebrow='Between Rounds',
            page_description='Tune the next Boss Rush round in this same session before starting it.',
            submit_title='Start Next Round',
            submit_button_label='Start Configured Boss Rush Round',
            submit_description='This creates a new Boss Rush round in the current session with the settings shown here.',
            ability_ui=_boss_ability_ui_payload(),
            game_session=game_session,
            previous_round=last_round,
        )

    if not attack_sets:
        flash('No Boss Rush attack problem sets exist yet. Mark a problem set as Boss Rush attack in Problem Sets.', 'error')
    if not recovery_sets:
        flash('No Recovery problem sets exist yet. Mark a problem set as Boss Rush recovery in Problem Sets.', 'error')

    if not form.validate():
        _flash_form_errors(form)
        return redirect(url_for('boss_rush_admin.next_round', session_id=session_id))

    now = datetime.now(timezone.utc)
    new_round = GameRound(
        session_id=session_id,
        problem_id=None,
        round_number=last_round.round_number + 1,
        started_at=now,
    )
    db.session.add(new_round)
    db.session.flush()

    new_config = _build_boss_rush_config_from_form(form, round_id=new_round.id)
    new_battle_state = BossRushBattleState(
        round_id=new_round.id,
        current_boss_hp=new_config.boss_max_hp,
        status=BOSS_RUSH_STATUS_ACTIVE,
    )
    db.session.add_all([new_config, new_battle_state])
    db.session.flush()
    schedule_next_ability(new_battle_state, new_config, now=now)
    game_session.problem_set_id = new_config.attack_problem_set_id
    game_session.group_id = form.group_id.data if form.group_id.data != 0 else None
    game_session.label = (form.label.data or '').strip() or None
    game_session.status = 'active'
    game_session.started_at = now
    snapshot_boss_rush_round_problem_sets(new_round, new_config)
    db.session.commit()
    _emit_live_state(session_id)
    flash(f'Boss Rush round {new_round.round_number} started with the configured settings.', 'success')
    return redirect(url_for('boss_rush_admin.manage', session_id=session_id))


@boss_rush_admin_bp.route('/<int:session_id>/end_session', methods=['POST'])
@login_required
@admin_required
def end_session(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    now = datetime.now(timezone.utc)
    game_round = _latest_round(session_id)
    if game_round and not game_round.ended_at:
        game_round.ended_at = now
    if game_round and game_round.boss_rush_battle_state and not game_round.boss_rush_battle_state.is_defeated:
        game_round.boss_rush_battle_state.status = BOSS_RUSH_STATUS_ENDED
        game_round.boss_rush_battle_state.next_ability_at = None
    if game_round:
        finalize_boss_rush_round(game_round)
    game_session.status = 'finished'
    game_session.ended_at = now
    db.session.commit()
    _emit_live_state(session_id)
    flash('Boss Rush session ended.', 'success')
    return redirect(url_for('boss_rush_admin.index'))


@boss_rush_admin_bp.route('/<int:session_id>/finalize', methods=['POST'])
@login_required
@admin_required
def finalize_rewards(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    game_round = _latest_round(session_id)
    config = game_round.boss_rush_config if game_round else None
    battle_state = game_round.boss_rush_battle_state if game_round else None
    if not game_round or not config or not battle_state:
        flash('Boss Rush setup is incomplete.', 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))
    try:
        result = finalize_boss_rush_rewards(
            game_session,
            game_round,
            config,
            battle_state,
            admin_player_id=current_user.id,
        )
        if game_session.status != 'finished':
            now = datetime.now(timezone.utc)
            game_session.status = 'finished'
            game_session.ended_at = game_session.ended_at or now
            game_round.ended_at = game_round.ended_at or now
        finalize_boss_rush_round(game_round, reward_snapshot=result.get('snapshot'))
        db.session.commit()
        _emit_live_state(session_id)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('boss_rush_admin.manage', session_id=session_id))

    if result['already_finalized']:
        flash('Boss Rush rewards were already finalized. No duplicate Diamonds were awarded.', 'info')
    else:
        flash('Boss Rush rewards finalized and Diamonds awarded.', 'success')
    return redirect(url_for('boss_rush_admin.manage', session_id=session_id))


@boss_rush_player_bp.route('/play')
@login_required
def play_entry():
    live_sessions = (
        GameSession.query
        .filter(
            GameSession.mode == BOSS_RUSH_MODE,
            GameSession.status.in_(['waiting', 'active']),
        )
        .order_by(GameSession.id.desc())
        .all()
    )
    for session in live_sessions:
        if _player_in_session_group(current_user, session):
            participant = RoundPlayer.query.filter_by(
                session_id=session.id,
                player_id=current_user.id,
            ).first()
            if participant:
                target = 'boss_rush_player.game' if session.status == 'active' else 'boss_rush_player.lobby'
                return redirect(url_for(target, session_id=session.id))
            flash('A Boss Rush session is available. Use the Hub or direct join control once enabled.', 'info')
            return redirect(url_for('player.dashboard'))
    flash('No Boss Rush session is available right now.', 'info')
    return redirect(url_for('player.dashboard'))


@boss_rush_player_bp.route('/join/<int:session_id>', methods=['POST'])
@login_required
def join(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    if game_session.status not in ('waiting', 'active'):
        flash('That Boss Rush session is not joinable.', 'error')
        return redirect(url_for('player.dashboard'))
    if not _player_in_session_group(current_user, game_session):
        flash('This Boss Rush session is restricted to another class.', 'error')
        return redirect(url_for('player.dashboard'))

    game_round = _latest_round(session_id)
    config = game_round.boss_rush_config if game_round else None
    if not game_round or not config:
        flash('Boss Rush setup is incomplete.', 'error')
        return redirect(url_for('player.dashboard'))
    _ensure_player_state(game_session, game_round, config)
    db.session.commit()
    _emit_live_state(session_id)

    target = 'boss_rush_player.game' if game_session.status == 'active' else 'boss_rush_player.lobby'
    return redirect(url_for(target, session_id=session_id))


@boss_rush_player_bp.route('/join', methods=['POST'])
@login_required
def join_entry():
    session_id = request.form.get('session_id', type=int)
    if not session_id:
        flash('Invalid session.', 'error')
        return redirect(url_for('player.dashboard'))
    return join(session_id)


@boss_rush_player_bp.route('/lobby/<int:session_id>')
@login_required
def lobby(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    if not RoundPlayer.query.filter_by(session_id=session_id, player_id=current_user.id).first():
        flash('Join the Boss Rush session before entering the lobby.', 'error')
        return redirect(url_for('player.dashboard'))
    if game_session.status == 'active':
        return redirect(url_for('boss_rush_player.game', session_id=session_id))
    game_round = _latest_round(session_id)
    return render_template('player/boss_rush/lobby.html', game_session=game_session, game_round=game_round)


@boss_rush_player_bp.route('/game/<int:session_id>')
@login_required
def game(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    if not RoundPlayer.query.filter_by(session_id=session_id, player_id=current_user.id).first():
        flash('Join the Boss Rush session before entering the game.', 'error')
        return redirect(url_for('player.dashboard'))
    if game_session.status in ('waiting', 'finished'):
        return redirect(url_for('boss_rush_player.lobby', session_id=session_id))
    game_round = _latest_round(session_id)
    config = game_round.boss_rush_config if game_round else None
    if not game_round or not config:
        flash('Boss Rush setup is incomplete.', 'error')
        return redirect(url_for('player.dashboard'))
    battle_state = initialize_battle_state(game_round, config)
    player_state = initialize_player_state(game_round, current_user.id, config)
    ability_result = process_due_ability(game_round, config, battle_state)
    current_problem = get_current_problem(player_state, config, battle_state) if game_session.status == 'active' else None
    db.session.commit()
    if ability_result.get('triggered'):
        _emit_live_state(session_id)
    body_view = build_problem_body_view(current_problem) if current_problem else None
    choice_view = build_problem_choice_view(current_problem) if current_problem else None
    player_state_payload = build_player_state_payload(player_state, config, battle_state, current_problem)
    reward_entry = get_reward_entry_for_player(battle_state, current_user.id) if battle_state.rewards_finalized_at else None
    live_state_payload = build_live_state_payload(game_session, game_round, config, battle_state)
    return render_template(
        'player/boss_rush/game.html',
        game_session=game_session,
        game_round=game_round,
        config=config,
        battle_state=battle_state,
        player_state=player_state,
        player_state_payload=player_state_payload,
        current_problem=current_problem,
        body_view=body_view,
        choice_view=choice_view,
        multiple_choice_answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
        reward_entry=reward_entry,
        live_state_payload=live_state_payload,
    )


@boss_rush_player_bp.route('/game/<int:session_id>/answer', methods=['POST'])
@login_required
def submit_answer(session_id):
    game_session = db.session.get(GameSession, session_id)
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        abort(404)
    if game_session.status != 'active':
        flash('Boss Rush is not active yet.', 'error')
        if game_session.status in ('waiting', 'finished'):
            return redirect(url_for('boss_rush_player.lobby', session_id=session_id))
        return redirect(url_for('player.dashboard'))
    if not RoundPlayer.query.filter_by(session_id=session_id, player_id=current_user.id).first():
        flash('Join the Boss Rush session before answering.', 'error')
        return redirect(url_for('player.dashboard'))

    game_round = _latest_round(session_id)
    config = game_round.boss_rush_config if game_round else None
    if not game_round or not config:
        flash('Boss Rush setup is incomplete.', 'error')
        return redirect(url_for('player.dashboard'))
    if game_round.ended_at:
        flash('That Boss Rush round has ended.', 'info')
        return redirect(url_for('boss_rush_player.lobby', session_id=session_id))
    battle_state = initialize_battle_state(game_round, config)
    player_state = initialize_player_state(game_round, current_user.id, config)
    selected_option_id = request.form.get('selected_option_id', type=int)
    result = submit_current_answer(
        player_state,
        config,
        battle_state,
        submitted_text=request.form.get('answer_text'),
        selected_option_id=selected_option_id,
    )
    process_due_ability(game_round, config, battle_state)
    db.session.commit()
    _emit_live_state(session_id)
    message, category = _boss_rush_answer_feedback(result)
    flash(message, category)
    return redirect(url_for('boss_rush_player.game', session_id=session_id))
