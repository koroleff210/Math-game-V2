# app/socketio_handlers/hub.py
#
# Socket.IO handlers for the persistent Hub page.
#
# When a player is on the Hub, their client emits 'hub_join' to subscribe
# to group-based rooms (hub_group_<id>).  When an admin creates a session
# restricted to a group, the server emits 'session_available' to that room
# so the Hub can instantly display the Join Game banner.
#
# Rooms:
#   hub_group_<group_id>   — all Hub-connected members of that group
#   hub_open               — Hub-connected players for open (no-group) sessions

from flask_login import current_user
from flask_socketio import emit, join_room


def register_hub_handlers(socketio):

    @socketio.on('hub_join')
    def _handle_hub_join(data):
        """Player's Hub page connected — join group rooms."""
        if not current_user or not current_user.is_authenticated:
            return

        group_ids = data.get('group_ids', [])
        for gid in group_ids:
            if isinstance(gid, int):
                join_room(f'hub_group_{gid}')

        # Every Hub player also joins the open-session room so they hear
        # about sessions created without group restriction.
        join_room('hub_open')

        emit('hub_join_ack', {'ok': True})
