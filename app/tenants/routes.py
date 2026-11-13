from flask import Blueprint, render_template, redirect, url_for, flash, request, \
    send_from_directory, abort
from flask_login import login_required, current_user
from app.utils import landlord_required
from datetime import date, datetime
import os
from werkzeug.utils import secure_filename
from app import db
from app.models import Tenant, TenantContract, Property, Room, Task, Transaction
from decimal import Decimal

CONTRACT_UPLOAD_FOLDER = 'app/static/uploads/contracts'
CONTRACT_ALLOWED_EXT   = {'pdf', 'jpg', 'jpeg', 'png'}

tenants_bp = Blueprint('tenants', __name__)


def _save_contract_file(file_obj, tenant_id):
    """Save an uploaded contract file; return stored filename or None."""
    if not file_obj or not file_obj.filename:
        return None
    ext = file_obj.filename.rsplit('.', 1)[-1].lower()
    if ext not in CONTRACT_ALLOWED_EXT:
        return None
    os.makedirs(CONTRACT_UPLOAD_FOLDER, exist_ok=True)
    filename = secure_filename(
        f'contract_tenant{tenant_id}_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}.{ext}'
    )
    file_obj.save(os.path.join(CONTRACT_UPLOAD_FOLDER, filename))
    return filename


def _ensure_contract_tasks(contract, tenant, user_id):
    """
    Create (or update) Tasks for renewal and end dates on the contract.
    Idempotent — skips if a task with the same title already exists.
    """
    for attr, label in [('renewal_date', 'Contract Renewal'),
                         ('end_date',     'Contract End')]:
        due = getattr(contract, attr)
        if not due:
            continue
        title = f'{label} — {tenant.full_name}'
        existing = Task.query.filter_by(
            user_id=user_id,
            tenant_id=tenant.id,
            title=title,
        ).filter(Task.status.in_(['open', 'in_progress'])).first()
        if existing:
            existing.due_date = due          # update if date changed
        else:
            task = Task(
                user_id=user_id,
                tenant_id=tenant.id,
                property_id=contract.property_id,
                room_id=contract.room_id,
                title=title,
                description=(
                    f'Contract for {tenant.full_name} at '
                    f'{contract.property.address_line1}, '
                    f'{contract.room.room_name}. '
                    f'{label} date: {due.strftime("%d %b %Y")}.'
                ),
                priority='high',
                status='open',
                due_date=due,
            )
            db.session.add(task)


def get_tenant_or_404(tenant_id):
    return Tenant.query.filter_by(
        id=tenant_id, user_id=current_user.id
    ).first_or_404()


# ── Tenants ──────────────────────────────────────────────────────────────────

@tenants_bp.route('/')
@login_required
@landlord_required
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
@landlord_required
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
@landlord_required
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
@landlord_required
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
@landlord_required
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
@landlord_required
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
@landlord_required
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
        property_id    = request.form.get('property_id')
        room_id        = request.form.get('room_id')
        start_date_str = request.form.get('start_date', '').strip()
        end_date_str   = request.form.get('end_date', '').strip()
        renewal_str    = request.form.get('renewal_date', '').strip()
        monthly_rent   = request.form.get('monthly_rent', '').strip()
        advanced_rent  = request.form.get('advanced_rent_agreed', '0').strip()
        uploaded_file  = request.files.get('contract_file')

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

        file_path = _save_contract_file(uploaded_file, tenant.id)

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
            contract_file_path=file_path,
        )
        db.session.add(contract)

        # Mark room as occupied
        room = Room.query.get(int(room_id))
        if room:
            room.is_occupied = True

        db.session.flush()   # get contract.id before creating tasks
        _ensure_contract_tasks(contract, tenant, current_user.id)
        db.session.commit()

        messages = []

        # 1. Auto-generate rent charges from contract start to today
        try:
            from app.invoices.rent_engine import generate_rent_charges
            from app.models import Transaction as Tx
            from decimal import Decimal as D

            charges = generate_rent_charges(user_id=current_user.id)
            tenant_charges = [
                c for c in charges if c['contract_id'] == contract.id
            ]
            if tenant_charges:
                messages.append(
                    f'{len(tenant_charges)} rent charge(s) generated '
                    f'({tenant_charges[0]["period"]} to '
                    f'{tenant_charges[-1]["period"]})'
                )
        except Exception as e:
            messages.append(
                f'Rent charges could not be auto-generated ({e}) — '
                f'run manually from Rent Roll'
            )

        # 2. Create Advanced Rent debit charge if agreed on contract
        if advanced_rent_val and advanced_rent_val > 0:
            try:
                from app.models import Transaction as Tx
                from decimal import Decimal as D
                adv_amount = D(str(advanced_rent_val))
                adv_charge = Tx(
                    tenant_id=tenant.id,
                    contract_id=contract.id,
                    amount=adv_amount,
                    credit_debit='db',
                    transaction_date=start_date,
                    user_id=current_user.id,
                    type='Advanced Rent',
                    month_year_period=start_date.strftime('%B %Y'),
                    source='system',
                    is_matched=True,
                    notes=(
                        f'Advanced Rent — {contract.room.room_name} '
                        f'({contract.property.address_line1})'
                    ),
                )
                db.session.add(adv_charge)

                # Add to tenant rent balance so it shows as outstanding
                tenant.rent_balance = (
                    D(str(tenant.rent_balance or 0)) + adv_amount
                )
                db.session.commit()
                messages.append(
                    f'Advanced rent charge of £{adv_amount:.2f} created'
                )
            except Exception as e:
                messages.append(f'Advanced rent charge failed ({e})')

        msg = f'Contract created for {tenant.full_name}.'
        if messages:
            msg += ' ' + '; '.join(messages) + '.'
        flash(msg, 'success')
        return redirect(url_for('tenants.view', tenant_id=tenant.id))

    return render_template('tenants/add_contract.html',
                           tenant=tenant, properties=properties, rooms=rooms,
                           selected_property_id=selected_property_id)


@tenants_bp.route('/<int:tenant_id>/contracts/<int:contract_id>/end', methods=['POST'])
@login_required
@landlord_required
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


@tenants_bp.route('/<int:tenant_id>/contracts/<int:contract_id>/edit',
                  methods=['GET', 'POST'])
@login_required
@landlord_required
def edit_contract(tenant_id, contract_id):
    tenant   = get_tenant_or_404(tenant_id)
    contract = TenantContract.query.filter_by(
        id=contract_id, tenant_id=tenant.id
    ).first_or_404()

    if request.method == 'POST':
        action        = request.form.get('action', 'save')   # 'save' | 'close'
        renewal_str   = request.form.get('renewal_date', '').strip()
        end_date_str  = request.form.get('end_date', '').strip()
        uploaded_file = request.files.get('contract_file')

        try:
            contract.renewal_date = (
                datetime.strptime(renewal_str, '%Y-%m-%d').date()
                if renewal_str else None
            )
            contract.end_date = (
                datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if end_date_str else None
            )
        except ValueError:
            flash('Invalid date format.', 'error')
            return render_template('tenants/edit_contract.html',
                                   tenant=tenant, contract=contract)

        # Replace document if a new one was uploaded
        new_file = _save_contract_file(uploaded_file, tenant.id)
        if new_file:
            if contract.contract_file_path:
                old = os.path.join(CONTRACT_UPLOAD_FOLDER,
                                   contract.contract_file_path)
                if os.path.exists(old):
                    os.remove(old)
            contract.contract_file_path = new_file

        # ── Contract Closure ─────────────────────────────────────────────
        if action == 'close':
            closure_type   = request.form.get('closure_type', '').strip()
            notice_str     = request.form.get('notice_end_date', '').strip()
            surrender_str  = request.form.get('surrender_date', '').strip()
            closure_notes  = request.form.get('closure_notes', '').strip()

            if closure_type not in ('notice', 'surrender'):
                flash('Please select a closure type (Notice or Surrender).', 'error')
                return render_template('tenants/edit_contract.html',
                                       tenant=tenant, contract=contract)

            try:
                if closure_type == 'notice':
                    if not notice_str:
                        flash('Notice End Date is required.', 'error')
                        return render_template('tenants/edit_contract.html',
                                               tenant=tenant, contract=contract)
                    true_end = datetime.strptime(notice_str, '%Y-%m-%d').date()
                    contract.notice_end_date = true_end
                else:  # surrender
                    if not surrender_str:
                        flash('Surrender Date is required.', 'error')
                        return render_template('tenants/edit_contract.html',
                                               tenant=tenant, contract=contract)
                    true_end = datetime.strptime(surrender_str, '%Y-%m-%d').date()
                    contract.surrender_date = true_end
            except ValueError:
                flash('Invalid closure date.', 'error')
                return render_template('tenants/edit_contract.html',
                                       tenant=tenant, contract=contract)

            contract.closure_type  = closure_type
            contract.closure_notes = closure_notes
            contract.end_date      = true_end   # canonical end date
            contract.is_active     = False

            # Mark room as vacant
            room = Room.query.get(contract.room_id)
            if room:
                room.is_occupied = False

            # ── Zero out future rent debits beyond true_end ───────────────
            # These are system-generated charges for periods that will not now
            # be served.  Setting amount to 0 keeps the audit trail but removes
            # the financial liability.  A note records why.
            future_debits = Transaction.query.filter(
                Transaction.tenant_id   == tenant.id,
                Transaction.credit_debit == 'db',
                Transaction.type         == 'Rent',
                Transaction.transaction_date > true_end,
            ).all()

            zeroed = 0
            for tx in future_debits:
                if tx.amount and Decimal(str(tx.amount)) > 0:
                    tx.amount = Decimal('0.00')
                    tx.notes  = (
                        f'Zeroed on contract closure ({closure_type}) — '
                        f'true end {true_end.strftime("%d %b %Y")}. '
                        + (tx.notes or '')
                    )
                    zeroed += 1

            db.session.commit()

            msg = f'Contract closed ({closure_type}). True end date: {true_end.strftime("%d %b %Y")}.'
            if zeroed:
                msg += f' {zeroed} future charge(s) set to £0.'
            flash(msg, 'success')
            return redirect(url_for('tenants.view', tenant_id=tenant.id))
        # ── End Contract Closure ─────────────────────────────────────────

        # Regular save
        _ensure_contract_tasks(contract, tenant, current_user.id)
        db.session.commit()
        flash('Contract updated.', 'success')
        return redirect(url_for('tenants.view', tenant_id=tenant.id))

    return render_template('tenants/edit_contract.html',
                           tenant=tenant, contract=contract)


@tenants_bp.route('/<int:tenant_id>/contracts/<int:contract_id>/download')
@login_required
@landlord_required
def download_contract(tenant_id, contract_id):
    tenant   = get_tenant_or_404(tenant_id)
    contract = TenantContract.query.filter_by(
        id=contract_id, tenant_id=tenant.id
    ).first_or_404()
    if not contract.contract_file_path:
        abort(404)
    return send_from_directory(
        os.path.abspath(CONTRACT_UPLOAD_FOLDER),
        contract.contract_file_path,
        as_attachment=False,
    )
