"""
QuickFile CSV Exporter
======================
Produces a CSV in the same format as the bank statement export,
filtered by UK tax year (6 April to 5 April).

Format matches QuickFile manual import:
Transaction Date, Transaction Type, Sort Code, Account Number,
Transaction Description, Debit Amount, Credit Amount

INCLUSION RULES
---------------
INCLUDE as Credits (income):
  - All matched credit transactions (tenant rent, bills, manual cash)
  - Deposit retained deductions (where deposit.deduction_amount > 0)

INCLUDE as Debits (outgoings):
  - Bank import debit transactions with NO tenant (tenant_id IS NULL)
    — these are real bank movements: direct debits, standing orders etc.
    — description and type carried through unchanged from the import
  - Expense table rows with source='bank' or source='cash'

EXCLUDE:
  - Debit transactions linked to a tenant (tenant_id IS NOT NULL)
    — these are internal charges passed to the tenant (rent, bills)
    — they are not money the landlord paid out
  - System-generated transactions (source='system')
  - Deposit credits (type='Deposit') — not income until retained
  - Bill-share calculation entries (expense source='manual')
"""

import csv
import io
from datetime import date
from decimal import Decimal


HEADERS = [
    'Transaction Date',
    'Transaction Type',
    'Sort Code',
    'Account Number',
    'Transaction Description',
    'Debit Amount',
    'Credit Amount',
]

# Transaction types that are not income until a deposit is retained
DEPOSIT_TYPES = {'Deposit'}


def get_tax_year_dates(year: int) -> tuple[date, date]:
    """
    Return start and end of UK tax year.
    year=2026 → 06/04/2025 to 05/04/2026
    """
    return date(year - 1, 4, 6), date(year, 4, 5)


def build_quickfile_csv(transactions, expenses, prop,
                         sort_code='', account_number='',
                         period_start=None, period_end=None) -> str:
    """
    Build a QuickFile-ready CSV string.

    transactions: list of Transaction model instances
    expenses:     list of Expense model instances for this property
    prop:         Property model instance
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(HEADERS)

    sc = f"'{sort_code}" if sort_code else ''
    an = account_number

    rows = []

    # ── Credit rows (income received) ────────────────────────────────────
    for t in transactions:
        if t.credit_debit != 'cr':
            continue

        # Skip internal system entries
        if t.source == 'system':
            continue

        # Skip deposit credits — not income until retained
        if t.type in DEPOSIT_TYPES:
            continue

        # Description: notes already contains "{bank_pattern} {type}" from
        # the matcher (e.g. "JIJIN JOSE Rent"). Fall back to type, then generic.
        description = (t.notes or t.type or 'Payment').strip()

        rows.append({
            'date':        t.transaction_date,
            'type':        'FPI',
            'sort_code':   sc,
            'account':     an,
            'description': description,
            'debit':       '',
            'credit':      f'{t.amount:.2f}',
        })

    # ── Debit rows from bank import (no tenant) ──────────────────────────
    # Real bank outgoings: direct debits, standing orders, fees etc.
    # Only include where tenant_id is None — debit transactions linked to
    # a tenant are internal charges (rent/bills) passed to them, not money
    # the landlord actually paid out.
    for t in transactions:
        if t.credit_debit != 'db':
            continue
        if t.tenant_id is not None:
            continue
        if t.source == 'system':
            continue
        description = (t.notes or t.type or 'Payment').strip()
        rows.append({
            'date':        t.transaction_date,
            'type':        'FPI',
            'sort_code':   sc,
            'account':     an,
            'description': description,
            'debit':       f'{t.amount:.2f}',
            'credit':      '',
        })

    # ── Debit rows from Expense table ────────────────────────────────────
    # Manually recorded expenses with a real cash movement:
    #   source='bank'  → direct debit / standing order entered manually
    #   source='cash'  → cash payment made in hand
    # Exclude source='manual' — bill-share calculation entries only,
    # never appeared as a movement on the landlord's bank account.
    for e in expenses:
        if e.source not in ('bank', 'cash'):
            continue
        description = e.description or 'Expense'
        rows.append({
            'date':        e.expense_date,
            'type':        'FPI',
            'sort_code':   sc,
            'account':     an,
            'description': description,
            'debit':       f'{e.amount:.2f}',
            'credit':      '',
        })

    # Sort all rows by date ascending
    rows.sort(key=lambda r: r['date'])

    for row in rows:
        writer.writerow([
            row['date'].strftime('%d/%m/%Y'),
            row['type'],
            row['sort_code'],
            row['account'],
            row['description'],
            row['debit'],
            row['credit'],
        ])

    return output.getvalue()


def build_retained_deposit_rows(user_id: int, property_id: int,
                                 period_start: date, period_end: date,
                                 sort_code: str = '',
                                 account_number: str = '') -> list[dict]:
    """
    Returns QuickFile rows for any deposit deductions that are
    genuine income (retained deposits after move-out).

    Only includes deposits where:
      - status = 'withdrawn' (fully retained) OR
      - deduction_amount > 0 (partial retention)
    AND the returned_date falls within the export period.
    """
    from app.models import Deposit, Tenant

    sc = f"'{sort_code}" if sort_code else ''
    rows = []

    deposits = Deposit.query.join(Tenant).filter(
        Tenant.user_id == user_id,
    ).all()

    for dep in deposits:
        # Only retained deposits are income
        if dep.status not in ('withdrawn', 'paid'):
            continue

        deduction = Decimal(str(dep.deduction_amount or 0))
        if deduction <= Decimal('0.00'):
            continue

        # Use returned_date as the transaction date
        ref_date = dep.returned_date or dep.date_received
        if not ref_date:
            continue

        if not (period_start <= ref_date <= period_end):
            continue

        tenant_name = dep.tenant.full_name if dep.tenant else 'Unknown'
        description = f'{tenant_name} Deposit Retained'
        if dep.deduction_reason:
            description += f' — {dep.deduction_reason[:50]}'

        rows.append({
            'date':        ref_date,
            'type':        'FPI',
            'sort_code':   sc,
            'account':     account_number,
            'description': description,
            'debit':       '',
            'credit':      f'{deduction:.2f}',
        })

    return rows
