"""
Rent Roll
=========
Builds a live snapshot of every active tenant's financial position
by reading directly from Transaction debits and credits — not from
the cached tenant.rent_balance / bill_balance fields, which can drift.

Balance model:
  rent_balance  = SUM(Rent db + Advanced Rent db) - SUM(Rent cr + Advanced Rent cr)
  bill_balance  = SUM(Bills db)                   - SUM(Bills cr)
  total_balance = rent_balance + bill_balance

A positive balance means the tenant owes money.
A negative balance means they are in credit.
"""

from decimal import Decimal
from datetime import date
from app.models import Tenant, TenantContract, Invoice, Transaction, Property


def _tx_sum(tenant_id, credit_debit, types):
    rows = Transaction.query.filter(
        Transaction.tenant_id == tenant_id,
        Transaction.credit_debit == credit_debit,
        Transaction.type.in_(types),
    ).all()
    return sum(Decimal(str(t.amount)) for t in rows)


def build_rent_roll(user_id: int, property_id: int = None) -> list[dict]:
    tenants = Tenant.query.filter_by(
        user_id=user_id, is_active=True
    ).order_by(Tenant.last_name).all()

    rows = []
    today = date.today()

    for tenant in tenants:
        contract = TenantContract.query.filter_by(
            tenant_id=tenant.id, is_active=True
        ).first()
        if not contract:
            continue
        if property_id and contract.property_id != property_id:
            continue

        # ── Live balances from transactions ───────────────────────────
        rent_db  = _tx_sum(tenant.id, 'db', ['Rent', 'Advanced Rent'])
        rent_cr  = _tx_sum(tenant.id, 'cr', ['Rent', 'Advanced Rent'])
        bills_db = _tx_sum(tenant.id, 'db', ['Bills'])
        bills_cr = _tx_sum(tenant.id, 'cr', ['Bills'])

        rent_balance  = rent_db  - rent_cr
        bill_balance  = bills_db - bills_cr
        total_balance = rent_balance + bill_balance

        # ── Outstanding invoices (for display, not balance calc) ──────
        outstanding_invoices = Invoice.query.filter(
            Invoice.tenant_id == tenant.id,
            Invoice.status.in_(['issued', 'partially_paid', 'overdue'])
        ).all()

        # ── Last payment ──────────────────────────────────────────────
        last_payment = Transaction.query.filter_by(
            tenant_id=tenant.id,
            credit_debit='cr',
            is_matched=True,
        ).order_by(Transaction.transaction_date.desc()).first()

        # ── Overdue check ─────────────────────────────────────────────
        overdue_invoices = [
            inv for inv in outstanding_invoices
            if inv.due_date and inv.due_date < today
        ]
        days_overdue = 0
        if overdue_invoices:
            oldest_due   = min(inv.due_date for inv in overdue_invoices)
            days_overdue = (today - oldest_due).days

        # ── Status ────────────────────────────────────────────────────
        if total_balance < Decimal('-0.01'):
            status = 'credit'
        elif total_balance <= Decimal('0.01'):
            status = 'current'
        elif overdue_invoices:
            status = 'overdue'
        else:
            status = 'outstanding'

        total_outstanding = sum(
            max(
                Decimal(str(inv.total_due or 0)) -
                Decimal(str(inv.amount_paid or 0)),
                Decimal('0.00')
            )
            for inv in outstanding_invoices
        )

        rows.append({
            'tenant':               tenant,
            'contract':             contract,
            'property':             contract.property,
            'room':                 contract.room,
            'monthly_rent':         Decimal(str(contract.monthly_rent or 0)),
            'next_rent_due':        contract.next_rent_due,
            'rent_balance':         rent_balance,
            'bill_balance':         bill_balance,
            'total_balance':        total_balance,
            'total_outstanding':    total_outstanding,
            'outstanding_invoices': outstanding_invoices,
            'overdue_invoices':     overdue_invoices,
            'days_overdue':         days_overdue,
            'last_payment':         last_payment,
            'status':               status,
        })

    status_order = {'overdue': 0, 'outstanding': 1, 'current': 2, 'credit': 3}
    rows.sort(key=lambda r: (
        status_order.get(r['status'], 99),
        r['property'].address_line1,
        r['tenant'].last_name,
    ))
    return rows
