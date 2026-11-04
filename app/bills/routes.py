from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime
from decimal import Decimal
from app import db
from app.models import Bill, BillTenantShare, Property, TenantContract, Tenant
from app.bills.calculator import calculate_shares, inclusive_days

bills_bp = Blueprint('bills', __name__)


def get_bill_or_404(bill_id):
    bill = Bill.query.join(Property).filter(
        Bill.id == bill_id,
        Property.user_id == current_user.id
    ).first_or_404()
    return bill


@bills_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    # Get recent bills per property
    property_ids = [p.id for p in properties]
    recent_bills = Bill.query.filter(
        Bill.property_id.in_(property_ids)
    ).order_by(Bill.period_end.desc()).limit(50).all()

    return render_template('bills/index.html',
                           properties=properties,
                           recent_bills=recent_bills)


@bills_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    if request.method == 'POST':
        property_id    = request.form.get('property_id', '').strip()
        bill_type      = request.form.get('bill_type', '').strip()
        amount_str     = request.form.get('amount', '').strip()
        period_start_str = request.form.get('period_start', '').strip()
        period_end_str   = request.form.get('period_end', '').strip()
        notes          = request.form.get('notes', '').strip()

        errors = []
        if not property_id:
            errors.append('Property is required.')
        if not bill_type:
            errors.append('Bill type is required.')
        if not amount_str:
            errors.append('Amount is required.')
        if not period_start_str:
            errors.append('Period start date is required.')
        if not period_end_str:
            errors.append('Period end date is required.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('bills/add.html', properties=properties)

        try:
            amount = Decimal(amount_str)
            period_start = datetime.strptime(period_start_str, '%Y-%m-%d').date()
            period_end   = datetime.strptime(period_end_str,   '%Y-%m-%d').date()
        except (ValueError, Exception):
            flash('Invalid amount or date format.', 'error')
            return render_template('bills/add.html', properties=properties)

        if period_end < period_start:
            flash('Period end date must be after start date.', 'error')
            return render_template('bills/add.html', properties=properties)

        days_in_period = inclusive_days(period_start, period_end)

        bill = Bill(
            property_id=int(property_id),
            user_id=current_user.id,
            bill_type=bill_type,
            amount=amount,
            period_start=period_start,
            period_end=period_end,
            days_in_period=days_in_period,
            is_shared=True,
            date_entered=datetime.utcnow().date(),
            notes=notes,
        )
        db.session.add(bill)
        db.session.flush()  # get bill.id before commit

        # Find all active contracts that overlap with the billing period
        overlapping_contracts = TenantContract.query.filter(
            TenantContract.property_id == int(property_id),
            TenantContract.is_active == True,
            TenantContract.start_date <= period_end,
        ).all()

        # Also include contracts that ended within or after the period
        ended_contracts = TenantContract.query.filter(
            TenantContract.property_id == int(property_id),
            TenantContract.is_active == False,
            TenantContract.start_date <= period_end,
            TenantContract.end_date >= period_start,
        ).all()

        all_contracts = overlapping_contracts + ended_contracts

        if not all_contracts:
            flash('Bill saved but no active tenants found for this period — no shares calculated.', 'warning')
            db.session.commit()
            return redirect(url_for('bills.view', bill_id=bill.id))

        # Build tenant list for calculator
        tenant_list = []
        for contract in all_contracts:
            tenant_list.append({
                'tenant_id':      contract.tenant_id,
                'contract_id':    contract.id,
                'contract_start': contract.start_date,
                'contract_end':   contract.end_date,
            })

        # Calculate pro-rata shares
        shares = calculate_shares(amount, tenant_list, period_start, period_end)

        for share in shares:
            if share['days_present'] > 0:
                bts = BillTenantShare(
                    bill_id=bill.id,
                    tenant_id=share['tenant_id'],
                    contract_id=share['contract_id'],
                    days_present=share['days_present'],
                    share_amount=share['share_amount'],
                )
                db.session.add(bts)

        db.session.commit()
        flash(f'Bill added and shares calculated for {len(shares)} tenant(s).', 'success')
        return redirect(url_for('bills.view', bill_id=bill.id))

    return render_template('bills/add.html', properties=properties)


@bills_bp.route('/<int:bill_id>')
@login_required
def view(bill_id):
    bill = get_bill_or_404(bill_id)
    shares = BillTenantShare.query.filter_by(bill_id=bill.id).all()

    # Attach tenant names
    for share in shares:
        share.tenant = Tenant.query.get(share.tenant_id)

    return render_template('bills/view.html', bill=bill, shares=shares)


@bills_bp.route('/<int:bill_id>/delete', methods=['POST'])
@login_required
def delete(bill_id):
    bill = get_bill_or_404(bill_id)
    db.session.delete(bill)
    db.session.commit()
    flash('Bill deleted.', 'success')
    return redirect(url_for('bills.index'))


@bills_bp.route('/property/<int:property_id>')
@login_required
def by_property(property_id):
    prop = Property.query.filter_by(
        id=property_id, user_id=current_user.id
    ).first_or_404()

    bills = Bill.query.filter_by(
        property_id=property_id
    ).order_by(Bill.period_end.desc()).all()

    return render_template('bills/by_property.html', prop=prop, bills=bills)
