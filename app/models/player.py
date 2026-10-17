# app/models/player.py
#
# The Player model represents both admin users and student players.
# is_admin flag separates the two roles — no separate roles table needed yet.

from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


class Player(UserMixin, db.Model):
    __tablename__ = 'player'

    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin   = db.Column(db.Boolean, default=False, nullable=False)
    yeargroup  = db.Column(db.String(32), nullable=True)
    shared_email = db.Column(db.String(254), unique=True, nullable=True)
    shared_identity_id = db.Column(db.Integer, unique=True, nullable=True)
    credential_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    avatar_body_variant = db.Column(db.String(8), nullable=False, default='m')
    avatar_gender_selected = db.Column(db.Boolean, nullable=False, default=True)
    selected_face_key = db.Column(db.String(16), nullable=False, default='001')
    character_locked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    @property
    def is_character_locked(self):
        return self.character_locked_at is not None

    # ── Password helpers ──────────────────────────────────────────────────────
    def set_password(self, password):
        """Hash and store the password.  Never stores the plain-text value."""
        self.password_hash = generate_password_hash(password)
        self.credential_version = (self.credential_version or 0) + 1

    def check_password(self, password):
        """Return True if the given plain-text password matches the stored hash."""
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

    # ── Flask-Login requirement ───────────────────────────────────────────────
    def get_id(self):
        """Flask-Login uses this to store the user identifier in the session."""
        return str(self.id)

    def __repr__(self):
        return f'<Player {self.username!r} admin={self.is_admin}>'
