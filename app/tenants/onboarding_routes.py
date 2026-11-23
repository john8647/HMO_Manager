"""
Tenant Onboarding Link routes
─────────────────────────────
Two public + one landlord-only endpoint:

  POST /tenants/<id>/generate-onboarding-link   (landlord, login required)
       Creates a TenantOnboardingToken and returns the link in the page.

  GET  /onboard/<token>                          (public)
       Shows the self-service form.

  POST /onboard/<token>                          (public)
       Processes the submission: fills in the tenant record, creates a
       portal User account, and marks the token as used.
"""
import secrets
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort, jsonify)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from app import db
from app.models import Tenant, User
from app.utils import landlord_required

onboarding_bp = Blueprint('onboarding', __name__)

# ── Token model is imported inline to avoid circular import issues ────────────
def _get_token_model():
    from app.models import TenantOnboardingToken
    return TenantOnboardingToken


# ─────────────────────────────────────────────────────────────────────────────
# Landlord: generate a one-time onboarding link
# ─────────────────────────────────────────────────────────────────────────────

@onboarding_bp.route('/tenants/<int:tenant_id>/generate-onboarding-link', methods=['POST'])
@login_required
@landlord_required
def generate_link(tenant_id):
    tenant = Tenant.query.filter_by(
        id=tenant_id, user_id=current_user.id
    ).first_or_404()

    TenantOnboardingToken = _get_token_model()

    # Expire any previous unused tokens for this tenant
    TenantOnboardingToken.query.filter_by(
        tenant_id=tenant.id, used_at=None
    ).update({'expires_at': datetime.utcnow()})
    db.session.flush()

    token_str = secrets.token_urlsafe(40)
    tok = TenantOnboardingToken(
        token=token_str,
        tenant_id=tenant.id,
        landlord_id=current_user.id,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.session.add(tok)
    db.session.commit()

    link = url_for('onboarding.onboard_form', token=token_str, _external=True)
    return render_template(
        'tenants/onboarding_link.html',
        tenant=tenant,
        link=link,
        expires_at=tok.expires_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public: tenant self-service form
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_token(token_str):
    """Return the token object or abort with 404/410."""
    TenantOnboardingToken = _get_token_model()
    tok = TenantOnboardingToken.query.filter_by(token=token_str).first()
    if tok is None:
        abort(404)
    if tok.used_at is not None:
        abort(410)   # Gone — already used
    if tok.expires_at < datetime.utcnow():
        abort(410)   # Gone — expired
    return tok


@onboarding_bp.route('/onboard/<token>', methods=['GET', 'POST'])
def onboard_form(token):
    tok = _resolve_token(token)
    tenant = Tenant.query.get_or_404(tok.tenant_id)

    if request.method == 'GET':
        return render_template('tenants/onboarding_form.html',
                               tenant=tenant, token=token)

    # ── POST: process the submission ─────────────────────────────────────────
    errors = []

    # Portal account fields
    portal_username = request.form.get('portal_username', '').strip()
    portal_password = request.form.get('portal_password', '').strip()
    portal_password2 = request.form.get('portal_password2', '').strip()

    if not portal_username:
        errors.append('Username is required.')
    elif User.query.filter_by(username=portal_username).first():
        errors.append('That username is already taken — please choose another.')

    if not portal_password:
        errors.append('Password is required.')
    elif len(portal_password) < 8:
        errors.append('Password must be at least 8 characters.')
    elif portal_password != portal_password2:
        errors.append('Passwords do not match.')

    # Personal details
    first_name   = request.form.get('first_name', '').strip()
    last_name    = request.form.get('last_name', '').strip()
    email        = request.form.get('email', '').strip().lower()
    phone        = request.form.get('phone', '').strip()
    dob_str      = request.form.get('date_of_birth', '').strip()
    nationality  = request.form.get('nationality', '').strip()
    student_status = request.form.get('student_status', 'Non-student')
    student_id   = request.form.get('student_id', '').strip()
    university   = request.form.get('university', '').strip()
    course_title = request.form.get('course_title', '').strip()
    home_address = request.form.get('home_address', '').strip()
    home_country = request.form.get('home_country', '').strip()
    share_code   = request.form.get('share_code', '').strip()
    gdpr_consent = request.form.get('gdpr_consent') == 'on'

    if not first_name or not last_name:
        errors.append('First name and last name are required.')
    if not email:
        errors.append('Email address is required.')
    if not gdpr_consent:
        errors.append('You must give your consent to continue.')

    dob = None
    if dob_str:
        try:
            from datetime import datetime as _dt
            dob = _dt.strptime(dob_str, '%Y-%m-%d').date()
        except ValueError:
            errors.append('Invalid date of birth format.')

    if errors:
        for e in errors:
            flash(e, 'error')
        return render_template('tenants/onboarding_form.html',
                               tenant=tenant, token=token)

    # ── All good — update tenant record ──────────────────────────────────────
    tenant.first_name     = first_name
    tenant.last_name      = last_name
    tenant.email          = email
    tenant.phone          = phone
    tenant.date_of_birth  = dob
    tenant.nationality    = nationality
    tenant.student_status = student_status
    tenant.student_id     = student_id
    tenant.university     = university
    tenant.course_title   = course_title
    tenant.home_address   = home_address
    tenant.home_country   = home_country
    tenant.right_to_rent_ref = share_code   # Share Code stored as right_to_rent_ref
    tenant.gdpr_consent   = True
    tenant.gdpr_consent_date = datetime.utcnow()

    # ── Create portal user account ───────────────────────────────────────────
    portal_user = User(
        username=portal_username,
        email=email,
        role='tenant',
        is_active=True,
    )
    portal_user.set_password(portal_password)
    db.session.add(portal_user)
    db.session.flush()   # get portal_user.id

    tenant.portal_user_id = portal_user.id

    # ── Mark token as used ───────────────────────────────────────────────────
    tok.used_at = datetime.utcnow()

    db.session.commit()

    return render_template('tenants/onboarding_complete.html',
                           tenant=tenant, portal_username=portal_username)
