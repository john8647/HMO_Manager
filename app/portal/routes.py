"""
Tenant Portal
=============
Routes accessible only to users with role='tenant'.
Every route resolves the linked Tenant record via
  current_user.id  →  tenant.portal_user_id
and scopes all data to that tenant only.
"""

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort)
from flask_login import login_required, current_user
from functools import wraps
from datetime import date, datetime, timedelta
from decimal import Decimal
from app import db
from app.models import Tenant, TenantContract, Transaction, Task, Property, Room

portal_bp = Blueprint('portal', __name__)

# ── Tenant categories tenants may use ────────────────────────────────────────

TENANT_CATEGORIES = [
    ('damage',         'Damage Report',      'Damage to the building or fixtures'),
    ('neighbour',      'Neighbour Issue',     'Problems involving other residents or neighbours'),
    ('awareness',      'Awareness',           'Just for awareness — no action required'),
    ('correspondence', 'Correspondence',      'Admin correspondence or financial query'),
    ('request',        'Management Request',  'General management request'),
    ('contract_query', 'Contract Query',      'Contracts related request'),
]

PRIORITIES = [
    ('urgent', 'Urgent',  'Needs immediate attention'),
    ('high',   'High',    'Important, action this week'),
    ('medium', 'Medium',  'Action within the month'),
    ('low',    'Low',     'No immediate deadline'),
]


# ── Guard decorator ───────────────────────────────────────────────────────────

def tenant_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'tenant':
            flash('This area is for tenant accounts only.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


def _get_tenant():
    """Return the Tenant record linked to the current portal user, or 404."""
    tenant = Tenant.query.filter_by(portal_user_id=current_user.id).first()
    if not tenant:
        abort(404)
    return tenant


def _active_contract(tenant):
    return TenantContract.query.filter_by(
        tenant_id=tenant.id, is_active=True
    ).first()


# ── Balance helpers (mirrors rent_roll.py) ───────────────────────────────────

def _tx_sum(tenant_id, credit_debit, types):
    rows = Transaction.query.filter(
        Transaction.tenant_id == tenant_id,
        Transaction.credit_debit == credit_debit,
        Transaction.type.in_(types),
    ).all()
    return sum(Decimal(str(t.amount)) for t in rows)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@portal_bp.route('/')
@login_required
@tenant_required
def index():
    tenant   = _get_tenant()
    contract = _active_contract(tenant)
    today    = date.today()

    rent_balance  = _tx_sum(tenant.id, 'db', ['Rent', 'Advanced Rent']) \
                  - _tx_sum(tenant.id, 'cr', ['Rent', 'Advanced Rent'])
    bill_balance  = _tx_sum(tenant.id, 'db', ['Bills']) \
                  - _tx_sum(tenant.id, 'cr', ['Bills'])
    total_balance = rent_balance + bill_balance

    # Public tasks for this tenant's property
    public_tasks = []
    if contract:
        public_tasks = Task.query.filter_by(
            property_id=contract.property_id,
            is_public=True,
        ).filter(
            Task.status.in_(['open', 'in_progress'])
        ).order_by(Task.due_date.asc().nullslast()).limit(5).all()

    # Tenant's own open tasks
    my_tasks = Task.query.filter_by(
        tenant_id=tenant.id,
    ).filter(
        Task.status.in_(['open', 'in_progress'])
    ).order_by(Task.created_at.desc()).limit(5).all()

    # Last 5 payments
    recent_payments = Transaction.query.filter_by(
        tenant_id=tenant.id,
        credit_debit='cr',
    ).order_by(Transaction.transaction_date.desc()).limit(5).all()

    return render_template('portal/index.html',
                           tenant=tenant,
                           contract=contract,
                           rent_balance=rent_balance,
                           bill_balance=bill_balance,
                           total_balance=total_balance,
                           public_tasks=public_tasks,
                           my_tasks=my_tasks,
                           recent_payments=recent_payments,
                           today=today)


# ── Personal details ──────────────────────────────────────────────────────────

@portal_bp.route('/profile')
@login_required
@tenant_required
def profile():
    tenant = _get_tenant()
    return render_template('portal/profile.html', tenant=tenant)


# ── Contracts ─────────────────────────────────────────────────────────────────

@portal_bp.route('/contracts')
@login_required
@tenant_required
def contracts():
    tenant    = _get_tenant()
    contracts = TenantContract.query.filter_by(
        tenant_id=tenant.id
    ).order_by(TenantContract.start_date.desc()).all()
    today = date.today()
    return render_template('portal/contracts.html',
                           tenant=tenant,
                           contracts=contracts,
                           today=today)


@portal_bp.route('/contracts/<int:contract_id>/extend', methods=['GET', 'POST'])
@login_required
@tenant_required
def extend_contract(contract_id):
    tenant   = _get_tenant()
    contract = TenantContract.query.filter_by(
        id=contract_id, tenant_id=tenant.id, is_active=True
    ).first_or_404()

    today = date.today()

    if request.method == 'POST':
        extend_months = request.form.get('extend_months', '').strip()
        end_date_s    = request.form.get('end_date', '').strip()

        # Validate months
        months = None
        if extend_months:
            try:
                months = int(extend_months)
                if not 1 <= months <= 12:
                    flash('Extension must be between 1 and 12 months.', 'error')
                    return redirect(url_for('portal.extend_contract',
                                            contract_id=contract_id))
            except ValueError:
                flash('Invalid number of months.', 'error')
                return redirect(url_for('portal.extend_contract',
                                        contract_id=contract_id))

        # Validate custom end date — must be after next rent due
        custom_end = None
        if end_date_s:
            try:
                custom_end = datetime.strptime(end_date_s, '%Y-%m-%d').date()
                min_date = contract.next_rent_due or today
                if custom_end <= min_date:
                    flash(
                        f'End date must be after next rent due '
                        f'({min_date.strftime("%d %b %Y")}).',
                        'error'
                    )
                    return redirect(url_for('portal.extend_contract',
                                            contract_id=contract_id))
            except ValueError:
                flash('Invalid date.', 'error')
                return redirect(url_for('portal.extend_contract',
                                        contract_id=contract_id))

        if not months and not custom_end:
            flash('Please choose an extension period or enter an end date.', 'error')
            return redirect(url_for('portal.extend_contract',
                                    contract_id=contract_id))

        # Build the request task title
        if months:
            detail = f'by {months} month{"s" if months != 1 else ""}'
        else:
            detail = f'to {custom_end.strftime("%d %b %Y")}'

        title = f'Contract Extension Request — {tenant.full_name} ({detail})'
        notes = f'Tenant requested via portal on {today.strftime("%d %b %Y")}.'
        if months:
            notes += f' Extend by {months} months.'
        if custom_end:
            notes += f' Requested end date: {custom_end.strftime("%d %b %Y")}.'

        task = Task(
            user_id=contract.user_id,
            title=title,
            description=notes,
            category='contract_query',
            priority='medium',
            status='open',
            property_id=contract.property_id,
            room_id=contract.room_id,
            tenant_id=tenant.id,
            is_public=True,
        )
        db.session.add(task)
        db.session.commit()

        flash(
            'Your extension request has been sent to the landlord. '
            'They will be in touch to confirm.',
            'success'
        )
        return redirect(url_for('portal.contracts'))

    # Minimum date for custom end: next rent due + 1 day, or tomorrow
    min_end = (contract.next_rent_due + timedelta(days=1)) \
              if contract.next_rent_due else (today + timedelta(days=1))

    return render_template('portal/extend_contract.html',
                           tenant=tenant,
                           contract=contract,
                           today=today,
                           min_end=min_end)


# ── Rent roll (live snapshot — tenant's own row only) ─────────────────────────

@portal_bp.route('/rent-roll')
@login_required
@tenant_required
def rent_roll():
    tenant   = _get_tenant()
    contract = _active_contract(tenant)
    today    = date.today()

    if not contract:
        return render_template('portal/rent_roll.html',
                               tenant=tenant, row=None, today=today)

    rent_balance  = _tx_sum(tenant.id, 'db', ['Rent', 'Advanced Rent']) \
                  - _tx_sum(tenant.id, 'cr', ['Rent', 'Advanced Rent'])
    bill_balance  = _tx_sum(tenant.id, 'db', ['Bills']) \
                  - _tx_sum(tenant.id, 'cr', ['Bills'])
    total_balance = rent_balance + bill_balance

    # Recent transactions
    transactions = Transaction.query.filter_by(
        tenant_id=tenant.id,
    ).order_by(Transaction.transaction_date.desc()).limit(20).all()

    status = 'current'
    if total_balance < Decimal('-0.01'):
        status = 'credit'
    elif total_balance > Decimal('0.01'):
        if contract.next_rent_due and contract.next_rent_due < today:
            status = 'overdue'
        else:
            status = 'outstanding'

    row = {
        'tenant':        tenant,
        'contract':      contract,
        'property':      contract.property,
        'room':          contract.room,
        'monthly_rent':  Decimal(str(contract.monthly_rent or 0)),
        'next_rent_due': contract.next_rent_due,
        'rent_balance':  rent_balance,
        'bill_balance':  bill_balance,
        'total_balance': total_balance,
        'status':        status,
        'transactions':  transactions,
    }

    return render_template('portal/rent_roll.html',
                           tenant=tenant,
                           row=row,
                           today=today)


# ── Tasks ─────────────────────────────────────────────────────────────────────

@portal_bp.route('/tasks')
@login_required
@tenant_required
def tasks():
    tenant   = _get_tenant()
    contract = _active_contract(tenant)

    # Tenant's own tasks
    my_tasks = Task.query.filter_by(
        tenant_id=tenant.id,
    ).order_by(Task.created_at.desc()).all()

    # Public tasks for the property (not raised by this tenant)
    property_tasks = []
    if contract:
        property_tasks = Task.query.filter(
            Task.property_id == contract.property_id,
            Task.is_public == True,
            Task.tenant_id != tenant.id,
        ).order_by(Task.created_at.desc()).all()

    return render_template('portal/tasks.html',
                           tenant=tenant,
                           contract=contract,
                           my_tasks=my_tasks,
                           property_tasks=property_tasks,
                           categories=TENANT_CATEGORIES,
                           today=date.today())


@portal_bp.route('/tasks/add', methods=['GET', 'POST'])
@login_required
@tenant_required
def add_task():
    tenant   = _get_tenant()
    contract = _active_contract(tenant)

    if not contract:
        flash('You need an active contract to raise a task.', 'error')
        return redirect(url_for('portal.tasks'))

    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category    = request.form.get('category', '').strip()
        priority    = request.form.get('priority', 'medium').strip()
        link_room   = request.form.get('link_room') == 'on'
        due_date_s  = request.form.get('due_date', '').strip()

        # Validate category — tenants may only use the allowed set
        allowed_cats = {c[0] for c in TENANT_CATEGORIES}
        if category not in allowed_cats:
            flash('Invalid category.', 'error')
            return redirect(url_for('portal.add_task'))

        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('portal.add_task'))

        due_date = None
        if due_date_s:
            try:
                due_date = datetime.strptime(due_date_s, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid due date.', 'error')
                return redirect(url_for('portal.add_task'))

        task = Task(
            user_id=contract.user_id,          # owned by the landlord
            title=title,
            description=description,
            category=category,
            priority=priority,
            status='open',
            property_id=contract.property_id,
            room_id=contract.room_id if link_room else None,
            tenant_id=tenant.id,
            due_date=due_date,
            is_public=True,                    # always public — raised by tenant
            repeat='none',
            time_bound=False,
        )
        db.session.add(task)
        db.session.commit()
        flash('Your request has been submitted.', 'success')
        return redirect(url_for('portal.tasks'))

    return render_template('portal/add_task.html',
                           tenant=tenant,
                           contract=contract,
                           categories=TENANT_CATEGORIES,
                           priorities=PRIORITIES)
