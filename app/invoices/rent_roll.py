"""
Rent Roll
=========
Builds a live snapshot of every active tenant's financial position:
  - Monthly rent due
  - Next rent due date
  - Outstanding invoice total
  - Rent balance (cumulative)
  - Bill balance (cumulative)
  - Total owed
  - Payment status (current / overdue / in credit)
  - Last payment date and amount
"""

from decimal import Decimal
from datetime import date
from app.models import (Tenant, TenantContract, Invoice,
                        InvoicePayment, Transaction, Property)


def build_rent_roll(user_id: int, property_id: int = None) -> list[dict]:
    """
    Returns a list of dicts — one per active tenant — sorted by
    property then tenant name.
    """
    query = Tenant.query.filter_by(user_id=user_id, is_active=True)
    tenants = query.order_by(Tenant.last_name).all()

    rows = []
    today = date.today()

    for tenant in tenants:
        # Get active contract
        contract = TenantContract.query.filter_by(
            tenant_id=tenant.id, is_active=True
        ).first()

        if not contract:
            continue

        # Filter by property if specified
        if property_id and contract.property_id != property_id:
            continue

        # Outstanding invoices
        outstanding_invoices = Invoice.query.filter(
            Invoice.tenant_id == tenant.id,
            Invoice.status.in_(['issued', 'partially_paid', 'overdue'])
        ).all()

        total_outstanding = sum(
            Decimal(str(inv.total_due or 0)) -
            Decimal(str(inv.amount_paid or 0))
            for inv in outstanding_invoices
        )

        # Balances from tenant record
        rent_balance = Decimal(str(tenant.rent_balance or 0))
        bill_balance = Decimal(str(tenant.bill_balance or 0))
        total_balance = rent_balance + bill_balance

        # Last payment
        last_payment = Transaction.query.filter_by(
            tenant_id=tenant.id,
            credit_debit='cr',
            is_matched=True,
        ).order_by(Transaction.transaction_date.desc()).first()

        # Overdue check — any issued invoice past due date
        overdue_invoices = [
            inv for inv in outstanding_invoices
            if inv.due_date and inv.due_date < today
        ]

        # Days overdue (worst case)
        days_overdue = 0
        if overdue_invoices:
            oldest_due = min(inv.due_date for inv in overdue_invoices)
            days_overdue = (today - oldest_due).days

        # Status
        if total_outstanding <= Decimal('0.01') and total_balance <= Decimal('0.01'):
            status = 'current'
        elif total_balance < Decimal('0.00'):
            status = 'credit'
        elif overdue_invoices:
            status = 'overdue'
        else:
            status = 'outstanding'

        rows.append({
            'tenant':             tenant,
            'contract':           contract,
            'property':           contract.property,
            'room':               contract.room,
            'monthly_rent':       Decimal(str(contract.monthly_rent or 0)),
            'next_rent_due':      contract.next_rent_due,
            'rent_balance':       rent_balance,
            'bill_balance':       bill_balance,
            'total_balance':      total_balance,
            'total_outstanding':  total_outstanding,
            'outstanding_invoices': outstanding_invoices,
            'overdue_invoices':   overdue_invoices,
            'days_overdue':       days_overdue,
            'last_payment':       last_payment,
            'status':             status,
        })

    # Sort: overdue first, then outstanding, then current, then credit
    status_order = {'overdue': 0, 'outstanding': 1, 'current': 2, 'credit': 3}
    rows.sort(key=lambda r: (
        status_order.get(r['status'], 99),
        r['property'].address_line1,
        r['tenant'].last_name,
    ))

    return rows
