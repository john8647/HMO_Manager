"""
QuickFile CSV exporter.

Produces a CSV in the same format as the bank statement,
with corrected/mapped descriptions, filtered by property
and UK tax year (April to April).
"""

import csv
import io
from datetime import date


HEADERS = [
    'Transaction Date', 'Transaction Type', 'Sort Code',
    'Account Number', 'Transaction Description', 'Debit Amount', 'Credit Amount'
]


def get_tax_year_dates(year: int) -> tuple[date, date]:
    """
    Return start and end of UK tax year.
    e.g. year=2026 → 06/04/2025 to 05/04/2026
    """
    return date(year - 1, 4, 6), date(year, 4, 5)


def build_quickfile_csv(transactions: list, property_ref: str = '',
                         sort_code: str = '', account_number: str = '') -> str:
    """
    Build a QuickFile-ready CSV string from a list of transaction dicts.

    Each transaction dict should have:
        - transaction_date (date)
        - transaction_type (str)
        - description (str) — the preferred mapped description
        - debit_amount (Decimal or None)
        - credit_amount (Decimal or None)
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(HEADERS)

    for t in transactions:
        writer.writerow([
            t['transaction_date'].strftime('%d/%m/%Y'),
            t.get('transaction_type', 'TRF'),
            f"'{sort_code}" if sort_code else '',
            f"'{account_number}" if account_number else '',
            t['description'],
            f"{t['debit_amount']:.2f}" if t.get('debit_amount') else '',
            f"{t['credit_amount']:.2f}" if t.get('credit_amount') else '',
        ])

    return output.getvalue()
