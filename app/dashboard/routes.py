from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from datetime import date, timedelta
from decimal import Decimal
from app.models import Property, Room, Tenant, TenantContract, Transaction, \
    ComplianceDocument, Task, Invoice
from app.utils import landlord_required

dashboard_bp = Blueprint('dashboard', __name__)

LOOKAHEAD_DAYS = 7


def _outstanding(tenant_id, type_):
    """Net outstanding for a debit type (debits - credits), min 0."""
    debits = Transaction.query.filter_by(
        tenant_id=tenant_id, credit_debit='db', type=type_
    ).all()
    credits_ = Transaction.query.filter_by(
        tenant_id=tenant_id, credit_debit='cr', type=type_
    ).all()
    total_db = sum(Decimal(str(t.amount)) for t in debits)
    total_cr = sum(Decimal(str(t.amount)) for t in credits_)
    return max(total_db - total_cr, Decimal('0.00'))


@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@login_required
@landlord_required
def index():
    today = date.today()
    lookahead = today + timedelta(days=LOOKAHEAD_DAYS)
    uid = current_user.id

    # ── All properties for this user ────────────────────────────────────
    properties = Property.query.filter_by(user_id=uid).order_by(
        Property.address_line1
    ).all()

    # ── Build per-property cards ─────────────────────────────────────────
    cards = []
    for prop in properties:
        # Active tenants & vacant rooms
        all_rooms = Room.query.filter_by(property_id=prop.id).all()
        total_rooms = len(all_rooms)

        active_contracts = TenantContract.query.filter_by(
            property_id=prop.id, is_active=True
        ).all()
        active_tenant_ids = [c.tenant_id for c in active_contracts]
        active_count = len(active_contracts)
        vacant_count = max(total_rooms - active_count, 0)

        # Outstanding balances across all active tenants in this property
        total_rent_outstanding = Decimal('0.00')
        total_bills_outstanding = Decimal('0.00')
        overdue_tenants = []

        for tid in active_tenant_ids:
            rent_out = _outstanding(tid, 'Rent') + _outstanding(tid, 'Advanced Rent')
            bills_out = _outstanding(tid, 'Bills')
            total_rent_outstanding += rent_out
            total_bills_outstanding += bills_out

            # Tenant overdue check: any issued invoice past due_date
            overdue_inv = Invoice.query.filter(
                Invoice.tenant_id == tid,
                Invoice.status.in_(['issued', 'partially_paid', 'overdue']),
                Invoice.due_date < today,
            ).first()
            tenant = Tenant.query.get(tid)
            if (overdue_inv or rent_out > Decimal('0.01')) and tenant:
                overdue_tenants.append({
                    'tenant': tenant,
                    'rent_owed': rent_out,
                    'bills_owed': bills_out,
                })

        total_outstanding = total_rent_outstanding + total_bills_outstanding

        # Rooms at this property (for task lookup by room_id)
        prop_room_ids = [r.id for r in all_rooms]

        def _task_base():
            """Base filter: tasks belonging to this property by any link."""
            from sqlalchemy import or_
            return Task.query.filter(
                Task.user_id == uid,
                Task.status.in_(['open', 'in_progress']),
                or_(
                    Task.property_id == prop.id,
                    Task.room_id.in_(prop_room_ids) if prop_room_ids else False,
                    Task.tenant_id.in_(active_tenant_ids) if active_tenant_ids else False,
                )
            )

        # Tasks due within LOOKAHEAD_DAYS for this property
        tasks_due = _task_base().filter(
            Task.due_date != None,
            Task.due_date >= today,
            Task.due_date <= lookahead,
        ).order_by(Task.due_date.asc(), Task.priority.desc()).all()

        # Overdue tasks (past due, still open)
        tasks_overdue = _task_base().filter(
            Task.due_date != None,
            Task.due_date < today,
        ).order_by(Task.due_date.asc()).all()

        # Open tasks with no due date (undated — just show count)
        tasks_undated = _task_base().filter(
            Task.due_date == None,
        ).count()

        # Compliance documents expiring within LOOKAHEAD_DAYS
        compliance_due = ComplianceDocument.query.filter(
            ComplianceDocument.property_id == prop.id,
            ComplianceDocument.expiry_date != None,
            ComplianceDocument.expiry_date >= today,
            ComplianceDocument.expiry_date <= lookahead,
        ).order_by(ComplianceDocument.expiry_date.asc()).all()

        # Expired compliance docs
        compliance_expired = ComplianceDocument.query.filter(
            ComplianceDocument.property_id == prop.id,
            ComplianceDocument.expiry_date != None,
            ComplianceDocument.expiry_date < today,
        ).order_by(ComplianceDocument.expiry_date.asc()).all()

        # Recent payments (last 5 credits across all tenants in this property)
        recent_payments = Transaction.query.filter(
            Transaction.tenant_id.in_(active_tenant_ids),
            Transaction.credit_debit == 'cr',
            Transaction.is_matched == True,
        ).order_by(Transaction.transaction_date.desc()).limit(5).all() \
            if active_tenant_ids else []

        # Overall property status flag
        if compliance_expired or tasks_overdue:
            status = 'danger'
        elif total_outstanding > Decimal('0.01') or compliance_due or tasks_due or tasks_undated:
            status = 'warning'
        else:
            status = 'ok'

        cards.append({
            'property': prop,
            'total_rooms': total_rooms,
            'active_count': active_count,
            'vacant_count': vacant_count,
            'total_rent_outstanding': total_rent_outstanding,
            'total_bills_outstanding': total_bills_outstanding,
            'total_outstanding': total_outstanding,
            'overdue_tenants': overdue_tenants,
            'tasks_due': tasks_due,
            'tasks_overdue': tasks_overdue,
            'tasks_undated': tasks_undated,
            'compliance_due': compliance_due,
            'compliance_expired': compliance_expired,
            'recent_payments': recent_payments,
            'status': status,
        })

    # ── Global summary numbers ───────────────────────────────────────────
    total_properties = len(properties)
    total_active_tenants = sum(c['active_count'] for c in cards)
    total_vacant = sum(c['vacant_count'] for c in cards)
    total_money_outstanding = sum(c['total_outstanding'] for c in cards)
    total_compliance_issues = sum(
        len(c['compliance_expired']) + len(c['compliance_due']) for c in cards
    )
    total_task_alerts = sum(
        len(c['tasks_overdue']) + len(c['tasks_due']) + c['tasks_undated']
        for c in cards
    )

    return render_template(
        'dashboard/index.html',
        cards=cards,
        today=today,
        lookahead_days=LOOKAHEAD_DAYS,
        total_properties=total_properties,
        total_active_tenants=total_active_tenants,
        total_vacant=total_vacant,
        total_money_outstanding=total_money_outstanding,
        total_compliance_issues=total_compliance_issues,
        total_task_alerts=total_task_alerts,
    )
