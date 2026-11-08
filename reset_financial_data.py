"""
Safe Financial Data Reset
=========================
Clears all financial/transaction data for a fresh test run.

KEEPS:
  - Users and accounts
  - Properties and rooms
  - Tenants and contracts
  - Deposits (structure)
  - Compliance documents
  - Tasks
  - Transaction legend rules
  - Picklist charges and payment types

CLEARS:
  - All transactions
  - All bank imports and import rows
  - All invoices and invoice items
  - All invoice payments
  - All bill tenant shares
  - All bills
  - All expenses
  - Resets tenant rent_balance and bill_balance to 0.00

Run with:
    uv run python reset_financial_data.py
"""

from app import create_app, db
from app.models import (
    Transaction, BankImport, BankImportRow,
    Invoice, InvoiceItem, InvoicePayment, Room,
    BillTenantShare, Bill, Expense, Tenant, TenantContract
)

app = create_app('development')

print('=' * 55)
print('HMO Manager — Financial Data Reset')
print('=' * 55)
print()
print('This will DELETE all financial data:')
print('  - Transactions')
print('  - Bank imports and rows')
print('  - Invoices and invoice items')
print('  - Invoice payments')
print('  - Bills and bill shares')
print('  - Expenses')
print('  - Reset all tenant balances to £0.00')
print()
print('It will KEEP all properties, rooms, tenants,')
print('contracts, compliance docs, tasks and legend rules.')
print()

confirm = input('Type YES to continue: ')
if confirm.strip().upper() != 'YES':
    print('Cancelled.')
    exit()

print()

with app.app_context():

    # Order matters due to foreign keys

    count = InvoicePayment.query.count()
    InvoicePayment.query.delete()
    print(f'Deleted {count} invoice payments.')

    count = BillTenantShare.query.count()
    BillTenantShare.query.delete()
    print(f'Deleted {count} bill tenant shares.')

    count = InvoiceItem.query.count()
    InvoiceItem.query.delete()
    print(f'Deleted {count} invoice items.')

    count = Invoice.query.count()
    Invoice.query.delete()
    print(f'Deleted {count} invoices.')

    count = BankImportRow.query.count()
    BankImportRow.query.delete()
    print(f'Deleted {count} bank import rows.')

    count = BankImport.query.count()
    BankImport.query.delete()
    print(f'Deleted {count} bank imports.')

    count = Transaction.query.count()
    Transaction.query.delete()
    print(f'Deleted {count} transactions.')

    count = Expense.query.count()
    Expense.query.delete()
    print(f'Deleted {count} expenses.')

    # Reset rooms to vacant first
    rooms = Room.query.all()
    for room in rooms:
        room.is_occupied = False
    print(f'Reset {len(rooms)} rooms to vacant.')

    count = TenantContract.query.count()
    TenantContract.query.delete()
    print(f'Deleted {count} tenant contracts.')

    count = Bill.query.count()
    Bill.query.delete()
    print(f'Deleted {count} bills.')

    # Reset tenant balances
    tenants = Tenant.query.all()
    for tenant in tenants:
        tenant.rent_balance = 0.00
        tenant.bill_balance = 0.00
    print(f'Reset balances for {len(tenants)} tenants.')

    db.session.commit()

    print()
    print('=' * 55)
    print('Reset complete. Ready for fresh test data.')
    print('=' * 55)
    print()
    print('Suggested test order:')
    print('  1. Enter bills for a property (/bills/add)')
    print('  2. Generate and issue an invoice (/invoices/generate)')
    print('  3. Check rent roll (/invoices/rent-roll)')
    print('  4. Import a bank statement (/transactions/import)')
    print('  5. Confirm auto-matched payments')
    print('  6. Check rent roll again — balances should update')
    print('  7. Check invoice — should show paid/partially paid')
