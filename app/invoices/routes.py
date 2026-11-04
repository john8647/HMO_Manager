from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user
from datetime import datetime, date
from decimal import Decimal
from app import db
from app.models import (Invoice, InvoiceItem, BillTenantShare, TenantContract,
                        Tenant, Property, PicklistCharge, User)

invoices_bp = Blueprint('invoices', __name__)


def get_invoice_or_404(invoice_id):
    return Invoice.query.join(Property).filter(
        Invoice.id == invoice_id,
        Property.user_id == current_user.id
    ).first_or_404()


def next_invoice_number(user_id):
    """Generate next sequential invoice number INV-YYYY-NNNN."""
    year = date.today().year
    prefix = f'INV-{year}-'
    last = Invoice.query.filter(
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


# ── Invoice list ─────────────────────────────────────────────────────────────

@invoices_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        invoices = Invoice.query.order_by(Invoice.issue_date.desc()).limit(100).all()
    else:
        invoices = Invoice.query.filter_by(
            user_id=current_user.id
        ).order_by(Invoice.issue_date.desc()).limit(100).all()
    return render_template('invoices/index.html', invoices=invoices)


# ── Generate invoice for one tenant ─────────────────────────────────────────

@invoices_bp.route('/generate', methods=['GET', 'POST'])
@login_required
def generate():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    # Get active contracts for tenant selection
    active_contracts = []
    selected_property_id = request.form.get('property_id') or request.args.get('property_id')
    if selected_property_id:
        active_contracts = TenantContract.query.filter_by(
            property_id=int(selected_property_id),
            is_active=True
        ).all()

    if request.method == 'POST' and request.form.get('action') != 'generate':
        # Property dropdown changed — reload tenant list
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

        # Create invoice
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
        )
        db.session.add(invoice)
        db.session.flush()

        subtotal = Decimal('0.00')

        # 1. Rent line item
        if include_rent:
            rent_amount = Decimal(rent_override) if rent_override else contract.monthly_rent
            rent_charge = PicklistCharge.query.filter_by(charge_name='Rent').first()
            item = InvoiceItem(
                invoice_id=invoice.id,
                description=f'Room Rent — {contract.room.room_name} '
                            f'({period_start.strftime("%d %b")} to {period_end.strftime("%d %b %Y")})',
                amount=rent_amount,
                charge_type_id=rent_charge.id if rent_charge else None,
            )
            db.session.add(item)
            subtotal += Decimal(str(rent_amount))

        # 2. Bill share line items
        if include_bills:
            shares = BillTenantShare.query.filter_by(
                tenant_id=tenant.id
            ).join(
                BillTenantShare.bill
            ).filter(
                BillTenantShare.invoice_item_id == None,
            ).all()

            # Filter to shares within this invoice period
            period_shares = [
                s for s in shares
                if s.bill.period_end >= period_start and s.bill.period_start <= period_end
            ]

            for share in period_shares:
                bill = share.bill
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

                # Mark share as invoiced
                share.invoice_item_id = item.id
                subtotal += Decimal(str(share.share_amount))

        # 3. Carry forward arrears from tenant balance
        arrears = Decimal(str(tenant.rent_balance or 0)) + \
                  Decimal(str(tenant.bill_balance or 0))
        if arrears < 0:
            arrears = abs(arrears)
        else:
            arrears = Decimal('0.00')

        invoice.subtotal = subtotal
        invoice.arrears_carried_forward = arrears
        invoice.total_due = subtotal + arrears
        db.session.commit()

        flash(f'Invoice {inv_number} generated for {tenant.full_name}.', 'success')
        return redirect(url_for('invoices.view', invoice_id=invoice.id))

    return render_template('invoices/generate.html',
                           properties=properties,
                           active_contracts=active_contracts,
                           selected_property_id=selected_property_id,
                           date=date)


# ── View invoice ─────────────────────────────────────────────────────────────

@invoices_bp.route('/<int:invoice_id>')
@login_required
def view(invoice_id):
    invoice = get_invoice_or_404(invoice_id)
    items   = invoice.items.all()
    landlord = User.query.get(invoice.user_id)
    return render_template('invoices/view.html',
                           invoice=invoice,
                           items=items,
                           landlord=landlord)


# ── Update invoice status ─────────────────────────────────────────────────────

@invoices_bp.route('/<int:invoice_id>/status', methods=['POST'])
@login_required
def update_status(invoice_id):
    invoice = get_invoice_or_404(invoice_id)
    new_status = request.form.get('status', '').strip()
    if new_status in ('draft', 'issued', 'paid', 'overdue'):
        invoice.status = new_status
        db.session.commit()
        flash(f'Invoice status updated to {new_status}.', 'success')
    return redirect(url_for('invoices.view', invoice_id=invoice.id))


# ── Add one-off charge to invoice ────────────────────────────────────────────

@invoices_bp.route('/<int:invoice_id>/add-item', methods=['POST'])
@login_required
def add_item(invoice_id):
    invoice = get_invoice_or_404(invoice_id)
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

    item = InvoiceItem(
        invoice_id=invoice.id,
        description=description,
        amount=amount,
    )
    db.session.add(item)

    # Recalculate totals
    invoice.subtotal = sum(
        Decimal(str(i.amount)) for i in invoice.items.all()
    ) + amount
    invoice.total_due = invoice.subtotal + Decimal(str(invoice.arrears_carried_forward or 0))
    db.session.commit()
    flash('Charge added to invoice.', 'success')
    return redirect(url_for('invoices.view', invoice_id=invoice.id))


# ── Delete invoice ────────────────────────────────────────────────────────────

@invoices_bp.route('/<int:invoice_id>/delete', methods=['POST'])
@login_required
def delete(invoice_id):
    invoice = get_invoice_or_404(invoice_id)

    # Unlink bill shares so they can be re-invoiced
    for item in invoice.items.all():
        if item.bill_id:
            share = BillTenantShare.query.filter_by(
                invoice_item_id=item.id
            ).first()
            if share:
                share.invoice_item_id = None

    db.session.delete(invoice)
    db.session.commit()
    flash('Invoice deleted. Bill shares are now available for re-invoicing.', 'success')
    return redirect(url_for('invoices.index'))


# ── PDF download ──────────────────────────────────────────────────────────────

@invoices_bp.route('/<int:invoice_id>/pdf')
@login_required
def pdf(invoice_id):
    invoice  = get_invoice_or_404(invoice_id)
    items    = invoice.items.all()
    landlord = User.query.get(invoice.user_id)

    html = render_template('invoices/pdf_template.html',
                           invoice=invoice,
                           items=items,
                           landlord=landlord)
    try:
        import io
        from xhtml2pdf import pisa

        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

        if pisa_status.err:
            flash('PDF generation failed — error in template rendering.', 'error')
            return redirect(url_for('invoices.view', invoice_id=invoice.id))

        pdf_buffer.seek(0)
        return Response(
            pdf_buffer.read(),
            mimetype='application/pdf',
            headers={
                'Content-Disposition':
                    f'attachment; filename={invoice.invoice_number}.pdf'
            }
        )
    except Exception as e:
        flash(f'PDF generation failed: {e}', 'error')
        return redirect(url_for('invoices.view', invoice_id=invoice.id))
