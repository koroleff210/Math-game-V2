# app/routes/auth.py
#
# Authentication blueprint: login and logout only.
# The user_loader callback (required by Flask-Login) is also registered here
# because it needs access to the Player model.

from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import text, update
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import login_manager, db
from app.models.player import Player
from app.services import login_rate_limit, shared_identity
from app.services.player_reset import reset_player_to_starting_state
from sqlalchemy.exc import IntegrityError
import hashlib


auth_bp = Blueprint('auth', __name__)
_dummy_password_hash = generate_password_hash('unregistered-login-placeholder')


@auth_bp.route('/healthz')
def healthz():
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        db.session.rollback()
        return {'status': 'unavailable'}, 503
    return {'status': 'ok'}


# ── Flask-Login user loader ───────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    """Called by Flask-Login on every request to reload the user from the session.

    Returns the Player object or None if the id is invalid.
    Uses the SQLAlchemy 2.0 session.get() API (replaces deprecated query.get).
    """
    try:
        player = db.session.get(Player, int(user_id))
    except (TypeError, ValueError):
        return None
    if player is None or session.get('credential_version', player.credential_version) != player.credential_version:
        return None
    if player.shared_identity_id and shared_identity.enabled():
        try:
            identity = shared_identity.call('lookup', email=player.shared_email)
        except shared_identity.IdentityUnavailable:
            return None
        if identity.get('id') != player.shared_identity_id or identity.get('version') != session.get('identity_version'):
            return None
    return player


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route('/')
def index():
    """Root URL — redirect straight to login (or dashboard if already logged in)."""
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard') if current_user.is_admin else url_for('player.dashboard'))
    return redirect(url_for('auth.login'))


def _sign_in(player, identity=None):
    session.clear()
    login_user(player)
    session['credential_version'] = player.credential_version
    if identity:
        session['identity_version'] = identity['version']
    return redirect(url_for('admin.dashboard') if player.is_admin else url_for('player.dashboard'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard') if current_user.is_admin else url_for('player.dashboard'))
    stage, username = 'username', ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()[:254]
        password = request.form.get('password', '')
        action = request.form.get('action', 'login')
        ip = request.remote_addr or 'unknown'
        limited = current_app.config.get('LOGIN_RATE_LIMIT_ENABLED', False)
        if limited and login_rate_limit.is_limited(ip, username):
            flash('Too many attempts. Please try again in five minutes.', 'error')
            return render_template('auth/login.html', stage=stage, username=username), 429
        player = Player.query.filter_by(username=username).first()
        if player is None:
            player = Player.query.filter_by(shared_email=username.lower()).first()
        use_shared = shared_identity.enabled() and not (player and player.is_admin) and (
            (player and player.shared_email) or '@' in username)
        identity = None
        try:
            if use_shared:
                email = player.shared_email if player and player.shared_email else username.lower()
                identity = shared_identity.call('lookup', email=email)
                if 'error' in identity:
                    flash('Ask your teacher to add this email or username first.', 'error')
                else:
                    stage = 'password' if identity['password_set'] else 'create'
            elif player:
                stage = 'password' if player.password_hash else 'create'
            else:
                check_password_hash(_dummy_password_hash, password)
                flash('Ask your teacher to add this email or username first.', 'error')

            if stage != 'username' and action != 'continue':
                error = None
                if stage == 'create':
                    if action != 'create':
                        error = 'Choose your password below to finish your first sign-in.'
                    elif not 8 <= len(password) <= 256:
                        error = 'Choose a password of 8–256 characters.'
                    elif password != request.form.get('password_confirm', ''):
                        error = 'The passwords do not match.'
                    elif use_shared:
                        identity = shared_identity.call('setup', email=email, password=password)
                        error = identity.get('error')
                    else:
                        # Compare-and-set prevents two first-login submissions replacing each other.
                        result = db.session.execute(update(Player).where(
                            Player.id == player.id, Player.password_hash == ''
                        ).values(password_hash=generate_password_hash(password),
                                 credential_version=Player.credential_version + 1))
                        if result.rowcount != 1:
                            error = 'Your sign-in changed. Please start again.'
                        db.session.commit()
                elif use_shared:
                    identity = shared_identity.call('authenticate', email=email, password=password)
                    error = identity.get('error')
                elif not player.check_password(password):
                    error = 'Password not recognised. Try again or ask your teacher to reset it.'
                if error:
                    flash(error, 'error')
                else:
                    if use_shared:
                        linked = Player.query.filter_by(shared_identity_id=identity['id']).first()
                        if linked:
                            player = linked
                        elif player is None:
                            alias = email if len(email) <= 64 else 'student-' + hashlib.sha256(email.encode()).hexdigest()[:24]
                            player = Player(username=alias, password_hash='', is_admin=False,
                                            avatar_gender_selected=False)
                            db.session.add(player)
                            db.session.flush()
                            reset_player_to_starting_state(player)
                        player.shared_email = identity['email']
                        player.shared_identity_id = identity['id']
                        db.session.commit()
                    if limited:
                        login_rate_limit.clear_pair(ip, username)
                    return _sign_in(player, identity if use_shared else None)
        except shared_identity.IdentityUnavailable as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return render_template('auth/login.html', stage='username', username=username), 503
        except IntegrityError:
            db.session.rollback()
            flash('Your account changed during sign-in. Please try again.', 'error')
        if limited and (stage == 'username' or action != 'continue'):
            login_rate_limit.record_failure(ip, username)
    return render_template('auth/login.html', stage=stage, username=username)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
