# app/routes/auth.py
#
# Authentication blueprint: login and logout only.
# The user_loader callback (required by Flask-Login) is also registered here
# because it needs access to the Player model.

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import login_manager, db
from app.models.player import Player


auth_bp = Blueprint('auth', __name__)


# ── Flask-Login user loader ───────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    """Called by Flask-Login on every request to reload the user from the session.

    Returns the Player object or None if the id is invalid.
    Uses the SQLAlchemy 2.0 session.get() API (replaces deprecated query.get).
    """
    return db.session.get(Player, int(user_id))


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route('/')
def index():
    """Root URL — redirect straight to login (or dashboard if already logged in)."""
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard') if current_user.is_admin else url_for('player.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # If the user is already logged in, skip the login page.
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('player.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Look up the player by username.
        player = Player.query.filter_by(username=username).first()

        if player and player.check_password(password):
            login_user(player)
            # Send admin to admin dashboard, players to their dashboard.
            if player.is_admin:
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('player.dashboard'))

        # Wrong credentials — stay on the login page with an error message.
        flash('Invalid username or password.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
