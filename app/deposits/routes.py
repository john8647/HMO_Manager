from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, send_from_directory, Response)
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
import os
from werkzeug.utils import secure_filename
from app import db
from app.models import Deposit, Tenant, TenantContract

deposits_bp = Blueprint('deposits', __name__)

UPLOAD_FOLDER  = 'app/static/uploads/deposits'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

DPS_COMPANIES = [
    'Deposit Protection Service (DPS)',
    'MyDeposits',
    'Tenancy Deposit Scheme (TDS)',
    'Other',
]

STATUSES = [
    ('pending',    'Pending',   'Deposit received but not yet registered with a scheme'),
    ('protected',  'Protected', 'Registered and protected with a DPS scheme'),
    ('paid',       'Paid',      'Deposit returned to tenant in full'),
    ('deducting',  'Deducting', 'Deductions being assessed before return'),
    ('withdrawn',  'Withdrawn', 'Deposit retained — breach of contract'),
]


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_deposit_or_404(deposit_id):
    return Deposit.query.join(Tenant).filter(
        Deposit.id == deposit_id,
        Tenant.user_id == current_user.id
    ).first_or_404()


# ── List ──────────────────────────────────────────────────────────────────────

@deposits_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        deposits = Deposit.query.order_by(Deposit.date_received.desc()).all()
    else:
        deposits = Deposit.query.join(Tenant).filter(
            Tenant.user_id == current_user.id
        ).order_by(Deposit.date_received.desc()).all()

    # Summary counts
    counts = {s[0]: 0 for s in STATUSES}
    total_held = Decimal('0.00')
    for d in deposits:
        if d.status in counts:
            counts[d.status] += 1
        if d.status in ('pending', 'protected', 'deducting'):
            total_held += Decimal(str(d.amount or 0))

    return render_template('deposits/index.html',
                           deposits=deposits,
                           counts=counts,
                           total_held=total_held,
                           statuses=STATUSES)


# ── Add ───────────────────────────────────────────────────────────────────────

@deposits_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if current_user.role == 'admin':
        tenants = Tenant.query.order_by(Tenant.last_name).all()
    else:
        tenants = Tenant.query.filter_by(
            user_id=current_user.id
        ).order_by(Tenant.last_name).all()

    # Pre-fill from query string (e.g. linked from tenant page)
    prefill_tenant = request.args.get('tenant_id', '')

    if request.method == 'POST':
        tenant_id      = request.form.get('tenant_id', '').strip()
        contract_id    = request.form.get('contract_id', '').strip()
        amount_str     = request.form.get('amount', '').strip()
        dps_scheme     = request.form.get('dps_scheme', '').strip()
        dps_reference  = request.form.get('dps_reference', '').strip()
        date_received_s = request.form.get('date_received', '').strip()
        date_protected_s = request.form.get('date_protected', '').strip()
        status         = request.form.get('status', 'pending').strip()
        notes          = request.form.get('notes', '').strip()

        errors = []
        if not tenant_id:
            errors.append('Tenant is required.')
        if not amount_str:
            errors.append('Deposit amount is required.')
        if not date_received_s:
            errors.append('Date received is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('deposits/add.html',
                                   tenants=tenants,
                                   dps_companies=DPS_COMPANIES,
                                   statuses=STATUSES,
                                   prefill_tenant=prefill_tenant)

        try:
            amount = Decimal(amount_str)
            date_received = datetime.strptime(date_received_s, '%Y-%m-%d').date()
            date_protected = (
                datetime.strptime(date_protected_s, '%Y-%m-%d').date()
                if date_protected_s else None
            )
        except ValueError:
            flash('Invalid amount or date.', 'error')
            return render_template('deposits/add.html',
                                   tenants=tenants,
                                   dps_companies=DPS_COMPANIES,
                                   statuses=STATUSES,
                                   prefill_tenant=prefill_tenant)

        # Handle file upload
        file_path = None
        uploaded_file = request.files.get('document_file')
        if uploaded_file and uploaded_file.filename:
            if not allowed_file(uploaded_file.filename):
                flash('Only PDF, JPG and PNG files are allowed.', 'error')
                return render_template('deposits/add.html',
                                       tenants=tenants,
                                       dps_companies=DPS_COMPANIES,
                                       statuses=STATUSES,
                                       prefill_tenant=prefill_tenant)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            filename = secure_filename(
                f'deposit_tenant{tenant_id}'
                f'_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'
                f'.{uploaded_file.filename.rsplit(".",1)[1].lower()}'
            )
            uploaded_file.save(os.path.join(UPLOAD_FOLDER, filename))
            file_path = filename

        deposit = Deposit(
            tenant_id=int(tenant_id),
            contract_id=int(contract_id) if contract_id else None,
            amount=amount,
            dps_scheme=dps_scheme,
            dps_reference=dps_reference,
            date_received=date_received,
            status=status,
            notes=notes,
        )

        # Store protected date and file in notes/file_path fields
        # (using existing schema fields)
        if date_protected:
            deposit.notes = (
                f'Protected: {date_protected.strftime("%d %b %Y")}. '
                + (notes or '')
            ).strip()

        if file_path:
            # Store in dps_reference field extension or notes
            # Schema has no file_path — store in notes as a reference
            # We'll add file_path to the model via migration
            deposit.notes = (deposit.notes or '') + f' | file:{file_path}'

        db.session.add(deposit)
        db.session.commit()
        flash(
            f'Deposit of £{amount} recorded for '
            f'{Tenant.query.get(int(tenant_id)).full_name}.',
            'success'
        )
        return redirect(url_for('deposits.view', deposit_id=deposit.id))

    # Load contracts for pre-filled tenant
    contracts = []
    if prefill_tenant:
        contracts = TenantContract.query.filter_by(
            tenant_id=int(prefill_tenant)
        ).order_by(TenantContract.start_date.desc()).all()

    return render_template('deposits/add.html',
                           tenants=tenants,
                           dps_companies=DPS_COMPANIES,
                           statuses=STATUSES,
                           prefill_tenant=prefill_tenant,
                           contracts=contracts)


# ── View ──────────────────────────────────────────────────────────────────────

@deposits_bp.route('/<int:deposit_id>')
@login_required
def view(deposit_id):
    deposit = get_deposit_or_404(deposit_id)
    return render_template('deposits/view.html',
                           deposit=deposit,
                           statuses=STATUSES,
                           dps_companies=DPS_COMPANIES)


# ── Edit ──────────────────────────────────────────────────────────────────────

@deposits_bp.route('/<int:deposit_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(deposit_id):
    deposit = get_deposit_or_404(deposit_id)

    if current_user.role == 'admin':
        tenants = Tenant.query.order_by(Tenant.last_name).all()
    else:
        tenants = Tenant.query.filter_by(
            user_id=current_user.id
        ).order_by(Tenant.last_name).all()

    contracts = TenantContract.query.filter_by(
        tenant_id=deposit.tenant_id
    ).order_by(TenantContract.start_date.desc()).all()

    if request.method == 'POST':
        deposit.amount        = Decimal(request.form.get('amount', deposit.amount))
        deposit.dps_scheme    = request.form.get('dps_scheme', '').strip()
        deposit.dps_reference = request.form.get('dps_reference', '').strip()
        deposit.status        = request.form.get('status', deposit.status)
        deposit.notes         = request.form.get('notes', '').strip()

        contract_id = request.form.get('contract_id', '').strip()
        if contract_id:
            deposit.contract_id = int(contract_id)

        date_received_s  = request.form.get('date_received', '').strip()
        date_protected_s = request.form.get('date_protected', '').strip()

        if date_received_s:
            try:
                deposit.date_received = datetime.strptime(
                    date_received_s, '%Y-%m-%d'
                ).date()
            except ValueError:
                flash('Invalid date received.', 'error')
                return render_template('deposits/edit.html',
                                       deposit=deposit, tenants=tenants,
                                       contracts=contracts,
                                       dps_companies=DPS_COMPANIES,
                                       statuses=STATUSES)

        # Handle file upload replacement
        uploaded_file = request.files.get('document_file')
        if uploaded_file and uploaded_file.filename:
            if allowed_file(uploaded_file.filename):
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                filename = secure_filename(
                    f'deposit_{deposit.id}'
                    f'_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'
                    f'.{uploaded_file.filename.rsplit(".",1)[1].lower()}'
                )
                uploaded_file.save(os.path.join(UPLOAD_FOLDER, filename))
                # Append new file reference
                notes = deposit.notes or ''
                # Remove old file reference if present
                import re
                notes = re.sub(r'\s*\|\s*file:\S+', '', notes).strip()
                deposit.notes = notes + f' | file:{filename}'

        # Handle deduction fields
        deduction_amount = request.form.get('deduction_amount', '').strip()
        deduction_reason = request.form.get('deduction_reason', '').strip()
        amount_returned  = request.form.get('amount_returned', '').strip()
        surrender        = request.form.get('surrender_accepted') == 'on'
        surrender_date_s = request.form.get('surrender_date', '').strip()
        returned_date_s  = request.form.get('returned_date', '').strip()

        if deduction_amount:
            deposit.deduction_amount = Decimal(deduction_amount)
        if deduction_reason:
            deposit.deduction_reason = deduction_reason
        if amount_returned:
            deposit.amount_returned = Decimal(amount_returned)

        deposit.surrender_accepted = surrender
        if surrender_date_s:
            try:
                deposit.surrender_date = datetime.strptime(
                    surrender_date_s, '%Y-%m-%d'
                ).date()
            except ValueError:
                pass
        if returned_date_s:
            try:
                deposit.returned_date = datetime.strptime(
                    returned_date_s, '%Y-%m-%d'
                ).date()
            except ValueError:
                pass

        db.session.commit()
        flash('Deposit updated.', 'success')
        return redirect(url_for('deposits.view', deposit_id=deposit.id))

    return render_template('deposits/edit.html',
                           deposit=deposit,
                           tenants=tenants,
                           contracts=contracts,
                           dps_companies=DPS_COMPANIES,
                           statuses=STATUSES)


# ── PDF certificate ───────────────────────────────────────────────────────────

@deposits_bp.route('/<int:deposit_id>/certificate')
@login_required
def certificate(deposit_id):
    deposit = get_deposit_or_404(deposit_id)

    html = render_template('deposits/certificate.html', deposit=deposit)
    try:
        import io
        from xhtml2pdf import pisa
        pdf_buffer = io.BytesIO()
        pisa.CreatePDF(html, dest=pdf_buffer)
        pdf_buffer.seek(0)
        filename = f'Deposit_Certificate_{deposit.tenant.full_name.replace(" ","_")}.pdf'
        return Response(
            pdf_buffer.read(),
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
    except Exception as e:
        flash(f'Certificate generation failed: {e}', 'error')
        return redirect(url_for('deposits.view', deposit_id=deposit.id))


# ── Download attached file ────────────────────────────────────────────────────

@deposits_bp.route('/<int:deposit_id>/download')
@login_required
def download(deposit_id):
    deposit = get_deposit_or_404(deposit_id)
    import re
    match = re.search(r'\|\s*file:(\S+)', deposit.notes or '')
    if not match:
        flash('No file attached to this deposit record.', 'error')
        return redirect(url_for('deposits.view', deposit_id=deposit.id))
    filename = match.group(1)
    return send_from_directory(
        os.path.abspath(UPLOAD_FOLDER),
        filename,
        as_attachment=True
    )


# ── Load contracts for tenant (AJAX) ─────────────────────────────────────────

@deposits_bp.route('/contracts/<int:tenant_id>')
@login_required
def contracts_for_tenant(tenant_id):
    from flask import jsonify
    contracts = TenantContract.query.filter_by(
        tenant_id=tenant_id
    ).order_by(TenantContract.start_date.desc()).all()
    return jsonify([{
        'id':    c.id,
        'label': f'{c.start_date.strftime("%d %b %Y")} — '
                 f'{c.property.address_line1}, {c.room.room_name} '
                 f'(£{c.monthly_rent}/mo)'
    } for c in contracts])


# ── Delete ────────────────────────────────────────────────────────────────────

@deposits_bp.route('/<int:deposit_id>/delete', methods=['POST'])
@login_required
def delete(deposit_id):
    deposit = get_deposit_or_404(deposit_id)
    db.session.delete(deposit)
    db.session.commit()
    flash('Deposit record deleted.', 'success')
    return redirect(url_for('deposits.index'))
