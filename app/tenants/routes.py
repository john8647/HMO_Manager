from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import date, datetime
from app import db
from app.models import Tenant, TenantContract, Property, Room

tenants_bp = Blueprint('tenants', __name__)


def get_tenant_or_404(tenant_id):
    return Tenant.query.filter_by(
        id=tenant_id, user_id=current_user.id
    ).first_or_404()


# ── Tenants ──────────────────────────────────────────────────────────────────

@tenants_bp.route('/')
@login_required
def index():
    show = request.args.get('show', 'active')
    if current_user.role == 'admin':
        query = Tenant.query
    else:
        query = Tenant.query.filter_by(user_id=current_user.id)

    if show == 'inactive':
        tenants = query.filter_by(is_active=False).order_by(Tenant.last_name).all()
    else:
        tenants = query.filter_by(is_active=True).order_by(Tenant.last_name).all()

    # Attach active contract to each tenant for display
    for tenant in tenants:
        tenant.active_contract = TenantContract.query.filter_by(
            tenant_id=tenant.id, is_active=True
        ).first()

    return render_template('tenants/index.html', tenants=tenants, show=show)


@tenants_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    properties = Property.query.filter_by(user_id=current_user.id).all()

    if request.method == 'POST':
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
        council_tax_ref    = request.form.get('council_tax_ref', '').strip()
        council_tax_number = request.form.get('council_tax_number', '').strip()
        right_to_rent_ref  = request.form.get('right_to_rent_ref', '').strip()
        home_address = request.form.get('home_address', '').strip()
        home_country = request.form.get('home_country', '').strip()
        gdpr_consent = request.form.get('gdpr_consent') == 'on'

        if not first_name or not last_name:
            flash('First name and last name are required.', 'error')
            return render_template('tenants/add.html', properties=properties)

        if not gdpr_consent:
            flash('GDPR consent must be confirmed to create a tenant record.', 'error')
            return render_template('tenants/add.html', properties=properties)

        dob = None
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date of birth format.', 'error')
                return render_template('tenants/add.html', properties=properties)

        # Generate invoice account number
        count = Tenant.query.filter_by(user_id=current_user.id).count()
        invoice_account_number = f'T{current_user.id:02d}{count + 1:04d}'

        tenant = Tenant(
            user_id=current_user.id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            date_of_birth=dob,
            nationality=nationality,
            student_status=student_status,
            student_id=student_id,
            university=university,
            course_title=course_title,
            council_tax_ref=council_tax_ref,
            council_tax_number=council_tax_number,
            right_to_rent_ref=right_to_rent_ref,
            home_address=home_address,
            home_country=home_country,
            invoice_account_number=invoice_account_number,
            is_active=True,
            has_left=False,
            gdpr_consent=gdpr_consent,
            gdpr_consent_date=datetime.utcnow() if gdpr_consent else None,
        )
        db.session.add(tenant)
        db.session.commit()
        flash(f'Tenant {tenant.full_name} added. Now create their contract.', 'success')
        return redirect(url_for('tenants.add_contract', tenant_id=tenant.id))

    return render_template('tenants/add.html', properties=properties)


@tenants_bp.route('/<int:tenant_id>')
@login_required
def view(tenant_id):
    tenant = get_tenant_or_404(tenant_id)
    contracts = TenantContract.query.filter_by(
        tenant_id=tenant.id
    ).order_by(TenantContract.start_date.desc()).all()
    active_contract = next((c for c in contracts if c.is_active), None)
    return render_template('tenants/view.html',
                           tenant=tenant,
                           contracts=contracts,
                           active_contract=active_contract,
                           date=date)


@tenants_bp.route('/<int:tenant_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(tenant_id):
    tenant = get_tenant_or_404(tenant_id)

    if request.method == 'POST':
        tenant.first_name    = request.form.get('first_name', '').strip()
        tenant.last_name     = request.form.get('last_name', '').strip()
        tenant.email         = request.form.get('email', '').strip().lower()
        tenant.phone         = request.form.get('phone', '').strip()
        tenant.nationality   = request.form.get('nationality', '').strip()
        tenant.student_status = request.form.get('student_status', 'Non-student')
        tenant.student_id    = request.form.get('student_id', '').strip()
        tenant.university    = request.form.get('university', '').strip()
        tenant.course_title  = request.form.get('course_title', '').strip()
        tenant.council_tax_ref    = request.form.get('council_tax_ref', '').strip()
        tenant.council_tax_number = request.form.get('council_tax_number', '').strip()
        tenant.right_to_rent_ref  = request.form.get('right_to_rent_ref', '').strip()
        tenant.home_address  = request.form.get('home_address', '').strip()
        tenant.home_country  = request.form.get('home_country', '').strip()

        dob_str = request.form.get('date_of_birth', '').strip()
        if dob_str:
            try:
                tenant.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date of birth.', 'error')
                return render_template('tenants/edit.html', tenant=tenant)

        council_in = request.form.get('council_informed_in', '').strip()
        council_out = request.form.get('council_informed_left', '').strip()
        if council_in:
            tenant.council_informed_in = datetime.strptime(council_in, '%Y-%m-%d').date()
        if council_out:
            tenant.council_informed_left = datetime.strptime(council_out, '%Y-%m-%d').date()

        if not tenant.first_name or not tenant.last_name:
            flash('First name and last name are required.', 'error')
            return render_template('tenants/edit.html', tenant=tenant)

        db.session.commit()
        flash('Tenant details updated.', 'success')
        return redirect(url_for('tenants.view', tenant_id=tenant.id))

    return render_template('tenants/edit.html', tenant=tenant)


@tenants_bp.route('/<int:tenant_id>/deactivate', methods=['POST'])
@login_required
def deactivate(tenant_id):
    tenant = get_tenant_or_404(tenant_id)
    tenant.is_active = False
    tenant.has_left = True
    # Deactivate all contracts
    for contract in tenant.contracts:
        if contract.is_active:
            contract.is_active = False
            # Mark room as vacant
            room = Room.query.get(contract.room_id)
            if room:
                room.is_occupied = False
    db.session.commit()
    flash(f'{tenant.full_name} marked as inactive and contracts closed.', 'success')
    return redirect(url_for('tenants.view', tenant_id=tenant.id))


@tenants_bp.route('/<int:tenant_id>/reactivate', methods=['POST'])
@login_required
def reactivate(tenant_id):
    tenant = get_tenant_or_404(tenant_id)
    tenant.is_active = True
    tenant.has_left = False
    db.session.commit()
    flash(f'{tenant.full_name} reactivated. Add a new contract to assign them a room.', 'success')
    return redirect(url_for('tenants.view', tenant_id=tenant.id))


# ── Contracts ────────────────────────────────────────────────────────────────

@tenants_bp.route('/<int:tenant_id>/contracts/add', methods=['GET', 'POST'])
@login_required
def add_contract(tenant_id):
    tenant = get_tenant_or_404(tenant_id)
    properties = Property.query.filter_by(user_id=current_user.id).all()

    # Build room options — only vacant rooms or currently assigned room
    selected_property_id = request.form.get('property_id') or request.args.get('property_id')
    rooms = []
    if selected_property_id:
        rooms = Room.query.filter_by(
            property_id=selected_property_id, is_occupied=False
        ).all()

    if request.method == 'POST':
        property_id   = request.form.get('property_id')
        room_id       = request.form.get('room_id')
        start_date_str = request.form.get('start_date', '').strip()
        end_date_str   = request.form.get('end_date', '').strip()
        renewal_str    = request.form.get('renewal_date', '').strip()
        monthly_rent   = request.form.get('monthly_rent', '').strip()
        advanced_rent  = request.form.get('advanced_rent_agreed', '0').strip()

        errors = []
        if not property_id:
            errors.append('Property is required.')
        if not room_id:
            errors.append('Room is required.')
        if not start_date_str:
            errors.append('Start date is required.')
        if not monthly_rent:
            errors.append('Monthly rent is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('tenants/add_contract.html',
                                   tenant=tenant, properties=properties, rooms=rooms)

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date   = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
            renewal_date = datetime.strptime(renewal_str, '%Y-%m-%d').date() if renewal_str else None
            monthly_rent_val = float(monthly_rent)
            advanced_rent_val = float(advanced_rent) if advanced_rent else 0.0
        except ValueError:
            flash('Invalid date or amount format.', 'error')
            return render_template('tenants/add_contract.html',
                                   tenant=tenant, properties=properties, rooms=rooms)

        # Deactivate any existing active contracts for this tenant
        for old in TenantContract.query.filter_by(tenant_id=tenant.id, is_active=True).all():
            old.is_active = False
            old_room = Room.query.get(old.room_id)
            if old_room:
                old_room.is_occupied = False

        contract = TenantContract(
            tenant_id=tenant.id,
            property_id=int(property_id),
            room_id=int(room_id),
            user_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
            renewal_date=renewal_date,
            monthly_rent=monthly_rent_val,
            frequency='monthly',
            next_rent_due=start_date,
            advanced_rent_agreed=advanced_rent_val,
            remaining_advance_rent=advanced_rent_val,
            is_active=True,
        )
        db.session.add(contract)

        # Mark room as occupied
        room = Room.query.get(int(room_id))
        if room:
            room.is_occupied = True

        db.session.commit()
        flash(f'Contract created for {tenant.full_name}.', 'success')
        return redirect(url_for('tenants.view', tenant_id=tenant.id))

    return render_template('tenants/add_contract.html',
                           tenant=tenant, properties=properties, rooms=rooms,
                           selected_property_id=selected_property_id)


@tenants_bp.route('/<int:tenant_id>/contracts/<int:contract_id>/end', methods=['POST'])
@login_required
def end_contract(tenant_id, contract_id):
    tenant = get_tenant_or_404(tenant_id)
    contract = TenantContract.query.filter_by(
        id=contract_id, tenant_id=tenant.id
    ).first_or_404()

    end_date_str = request.form.get('end_date', '').strip()
    if end_date_str:
        try:
            contract.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid end date.', 'error')
            return redirect(url_for('tenants.view', tenant_id=tenant.id))

    contract.is_active = False
    room = Room.query.get(contract.room_id)
    if room:
        room.is_occupied = False

    db.session.commit()
    flash('Contract ended and room marked as vacant.', 'success')
    return redirect(url_for('tenants.view', tenant_id=tenant.id))
