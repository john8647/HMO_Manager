from app import create_app, db
from sqlalchemy import inspect
app = create_app('development')
with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print('invoice_payments exists:', 'invoice_payments' in tables)
    if 'invoice_payments' in tables:
        print('  columns:', [c['name']
              for c in inspector.get_columns('invoice_payments')])
    inv_cols = [c['name'] for c in inspector.get_columns('invoices')]
    print('amount_paid in invoices:', 'amount_paid' in inv_cols)
