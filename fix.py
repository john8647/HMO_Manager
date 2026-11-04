from app import create_app, db
from app.models import PicklistCharge, PicklistPaymentType
app = create_app('development')
with app.app_context():
    charges = [
        ('Council Tax', ''),
        ('Gas/Electric', ''),
        ('Rent', ''),
        ('Interest', 'UK Property 26 - Rent, rates, insurance, ground rents etc'),
        ('Key replacement', 'UK Property 27 - Property Repairs and Maintenance'),
        ('Refurbishment', 'UK Property 27 - Property Repairs and Maintenance'),
        ('Operating Expenses',
         'UK Property 30 - Costs of services provided, including wages'),
        ('Financial Expenses', 'UK Property 26 - Rent, rates, insurance, ground rents etc'),
        ('Furniture', 'UK Property 27 - Property Repairs and Maintenance'),
        ('Equipment', 'UK Property 27 - Property Repairs and Maintenance'),
        ('Wages', 'UK Property 30 - Costs of services provided, including wages'),
        ('Services', 'UK Property 30 - Costs of services provided, including wages'),
        ('Advertising', 'UK Property 30 - Costs of services provided, including wages'),
        ('Maintenance', 'UK Property 27 - Property Repairs and Maintenance'),
        ('Legal expenses', ''),
        ('Travel', 'UK Property 31 - Other Allowable property expenses'),
        ('Office expenses and supplies',
         'UK Property 31 - Other Allowable property expenses'),
        ('Insurance', 'UK Property 26 - Rent, rates, insurance, ground rents etc'),
        ('Water', 'UK Property 30 - Costs of services provided, including wages'),
        ('Broadband', 'UK Property 30 - Costs of services provided, including wages'),
    ]
    for name, cat in charges:
        if not PicklistCharge.query.filter_by(charge_name=name).first():
            db.session.add(PicklistCharge(charge_name=name, hmrc_category=cat))
    db.session.commit()
    print('Picklist charges seeded.')
