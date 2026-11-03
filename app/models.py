from datetime import datetime
from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='landlord')  # admin / landlord / tenant
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    properties = db.relationship('Property', backref='owner', lazy='dynamic')
    tenants = db.relationship('Tenant', backref='landlord', lazy='dynamic',
                               foreign_keys='Tenant.user_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Property(db.Model):
    __tablename__ = 'properties'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    address_line1 = db.Column(db.String(200), nullable=False)
    address_line2 = db.Column(db.String(200))
    city = db.Column(db.String(100))
    postcode = db.Column(db.String(20))
    property_ref = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rooms = db.relationship('Room', backref='property', lazy='dynamic',
                             cascade='all, delete-orphan')
    bills = db.relationship('Bill', backref='property', lazy='dynamic')
    compliance_docs = db.relationship('ComplianceDocument', backref='property', lazy='dynamic')
    tasks = db.relationship('Task', backref='property', lazy='dynamic')


class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    room_name = db.Column(db.String(50), nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)

    contracts = db.relationship('TenantContract', backref='room', lazy='dynamic')
    tasks = db.relationship('Task', backref='room', lazy='dynamic')


class Tenant(db.Model):
    __tablename__ = 'tenants'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    portal_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    date_of_birth = db.Column(db.Date)
    nationality = db.Column(db.String(100))
    student_status = db.Column(db.String(20))  # Student / Non-student
    student_id = db.Column(db.String(50))
    university = db.Column(db.String(200))
    course_title = db.Column(db.String(200))
    council_tax_ref = db.Column(db.String(100))
    council_tax_number = db.Column(db.String(100))
    right_to_rent_ref = db.Column(db.String(100))
    home_address = db.Column(db.Text)
    home_country = db.Column(db.String(100))
    invoice_account_number = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    has_left = db.Column(db.Boolean, default=False)
    council_informed_in = db.Column(db.Date)
    council_informed_left = db.Column(db.Date)
    rent_balance = db.Column(db.Numeric(10, 2), default=0.00)
    bill_balance = db.Column(db.Numeric(10, 2), default=0.00)
    gdpr_consent = db.Column(db.Boolean, default=False)
    gdpr_consent_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contracts = db.relationship('TenantContract', backref='tenant', lazy='dynamic',
                                 foreign_keys='TenantContract.tenant_id')
    deposits = db.relationship('Deposit', backref='tenant', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='tenant', lazy='dynamic')
    tasks = db.relationship('Task', backref='tenant', lazy='dynamic')

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'


class TenantContract(db.Model):
    __tablename__ = 'tenant_contracts'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    renewal_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    monthly_rent = db.Column(db.Numeric(10, 2), nullable=False)
    frequency = db.Column(db.String(20), default='monthly')
    next_rent_due = db.Column(db.Date)
    advanced_rent_agreed = db.Column(db.Numeric(10, 2), default=0.00)
    remaining_advance_rent = db.Column(db.Numeric(10, 2), default=0.00)
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    property = db.relationship('Property', backref='contracts')
    invoices = db.relationship('Invoice', backref='contract', lazy='dynamic')
    bill_shares = db.relationship('BillTenantShare', backref='contract', lazy='dynamic')


class Deposit(db.Model):
    __tablename__ = 'deposits'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('tenant_contracts.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    dps_scheme = db.Column(db.String(100))
    dps_reference = db.Column(db.String(100))
    date_received = db.Column(db.Date)
    status = db.Column(db.String(20), default='held')  # held / deducting / returned
    deduction_amount = db.Column(db.Numeric(10, 2))
    deduction_reason = db.Column(db.Text)
    amount_returned = db.Column(db.Numeric(10, 2))
    surrender_accepted = db.Column(db.Boolean, default=False)
    surrender_date = db.Column(db.Date)
    returned_date = db.Column(db.Date)
    notes = db.Column(db.Text)


class Bill(db.Model):
    __tablename__ = 'bills'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bill_type = db.Column(db.String(30), nullable=False)  # gas / electric / council_tax
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    days_in_period = db.Column(db.Integer)
    is_shared = db.Column(db.Boolean, default=True)
    date_entered = db.Column(db.Date, default=datetime.utcnow)
    notes = db.Column(db.Text)

    shares = db.relationship('BillTenantShare', backref='bill', lazy='dynamic',
                              cascade='all, delete-orphan')


class BillTenantShare(db.Model):
    __tablename__ = 'bill_tenant_shares'
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('tenant_contracts.id'), nullable=False)
    days_present = db.Column(db.Integer)
    share_amount = db.Column(db.Numeric(10, 2))
    invoice_item_id = db.Column(db.Integer, db.ForeignKey('invoice_items.id'), nullable=True)


class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(30), unique=True, nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('tenant_contracts.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    issue_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    subtotal = db.Column(db.Numeric(10, 2), default=0.00)
    arrears_carried_forward = db.Column(db.Numeric(10, 2), default=0.00)
    total_due = db.Column(db.Numeric(10, 2), default=0.00)
    status = db.Column(db.String(20), default='draft')  # draft/issued/paid/overdue
    pdf_path = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('InvoiceItem', backref='invoice', lazy='dynamic',
                             cascade='all, delete-orphan')
    tenant = db.relationship('Tenant', backref='invoices')


class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    charge_type_id = db.Column(db.Integer, db.ForeignKey('picklist_charges.id'), nullable=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=True)


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('tenant_contracts.id'), nullable=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    credit_debit = db.Column(db.String(2), nullable=False)  # cr / db
    transaction_date = db.Column(db.Date, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50))
    charge_type_id = db.Column(db.Integer, db.ForeignKey('picklist_charges.id'), nullable=True)
    payment_type_id = db.Column(db.Integer, db.ForeignKey('picklist_payment_types.id'), nullable=True)
    bank_ref = db.Column(db.String(100))
    month_year_period = db.Column(db.String(30))
    source = db.Column(db.String(20), default='manual')  # bank_import / manual / cash
    is_matched = db.Column(db.Boolean, default=False)
    bank_import_id = db.Column(db.Integer, db.ForeignKey('bank_imports.id'), nullable=True)
    charges_are_paid = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)


class BankImport(db.Model):
    __tablename__ = 'bank_imports'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=True)
    import_date = db.Column(db.DateTime, default=datetime.utcnow)
    filename = db.Column(db.String(200))
    row_count = db.Column(db.Integer, default=0)
    matched_count = db.Column(db.Integer, default=0)
    unmatched_count = db.Column(db.Integer, default=0)

    rows = db.relationship('BankImportRow', backref='import_batch', lazy='dynamic',
                            cascade='all, delete-orphan')


class BankImportRow(db.Model):
    __tablename__ = 'bank_import_rows'
    id = db.Column(db.Integer, primary_key=True)
    import_id = db.Column(db.Integer, db.ForeignKey('bank_imports.id'), nullable=False)
    transaction_date = db.Column(db.Date)
    transaction_type = db.Column(db.String(10))
    sort_code = db.Column(db.String(20))
    account_number = db.Column(db.String(20))
    description = db.Column(db.String(300))
    debit_amount = db.Column(db.Numeric(10, 2), nullable=True)
    credit_amount = db.Column(db.Numeric(10, 2), nullable=True)
    match_status = db.Column(db.String(20), default='unmatched')  # auto/manual/unmatched/split
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)


class TransactionLegend(db.Model):
    __tablename__ = 'transaction_legend'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    description_pattern = db.Column(db.String(200), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)
    income_type = db.Column(db.String(100))
    expense_type = db.Column(db.String(100))
    preferred_description = db.Column(db.String(200))


class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=True)
    charge_type_id = db.Column(db.Integer, db.ForeignKey('picklist_charges.id'), nullable=True)
    description = db.Column(db.String(300))
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(20), default='manual')  # bank / cash
    bank_import_row_id = db.Column(db.Integer, db.ForeignKey('bank_import_rows.id'), nullable=True)
    receipt_path = db.Column(db.String(300))
    notes = db.Column(db.Text)


class PicklistCharge(db.Model):
    __tablename__ = 'picklist_charges'
    id = db.Column(db.Integer, primary_key=True)
    charge_name = db.Column(db.String(100), nullable=False)
    hmrc_category = db.Column(db.String(200))


class PicklistPaymentType(db.Model):
    __tablename__ = 'picklist_payment_types'
    id = db.Column(db.Integer, primary_key=True)
    payment_name = db.Column(db.String(100), nullable=False)
    hmrc_income_category = db.Column(db.String(200))


class ComplianceDocument(db.Model):
    __tablename__ = 'compliance_documents'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    document_type = db.Column(db.String(100), nullable=False)
    # e.g. Gas Safety / EICR / EPC / Fire Alarm / Insurance / Tariff / Right to Rent
    issue_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    renewal_years = db.Column(db.Integer)  # 1, 2 or 5
    file_path = db.Column(db.String(300))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')  # low/medium/high/urgent
    status = db.Column(db.String(20), default='open')  # open/in_progress/complete
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True)
    subject = db.Column(db.String(200))
    body = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
