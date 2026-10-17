# app/__init__.py
#
# Application factory.  Call create_app() to get a configured Flask instance.
# Nothing game-specific lives here — only wiring of extensions and blueprints.
#
# IMPORTANT: the Flask instance is named 'flask_app' (not 'app') to avoid a
# name collision with the 'app' package itself when using 'import app.models'.

import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from app.extensions import db, migrate, login_manager, socketio, csrf


def create_app(config_class=Config):
    instance_path = getattr(config_class, 'INSTANCE_PATH', None)
    flask_app = Flask(__name__, instance_relative_config=True,
                      **({'instance_path': os.path.abspath(instance_path)} if instance_path else {}))
    flask_app.config.from_object(config_class)

    if flask_app.config.get('GAME_ENV') == 'production':
        if not flask_app.config.get('SECRET_KEY') or flask_app.config['SECRET_KEY'] == 'dev-secret-change-before-deployment':
            raise RuntimeError('Production requires a unique SECRET_KEY.')
        if not flask_app.config.get('SQLALCHEMY_DATABASE_URI', '').startswith('postgresql+psycopg://'):
            raise RuntimeError('Production requires a PostgreSQL DATABASE_URL.')
        if not (os.environ.get('GAME_PUBLIC_ORIGINS') or os.environ.get('RENDER_EXTERNAL_URL')):
            raise RuntimeError('Production requires GAME_PUBLIC_ORIGINS (an HTTPS origin).')
        # The hosting proxy supplies the external HTTPS scheme and host.
        flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Initialise extensions ───────────────────────────────────────────────────
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)
    socketio_options = {'async_mode': flask_app.config['SOCKETIO_ASYNC_MODE']}
    if flask_app.config.get('GAME_ENV') == 'production':
        origins = [
            origin.strip().rstrip('/')
            for origin in (
                os.environ.get('RENDER_EXTERNAL_URL', ''),
                *os.environ.get('GAME_PUBLIC_ORIGINS', '').split(','),
            )
            if origin.strip()
        ]
        if not origins or any(not origin.startswith('https://') or '*' in origin for origin in origins):
            raise RuntimeError('Production public origins must be explicit HTTPS origins.')
        socketio_options['cors_allowed_origins'] = list(dict.fromkeys(origins))
    socketio.init_app(flask_app, **socketio_options)
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
    from app.routes.media import media_bp
    flask_app.register_blueprint(media_bp)
    from app.routes.content_import import import_bp
    flask_app.register_blueprint(import_bp)
    from app.routes.assets import assets_bp
    flask_app.register_blueprint(assets_bp)

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

    from app.cli.bootstrap import create_admin_command
    flask_app.cli.add_command(create_admin_command)

    return flask_app

