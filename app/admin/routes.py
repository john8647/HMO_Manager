from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request)
from flask_login import login_required, current_user
from app.utils import landlord_required
from functools import wraps
from datetime import datetime
from app import db
from app.models import User, Tenant, Property

admin_bp = Blueprint('admin', __name__)


# ── Admin-only decorator ──────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('You need administrator access to view that page.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@login_required
@landlord_required
@admin_required
def index():
    users     = User.query.order_by(User.role, User.username).all()
    landlords = [u for u in users if u.role == 'landlord']
    admins    = [u for u in users if u.role == 'admin']
    tenants   = [u for u in users if u.role == 'tenant']

    # Count linked data per landlord
    for u in landlords:
        u.property_count = Property.query.filter_by(user_id=u.id).count()
        u.tenant_count   = Tenant.query.filter_by(user_id=u.id).count()

    # Count linked tenant records per portal user
    for u in tenants:
        u.linked_tenant = Tenant.query.filter_by(portal_user_id=u.id).first()

    stats = {
        'total_users':     len(users),
        'total_landlords': len(landlords),
        'total_admins':    len(admins),
        'total_tenants':   len(tenants),
        'total_properties': Property.query.count(),
        'total_tenants_db': Tenant.query.count(),
    }

    return render_template('admin/index.html',
                           landlords=landlords,
                           admins=admins,
                           tenant_users=tenants,
                           stats=stats)


# ── Create landlord user ──────────────────────────────────────────────────────

@admin_bp.route('/landlord/add', methods=['GET', 'POST'])
@login_required
@landlord_required
@admin_required
def add_landlord():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')

        errors = []
        if not username:
            errors.append('Username is required.')
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')
        if User.query.filter_by(username=username).first():
            errors.append(f'Username "{username}" is already taken.')
        if User.query.filter_by(email=email).first():
            errors.append(f'Email "{email}" is already registered.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('admin/add_landlord.html',
                                   username=username, email=email)

        user = User(username=username, email=email, role='landlord')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(
            f'Landlord account "{username}" created successfully. '
            f'They can now log in and add their own properties and tenants.',
            'success'
        )
        return redirect(url_for('admin.index'))

    return render_template('admin/add_landlord.html')


# ── Invite tenant portal user ─────────────────────────────────────────────────

@admin_bp.route('/tenant/invite', methods=['GET', 'POST'])
@login_required
@landlord_required
@admin_required
def invite_tenant():
    # Only tenants without a portal account
    unlinked_tenants = Tenant.query.filter_by(
        portal_user_id=None
    ).order_by(Tenant.last_name).all()

    if request.method == 'POST':
        tenant_id = request.form.get('tenant_id', '').strip()
        username  = request.form.get('username', '').strip()
        email     = request.form.get('email', '').strip().lower()
        password  = request.form.get('password', '')
        confirm   = request.form.get('confirm_password', '')

        errors = []
        if not tenant_id:
            errors.append('Tenant record is required.')
        if not username:
            errors.append('Username is required.')
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')
        if User.query.filter_by(username=username).first():
            errors.append(f'Username "{username}" is already taken.')
        if User.query.filter_by(email=email).first():
            errors.append(f'Email "{email}" is already registered.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('admin/invite_tenant.html',
                                   unlinked_tenants=unlinked_tenants,
                                   username=username, email=email,
                                   selected_tenant_id=tenant_id)

        # Create portal user
        portal_user = User(
            username=username,
            email=email,
            role='tenant',
        )
        portal_user.set_password(password)
        db.session.add(portal_user)
        db.session.flush()

        # Link to tenant record
        tenant = Tenant.query.get_or_404(int(tenant_id))
        tenant.portal_user_id = portal_user.id

        db.session.commit()
        flash(
            f'Portal account created for {tenant.full_name}. '
            f'They can log in at /auth/login with username "{username}".',
            'success'
        )
        return redirect(url_for('admin.index'))

    return render_template('admin/invite_tenant.html',
                           unlinked_tenants=unlinked_tenants)


# ── Edit user ─────────────────────────────────────────────────────────────────

@admin_bp.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@landlord_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    # Prevent editing own account here — use change_password instead
    if user.id == current_user.id:
        flash('To edit your own account use the Change Password page.', 'info')
        return redirect(url_for('admin.index'))

    if request.method == 'POST':
        new_email    = request.form.get('email', '').strip().lower()
        new_username = request.form.get('username', '').strip()
        new_role     = request.form.get('role', user.role)
        is_active    = request.form.get('is_active') == 'on'
        new_password = request.form.get('new_password', '').strip()

        errors = []
        if not new_username:
            errors.append('Username is required.')
        if not new_email:
            errors.append('Email is required.')

        # Check uniqueness excluding this user
        existing_user = User.query.filter_by(username=new_username).first()
        if existing_user and existing_user.id != user.id:
            errors.append(f'Username "{new_username}" is already taken.')

        existing_email = User.query.filter_by(email=new_email).first()
        if existing_email and existing_email.id != user.id:
            errors.append(f'Email "{new_email}" is already registered.')

        if new_password and len(new_password) < 8:
            errors.append('New password must be at least 8 characters.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('admin/edit_user.html', user=user)

        user.username  = new_username
        user.email     = new_email
        user.role      = new_role
        user.is_active = is_active

        if new_password:
            user.set_password(new_password)
            flash('Password updated.', 'info')

        db.session.commit()
        flash(f'User "{user.username}" updated.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('admin/edit_user.html', user=user)


# ── Deactivate / reactivate user ──────────────────────────────────────────────

@admin_bp.route('/user/<int:user_id>/toggle', methods=['POST'])
@login_required
@landlord_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'error')
        return redirect(url_for('admin.index'))

    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User "{user.username}" {status}.', 'success')
    return redirect(url_for('admin.index'))


# ── Delete user ───────────────────────────────────────────────────────────────

@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
@login_required
@landlord_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin.index'))

    # Unlink any tenant portal accounts
    linked_tenant = Tenant.query.filter_by(portal_user_id=user.id).first()
    if linked_tenant:
        linked_tenant.portal_user_id = None

    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted.', 'success')
    return redirect(url_for('admin.index'))
