# app/modes/boss_rush/events.py
#
# Socket.IO listeners for Boss Rush live-state rooms.

from flask_login import current_user
from flask_socketio import emit, join_room

from app.extensions import db
from app.models.game import GameRound, GameSession, RoundPlayer
from app.modes.boss_rush.engine import BOSS_RUSH_MODE, build_live_state_payload, process_due_ability


def boss_rush_room(session_id):
    return f'boss_rush_{int(session_id)}'


def _latest_round(session_id):
    return (
        GameRound.query
        .filter_by(session_id=session_id)
        .order_by(GameRound.round_number.desc())
        .first()
    )


def build_boss_rush_room_payload(session_id):
    game_session = db.session.get(GameSession, int(session_id))
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        return None
    game_round = _latest_round(game_session.id)
    if not game_round or not game_round.boss_rush_config or not game_round.boss_rush_battle_state:
        return None
    result = process_due_ability(
        game_round,
        game_round.boss_rush_config,
        game_round.boss_rush_battle_state,
    )
    if result.get('triggered'):
        db.session.commit()
    return build_live_state_payload(
        game_session,
        game_round,
        game_round.boss_rush_config,
        game_round.boss_rush_battle_state,
    )


def emit_boss_rush_state(socketio, session_id):
    payload = build_boss_rush_room_payload(session_id)
    if payload:
        socketio.emit('boss_rush_state_update', payload, room=boss_rush_room(session_id))
    return payload


def _can_watch_boss_rush(game_session):
    if not current_user.is_authenticated:
        return False
    if bool(getattr(current_user, 'is_admin', False)):
        return True
    return RoundPlayer.query.filter_by(
        session_id=game_session.id,
        player_id=current_user.id,
    ).first() is not None


def _validate_session_for_socket(data):
    if not current_user.is_authenticated:
        emit('boss_rush_error', {'msg': 'Login required.'})
        return None
    session_id = (data or {}).get('session_id')
    if not session_id:
        emit('boss_rush_error', {'msg': 'Missing session_id.'})
        return None
    game_session = db.session.get(GameSession, int(session_id))
    if not game_session or game_session.mode != BOSS_RUSH_MODE:
        emit('boss_rush_error', {'msg': 'Boss Rush session not found.'})
        return None
    if not _can_watch_boss_rush(game_session):
        emit('boss_rush_error', {'msg': 'Join the Boss Rush session before watching live state.'})
        return None
    return game_session


def register_boss_rush_handlers(socketio):
    @socketio.on('boss_rush_join')
    def boss_rush_join(data):
        game_session = _validate_session_for_socket(data)
        if game_session is None:
            return

        join_room(boss_rush_room(game_session.id))
        payload = build_boss_rush_room_payload(game_session.id)
        if payload:
            emit('boss_rush_state_update', payload)

    @socketio.on('boss_rush_check_ability')
    def boss_rush_check_ability(data):
        game_session = _validate_session_for_socket(data)
        if game_session is None:
            return

        game_round = _latest_round(game_session.id)
        if not game_round or not game_round.boss_rush_config or not game_round.boss_rush_battle_state:
            emit('boss_rush_error', {'msg': 'Boss Rush round is missing ability state.'})
            return

        result = process_due_ability(
            game_round,
            game_round.boss_rush_config,
            game_round.boss_rush_battle_state,
        )
        if result.get('triggered'):
            db.session.commit()
            payload = build_live_state_payload(
                game_session,
                game_round,
                game_round.boss_rush_config,
                game_round.boss_rush_battle_state,
            )
            socketio.emit('boss_rush_state_update', payload, room=boss_rush_room(game_session.id))
            return

        payload = build_live_state_payload(
            game_session,
            game_round,
            game_round.boss_rush_config,
            game_round.boss_rush_battle_state,
        )
        emit('boss_rush_state_update', payload)
