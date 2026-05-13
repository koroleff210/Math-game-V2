# app/__init__.py
#
# Application factory.  Call create_app() to get a configured Flask instance.
# Nothing game-specific lives here — only wiring of extensions and blueprints.
#
# IMPORTANT: the Flask instance is named 'flask_app' (not 'app') to avoid a
# name collision with the 'app' package itself when using 'import app.models'.

from flask import Flask
from config import Config
from app.extensions import db, migrate, login_manager, socketio, csrf


def create_app(config_class=Config):
    flask_app = Flask(__name__, instance_relative_config=True)
    flask_app.config.from_object(config_class)

    # ── Initialise extensions ───────────────────────────────────────────────────
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)
    socketio.init_app(flask_app, async_mode=flask_app.config['SOCKETIO_ASYNC_MODE'])
    # csrf must be initialized AFTER secret key is set so it can sign tokens.
    csrf.init_app(flask_app)

    # ── Register blueprints ───────────────────────────────────────────────────
    # Import models so Flask-Migrate can detect all tables for migrations.
    import app.models  # noqa: F401  — side-effect import, registers models with SQLAlchemy

    from app.routes.auth   import auth_bp
    from app.routes.admin  import admin_bp
    from app.routes.player import player_bp

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(admin_bp)
    flask_app.register_blueprint(player_bp)

    from app.modes.classic.routes import classic_admin_bp, classic_player_bp
    flask_app.register_blueprint(classic_admin_bp)
    flask_app.register_blueprint(classic_player_bp)

    from app.modes.boss_rush.routes import boss_rush_admin_bp, boss_rush_player_bp
    flask_app.register_blueprint(boss_rush_admin_bp)
    flask_app.register_blueprint(boss_rush_player_bp)

    # ── Register Socket.IO event handlers ─────────────────────────────────────
    from app.socketio_handlers import register_all_handlers
    register_all_handlers(socketio)

    # ── Register maintenance CLI commands ─────────────────────────────────────
    from app.cli.maintenance import (
        pilot_reset_command,
        fresh_start_command,
        migrate_gear_assets_command,
        audit_legacy_gear_keys_command,
        migrate_gear_image_keys_to_packages_command,
    )
    flask_app.cli.add_command(pilot_reset_command)
    flask_app.cli.add_command(fresh_start_command)
    flask_app.cli.add_command(migrate_gear_assets_command)
    flask_app.cli.add_command(audit_legacy_gear_keys_command)
    flask_app.cli.add_command(migrate_gear_image_keys_to_packages_command)

    return flask_app

