"""
Bank statement CSV importer.

Expected CSV format from bank:
Transaction Date, Transaction Type, Sort Code, Account Number,
Transaction Description, Debit Amount, Credit Amount
"""

import csv
import io
from datetime import datetime
from decimal import Decimal


EXPECTED_HEADERS = [
    'Transaction Date', 'Transaction Type', 'Sort Code',
    'Account Number', 'Transaction Description', 'Debit Amount', 'Credit Amount'
]


def parse_bank_csv(file_content: str) -> list[dict]:
    """
    Parse bank statement CSV content into a list of row dicts.
    Strips quotes and whitespace from all values.
    Returns list of parsed rows or raises ValueError on bad format.
    """
    reader = csv.DictReader(io.StringIO(file_content))

    # Validate headers
    headers = [h.strip() for h in (reader.fieldnames or [])]
    for expected in EXPECTED_HEADERS:
        if expected not in headers:
            raise ValueError(
                f"Missing column '{expected}'. "
                f"Found: {headers}"
            )

    rows = []
    for i, row in enumerate(reader, start=2):
        try:
            transaction_date = datetime.strptime(
                row['Transaction Date'].strip(), '%d/%m/%Y'
            ).date()
        except ValueError:
            raise ValueError(f"Row {i}: Invalid date '{row['Transaction Date']}'")

        debit_raw = row.get('Debit Amount', '').strip().replace(',', '')
        credit_raw = row.get('Credit Amount', '').strip().replace(',', '')

        debit = Decimal(debit_raw) if debit_raw else None
        credit = Decimal(credit_raw) if credit_raw else None

        rows.append({
            'transaction_date': transaction_date,
            'transaction_type': row.get('Transaction Type', '').strip().lstrip("'"),
            'sort_code': row.get('Sort Code', '').strip().lstrip("'"),
            'account_number': row.get('Account Number', '').strip().lstrip("'"),
            'description': row.get('Transaction Description', '').strip(),
            'debit_amount': debit,
            'credit_amount': credit,
            'match_status': 'unmatched',
        })

    return rows


def auto_match_rows(rows: list[dict], legends: list) -> list[dict]:
    """
    Attempt to auto-match each bank row against the TransactionLegend table.
    legends: list of TransactionLegend model instances.

    Sets match_status to 'auto' and attaches legend data if matched.
    """
    legend_map = {
        leg.description_pattern.upper(): leg for leg in legends
    }

    for row in rows:
        desc_upper = row['description'].upper()
        matched_legend = None

        for pattern, legend in legend_map.items():
            if pattern in desc_upper:
                matched_legend = legend
                break

        if matched_legend:
            row['match_status'] = 'auto'
            row['matched_tenant_id'] = matched_legend.tenant_id
            row['preferred_description'] = matched_legend.preferred_description
            row['income_type'] = matched_legend.income_type
            row['expense_type'] = matched_legend.expense_type
        else:
            row['match_status'] = 'unmatched'
            row['matched_tenant_id'] = None

    return rows
