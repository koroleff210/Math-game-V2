"""Live, in-memory WebRTC signaling and gameplay admission for one game worker."""

from dataclasses import dataclass
from threading import RLock
from time import monotonic

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_socketio import emit

from app.extensions import db
from app.models.game import GameSession, RoundPlayer


bp = Blueprint('proctoring', __name__)
SHARE_REQUIRED = 'Share your entire screen to continue.'


@dataclass
class Share:
    player_id: int
    name: str
    connection: str
    viewed_until: float = 0
    viewer: str | None = None


class ProctorRooms:
    def __init__(self):
        self.lock = RLock()
        self.viewers = {}
        self.shares = {}

    def allowed(self, game, player_id):
        if not game.proctoring_required:
            return True
        with self.lock:
            share = self.shares.get(game.id, {}).get(player_id)
            return bool(share and share.viewed_until > monotonic())


def rooms():
    return current_app.extensions['proctor_rooms']


def may_play(game, player_id):
    return not game.proctoring_required or rooms().allowed(game, player_id)


def end_proctoring(game_id):
    with rooms().lock:
        viewer = rooms().viewers.pop(game_id, None)
        shares = rooms().shares.pop(game_id, {})
        for connection in [viewer, *(share.connection for share in shares.values())]:
            if connection:
                current_app.extensions['socketio'].emit('proctor_ended', to=connection)


@bp.get('/admin/proctoring/<int:game_id>')
@login_required
def monitor(game_id):
    if not current_user.is_admin:
        abort(403)
    game = db.get_or_404(GameSession, game_id)
    if not game.proctoring_required or game.status == 'finished':
        abort(404)
    players = game.group.members.all() if game.group else [
        row.player for row in RoundPlayer.query.filter_by(session_id=game.id)
    ]
    return render_template('admin/proctoring.html', game=game, players=players)


@bp.get('/proctoring/<int:game_id>/status')
@login_required
def status(game_id):
    game = db.get_or_404(GameSession, game_id)
    if game.group_id and not any(group.id == game.group_id for group in current_user.groups):
        abort(403)
    return {'required': game.proctoring_required and game.status != 'finished'}


@bp.post('/admin/proctoring/<int:game_id>/disable')
@login_required
def disable(game_id):
    if not current_user.is_admin:
        abort(403)
    game = db.get_or_404(GameSession, game_id)
    endpoint = {'classic': 'classic_admin.manage', 'boss_rush': 'boss_rush_admin.manage'}.get(game.mode)
    if endpoint is None:
        abort(404)
    game.proctoring_required = False
    db.session.commit()
    end_proctoring(game.id)
    return redirect(url_for(endpoint, session_id=game.id))


def register(socketio, app):
    app.extensions['proctor_rooms'] = ProctorRooms()

    def game_for(data):
        game_id = data.get('session_id') if isinstance(data, dict) else None
        if not current_user.is_authenticated or type(game_id) is not int:
            return None
        game = db.session.get(GameSession, game_id)
        if not game or not game.proctoring_required or game.status == 'finished':
            return None
        return game

    def announce(share, viewer):
        if share.viewer == viewer:
            return
        share.viewer = viewer
        socketio.emit('proctor_peer', {'peer': share.connection, 'player_id': share.player_id,
                                      'name': share.name}, to=viewer)
        socketio.emit('proctor_negotiate', to=share.connection)

    @socketio.on('proctor_watch')
    def watch(data):
        game = game_for(data)
        if not game or not current_user.is_admin:
            return {'ok': False}
        with rooms().lock:
            previous = rooms().viewers.get(game.id)
            if previous and previous != request.sid:
                return {'ok': False, 'message': 'A monitoring tab is already open for this session.'}
            rooms().viewers[game.id] = request.sid
        return {'ok': True, 'ice_servers': current_app.config['PROCTOR_ICE_SERVERS']}

    @socketio.on('proctor_watch_ready')
    def watch_ready(data):
        game = game_for(data)
        if not game or not current_user.is_admin:
            return
        with rooms().lock:
            if rooms().viewers.get(game.id) == request.sid:
                for share in rooms().shares.get(game.id, {}).values():
                    announce(share, request.sid)

    @socketio.on('proctor_share')
    def start_share(data):
        game = game_for(data)
        if (not game or current_user.is_admin or data.get('surface') != 'monitor'
                or (game.group_id and not any(g.id == game.group_id for g in current_user.groups))):
            return {'ok': False, 'message': SHARE_REQUIRED}
        with rooms().lock:
            shares = rooms().shares.setdefault(game.id, {})
            previous = shares.get(current_user.id)
            viewer = rooms().viewers.get(game.id)
            if previous and previous.connection != request.sid:
                socketio.emit('proctor_replaced', to=previous.connection)
                if viewer:
                    socketio.emit('proctor_peer_left', {'peer': previous.connection}, to=viewer)
            shares[current_user.id] = Share(current_user.id, current_user.username, request.sid)
        return {'ok': True, 'ice_servers': current_app.config['PROCTOR_ICE_SERVERS']}

    @socketio.on('proctor_share_ready')
    def share_ready(data):
        game = game_for(data)
        if not game or current_user.is_admin:
            return
        with rooms().lock:
            share = rooms().shares.get(game.id, {}).get(current_user.id)
            viewer = rooms().viewers.get(game.id)
            if share and viewer and share.connection == request.sid:
                announce(share, viewer)

    @socketio.on('proctor_signal')
    def signal(data):
        game = game_for(data)
        if not game:
            return
        message = data.get('description')
        if (not isinstance(message, dict) or not isinstance(message.get('sdp'), str)
                or len(message['sdp']) > 30000):
            return
        with rooms().lock:
            viewer = rooms().viewers.get(game.id)
            shares = rooms().shares.get(game.id, {})
            if current_user.is_admin and viewer == request.sid and message.get('type') == 'answer':
                peer = data.get('peer')
                if any(share.connection == peer for share in shares.values()):
                    socketio.emit('proctor_signal', {'description': message}, to=peer)
            elif not current_user.is_admin and viewer and message.get('type') == 'offer':
                share = shares.get(current_user.id)
                if share and share.connection == request.sid:
                    socketio.emit('proctor_signal', {'peer': request.sid, 'description': message}, to=viewer)

    @socketio.on('proctor_viewed')
    def viewed(data):
        game = game_for(data)
        peers = data.get('peers') if game else None
        if not game or not current_user.is_admin or not isinstance(peers, list) or len(peers) > 100:
            return
        with rooms().lock:
            if rooms().viewers.get(game.id) != request.sid:
                return
            now = monotonic()
            for share in rooms().shares.get(game.id, {}).values():
                active = share.connection in peers
                was_active = share.viewed_until > now
                share.viewed_until = now + 12 if active else 0
                if active or was_active:
                    socketio.emit('proctor_status', {'active': active}, to=share.connection)

    @socketio.on('disconnect')
    def disconnected(_reason=None):
        with rooms().lock:
            for game_id, viewer in list(rooms().viewers.items()):
                if viewer == request.sid:
                    del rooms().viewers[game_id]
                    for share in rooms().shares.get(game_id, {}).values():
                        share.viewed_until = 0
                        socketio.emit('proctor_status', {'active': False}, to=share.connection)
            for game_id, shares in list(rooms().shares.items()):
                for player_id, share in list(shares.items()):
                    if share.connection == request.sid:
                        del shares[player_id]
                        viewer = rooms().viewers.get(game_id)
                        if viewer:
                            socketio.emit('proctor_peer_left', {'peer': request.sid}, to=viewer)
                if not shares:
                    rooms().shares.pop(game_id)
