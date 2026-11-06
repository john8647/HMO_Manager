from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime
from decimal import Decimal
from app import db
from app.models import Bill, BillTenantShare, Property, TenantContract, Tenant
from app.bills.calculator import calculate_shares, inclusive_days

# This blueprint groups all bill-related pages and API actions under a shared
# prefix (for example, /bills/... in the app). The routes below handle viewing,
# creating, deleting, and listing bills for a property.
bills_bp = Blueprint('bills', __name__)


# Helper used by several routes to verify that a bill belongs to the currently
# logged-in user before returning it. This prevents a user from viewing or
# deleting another owner's records.
def get_bill_or_404(bill_id):
    bill = Bill.query.join(Property).filter(
        Bill.id == bill_id,
        Property.user_id == current_user.id
    ).first_or_404()
    return bill


# Shows the main bill dashboard. Admin users can see all properties; regular
# users only see properties they own. It also fetches the most recent bills so
# the page can display a quick overview of activity.
@bills_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        properties = Property.query.order_by(Property.address_line1).all()
    else:
        properties = Property.query.filter_by(
            user_id=current_user.id
        ).order_by(Property.address_line1).all()

    # Pull the newest bills for the properties the user is allowed to access.
    property_ids = [p.id for p in properties]
    recent_bills = Bill.query.filter(
        Bill.property_id.in_(property_ids)
    ).order_by(Bill.period_end.desc()).limit(50).all()

    return render_template('bills/index.html',
                           properties=properties,
                           recent_bills=recent_bills)


# Handles bill creation. On GET, it shows the form with the list of properties
# the user can assign a bill to. On POST, it validates form data, creates the
# Bill record, and calculates tenant cost shares for the billing period.
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
        # Read all fields from the submitted form and normalize them.
        property_id    = request.form.get('property_id', '').strip()
        bill_type      = request.form.get('bill_type', '').strip()
        amount_str     = request.form.get('amount', '').strip()
        period_start_str = request.form.get('period_start', '').strip()
        period_end_str   = request.form.get('period_end', '').strip()
        notes          = request.form.get('notes', '').strip()

        # Require all critical values before continuing.
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

        # Parse values carefully so bad input does not reach the database.
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

        # Count the total days in the period so the bill can be prorated if needed.
        days_in_period = inclusive_days(period_start, period_end)

        # Save the base bill record first so it gets an ID for the tenant-share rows.
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

        # Find tenant contracts relevant to this billing period. We include both
        # active contracts and contracts that ended during the period so the bill
        # can still be shared fairly across any tenant who occupied the property.
        overlapping_contracts = TenantContract.query.filter(
            TenantContract.property_id == int(property_id),
            TenantContract.is_active == True,
            TenantContract.start_date <= period_end,
        ).all()

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

        # Prepare the tenant data structure expected by the billing calculator,
        # which computes each tenant's pro-rata share based on overlap days.
        tenant_list = []
        for contract in all_contracts:
            tenant_list.append({
                'tenant_id':      contract.tenant_id,
                'contract_id':    contract.id,
                'contract_start': contract.start_date,
                'contract_end':   contract.end_date,
            })

        # calculate_shares() does the actual math: it prorates the bill across
        # each tenant's days in the billing period.
        shares = calculate_shares(amount, tenant_list, period_start, period_end)

        # Save one BillTenantShare row per tenant with a positive occupancy period.
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


# Displays one bill plus all tenant-share allocations for that bill. We enrich
# each share with the tenant object so the template can print the tenant name.
@bills_bp.route('/<int:bill_id>')
@login_required
def view(bill_id):
    bill = get_bill_or_404(bill_id)
    shares = BillTenantShare.query.filter_by(bill_id=bill.id).all()

    for share in shares:
        share.tenant = Tenant.query.get(share.tenant_id)

    return render_template('bills/view.html', bill=bill, shares=shares)


# Deletes a bill after confirming the user owns it. This removes the bill record
# itself, and the database relationship will also remove related share rows if
# configured by the schema.
@bills_bp.route('/<int:bill_id>/delete', methods=['POST'])
@login_required
def delete(bill_id):
    bill = get_bill_or_404(bill_id)
    db.session.delete(bill)
    db.session.commit()
    flash('Bill deleted.', 'success')
    return redirect(url_for('bills.index'))


# Lists all bills for a single property, ordered newest-first. This is useful for
# property-specific billing history and lets managers drill into a property's bill
# ledger without seeing unrelated records.
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
