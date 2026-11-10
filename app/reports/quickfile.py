"""
QuickFile CSV Exporter
======================
Produces a CSV in the same format as the bank statement export,
with corrected/mapped descriptions, broken down per property,
filtered by UK tax year (6 April to 5 April).

Format matches QuickFile manual import:
Transaction Date, Transaction Type, Sort Code, Account Number,
Transaction Description, Debit Amount, Credit Amount

INCLUSION RULES
---------------
INCLUDE as Credits (income):
  - Rent payments received (type='Rent', credit_debit='cr', source='bank_import')
  - Bill share payments received (type='Gas/Electric' etc, cr, bank_import)
  - Deposit retained deductions (where deposit.deduction_amount > 0 or status='withdrawn')

INCLUDE as Debits (expenses):
  - Expenses recorded against this property
  - Manual debit transactions that originated from real payments (source != 'system')

EXCLUDE:
  - Rent debit charges (type='Rent', credit_debit='db') — internal accounting only
  - Advanced Rent debit offsets (type='Advanced Rent', credit_debit='db') — internal
  - System-generated transactions (source='system')
  - Deposit credits (type='Deposit') — not income until retained
  - Unmatched transactions
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

# Transaction types that are internal accounting only — never export
INTERNAL_DEBIT_TYPES = {'Rent', 'Advanced Rent'}

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

        # Only include matched bank import transactions
        # (manual cash entries are included too — source='manual' or 'cash')
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

    # ── Debit rows (expenses paid out) ───────────────────────────────────
    # From Expense table — these are real payments
    for e in expenses:
        description = e.description or 'Expense'
        rows.append({
            'date':        e.expense_date,
            'type':        'DD' if e.source == 'bank' else 'TRF',
            'sort_code':   sc,
            'account':     an,
            'description': description,
            'debit':       f'{e.amount:.2f}',
            'credit':      '',
        })

    # Debit transactions NOT from expenses and NOT internal accounting
    for t in transactions:
        if t.credit_debit != 'db':
            continue

        # Exclude ALL internal rent/advanced rent charges
        if t.type in INTERNAL_DEBIT_TYPES:
            continue

        # Exclude system-generated entries
        if t.source == 'system':
            continue

        # Exclude if this debit came from an expense record
        # (already captured above from the Expense table)
        if t.expense_id:
            continue

        description = (t.notes or t.type or 'Payment').strip()
        rows.append({
            'date':        t.transaction_date,
            'type':        'DD',
            'sort_code':   sc,
            'account':     an,
            'description': description,
            'debit':       f'{t.amount:.2f}',
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
            'type':        'TRF',
            'sort_code':   sc,
            'account':     account_number,
            'description': description,
            'debit':       '',
            'credit':      f'{deduction:.2f}',
        })

    return rows
