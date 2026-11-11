"""
Payment Matching Engine
=======================
Priority order for splitting an incoming payment:

  1. Advanced Rent debits outstanding  (from contract creation)
  2. Rent debits outstanding           (from rent engine)
  3. Bills debits outstanding          (from invoice issue)
  4. Surplus → Deposit check → early Rent credit

Every charge type now has a Transaction debit, so the matcher
simply works through debits in priority order.
"""

from decimal import Decimal
from datetime import date
from app import db
from app.models import Invoice, InvoicePayment, Transaction, Tenant


def _outstanding_debit(tenant_id: int, type_: str) -> Decimal:
    """
    Net outstanding for a debit type:
      SUM(debits of type_) - SUM(credits of type_)
    Returns 0 if already in credit.
    """
    debits = Transaction.query.filter_by(
        tenant_id=tenant_id, credit_debit='db', type=type_
    ).all()
    credits = Transaction.query.filter_by(
        tenant_id=tenant_id, credit_debit='cr', type=type_
    ).all()
    total_db = sum(Decimal(str(t.amount)) for t in debits)
    total_cr = sum(Decimal(str(t.amount)) for t in credits)
    return max(total_db - total_cr, Decimal('0.00'))


def auto_match_payment(
    tenant_id: int,
    payment_amount: Decimal,
    payment_date: date,
    user_id: int,
    bank_import_id: int,
    preferred_description: str,
    transaction_type: str = 'FPI',
) -> dict:
    remaining   = Decimal(str(payment_amount))
    transactions = []
    summary      = []
    base_desc    = (preferred_description or '').strip()

    def make_credit(amount, type_, notes):
        t = Transaction(
            tenant_id=tenant_id,
            amount=amount,
            credit_debit='cr',
            transaction_date=payment_date,
            user_id=user_id,
            type=type_,
            month_year_period=payment_date.strftime('%B %Y'),
            source='bank_import',
            bank_import_id=bank_import_id,
            is_matched=True,
            notes=notes,
        )
        db.session.add(t)
        return t

    # ── STEP 1: Advanced Rent ────────────────────────────────────────────
    adv_owed = _outstanding_debit(tenant_id, 'Advanced Rent')
    if adv_owed > Decimal('0.00') and remaining > Decimal('0.00'):
        pay = min(adv_owed, remaining)
        remaining -= pay
        t = make_credit(pay, 'Advanced Rent',
                        f'{base_desc} Advanced Rent'.strip())
        transactions.append(t)
        summary.append(f'£{pay:.2f} → Advanced Rent charge.')

    # ── STEP 2: Rent ─────────────────────────────────────────────────────
    rent_owed = _outstanding_debit(tenant_id, 'Rent')
    if rent_owed > Decimal('0.00') and remaining > Decimal('0.00'):
        pay = min(rent_owed, remaining)
        remaining -= pay
        t = make_credit(pay, 'Rent', f'{base_desc} Rent'.strip())
        transactions.append(t)
        summary.append(f'£{pay:.2f} → Rent charge.')

    # ── STEP 3: Bills ────────────────────────────────────────────────────
    bills_owed = _outstanding_debit(tenant_id, 'Bills')
    if bills_owed > Decimal('0.00') and remaining > Decimal('0.00'):
        pay = min(bills_owed, remaining)
        remaining -= pay
        t = make_credit(pay, 'Bills', f'{base_desc} Bills'.strip())
        transactions.append(t)
        # Mark invoices settled oldest first
        _settle_invoices(tenant_id, pay, payment_date, bank_import_id)
        summary.append(f'£{pay:.2f} → Bill invoices.')

    # ── STEP 4: Surplus ──────────────────────────────────────────────────
    if remaining > Decimal('0.00'):
        from app.models import Deposit
        dep = Deposit.query.filter_by(
            tenant_id=tenant_id, status='pending'
        ).first()
        if dep and abs(remaining - Decimal(str(dep.amount))) < Decimal('1.00'):
            t = make_credit(remaining, 'Deposit',
                            f'{base_desc} Deposit'.strip())
            transactions.append(t)
            summary.append(f'£{remaining:.2f} → Deposit.')
        else:
            # Early payment — label as Rent so rent engine skips period
            t = make_credit(remaining, 'Rent',
                            f'{base_desc} Rent'.strip())
            transactions.append(t)
            summary.append(
                f'£{remaining:.2f} recorded as early Rent '
                f'({payment_date.strftime("%B %Y")}).'
            )
        remaining = Decimal('0.00')

    # Flush and recalculate balance from raw transactions
    db.session.flush()
    from app.invoices.rent_engine import recalculate_tenant_balance
    recalculate_tenant_balance(tenant_id)

    if not summary:
        summary.append(f'£{payment_amount:.2f} recorded.')

    return {
        'transactions_created': transactions,
        'invoices_updated':     [],
        'rent_allocated':       Decimal('0.00'),
        'bills_allocated':      Decimal('0.00'),
        'surplus':              remaining,
        'summary':              summary,
    }


def _settle_invoices(tenant_id, bills_payment, payment_date, bank_import_id):
    """Mark bill invoices as paid/partially paid oldest first."""
    invoices = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(['issued', 'partially_paid'])
    ).order_by(Invoice.issue_date.asc(), Invoice.id.asc()).all()

    remaining = Decimal(str(bills_payment))
    for inv in invoices:
        if remaining <= Decimal('0.00'):
            break
        outstanding = max(
            Decimal(str(inv.total_due or 0)) -
            Decimal(str(inv.amount_paid or 0)),
            Decimal('0.00')
        )
        if outstanding <= Decimal('0.00'):
            continue
        pay = min(outstanding, remaining)
        remaining -= pay
        inv.amount_paid = Decimal(str(inv.amount_paid or 0)) + pay
        new_out = Decimal(str(inv.total_due or 0)) - inv.amount_paid
        inv.status = 'paid' if new_out <= Decimal('0.01') else 'partially_paid'
