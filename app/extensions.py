# app/extensions.py
#
# All Flask extension instances are created here — separate from create_app().
# This breaks circular imports: models can import db, socketio_handlers can
# import socketio, etc., without importing the full app factory.

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect

# Database ORM
db = SQLAlchemy()

# Database migration manager (flask db init / flask db upgrade)
migrate = Migrate()

# Session/login manager — redirect unauthenticated users to login page
login_manager = LoginManager()
login_manager.login_view = 'auth.login'       # route name for the login page
login_manager.login_message = 'Please log in to access this page.'

# Real-time WebSocket server
socketio = SocketIO()

# CSRF protection — makes csrf_token() available in all Jinja2 templates
# and enforces CSRF tokens on all POST/PUT/DELETE/PATCH requests.
csrf = CSRFProtect()
