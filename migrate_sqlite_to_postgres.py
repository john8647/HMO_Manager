"""
SQLite → PostgreSQL Migration Script
=====================================
Copies all data from the local SQLite database into a PostgreSQL database.

Usage:
    1. Make sure your .env has DATABASE_URL pointing at your PostgreSQL instance
    2. Make sure the PostgreSQL database is empty (flask db upgrade run first)
    3. Run:  uv run python migrate_sqlite_to_postgres.py
             or:  python migrate_sqlite_to_postgres.py

The script reads directly from the SQLite file using sqlite3, then inserts
into PostgreSQL via SQLAlchemy so all your models and relationships are
respected.  It runs tables in dependency order to avoid foreign key
violations.

Safe to re-run: existing rows in PostgreSQL are skipped (INSERT OR IGNORE
equivalent via ON CONFLICT DO NOTHING).
"""

from app.models import (
    User, Property, Room, Tenant, TenantContract, Deposit,
    Bill, BillTenantShare, Invoice, InvoiceItem, InvoicePayment,
    Transaction, BankImport, BankImportRow, TransactionLegend,
    Expense, PicklistCharge, PicklistPaymentType,
    ComplianceDocument, Task, Message,
)
from app import create_app, db
import os
import sys
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Locate the SQLite file ────────────────────────────────────────────────────
# Default location — adjust if yours is elsewhere
SQLITE_PATH = Path(__file__).parent / 'instance' / 'app.db'
if not SQLITE_PATH.exists():
    # Try the old location
    SQLITE_PATH = Path(__file__).parent / 'app.db'
if not SQLITE_PATH.exists():
    print(f'ERROR: SQLite database not found.')
    print(f'Expected at: {SQLITE_PATH}')
    print('Set SQLITE_PATH at the top of this script to the correct path.')
    sys.exit(1)

print(f'SQLite source:  {SQLITE_PATH}')

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL or DATABASE_URL.startswith('sqlite'):
    print('ERROR: DATABASE_URL must point to PostgreSQL.')
    print('Set it in your .env file, e.g.:')
    print('  DATABASE_URL=postgresql://user:pass@localhost:5432/hmo_landlord')
    sys.exit(1)

print(f'PostgreSQL target: {DATABASE_URL.split("@")[-1]}')  # hide credentials

# ── Bootstrap Flask app so SQLAlchemy models are available ───────────────────

app = create_app('production')


def sqlite_rows(conn, table):
    """Return all rows from a SQLite table as a list of dicts."""
    cur = conn.cursor()
    cur.execute(f'SELECT * FROM "{table}"')
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def migrate_table(conn, model, table_name, transform=None):
    """
    Copy all rows from SQLite table → PostgreSQL model table.
    transform: optional function(row_dict) → row_dict for any adjustments.
    Skips rows whose primary key already exists in PostgreSQL.
    """
    rows = sqlite_rows(conn, table_name)
    if not rows:
        print(f'  {table_name}: 0 rows (empty)')
        return 0

    inserted = 0
    skipped = 0
    for row in rows:
        if transform:
            row = transform(row)
        if row is None:
            skipped += 1
            continue

        # Check if already exists by primary key (id)
        pk = row.get('id')
        if pk and db.session.get(model, pk):
            skipped += 1
            continue

        # Drop any columns from SQLite that no longer exist in the model
        valid_cols = {c.key for c in model.__table__.columns}
        row = {k: v for k, v in row.items() if k in valid_cols}
        obj = model(**row)
        db.session.add(obj)
        inserted += 1

    db.session.flush()
    print(f'  {table_name}: {inserted} inserted, {skipped} skipped')
    return inserted


def bool_fix(row, *fields):
    """SQLite stores booleans as 0/1 integers — convert to Python bool."""
    for f in fields:
        if f in row and row[f] is not None:
            row[f] = bool(row[f])
    return row


with app.app_context():
    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    print('\nStarting migration...\n')

    try:
        # Tables in dependency order (parents before children)

        migrate_table(sqlite_conn, User, 'users',
                      lambda r: bool_fix(r, 'is_active', 'is_admin'))

        migrate_table(sqlite_conn, Property, 'properties')

        migrate_table(sqlite_conn, Room, 'rooms',
                      lambda r: bool_fix(r, 'is_occupied', 'en_suite'))

        migrate_table(sqlite_conn, Tenant, 'tenants',
                      lambda r: bool_fix(r, 'is_active'))

        migrate_table(sqlite_conn, TenantContract, 'tenant_contracts',
                      lambda r: bool_fix(r, 'is_active', 'surrender_accepted'))

        migrate_table(sqlite_conn, Deposit, 'deposits',
                      lambda r: bool_fix(r, 'surrender_accepted'))

        migrate_table(sqlite_conn, Bill, 'bills')

        migrate_table(sqlite_conn, BillTenantShare, 'bill_tenant_shares',
                      lambda r: bool_fix(r, 'is_paid'))

        migrate_table(sqlite_conn, Invoice, 'invoices')

        migrate_table(sqlite_conn, InvoiceItem, 'invoice_items')

        migrate_table(sqlite_conn, InvoicePayment, 'invoice_payments')

        migrate_table(sqlite_conn, Transaction, 'transactions',
                      lambda r: bool_fix(r, 'is_matched'))

        migrate_table(sqlite_conn, BankImport, 'bank_imports')

        migrate_table(sqlite_conn, BankImportRow, 'bank_import_rows')

        migrate_table(sqlite_conn, TransactionLegend, 'transaction_legend')

        migrate_table(sqlite_conn, Expense, 'expenses')

        migrate_table(sqlite_conn, PicklistCharge, 'picklist_charges')

        migrate_table(sqlite_conn, PicklistPaymentType,
                      'picklist_payment_types')

        migrate_table(sqlite_conn, ComplianceDocument, 'compliance_documents')

        migrate_table(sqlite_conn, Task, 'tasks',
                      lambda r: bool_fix(r, 'is_complete'))

        migrate_table(sqlite_conn, Message, 'messages',
                      lambda r: bool_fix(r, 'is_read'))

        db.session.commit()
        print('\n✓ Migration complete. All data committed to PostgreSQL.')

        # ── Reset PostgreSQL sequences ────────────────────────────────────
        # PostgreSQL auto-increment sequences need to be advanced past the
        # highest existing id, otherwise new inserts will collide.
        print('\nResetting PostgreSQL sequences...')
        tables = [
            'users', 'properties', 'rooms', 'tenants', 'tenant_contracts',
            'deposits', 'bills', 'bill_tenant_shares', 'invoices',
            'invoice_items', 'invoice_payments', 'transactions',
            'bank_imports', 'bank_import_rows', 'transaction_legend',
            'expenses', 'picklist_charges', 'picklist_payment_types',
            'compliance_documents', 'tasks', 'messages',
        ]
        for table in tables:
            try:
                db.session.execute(
                    db.text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE(MAX(id), 1)) FROM \"{table}\""
                    )
                )
            except Exception as e:
                print(f'  Warning: could not reset sequence for {table}: {e}')
        db.session.commit()
        print('✓ Sequences reset.\n')

    except Exception as e:
        db.session.rollback()
        print(f'\n✗ Migration failed: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        sqlite_conn.close()
