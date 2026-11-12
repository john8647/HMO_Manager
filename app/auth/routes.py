from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'tenant':
            return redirect(url_for('portal.index'))
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been disabled. Contact the administrator.', 'error')
                return redirect(url_for('auth.login'))
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.username}!', 'success')
            # Tenants go to their portal, everyone else to the dashboard
            if user.role == 'tenant':
                return redirect(next_page or url_for('portal.index'))
            return redirect(next_page or url_for('dashboard.index'))
        else:
            flash('Incorrect username or password.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Only admin can access registration directly
    # Later: invite-based registration for tenants
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        role = request.form.get('role', 'landlord')

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
            errors.append('That username is already taken.')
        if User.query.filter_by(email=email).first():
            errors.append('That email is already registered.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html',
                                   username=username, email=email, role=role)

        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash(f'Account created for {username}. They can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'error')
        elif len(new_password) < 8:
            flash('New password must be at least 8 characters.', 'error')
        elif new_password != confirm:
            flash('New passwords do not match.', 'error')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Password changed successfully.', 'success')
            if current_user.role == 'tenant':
                return redirect(url_for('portal.index'))
            return redirect(url_for('dashboard.index'))

    return render_template('auth/change_password.html')
