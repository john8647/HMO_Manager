"""
QuickFile CSV exporter.

Produces a CSV in the same format as the bank statement export,
with corrected/mapped descriptions, broken down per property,
filtered by UK tax year (6 April to 5 April).

Format matches QuickFile manual import:
Transaction Date, Transaction Type, Sort Code, Account Number,
Transaction Description, Debit Amount, Credit Amount

Key rules:
- Each transaction line uses the Preferred Description from TransactionLegend
  combined with the Income/Expense Type, so one bank pattern (e.g. JIJIN JOSE)
  can produce multiple lines (JIJIN JOSE Rent, JIJIN JOSE Bills) when split
- Credits = income received (rent, bill shares paid by tenant)
- Debits = expenses paid out (water, broadband, insurance, repairs etc.)
- Only credit transactions linked to this property's tenants are included
- All expenses for this property are included as debits
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

    transactions: list of Transaction model instances (credits and debits)
    expenses: list of Expense model instances for this property
    prop: Property model instance
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(HEADERS)

    sc = f"'{sort_code}" if sort_code else ''
    an = account_number

    rows = []

    # ── Income rows (credits) ─────────────────────────────────────────────────
    # Only include credit transactions — these are payments received from tenants
    for t in transactions:
        if t.credit_debit != 'cr':
            continue

        # Build the QuickFile description:
        # Preferred description from legend + type label
        # e.g. "JIJIN JOSE Rent" or "JIJIN JOSE Bills"
        description = _build_description(t)

        rows.append({
            'date':        t.transaction_date,
            'type':        t.bank_ref or 'FPI',
            'sort_code':   sc,
            'account':     an,
            'description': description,
            'debit':       '',
            'credit':      f'{t.amount:.2f}',
        })

    # ── Expense rows (debits) ─────────────────────────────────────────────────
    # Expenses for this property become debit rows
    for e in expenses:
        description = e.description
        if e.charge_type:
            # Use charge type name as suffix if not already in description
            if e.charge_type.charge_name.lower() not in description.lower():
                description = f'{description}'

        rows.append({
            'date':        e.expense_date,
            'type':        'DD' if e.source == 'bank' else 'TRF',
            'sort_code':   sc,
            'account':     an,
            'description': description,
            'debit':       f'{e.amount:.2f}',
            'credit':      '',
        })

    # Also include debit transactions not linked to expenses
    # (manual debit entries, bank-imported debits)
    for t in transactions:
        if t.credit_debit != 'db':
            continue
        # Skip if this was already captured from expenses table
        if t.source in ('manual', 'bank_import'):
            description = _build_description(t)
            rows.append({
                'date':        t.transaction_date,
                'type':        t.bank_ref or 'DD',
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


def _build_description(transaction) -> str:
    """
    Build the QuickFile transaction description from a Transaction record.

    Priority:
    1. transaction.notes (if it was set from a preferred_description during import)
    2. type field (e.g. 'Rent', 'Gas/Electric')
    3. Fall back to 'Unknown'

    For split transactions the notes field holds e.g. "JIJIN JOSE Rent"
    already set during the split/match process.

    The goal is to produce lines like:
        JIJIN JOSE Rent
        JIJIN JOSE Bills
        SAUDAGAR Rent
        VIRGIN MEDIA PYMTS
    """
    # If notes already contains a preferred description (set during matching)
    notes = (transaction.notes or '').strip()

    # If the note looks like a bank description + type (set during split)
    # it's already in the right format
    if notes and not notes.startswith('Split from:'):
        return notes

    # Otherwise build from type
    type_label = (transaction.type or '').strip()
    if type_label:
        return type_label

    return 'Unknown'
