# app/socketio_handlers/__init__.py
#
# Central Socket.IO event registry.
#
# All Socket.IO event handlers for every game mode are imported and registered
# here.  This keeps the app factory clean and makes it easy to see exactly
# which socket events exist in the project.
#
# Usage pattern — add one line per module as each mode is built:
#   from app.socketio_handlers.classic  import register as register_classic
#   from app.socketio_handlers.team     import register as register_team
#   from app.socketio_handlers.boss_rush import register as register_boss_rush
#
# Each module exposes a register(socketio) function that calls
# @socketio.on(...) decorators for its own events.


def register_all_handlers(socketio):
    """Register all Socket.IO event handlers with the given socketio instance.

    Called once from create_app().  Add handler modules here as each
    game mode is developed.
    """
    from app.modes.classic.events import register_classic_handlers
    register_classic_handlers(socketio)

    from app.socketio_handlers.hub import register_hub_handlers
    register_hub_handlers(socketio)

    from app.modes.boss_rush.events import register_boss_rush_handlers
    register_boss_rush_handlers(socketio)
