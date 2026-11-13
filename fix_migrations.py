"""
fix_migrations.py
=================
Stamps the Alembic migration chain as fully applied and adds any columns
that the migration scripts tried (and failed) to add, using raw SQL which
works reliably on SQLite.

Run once after the migration errors:
    uv run python fix_migrations.py

This script is idempotent — safe to run multiple times.
"""

import sqlite3
import os

DB_PATH = os.path.join('instance', 'app.db')


def col_exists(cur, table, column):
    cur.execute(f'PRAGMA table_info({table})')
    return any(row[1] == column for row in cur.fetchall())


def table_exists(cur, table):
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    )
    return cur.fetchone() is not None


def index_exists(cur, name):
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (name,)
    )
    return cur.fetchone() is not None


con = sqlite3.connect(DB_PATH)
cur = con.cursor()

print(f'Connected to {DB_PATH}')

# ── Add columns that failed in migration scripts ───────────────────────────

adds = [
    # (table, column, sql_type_default)
    ('deposits',          'file_path',          'VARCHAR(300)'),
    ('tenant_contracts',  'contract_file_path', 'VARCHAR(300)'),
    ('tasks',        'category',           'VARCHAR(50)'),
    ('tasks',        'repeat_frequency',   'VARCHAR(50)'),
    ('tasks',        'remind_days_before', 'INTEGER'),
    ('transactions', 'expense_id',         'INTEGER'),
    ('transactions', 'invoice_id',         'INTEGER'),
    ('transactions', 'contract_id',        'INTEGER'),
    ('transactions', 'bank_import_id',     'INTEGER'),
    ('transactions', 'is_matched',         'BOOLEAN DEFAULT 0'),
    ('transactions', 'source',             "VARCHAR(50) DEFAULT 'manual'"),
    ('transactions', 'month_year_period',  'VARCHAR(20)'),
    ('transactions', 'notes',              'VARCHAR(500)'),
    ('invoices',     'amount_paid',        'NUMERIC(10,2) DEFAULT 0'),
    ('tasks',        'repeat',             "VARCHAR(20) DEFAULT 'none'"),
    ('tasks',        'time_bound',         'BOOLEAN DEFAULT 0'),
    ('tasks',        'is_public',          'BOOLEAN DEFAULT 0'),
    # Contract closure fields
    ('tenant_contracts', 'closure_type',    'VARCHAR(20)'),
    ('tenant_contracts', 'notice_end_date', 'DATE'),
    ('tenant_contracts', 'surrender_date',  'DATE'),
    ('tenant_contracts', 'closure_notes',   'TEXT'),
]

for table, col, defn in adds:
    if not col_exists(cur, table, col):
        cur.execute(f'ALTER TABLE {table} ADD COLUMN {col} {defn}')
        print(f'  Added {table}.{col}')
    else:
        print(f'  OK    {table}.{col} already exists')

# ── Create invoice_payments table if missing ───────────────────────────────

if not table_exists(cur, 'invoice_payments'):
    cur.execute('''
        CREATE TABLE invoice_payments (
            id           INTEGER NOT NULL PRIMARY KEY,
            invoice_id   INTEGER NOT NULL REFERENCES invoices(id),
            transaction_id INTEGER NOT NULL REFERENCES transactions(id),
            amount       NUMERIC(10,2) NOT NULL,
            payment_date DATE NOT NULL,
            notes        VARCHAR(200)
        )
    ''')
    print('  Created invoice_payments table')
else:
    print('  OK    invoice_payments already exists')

# ── Stamp all migration revisions as applied ───────────────────────────────
# Get all revision ids from the versions folder

import glob, re

versions_dir = os.path.join('migrations', 'versions')
revision_ids = []
if os.path.isdir(versions_dir):
    for f in glob.glob(os.path.join(versions_dir, '*.py')):
        with open(f) as fh:
            content = fh.read()
        m = re.search(r"^revision\s*=\s*['\"]([a-f0-9]+)['\"]", content, re.M)
        if m:
            revision_ids.append(m.group(1))

if revision_ids:
    # Find the head (revision with no down_revision that points to it)
    down_revisions = set()
    heads = []
    rev_map = {}
    for f in glob.glob(os.path.join(versions_dir, '*.py')):
        with open(f) as fh:
            content = fh.read()
        rev_m  = re.search(r"^revision\s*=\s*['\"]([a-f0-9]+)['\"]", content, re.M)
        down_m = re.search(r"^down_revision\s*=\s*['\"]?([a-f0-9]*)['\"]?", content, re.M)
        if rev_m:
            rid  = rev_m.group(1)
            down = down_m.group(1) if down_m else ''
            rev_map[rid] = down
            if down:
                down_revisions.add(down)

    heads = [r for r in rev_map if r not in down_revisions]
    head_rev = heads[0] if heads else revision_ids[-1]

    # Upsert into alembic_version
    if not table_exists(cur, 'alembic_version'):
        cur.execute(
            'CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'
        )
    cur.execute('DELETE FROM alembic_version')
    cur.execute('INSERT INTO alembic_version VALUES (?)', (head_rev,))
    print(f'  Stamped alembic_version → {head_rev}')
else:
    print('  No migration versions found — skipping stamp')

con.commit()
con.close()
print('\nDone. Run: uv run flask --app run.py run')
