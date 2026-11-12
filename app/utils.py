"""
Shared decorators and helpers used across multiple blueprints.
"""
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user


def landlord_required(f):
    """
    Restrict a route to landlord or admin users only.
    Tenants (role='tenant') are redirected to their portal.
    Unauthenticated users are handled by @login_required (apply that first).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if current_user.role == 'tenant':
            flash('That area is for landlord accounts only.', 'error')
            return redirect(url_for('portal.index'))
        return f(*args, **kwargs)
    return decorated
