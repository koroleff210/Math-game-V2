# app/routes/player.py
#
# Player blueprint — player-facing pages.
#
# Routes:
#   GET  /player/dashboard         — persistent Hub (identity, diamonds, upgrades, join gate)
#   GET  /player/blacksmith        — Diamonds & upgrade shop (D2)
#   POST /player/blacksmith/buy    — purchase one upgrade level (D2)

from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.game import GameSession, RoundPlayer
from app.models.progression import PlayerProgression
from app.services.progression import (
    get_or_create_player_progression,
    get_player_upgrade_map,
    purchase_upgrade,
)
from app.services.gear import (
    build_player_gear_hub_view,
    equip_player_gear_item,
    list_blacksmith_gear_for_player,
    purchase_blacksmith_gear,
    unequip_player_gear_slot,
)
from app.services.avatar import (
    build_player_avatar_view,
    cycle_player_face_selection,
    get_valid_selected_face_key,
    normalize_avatar_body_variant,
    set_player_body_variant,
)
from app.services.upgrade_catalog import UPGRADE_CATALOG, UPGRADE_ORDER
from app.services.analytics_reports import build_player_dashboard


player_bp = Blueprint('player', __name__, url_prefix='/player')


def _player_in_unfinished_session(player_id: int):
    """Return an unfinished session enrollment row if the player has already joined.

    This is the Hub/session boundary guard: once a player joins a waiting or
    active session, persistent gear edits stay locked until that session ends.
    """
    return (
        RoundPlayer.query
        .join(GameSession, RoundPlayer.session_id == GameSession.id)
        .filter(
            RoundPlayer.player_id == player_id,
            GameSession.status != 'finished',
        )
        .first()
    )


def _dashboard_redirect_for_gear_state(filter_key: str | None, selected_item_id: str | None):
    route_args = {}
    if filter_key:
        route_args['gear_filter'] = filter_key
    if selected_item_id:
        route_args['selected_item'] = selected_item_id
    return redirect(url_for('player.dashboard', **route_args))


def _is_js_shell_request() -> bool:
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _flash_if_full_page(message: str, category: str) -> None:
    if not _is_js_shell_request():
        flash(message, category)


def _build_player_gear_view_for_state(selected_filter: str | None, selected_item_id: str | None):
    gear_view = build_player_gear_hub_view(
        current_user.id,
        selected_filter=selected_filter,
        selected_item_id=selected_item_id,
    )
    if gear_view['loadout_created'] or gear_view['loadout_normalized']:
        db.session.commit()
    return gear_view


def _build_player_gear_shell_context(
    *,
    selected_filter: str | None,
    selected_item_id: str | None,
    gear_shell_message: dict | None = None,
):
    from app.services.hub import get_player_hub_status

    gear_view = _build_player_gear_view_for_state(selected_filter, selected_item_id)
    avatar_view = build_player_avatar_view(current_user, gear_view['loadout'])
    return {
        'gear_filter': gear_view['selected_filter'],
        'gear_filter_tabs': gear_view['filter_tabs'],
        'gear_inventory_items': gear_view['inventory_items'],
        'gear_visible_items': gear_view['visible_items'],
        'gear_selected_item': gear_view['selected_item'],
        'gear_inventory_groups': gear_view['inventory_groups'],
        'gear_loadout_slots': gear_view['slot_rows'],
        'gear_active_bonus_summary': gear_view['active_bonus_summary'],
        'gear_avatar': avatar_view,
        'hub_status': get_player_hub_status(current_user),
        'character_face_locked': current_user.is_character_locked,
        'character_selection_required': not current_user.is_character_locked,
        'avatar_body_variant': normalize_avatar_body_variant(getattr(current_user, 'avatar_body_variant', None)),
        'gear_shell_message': gear_shell_message,
    }


def _build_current_player_gear_view():
    return _build_player_gear_view_for_state(
        request.args.get('gear_filter', 'all'),
        request.args.get('selected_item'),
    )


def _render_gear_shell_partial(
    *,
    selected_filter: str | None,
    selected_item_id: str | None,
    gear_shell_message: dict | None = None,
):
    return render_template(
        'player/_gear_shell.html',
        **_build_player_gear_shell_context(
            selected_filter=selected_filter,
            selected_item_id=selected_item_id,
            gear_shell_message=gear_shell_message,
        ),
    )


@player_bp.route('/dashboard')
@login_required
def dashboard():
    from app.services.hub import get_player_hub_status

    prog = PlayerProgression.query.filter_by(player_id=current_user.id).first()
    balance = prog.diamonds_balance if prog else 0

    upgrade_map = get_player_upgrade_map(current_user.id)
    upgrades = []
    for ut in UPGRADE_ORDER:
        defn = UPGRADE_CATALOG[ut]
        row  = upgrade_map.get(ut)
        current_level = row.level if row else 0
        current_effect = defn.effect_at_level(current_level)
        next_effect = (defn.effect_at_level(current_level + 1)
                       if current_level < defn.max_level else None)
        upgrades.append({
            'upgrade_type':    ut,
            'label':           defn.label,
            'description':     defn.description,
            'current_level':   current_level,
            'max_level':       defn.max_level,
            'current_effect':  defn.format_effect(current_level),
            'next_effect':     defn.format_effect(current_level + 1) if next_effect is not None else None,
        })

    hub_status = get_player_hub_status(current_user)
    gear_context = _build_player_gear_shell_context(
        selected_filter=request.args.get('gear_filter', 'all'),
        selected_item_id=request.args.get('selected_item'),
    )

    # Step 3: if the player is already enrolled in an unfinished session,
    # route them directly into the correct session stage instead of leaving
    # them in Hub.  Only redirect if the player is still group-eligible for
    # that session; if they were removed from the group after joining, fall
    # through to the normal hub render to avoid a dashboard ↔ classic-route
    # redirect loop.
    from app.services.hub import HUB_STATE_ENROLLED_UNFINISHED
    from app.modes.classic.routes import player_in_session_group
    if hub_status.state == HUB_STATE_ENROLLED_UNFINISHED and hub_status.session:
        sess = hub_status.session
        if player_in_session_group(current_user, sess):
            if sess.mode == 'boss_rush':
                if sess.status == 'waiting':
                    return redirect(url_for('boss_rush_player.lobby', session_id=sess.id))
                if sess.status == 'active':
                    return redirect(url_for('boss_rush_player.game', session_id=sess.id))
            elif sess.status == 'waiting':
                return redirect(url_for('classic_player.lobby', session_id=sess.id))
            elif sess.status == 'active':
                return redirect(url_for('classic_player.game', session_id=sess.id))
        # 'finished' or group-removed → fall through to hub

    # Player's group IDs for Hub Socket.IO room subscriptions.
    group_ids = [g.id for g in current_user.groups]

    return render_template(
        'player/hub.html',
        balance=balance,
        upgrades=upgrades,
        group_ids=group_ids,
        **gear_context,
    )


@player_bp.route('/gear/shell')
@login_required
def gear_shell():
    if not current_user.is_character_locked:
        return _render_gear_shell_partial(
            selected_filter=request.args.get('gear_filter', 'all'),
            selected_item_id=request.args.get('selected_item'),
            gear_shell_message={
                'category': 'info',
                'text': 'Choose and confirm your character before using the normal Hub.',
            },
        )
    return _render_gear_shell_partial(
        selected_filter=request.args.get('gear_filter', 'all'),
        selected_item_id=request.args.get('selected_item'),
    )


@player_bp.route('/gear/equip', methods=['POST'])
@login_required
def gear_equip():
    selected_filter = (request.form.get('gear_filter') or 'all').strip()
    selected_item_id = (request.form.get('selected_item') or '').strip() or None
    if _player_in_unfinished_session(current_user.id):
        message = 'Gear changes are unavailable after you join a session.'
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )
        return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)

    item_id = (request.form.get('item_id') or '').strip()
    slot_key = (request.form.get('slot_key') or '').strip()

    try:
        result = equip_player_gear_item(
            player_id=current_user.id,
            item_id=item_id,
            slot_key=slot_key,
        )
        db.session.commit()
        message = f'{result["item"].name} equipped in {result["slot_key"].replace("_", " ").title()}.'
        _flash_if_full_page(message, 'success')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id or item_id,
                gear_shell_message={'category': 'success', 'text': message},
            )
    except ValueError as exc:
        db.session.rollback()
        message = str(exc)
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id or item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )

    return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id or item_id)


@player_bp.route('/gear/unequip', methods=['POST'])
@login_required
def gear_unequip():
    selected_filter = (request.form.get('gear_filter') or 'all').strip()
    selected_item_id = (request.form.get('selected_item') or '').strip() or None
    if _player_in_unfinished_session(current_user.id):
        message = 'Gear changes are unavailable after you join a session.'
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )
        return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)

    slot_key = (request.form.get('slot_key') or '').strip()

    try:
        result = unequip_player_gear_slot(
            player_id=current_user.id,
            slot_key=slot_key,
        )
        db.session.commit()
        if result['changed']:
            message = f'{result["slot_key"].replace("_", " ").title()} unequipped.'
            _flash_if_full_page(message, 'success')
        else:
            message = 'That slot is already empty.'
            _flash_if_full_page(message, 'info')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'success' if result['changed'] else 'info', 'text': message},
            )
    except ValueError as exc:
        db.session.rollback()
        message = str(exc)
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )

    return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)


@player_bp.route('/avatar/face', methods=['POST'])
@login_required
def avatar_face():
    selected_filter = (request.form.get('gear_filter') or 'all').strip()
    selected_item_id = (request.form.get('selected_item') or '').strip() or None

    if _player_in_unfinished_session(current_user.id):
        message = 'Avatar changes are unavailable after you join a session.'
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )
        return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)

    if current_user.is_character_locked:
        message = 'Your character face is locked. Gear can still be changed normally.'
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )
        return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)

    direction = (request.form.get('direction') or '').strip()
    try:
        face_key = cycle_player_face_selection(current_user, direction)
        db.session.commit()
        message = f'Face {face_key} selected.'
        _flash_if_full_page(message, 'success')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'success', 'text': message},
            )
    except ValueError as exc:
        db.session.rollback()
        message = str(exc)
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )

    return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)


@player_bp.route('/avatar/body', methods=['POST'])
@login_required
def avatar_body():
    selected_filter = (request.form.get('gear_filter') or 'all').strip()
    selected_item_id = (request.form.get('selected_item') or '').strip() or None

    if _player_in_unfinished_session(current_user.id):
        message = 'Avatar changes are unavailable after you join a session.'
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )
        return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)

    if current_user.is_character_locked:
        message = 'Your character body is locked. Gear can still be changed normally.'
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )
        return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)

    variant = (request.form.get('variant') or '').strip().lower()
    if variant not in {'m', 'f'}:
        message = 'Invalid body selection.'
        _flash_if_full_page(message, 'error')
        if _is_js_shell_request():
            return _render_gear_shell_partial(
                selected_filter=selected_filter,
                selected_item_id=selected_item_id,
                gear_shell_message={'category': 'error', 'text': message},
            )
        return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)

    set_player_body_variant(current_user, variant)
    db.session.commit()
    message = f'Body set to {"Male" if variant == "m" else "Female"}.'
    _flash_if_full_page(message, 'success')
    if _is_js_shell_request():
        return _render_gear_shell_partial(
            selected_filter=selected_filter,
            selected_item_id=selected_item_id,
            gear_shell_message={'category': 'success', 'text': message},
        )
    return _dashboard_redirect_for_gear_state(selected_filter, selected_item_id)


@player_bp.route('/avatar/confirm', methods=['POST'])
@login_required
def avatar_confirm():
    if current_user.is_character_locked:
        flash('Your character is already locked. Gear can still be changed normally.', 'info')
        return redirect(url_for('player.dashboard'))

    current_user.avatar_body_variant = normalize_avatar_body_variant(
        getattr(current_user, 'avatar_body_variant', None)
    )
    current_user.selected_face_key = get_valid_selected_face_key(
        current_user.selected_face_key,
        current_user.avatar_body_variant,
    )
    current_user.character_locked_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('Character confirmed. Your face is now locked; gear can still be changed normally.', 'success')
    return redirect(url_for('player.dashboard'))


# ── Blacksmith ────────────────────────────────────────────────────────────────

@player_bp.route('/blacksmith')
@login_required
def blacksmith():
    """Player-facing Diamonds & upgrade shop.

    Blocked after the player joins any non-finished session.
    """
    active_session = _player_in_unfinished_session(current_user.id)
    if active_session:
        flash('The Blacksmith is unavailable after you join a session.', 'error')
        return redirect(url_for('player.dashboard'))

    prog = PlayerProgression.query.filter_by(player_id=current_user.id).first()
    balance = prog.diamonds_balance if prog else 0
    upgrade_map = get_player_upgrade_map(current_user.id)
    gear_items = list_blacksmith_gear_for_player(current_user.id)

    # Build display rows in catalog order
    upgrades = []
    for ut in UPGRADE_ORDER:
        defn = UPGRADE_CATALOG[ut]
        row  = upgrade_map.get(ut)
        current_level = row.level if row else 0
        cost = defn.cost_for_next_level(current_level)
        next_effect = (
            defn.format_effect(current_level + 1)
            if current_level < defn.max_level
            else None
        )
        upgrades.append({
            'upgrade_type':  ut,
            'label':         defn.label,
            'description':   defn.description,
            'current_level': current_level,
            'max_level':     defn.max_level,
            'current_effect': defn.format_effect(current_level),
            'next_effect':    next_effect,
            'cost':          cost,             # None if maxed
            'can_afford':    cost is not None and balance >= cost,
            'maxed':         current_level >= defn.max_level,
        })

    active_tab = (request.args.get('tab') or 'upgrades').strip().lower()
    if active_tab not in {'upgrades', 'gear'}:
        active_tab = 'upgrades'

    return render_template(
        'player/blacksmith.html',
        balance=balance,
        upgrades=upgrades,
        gear_items=gear_items,
        active_tab=active_tab,
    )


@player_bp.route('/blacksmith/buy', methods=['POST'])
@login_required
def blacksmith_buy():
    """Purchase one level of the requested upgrade for the current player.

    Validates ownership: a player can only purchase for themselves (current_user).
    The player_id in the POST body is ignored; current_user.id is always used.
    """
    active_session = _player_in_unfinished_session(current_user.id)
    if active_session:
        flash('The Blacksmith is unavailable after you join a session.', 'error')
        return redirect(url_for('player.dashboard'))
    upgrade_type = request.form.get('upgrade_type', '').strip()
    return_tab = (request.form.get('return_tab') or 'upgrades').strip().lower()
    if return_tab not in {'upgrades', 'gear'}:
        return_tab = 'upgrades'

    try:
        result = purchase_upgrade(
            player_id=current_user.id,
            upgrade_type=upgrade_type,
        )
        db.session.commit()
        flash(
            f'{UPGRADE_CATALOG[upgrade_type].label} upgraded to level {result["new_level"]}! '
            f'({result["cost"]} Diamond(s) spent — balance: {result["new_balance"]})',
            'success',
        )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')

    return redirect(url_for('player.blacksmith', tab=return_tab))


@player_bp.route('/blacksmith/buy_gear', methods=['POST'])
@login_required
def blacksmith_buy_gear():
    active_session = _player_in_unfinished_session(current_user.id)
    if active_session:
        flash('The Blacksmith is unavailable after you join a session.', 'error')
        return redirect(url_for('player.dashboard'))

    item_id = (request.form.get('item_id') or '').strip()
    return_tab = (request.form.get('return_tab') or 'gear').strip().lower()
    if return_tab not in {'upgrades', 'gear'}:
        return_tab = 'gear'

    try:
        result = purchase_blacksmith_gear(
            player_id=current_user.id,
            item_id=item_id,
        )
        db.session.commit()
        flash(
            f'{result["item_name"]} purchased! '
            f'({result["cost"]} Diamond(s) spent — balance: {result["new_balance"]})',
            'success',
        )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')

    return redirect(url_for('player.blacksmith', tab=return_tab))


@player_bp.route('/performance')
@login_required
def performance():
    return render_template(
        'player/meta_placeholder.html',
        page_title='Performance',
        page_heading='Performance',
        page_description='Player performance summaries and deeper analysis will live here.',
    )


@player_bp.route('/progress')
@login_required
def progress():
    return render_template(
        'player/progress.html',
        dashboard=build_player_dashboard(current_user.id),
    )


@player_bp.route('/history')
@login_required
def history():
    return render_template(
        'player/meta_placeholder.html',
        page_title='History',
        page_heading='History',
        page_description='Session and round history views will live here.',
    )

