from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, send_from_directory, Response)
from flask_login import login_required, current_user
from app.utils import landlord_required
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


def _reclassify_advanced_rent(tenant_id: int, deposit_amount,
                               deposit_date, user_id: int):
    """
    When a deposit is recorded, find the surplus rent credit that
    represents the advanced rent payment and:

    1. Reclassify that Transaction from type='Rent' to type='Advanced Rent'
       and update its notes accordingly
    2. Create a matching debit Transaction for the same amount so the
       balance returns to £0

    Logic:
      - Sum all Rent debits (charges) for the tenant
      - Sum all Rent credits (payments) for the tenant
      - If credits > debits, the difference is the surplus = advanced rent
      - Find the most recent Rent credit transaction that makes up that surplus
      - Reclassify it and create the offsetting debit

    Returns the advanced rent amount reclassified, or None if no surplus.
    """
    from decimal import Decimal
    from app.models import Transaction
    from app.invoices.rent_engine import recalculate_tenant_balance

    # Calculate current rent surplus
    debits = Transaction.query.filter_by(
        tenant_id=tenant_id,
        credit_debit='db',
        type='Rent',
    ).all()

    credits = Transaction.query.filter_by(
        tenant_id=tenant_id,
        credit_debit='cr',
        type='Rent',
    ).all()

    total_charged = sum(Decimal(str(t.amount)) for t in debits)
    total_paid    = sum(Decimal(str(t.amount)) for t in credits)
    surplus       = total_paid - total_charged

    if surplus <= Decimal('0.00'):
        return None

    # Use the deposit amount as the advanced rent amount
    # (can't be more than the actual surplus)
    adv_amount = min(Decimal(str(deposit_amount)), surplus)

    # Find the most recent Rent credit to reclassify
    # (the last payment that created the surplus)
    recent_credit = Transaction.query.filter_by(
        tenant_id=tenant_id,
        credit_debit='cr',
        type='Rent',
    ).order_by(Transaction.transaction_date.desc()).first()

    if not recent_credit:
        return None

    # Reclassify the credit
    old_notes = recent_credit.notes or ''
    recent_credit.type  = 'Advanced Rent'
    recent_credit.notes = old_notes.replace(
        ' Rent', ' Advanced Rent'
    ) if ' Rent' in old_notes else f'{old_notes} (Advanced Rent)'

    # Create offsetting debit so balance = £0
    from app.models import Transaction as Tx
    adv_debit = Tx(
        tenant_id=tenant_id,
        amount=adv_amount,
        credit_debit='db',
        transaction_date=deposit_date,
        user_id=user_id,
        type='Advanced Rent',
        month_year_period=deposit_date.strftime('%B %Y'),
        source='system',
        is_matched=True,
        notes=f'Advanced rent offset — deposit recorded {deposit_date.strftime("%d %b %Y")}',
    )
    db.session.add(adv_debit)
    db.session.flush()

    # Recalculate balance from raw transactions
    recalculate_tenant_balance(tenant_id)

    return adv_amount


def get_deposit_or_404(deposit_id):
    return Deposit.query.join(Tenant).filter(
        Deposit.id == deposit_id,
        Tenant.user_id == current_user.id
    ).first_or_404()


# ── List ──────────────────────────────────────────────────────────────────────

@deposits_bp.route('/')
@login_required
@landlord_required
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
@landlord_required
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

        if date_protected:
            deposit.notes = (
                f'Protected: {date_protected.strftime("%d %b %Y")}. '
                + (notes or '')
            ).strip()

        if file_path:
            deposit.notes = (deposit.notes or '') + f' | file:{file_path}'

        db.session.add(deposit)
        db.session.flush()

        tenant_obj = Tenant.query.get(int(tenant_id))

        # ── Advanced Rent reclassification ──────────────────────────────
        # Find the most recent Rent credit for this tenant that is a
        # surplus above what the rent engine has charged — this is the
        # advanced rent payment. Reclassify it and create a matching
        # debit so the balance returns to £0.
        advanced_rent_amount = _reclassify_advanced_rent(
            tenant_id=int(tenant_id),
            deposit_amount=amount,
            deposit_date=date_received,
            user_id=current_user.id,
        )

        db.session.commit()

        msg = f'Deposit of £{amount} recorded for {tenant_obj.full_name}.'
        if advanced_rent_amount:
            msg += (
                f' £{advanced_rent_amount:.2f} advanced rent reclassified '
                f'— tenant balance updated.'
            )
        flash(msg, 'success')
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
@landlord_required
def view(deposit_id):
    deposit = get_deposit_or_404(deposit_id)
    return render_template('deposits/view.html',
                           deposit=deposit,
                           statuses=STATUSES,
                           dps_companies=DPS_COMPANIES)


# ── Edit ──────────────────────────────────────────────────────────────────────

@deposits_bp.route('/<int:deposit_id>/edit', methods=['GET', 'POST'])
@login_required
@landlord_required
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
@landlord_required
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
@landlord_required
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
@landlord_required
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
@landlord_required
def delete(deposit_id):
    deposit = get_deposit_or_404(deposit_id)
    db.session.delete(deposit)
    db.session.commit()
    flash('Deposit record deleted.', 'success')
    return redirect(url_for('deposits.index'))
