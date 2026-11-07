"""
Polish Pass Step 1 — Model fixes and seed data.

Run this AFTER applying the migration:
    uv run flask --app run.py db migrate -m "polish pass 1 model additions"
    uv run flask --app run.py db upgrade
    uv run python polish_pass_1_setup.py

Adds:
  - Deposit.file_path column
  - Task.repeat_frequency and Task.remind_days_before columns
  - Transaction.expense_id FK (for QuickFile deduplication)
  - Seeds PicklistPaymentType table
"""

from app import create_app, db
from app.models import PicklistPaymentType

app = create_app('development')

with app.app_context():

    # ── Seed PicklistPaymentType ──────────────────────────────────────────────
    payment_types = [
        ('Rent',                    'UK Property income'),
        ('Gas/Electric',            'UK Property income'),
        ('Council Tax',             'UK Property income'),
        ('Deposit',                 ''),
        ('Advanced Rent',           'UK Property income'),
        ('Key Replacement',         'UK Property income'),
        ('Utility Bills',           'UK Property income'),
        ('Maintenance Charge',      'UK Property income'),
        ('Other Income',            'UK Property income'),
    ]

    added = 0
    for name, cat in payment_types:
        if not PicklistPaymentType.query.filter_by(payment_name=name).first():
            db.session.add(PicklistPaymentType(
                payment_name=name,
                hmrc_income_category=cat
            ))
            added += 1

    db.session.commit()
    print(f'Payment types seeded — {added} added.')
    print('Done.')
