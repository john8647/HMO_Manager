from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user
from app.utils import landlord_required
from datetime import datetime, date
from decimal import Decimal
from app import db
from app.models import (Invoice, InvoiceItem, BillTenantShare, TenantContract,
                        Tenant, Property, PicklistCharge, User, InvoicePayment)

invoices_bp = Blueprint('invoices', __name__)


def get_invoice_or_404(invoice_id):
    return Invoice.query.join(Property).filter(
        Invoice.id == invoice_id,
        Property.user_id == current_user.id
    ).first_or_404()


def next_invoice_number(user_id):
    year   = date.today().year
    prefix = f'INV-{year}-'
    last   = Invoice.query.filter(
        Invoice.invoice_number.like(f'{prefix}%'),
        Invoice.user_id == user_id
    ).order_by(Invoice.invoice_number.desc()).first()
    if last:
        try:
            last_num = int(last.invoice_number.split('-')[-1])
        except ValueError:
            last_num = 0
    else:
        last_num = 0
    return f'{prefix}{last_num + 1:04d}'


def update_tenant_balances_on_issue(invoice):
    """
    When an invoice is issued:
    - Calculate bill total (non-rent items only)
    - Create a Transaction debit of type 'Bills' for that amount
    - Update tenant.bill_balance
    - Rent balance is NOT touched here — rent debits come from the rent engine
    """
    from app.models import Transaction as Tx
    tenant = Tenant.query.get(invoice.tenant_id)
    if not tenant:
        return

    rent_charge = PicklistCharge.query.filter_by(charge_name='Rent').first()
    bills_total = Decimal('0.00')

    for item in invoice.items:
        is_rent = (
            (rent_charge and item.charge_type_id == rent_charge.id) or
            (item.description and 'rent' in item.description.lower())
        )
        if not is_rent:
            bills_total += Decimal(str(item.amount))

    if bills_total > Decimal('0.00'):
        # Create bill debit transaction
        bill_debit = Tx(
            tenant_id=tenant.id,
            invoice_id=invoice.id,
            amount=bills_total,
            credit_debit='db',
            transaction_date=invoice.issue_date or invoice.created_at.date(),
            user_id=invoice.user_id,
            type='Bills',
            month_year_period=(
                invoice.issue_date or invoice.created_at.date()
            ).strftime('%B %Y'),
            source='system',
            is_matched=True,
            notes=(
                f'Bill Invoice {invoice.invoice_number} — '
                f'{invoice.tenant.full_name}'
            ),
        )
        db.session.add(bill_debit)
        tenant.bill_balance = (
            Decimal(str(tenant.bill_balance or 0)) + bills_total
        )


def revert_tenant_balances_on_delete(invoice):
    if invoice.status == 'draft':
        return
    tenant = Tenant.query.get(invoice.tenant_id)
    if not tenant:
        return
    rent_charge = PicklistCharge.query.filter_by(charge_name='Rent').first()
    rent_total  = Decimal('0.00')
    bills_total = Decimal('0.00')
    for item in invoice.items:
        is_rent = (
            (rent_charge and item.charge_type_id == rent_charge.id) or
            (item.description and 'rent' in item.description.lower())
        )
        if is_rent:
            rent_total += Decimal(str(item.amount))
        else:
            bills_total += Decimal(str(item.amount))
    tenant.rent_balance = Decimal(str(tenant.rent_balance or 0)) - rent_total
    tenant.bill_balance = Decimal(str(tenant.bill_balance or 0)) - bills_total
    amount_paid = Decimal(str(invoice.amount_paid or 0))
    if amount_paid > Decimal('0.00'):
        tenant.rent_balance = Decimal(str(tenant.rent_balance or 0)) + amount_paid


@invoices_bp.route('/')
@login_required
@landlord_required
def index():
    if current_user.role == 'admin':
        invoices = Invoice.query.order_by(Invoice.issue_date.desc()).limit(100).all()
    else:
        invoices = Invoice.query.filter_by(
            user_id=current_user.id
        ).order_by(Invoice.issue_date.desc()).limit(100).all()
    for inv in invoices:
        inv.outstanding = (
            Decimal(str(inv.total_due or 0)) -
            Decimal(str(inv.amount_paid or 0))
        )
    return render_template('invoices/index.html', invoices=invoices)


@invoices_bp.route('/generate', methods=['GET', 'POST'])
@login_required
@landlord_required
def generate():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    active_contracts     = []
    selected_property_id = request.form.get('property_id') or request.args.get('property_id')

    if selected_property_id:
        active_contracts = TenantContract.query.filter_by(
            property_id=int(selected_property_id), is_active=True
        ).all()

    if request.method == 'POST' and request.form.get('action') != 'generate':
        return render_template('invoices/generate.html',
                               properties=properties,
                               active_contracts=active_contracts,
                               selected_property_id=selected_property_id,
                               date=date)

    if request.method == 'POST' and request.form.get('action') == 'generate':
        contract_id    = request.form.get('contract_id', '').strip()
        period_start_s = request.form.get('period_start', '').strip()
        period_end_s   = request.form.get('period_end', '').strip()
        issue_date_s   = request.form.get('issue_date', '').strip()
        due_date_s     = request.form.get('due_date', '').strip()
        include_rent   = request.form.get('include_rent') == 'on'
        include_bills  = request.form.get('include_bills') == 'on'
        rent_override  = request.form.get('rent_override', '').strip()
        issue_now      = request.form.get('issue_now') == 'on'

        errors = []
        if not contract_id:
            errors.append('Tenant contract is required.')
        if not period_start_s or not period_end_s:
            errors.append('Period start and end are required.')
        if not issue_date_s:
            errors.append('Issue date is required.')
        if not due_date_s:
            errors.append('Due date is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('invoices/generate.html',
                                   properties=properties,
                                   active_contracts=active_contracts,
                                   selected_property_id=selected_property_id,
                                   date=date)

        contract = TenantContract.query.get_or_404(int(contract_id))
        tenant   = contract.tenant
        prop     = contract.property

        try:
            period_start = datetime.strptime(period_start_s, '%Y-%m-%d').date()
            period_end   = datetime.strptime(period_end_s,   '%Y-%m-%d').date()
            issue_date   = datetime.strptime(issue_date_s,   '%Y-%m-%d').date()
            due_date     = datetime.strptime(due_date_s,     '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format.', 'error')
            return render_template('invoices/generate.html',
                                   properties=properties,
                                   active_contracts=active_contracts,
                                   selected_property_id=selected_property_id,
                                   date=date)

        inv_number = next_invoice_number(current_user.id)
        invoice = Invoice(
            invoice_number=inv_number,
            tenant_id=tenant.id,
            contract_id=contract.id,
            property_id=prop.id,
            user_id=current_user.id,
            issue_date=issue_date,
            due_date=due_date,
            period_start=period_start,
            period_end=period_end,
            status='draft',
            amount_paid=Decimal('0.00'),
        )
        db.session.add(invoice)
        db.session.flush()

        subtotal = Decimal('0.00')

        if include_rent:
            rent_amount = Decimal(rent_override) if rent_override else contract.monthly_rent
            rent_charge = PicklistCharge.query.filter_by(charge_name='Rent').first()
            item = InvoiceItem(
                invoice_id=invoice.id,
                description=(
                    f'Room Rent — {contract.room.room_name} '
                    f'({period_start.strftime("%d %b")} to '
                    f'{period_end.strftime("%d %b %Y")})'
                ),
                amount=rent_amount,
                charge_type_id=rent_charge.id if rent_charge else None,
            )
            db.session.add(item)
            subtotal += Decimal(str(rent_amount))

        if include_bills:
            shares = BillTenantShare.query.filter_by(
                tenant_id=tenant.id, invoice_item_id=None
            ).all()
            period_shares = [
                s for s in shares
                if s.bill.period_end >= period_start
                and s.bill.period_start <= period_end
            ]
            for share in period_shares:
                bill       = share.bill
                type_label = bill.bill_type.replace('_', ' ').title()
                description = (
                    f'{type_label} — '
                    f'{bill.period_start.strftime("%d %b")} to '
                    f'{bill.period_end.strftime("%d %b %Y")} '
                    f'| {bill.days_in_period} days '
                    f'({share.days_present} days present)'
                )
                charge = PicklistCharge.query.filter(
                    PicklistCharge.charge_name.ilike(
                        '%council%' if 'council' in bill.bill_type else '%gas%'
                    )
                ).first()
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    description=description,
                    amount=share.share_amount,
                    charge_type_id=charge.id if charge else None,
                    bill_id=bill.id,
                )
                db.session.add(item)
                db.session.flush()
                share.invoice_item_id = item.id
                subtotal += Decimal(str(share.share_amount))

        # Invoices are for bills only — no arrears carried forward.
        # Rent balance is tracked via Transaction debits, not invoice totals.
        invoice.subtotal                = subtotal
        invoice.arrears_carried_forward = Decimal('0.00')
        invoice.total_due               = subtotal

        if issue_now:
            invoice.status = 'issued'
            update_tenant_balances_on_issue(invoice)
            flash(
                f'Invoice {inv_number} generated and issued to {tenant.full_name}. '
                f'Tenant balance updated.',
                'success'
            )
        else:
            flash(f'Invoice {inv_number} created as draft for {tenant.full_name}.', 'success')

        db.session.commit()
        return redirect(url_for('invoices.view', invoice_id=invoice.id))

    return render_template('invoices/generate.html',
                           properties=properties,
                           active_contracts=active_contracts,
                           selected_property_id=selected_property_id,
                           date=date)


@invoices_bp.route('/<int:invoice_id>')
@login_required
@landlord_required
def view(invoice_id):
    invoice     = get_invoice_or_404(invoice_id)
    items       = invoice.items.all()
    landlord    = User.query.get(invoice.user_id)
    payments    = InvoicePayment.query.filter_by(invoice_id=invoice.id).all()
    outstanding = (
        Decimal(str(invoice.total_due or 0)) -
        Decimal(str(invoice.amount_paid or 0))
    )
    return render_template('invoices/view.html',
                           invoice=invoice,
                           items=items,
                           landlord=landlord,
                           payments=payments,
                           outstanding=outstanding)


@invoices_bp.route('/<int:invoice_id>/status', methods=['POST'])
@login_required
@landlord_required
def update_status(invoice_id):
    invoice    = get_invoice_or_404(invoice_id)
    new_status = request.form.get('status', '').strip()
    old_status = invoice.status

    if new_status not in ('draft', 'issued', 'partially_paid', 'paid', 'overdue'):
        flash('Invalid status.', 'error')
        return redirect(url_for('invoices.view', invoice_id=invoice.id))

    if new_status == 'issued' and old_status == 'draft':
        # Recalculate total_due from items only — no arrears ever
        subtotal = sum(Decimal(str(i.amount)) for i in invoice.items.all())
        invoice.subtotal                = subtotal
        invoice.arrears_carried_forward = Decimal('0.00')
        invoice.total_due               = subtotal
        # Create the Bills debit transaction
        update_tenant_balances_on_issue(invoice)

    invoice.status = new_status
    db.session.commit()
    flash(f'Invoice status updated to {new_status}.', 'success')
    return redirect(url_for('invoices.view', invoice_id=invoice.id))


@invoices_bp.route('/<int:invoice_id>/add-item', methods=['POST'])
@login_required
@landlord_required
def add_item(invoice_id):
    invoice     = get_invoice_or_404(invoice_id)
    description = request.form.get('description', '').strip()
    amount_str  = request.form.get('amount', '').strip()

    if not description or not amount_str:
        flash('Description and amount are required.', 'error')
        return redirect(url_for('invoices.view', invoice_id=invoice.id))

    try:
        amount = Decimal(amount_str)
    except Exception:
        flash('Invalid amount.', 'error')
        return redirect(url_for('invoices.view', invoice_id=invoice.id))

    item = InvoiceItem(invoice_id=invoice.id, description=description, amount=amount)
    db.session.add(item)
    db.session.flush()  # item is now in session; include it in the sum
    # Recalculate subtotal from all items (item already flushed so included)
    current_subtotal  = sum(Decimal(str(i.amount)) for i in invoice.items.all())
    invoice.subtotal  = current_subtotal
    # Invoices never carry forward arrears — total_due = subtotal only
    invoice.arrears_carried_forward = Decimal('0.00')
    invoice.total_due = current_subtotal

    # If invoice is already issued, update the Bills debit to match new total
    if invoice.status == 'issued':
        from app.models import Transaction as Tx
        bill_debit = Tx.query.filter_by(
            invoice_id=invoice.id,
            credit_debit='db',
            type='Bills',
        ).first()
        if bill_debit:
            bill_debit.amount = current_subtotal
        else:
            # Create it if missing
            update_tenant_balances_on_issue(invoice)

    db.session.commit()
    flash('Charge added to invoice.', 'success')
    return redirect(url_for('invoices.view', invoice_id=invoice.id))


@invoices_bp.route('/<int:invoice_id>/delete', methods=['POST'])
@login_required
@landlord_required
def delete(invoice_id):
    invoice = get_invoice_or_404(invoice_id)
    revert_tenant_balances_on_delete(invoice)
    for item in invoice.items.all():
        if item.bill_id:
            share = BillTenantShare.query.filter_by(invoice_item_id=item.id).first()
            if share:
                share.invoice_item_id = None
    db.session.delete(invoice)
    db.session.commit()
    flash('Invoice deleted. Bill shares released for re-invoicing.', 'success')
    return redirect(url_for('invoices.index'))


@invoices_bp.route('/<int:invoice_id>/pdf')
@login_required
@landlord_required
def pdf(invoice_id):
    invoice  = get_invoice_or_404(invoice_id)
    items    = invoice.items.all()
    landlord = User.query.get(invoice.user_id)
    html = render_template('invoices/pdf_template.html',
                           invoice=invoice, items=items, landlord=landlord)
    try:
        import io
        from xhtml2pdf import pisa
        pdf_buffer = io.BytesIO()
        pisa.CreatePDF(html, dest=pdf_buffer)
        pdf_buffer.seek(0)
        return Response(
            pdf_buffer.read(),
            mimetype='application/pdf',
            headers={'Content-Disposition':
                     f'attachment; filename={invoice.invoice_number}.pdf'}
        )
    except Exception as e:
        flash(f'PDF generation failed: {e}', 'error')
        return redirect(url_for('invoices.view', invoice_id=invoice.id))


# ── Rent Roll ─────────────────────────────────────────────────────────────────

@invoices_bp.route('/rent-roll')
@login_required
@landlord_required
def rent_roll():
    from app.invoices.rent_roll import build_rent_roll
    from app.models import Property as Prop

    if current_user.role == 'admin':
        properties = Prop.query.order_by(Prop.address_line1).all()
    else:
        properties = Prop.query.filter_by(
            user_id=current_user.id
        ).order_by(Prop.address_line1).all()

    property_id = request.args.get('property_id', type=int)
    rows        = build_rent_roll(current_user.id, property_id=property_id)

    total_outstanding = sum(r['total_outstanding'] for r in rows)
    total_rent_bal    = sum(r['rent_balance']       for r in rows)
    total_bill_bal    = sum(r['bill_balance']        for r in rows)
    total_balance     = sum(r['total_balance']       for r in rows)
    total_rent_roll   = sum(r['monthly_rent']        for r in rows)

    return render_template(
        'invoices/rent_roll.html',
        rows=rows,
        properties=properties,
        selected_property_id=property_id,
        total_outstanding=total_outstanding,
        total_rent_bal=total_rent_bal,
        total_bill_bal=total_bill_bal,
        total_balance=total_balance,
        total_rent_roll=total_rent_roll,
        today=date.today(),
    )


@invoices_bp.route('/rent-roll/run-charges', methods=['POST'])
@login_required
@landlord_required
def run_rent_charges():
    from app.invoices.rent_engine import generate_rent_charges
    charges = generate_rent_charges(user_id=current_user.id)
    if charges:
        flash(f'{len(charges)} rent charge(s) generated.', 'success')
    else:
        flash('No new rent charges needed — all tenants are up to date.', 'info')
    return redirect(url_for('invoices.rent_roll'))


@invoices_bp.route('/rent-roll/preview-charges')
@login_required
@landlord_required
def preview_rent_charges():
    from app.invoices.rent_engine import generate_rent_charges
    charges = generate_rent_charges(user_id=current_user.id, dry_run=True)
    return render_template('invoices/preview_charges.html', charges=charges)


@invoices_bp.route('/rent-roll/recalculate', methods=['POST'])
@login_required
@landlord_required
def recalculate_balances():
    from app.invoices.rent_engine import recalculate_tenant_balance
    from app.models import Tenant as T
    tenants = T.query.filter_by(user_id=current_user.id, is_active=True).all()
    for tenant in tenants:
        recalculate_tenant_balance(tenant.id)
    db.session.commit()
    flash(f'Balances recalculated for {len(tenants)} tenant(s).', 'success')
    return redirect(url_for('invoices.rent_roll'))
