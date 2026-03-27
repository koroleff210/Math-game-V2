# app/decorators.py
#
# Reusable route decorators for access control.
# Apply these on top of @login_required from Flask-Login.

from functools import wraps
from flask import abort
from flask_login import current_user


def admin_required(f):
    """Restrict a route to admin users only.

    Must be applied *after* @login_required so current_user is already set.
    Returns 403 Forbidden if the logged-in user is not an admin.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated
