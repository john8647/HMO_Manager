"""
Payment Matching Engine
=======================
When a bank import row is matched to a tenant via TransactionLegend,
this engine:

1. Looks up all outstanding invoices for that tenant (oldest first)
2. Automatically splits the payment across rent and bill portions
3. Creates Transaction credit rows with correct Notes for QuickFile
4. Creates InvoicePayment records linking payments to invoices
5. Updates invoice amount_paid and status
6. Updates tenant rent_balance and bill_balance

QuickFile description format (from Notes field):
  "GOLLA H Rent"   → credit transaction for rent portion
  "GOLLA H Bills"  → credit transaction for bills portion

The preferred_description from TransactionLegend is the base
(e.g. "GOLLA H"), and the type label is appended.
"""

from decimal import Decimal
from datetime import date
from app import db
from app.models import (Invoice, InvoiceItem, InvoicePayment,
                        Transaction, Tenant, PicklistCharge)


def get_outstanding_invoices(tenant_id: int) -> list:
    """
    Return all issued/partially_paid invoices for a tenant,
    oldest first (by issue_date then id).
    """
    return Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(['issued', 'partially_paid'])
    ).order_by(
        Invoice.issue_date.asc(),
        Invoice.id.asc()
    ).all()


def invoice_outstanding(invoice: Invoice) -> Decimal:
    """Return the outstanding balance on an invoice."""
    total = Decimal(str(invoice.total_due or 0))
    paid  = Decimal(str(invoice.amount_paid or 0))
    return max(total - paid, Decimal('0.00'))


def invoice_rent_outstanding(invoice: Invoice) -> Decimal:
    """Return how much of the outstanding balance is rent."""
    paid      = Decimal(str(invoice.amount_paid or 0))
    total_due = Decimal(str(invoice.total_due or 0))
    if paid >= total_due:
        return Decimal('0.00')

    # Sum rent items
    rent_charge = PicklistCharge.query.filter_by(charge_name='Rent').first()
    rent_total = Decimal('0.00')
    for item in invoice.items:
        if rent_charge and item.charge_type_id == rent_charge.id:
            rent_total += Decimal(str(item.amount))
        elif item.description and 'rent' in item.description.lower():
            rent_total += Decimal(str(item.amount))

    # How much rent has already been paid?
    # We approximate: rent is paid first
    already_paid = paid
    rent_paid = min(already_paid, rent_total)
    return max(rent_total - rent_paid, Decimal('0.00'))


def invoice_bills_outstanding(invoice: Invoice) -> Decimal:
    """Return how much of the outstanding balance is bills (non-rent)."""
    paid      = Decimal(str(invoice.amount_paid or 0))
    total_due = Decimal(str(invoice.total_due or 0))
    if paid >= total_due:
        return Decimal('0.00')

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

    # Rent paid first
    already_paid  = paid
    rent_paid     = min(already_paid, rent_total)
    bills_paid    = min(max(already_paid - rent_paid, Decimal('0')), bills_total)
    return max(bills_total - bills_paid, Decimal('0.00'))


def auto_match_payment(
    tenant_id: int,
    payment_amount: Decimal,
    payment_date: date,
    user_id: int,
    bank_import_id: int,
    preferred_description: str,
    transaction_type: str = 'FPI',
) -> dict:
    """
    Main entry point. Auto-splits a payment across outstanding invoices.

    Returns a dict with:
        transactions_created: list of Transaction objects
        invoices_updated:     list of Invoice objects
        rent_allocated:       Decimal
        bills_allocated:      Decimal
        surplus:              Decimal (overpayment beyond all invoices)
        summary:              list of human-readable strings
    """
    remaining     = Decimal(str(payment_amount))
    rent_alloc    = Decimal('0.00')
    bills_alloc   = Decimal('0.00')
    transactions  = []
    inv_updated   = []
    summary       = []

    invoices = get_outstanding_invoices(tenant_id)

    for invoice in invoices:
        if remaining <= Decimal('0.00'):
            break

        outstanding = invoice_outstanding(invoice)
        if outstanding <= Decimal('0.00'):
            continue

        # How much of this invoice is rent vs bills
        rent_due  = invoice_rent_outstanding(invoice)
        bills_due = invoice_bills_outstanding(invoice)

        # Pay rent portion first
        rent_payment = min(rent_due, remaining)
        if rent_payment > Decimal('0.00'):
            remaining   -= rent_payment
            rent_alloc  += rent_payment

        # Then pay bills portion
        bills_payment = min(bills_due, remaining)
        if bills_payment > Decimal('0.00'):
            remaining   -= bills_payment
            bills_alloc += bills_payment

        total_payment = rent_payment + bills_payment

        # Update invoice
        invoice.amount_paid = Decimal(str(invoice.amount_paid or 0)) + total_payment
        new_outstanding = invoice_outstanding(invoice)

        if new_outstanding <= Decimal('0.01'):
            invoice.status = 'paid'
        else:
            invoice.status = 'partially_paid'

        inv_updated.append(invoice)

        # Create InvoicePayment record — one per invoice
        # (we'll link it to transactions after creating them)
        summary.append(
            f'Invoice {invoice.invoice_number}: '
            f'£{total_payment:.2f} applied '
            f'(rent £{rent_payment:.2f}, bills £{bills_payment:.2f})'
        )

    # Update tenant balances
    tenant = Tenant.query.get(tenant_id)
    if tenant:
        tenant.rent_balance = Decimal(str(tenant.rent_balance or 0)) - rent_alloc
        tenant.bill_balance = Decimal(str(tenant.bill_balance or 0)) - bills_alloc

    # Create Transaction credit rows
    # One for rent, one for bills — matching QuickFile format
    base_desc = preferred_description or ''

    if rent_alloc > Decimal('0.00'):
        t_rent = Transaction(
            tenant_id=tenant_id,
            amount=rent_alloc,
            credit_debit='cr',
            transaction_date=payment_date,
            user_id=user_id,
            type='Rent',
            month_year_period=payment_date.strftime('%B %Y'),
            source='bank_import',
            bank_import_id=bank_import_id,
            is_matched=True,
            notes=f'{base_desc} Rent'.strip(),
        )
        db.session.add(t_rent)
        transactions.append(t_rent)

    if bills_alloc > Decimal('0.00'):
        t_bills = Transaction(
            tenant_id=tenant_id,
            amount=bills_alloc,
            credit_debit='cr',
            transaction_date=payment_date,
            user_id=user_id,
            type='Gas/Electric',
            month_year_period=payment_date.strftime('%B %Y'),
            source='bank_import',
            bank_import_id=bank_import_id,
            is_matched=True,
            notes=f'{base_desc} Bills'.strip(),
        )
        db.session.add(t_bills)
        transactions.append(t_bills)

    # Handle surplus after all invoices are settled
    surplus = remaining
    if surplus > Decimal('0.00'):
        from app.models import Deposit

        # Check if amount matches a pending deposit
        existing_deposit = Deposit.query.filter_by(
            tenant_id=tenant_id,
            status='pending'
        ).first()

        if existing_deposit and abs(
            surplus - Decimal(str(existing_deposit.amount))
        ) < Decimal('1.00'):
            surplus_type  = 'Deposit'
            surplus_notes = f'{base_desc} Deposit'.strip()
            surplus_msg   = (
                f'£{surplus:.2f} matched to deposit '
                f'DEP-{existing_deposit.id:04d}.'
            )
        else:
            # Treat as early/advance rent payment — NOT "Advanced Rent"
            # label. Use plain "Rent" so rent engine skips this period.
            surplus_type  = 'Rent'
            surplus_notes = f'{base_desc} Rent'.strip()
            surplus_msg   = (
                f'£{surplus:.2f} recorded as Rent credit '
                f'(paid ahead of charge).'
            )

        t_surplus = Transaction(
            tenant_id=tenant_id,
            amount=surplus,
            credit_debit='cr',
            transaction_date=payment_date,
            user_id=user_id,
            type=surplus_type,
            month_year_period=payment_date.strftime('%B %Y'),
            source='bank_import',
            bank_import_id=bank_import_id,
            is_matched=True,
            notes=surplus_notes,
        )
        db.session.add(t_surplus)
        transactions.append(t_surplus)
        # Adjust tenant balance
        tenant = Tenant.query.get(tenant_id)
        if tenant and surplus_type == 'Rent':
            tenant.rent_balance = (
                Decimal(str(tenant.rent_balance or 0)) - surplus
            )
        summary.append(surplus_msg)

    db.session.flush()

    # Link InvoicePayment records to first rent transaction
    if transactions and inv_updated:
        first_tx = transactions[0]
        for invoice in inv_updated:
            ip = InvoicePayment(
                invoice_id=invoice.id,
                transaction_id=first_tx.id,
                amount=Decimal(str(invoice.amount_paid or 0)),
                payment_date=payment_date,
                notes=f'Auto-matched from bank import {bank_import_id}',
            )
            db.session.add(ip)

    if not summary:
        # No outstanding invoices found — payment arrived before rent
        # charge was generated (tenant paid early / on standing order).
        # Always label as Rent so the rent engine skips this month.
        if surplus > Decimal('0.00'):
            t_rent = Transaction(
                tenant_id=tenant_id,
                amount=surplus,
                credit_debit='cr',
                transaction_date=payment_date,
                user_id=user_id,
                type='Rent',
                month_year_period=payment_date.strftime('%B %Y'),
                source='bank_import',
                bank_import_id=bank_import_id,
                is_matched=True,
                notes=f'{base_desc} Rent'.strip(),
            )
            db.session.add(t_rent)
            transactions.append(t_rent)
            tenant = Tenant.query.get(tenant_id)
            if tenant:
                tenant.rent_balance = (
                    Decimal(str(tenant.rent_balance or 0)) - surplus
                )
            surplus = Decimal('0.00')
            summary.append(
                f'£{payment_amount:.2f} recorded as Rent — '
                f'rent engine will skip {payment_date.strftime("%B %Y")}.'
            )

    # Recalculate balance from raw transactions to prevent drift
    from app.invoices.rent_engine import recalculate_tenant_balance
    recalculate_tenant_balance(tenant_id)

    return {
        'transactions_created': transactions,
        'invoices_updated':     inv_updated,
        'rent_allocated':       rent_alloc,
        'bills_allocated':      bills_alloc,
        'surplus':              surplus,
        'summary':              summary,
    }
