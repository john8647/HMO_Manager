# Technical Development Log
## HMO Landlord Management System — Project 5

**Project Path:** `C:\scripts\codeInst_projects\Project5\Prototype`
**Started:** 2026
**Stack:** Python · Flask · UV · SQLite → PostgreSQL · Jinja2 · WeasyPrint
**Deployment Target:** DigitalOcean VPS

---

## Log Convention

Each entry should follow this format:

```
### [DATE] — [CATEGORY] — [SHORT TITLE]
- What was done
- Why it was done
- Any decisions made or alternatives considered
- Known issues or follow-up actions
```

Categories: `SETUP` · `SCHEMA` · `FEATURE` · `BUG` · `REFACTOR` · `MIGRATION` · `SECURITY` · `DEPLOY`

---

## Architecture Overview

### Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Runtime manager | UV | Replaces pip/venv, fast dependency resolution |
| Web framework | Flask | Lightweight, Python-native, Jinja2 templating |
| Database (local) | SQLite | Single file `app.db`, zero config for development |
| Database (production) | PostgreSQL | DigitalOcean managed DB when deployed |
| ORM | SQLAlchemy | Abstracts SQLite↔PostgreSQL switch |
| PDF generation | WeasyPrint | HTML/CSS → PDF, used for invoices and deposit certificates |
| Frontend | Jinja2 + plain HTML/CSS | Server-side rendered, no JS framework |
| Auth | Flask-Login + Werkzeug | Password hashing, session management |
| CSV handling | Python csv module | Bank statement import and QuickFile export |
| IDE | Visual Studio Code | Local development |

### Design System
- **Colour palette:** White background, leaf green primary (inspired by HMRC portal)
- **Typography:** Clean sans-serif, system fonts preferred
- **Layout:** Desktop-first, sidebar navigation, dashboard widgets

---

## Database Schema

### `users`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| username | VARCHAR | Unique |
| email | VARCHAR | Unique |
| password_hash | VARCHAR | Werkzeug hashed |
| role | VARCHAR | `admin` or `landlord` |
| created_at | DATETIME | |
| is_active | BOOLEAN | |

### `properties` (houses)
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | FK → users | Owning landlord |
| address_line1 | VARCHAR | |
| address_line2 | VARCHAR | |
| city | VARCHAR | |
| postcode | VARCHAR | |
| property_ref | VARCHAR | e.g. house 31 |
| created_at | DATETIME | |

### `rooms`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| property_id | FK → properties | |
| room_name | VARCHAR | e.g. Room 2 |
| is_occupied | BOOLEAN | |

### `tenants`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | FK → users | Landlord owner |
| first_name | VARCHAR | |
| last_name | VARCHAR | |
| email | VARCHAR | |
| phone | VARCHAR | |
| date_of_birth | DATE | |
| nationality | VARCHAR | |
| student_status | VARCHAR | Student / Non-student |
| student_id | VARCHAR | |
| university | VARCHAR | |
| course_title | VARCHAR | |
| council_tax_ref | VARCHAR | Council submission reference |
| council_tax_number | VARCHAR | |
| right_to_rent_ref | VARCHAR | |
| home_address | TEXT | |
| home_country | VARCHAR | |
| invoice_account_number | VARCHAR | Sequential invoice ref |
| is_active | BOOLEAN | |
| has_left | BOOLEAN | |
| council_informed_in | DATE | |
| council_informed_left | DATE | |
| portal_user_id | FK → users NULL | Linked portal login if invited |
| created_at | DATETIME | |

### `tenant_contracts`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| tenant_id | FK → tenants | |
| property_id | FK → properties | |
| room_id | FK → rooms | |
| user_id | FK → users | Landlord |
| start_date | DATE | |
| renewal_date | DATE | |
| end_date | DATE | NULL if ongoing |
| monthly_rent | DECIMAL(10,2) | |
| frequency | VARCHAR | monthly |
| next_rent_due | DATE | Calculated from move-in day |
| advanced_rent_agreed | DECIMAL(10,2) | |
| remaining_advance_rent | DECIMAL(10,2) | |
| is_active | BOOLEAN | |
| notes | TEXT | |
| created_at | DATETIME | |

### `deposits`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| tenant_id | FK → tenants | |
| contract_id | FK → tenant_contracts | |
| amount | DECIMAL(10,2) | |
| dps_scheme | VARCHAR | Scheme name |
| dps_reference | VARCHAR | |
| date_received | DATE | |
| status | VARCHAR | `held` · `deducting` · `returned` |
| deduction_amount | DECIMAL(10,2) | NULL until move-out |
| deduction_reason | TEXT | |
| amount_returned | DECIMAL(10,2) | |
| surrender_accepted | BOOLEAN | Early surrender flag |
| surrender_date | DATE | |
| returned_date | DATE | |
| notes | TEXT | |

### `bills`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| property_id | FK → properties | |
| user_id | FK → users | |
| bill_type | VARCHAR | `gas` · `electric` · `council_tax` |
| amount | DECIMAL(10,2) | Total bill amount |
| period_start | DATE | |
| period_end | DATE | |
| days_in_period | INTEGER | Inclusive count |
| is_shared | BOOLEAN | True for gas/electric/council tax |
| date_entered | DATE | |
| notes | TEXT | |

### `bill_tenant_shares`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| bill_id | FK → bills | |
| tenant_id | FK → tenants | |
| contract_id | FK → tenant_contracts | |
| days_present | INTEGER | Inclusive days in period |
| share_amount | DECIMAL(10,2) | Calculated proportional share |
| invoice_item_id | FK → invoice_items NULL | Linked once invoiced |

### `invoices`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| invoice_number | VARCHAR | e.g. INV-2026-001 |
| tenant_id | FK → tenants | |
| contract_id | FK → tenant_contracts | |
| property_id | FK → properties | |
| user_id | FK → users | |
| issue_date | DATE | |
| due_date | DATE | Matches rent due date |
| period_start | DATE | |
| period_end | DATE | |
| subtotal | DECIMAL(10,2) | |
| arrears_carried_forward | DECIMAL(10,2) | |
| total_due | DECIMAL(10,2) | |
| status | VARCHAR | `draft` · `issued` · `paid` · `overdue` |
| pdf_path | VARCHAR | Path to generated PDF |
| created_at | DATETIME | |

### `invoice_items`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| invoice_id | FK → invoices | |
| description | VARCHAR | e.g. "Gas 15/09 - 14/10 \| 30 days" |
| amount | DECIMAL(10,2) | |
| charge_type_id | FK → picklist_charges | |
| bill_id | FK → bills NULL | If from shared bill |

### `transactions`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| tenant_id | FK → tenants NULL | |
| contract_id | FK → tenant_contracts NULL | |
| bill_id | FK → bills NULL | |
| invoice_id | FK → invoices NULL | |
| amount | DECIMAL(10,2) | |
| credit_debit | VARCHAR | `cr` or `db` |
| transaction_date | DATE | |
| user_id | FK → users | |
| type | VARCHAR | `Rent` · `Gas/Electric` · `Council Tax` · `Expense` etc |
| charge_type_id | FK → picklist_charges NULL | |
| payment_type_id | FK → picklist_payment_types NULL | |
| bank_ref | VARCHAR | Bank account ref |
| month_year_period | VARCHAR | e.g. August 2023 |
| source | VARCHAR | `bank_import` · `manual` · `cash` |
| is_matched | BOOLEAN | Bank statement matched |
| bank_import_id | FK → bank_imports NULL | |
| charges_are_paid | BOOLEAN | |
| notes | TEXT | |

### `bank_imports`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | FK → users | |
| property_id | FK → properties NULL | |
| import_date | DATETIME | |
| filename | VARCHAR | |
| row_count | INTEGER | |
| matched_count | INTEGER | |
| unmatched_count | INTEGER | |

### `bank_import_rows`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| import_id | FK → bank_imports | |
| transaction_date | DATE | |
| transaction_type | VARCHAR | DD · FPI · DEB etc |
| sort_code | VARCHAR | |
| account_number | VARCHAR | |
| description | VARCHAR | Raw bank description |
| debit_amount | DECIMAL(10,2) NULL | |
| credit_amount | DECIMAL(10,2) NULL | |
| match_status | VARCHAR | `auto` · `manual` · `unmatched` · `split` |
| transaction_id | FK → transactions NULL | After matching |

### `transaction_legend`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | FK → users | |
| description_pattern | VARCHAR | e.g. GOLLA H |
| tenant_id | FK → tenants NULL | |
| income_type | VARCHAR | |
| expense_type | VARCHAR | |
| preferred_description | VARCHAR | Mapped label |

### `expenses`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | FK → users | |
| property_id | FK → properties NULL | |
| charge_type_id | FK → picklist_charges | |
| description | VARCHAR | |
| amount | DECIMAL(10,2) | |
| expense_date | DATE | |
| source | VARCHAR | `bank` · `cash` |
| bank_import_row_id | FK → bank_import_rows NULL | |
| receipt_path | VARCHAR | Uploaded file path |
| notes | TEXT | |

### `picklist_charges`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| charge_name | VARCHAR | |
| hmrc_category | VARCHAR | UK Property box reference |

### `picklist_payment_types`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| payment_name | VARCHAR | |
| hmrc_income_category | VARCHAR | |

### `compliance_documents`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| property_id | FK → properties | |
| user_id | FK → users | |
| document_type | VARCHAR | Gas Safety · EICR · EPC · Fire Alarm · Insurance · Tariff etc |
| issue_date | DATE | |
| expiry_date | DATE | |
| renewal_years | INTEGER | 1, 2, or 5 |
| file_path | VARCHAR | Uploaded PDF |
| notes | TEXT | |
| created_at | DATETIME | |

### `tasks`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | FK → users | |
| title | VARCHAR | |
| description | TEXT | |
| priority | VARCHAR | `low` · `medium` · `high` · `urgent` |
| status | VARCHAR | `open` · `in_progress` · `complete` |
| property_id | FK → properties NULL | |
| room_id | FK → rooms NULL | |
| tenant_id | FK → tenants NULL | |
| due_date | DATE NULL | |
| created_at | DATETIME | |
| completed_at | DATETIME NULL | |

### `messages`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| from_user_id | FK → users | |
| to_user_id | FK → users | |
| tenant_id | FK → tenants NULL | |
| subject | VARCHAR | |
| body | TEXT | |
| is_read | BOOLEAN | |
| created_at | DATETIME | |

---

## Project Folder Structure

```
C:\scripts\codeInst_projects\Project5\Prototype\
│
├── app/
│   ├── __init__.py              # App factory, extensions init
│   ├── models.py                # SQLAlchemy models
│   ├── auth/
│   │   ├── routes.py            # Login, register, reset password
│   │   └── forms.py
│   ├── dashboard/
│   │   └── routes.py
│   ├── properties/
│   │   ├── routes.py
│   │   └── forms.py
│   ├── tenants/
│   │   ├── routes.py
│   │   └── forms.py
│   ├── contracts/
│   │   └── routes.py
│   ├── bills/
│   │   ├── routes.py
│   │   └── calculator.py        # Pro-rata bill split logic
│   ├── invoices/
│   │   ├── routes.py
│   │   ├── generator.py         # Invoice creation logic
│   │   └── pdf.py               # WeasyPrint PDF rendering
│   ├── transactions/
│   │   ├── routes.py
│   │   ├── importer.py          # CSV bank import logic
│   │   └── matcher.py           # Auto-match logic
│   ├── expenses/
│   │   └── routes.py
│   ├── reports/
│   │   ├── routes.py
│   │   └── quickfile.py         # QuickFile CSV export
│   ├── compliance/
│   │   └── routes.py
│   ├── tasks/
│   │   └── routes.py
│   ├── deposits/
│   │   ├── routes.py
│   │   └── pdf.py               # Deposit certificate PDF
│   ├── portal/
│   │   └── routes.py            # Tenant portal views
│   ├── admin/
│   │   └── routes.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard/
│   │   ├── properties/
│   │   ├── tenants/
│   │   ├── bills/
│   │   ├── invoices/
│   │   ├── transactions/
│   │   ├── compliance/
│   │   ├── tasks/
│   │   ├── portal/
│   │   └── pdf/                 # PDF-specific templates
│   ├── static/
│   │   ├── css/
│   │   │   └── main.css
│   │   ├── js/
│   │   └── uploads/             # Uploaded compliance docs, receipts
│   └── utils/
│       ├── decorators.py        # Role-based access control
│       ├── date_helpers.py      # Inclusive day count, period logic
│       └── gdpr.py              # Consent helpers
│
├── migrations/                  # Flask-Migrate Alembic files
├── tests/                       # Unit tests
├── instance/
│   └── app.db                   # SQLite database file
├── .env                         # Secret key, config (NOT committed)
├── .gitignore
├── config.py                    # App config classes (dev/prod)
├── pyproject.toml               # UV / PEP 517 project file
├── README.md
└── TECHNICAL_LOG.md             # This file
```

---

## Module Route Plan

| Module | URL Prefix | Key Routes |
|---|---|---|
| Auth | `/auth` | `/login` `/logout` `/register` `/reset-password` |
| Dashboard | `/` | `/dashboard` |
| Properties | `/properties` | `/` `/add` `/<id>` `/<id>/edit` |
| Rooms | `/properties/<id>/rooms` | `/add` `/<room_id>/edit` |
| Tenants | `/tenants` | `/` `/add` `/<id>` `/<id>/edit` `/<id>/contracts` |
| Contracts | `/contracts` | `/<id>` `/add` `/<id>/edit` `/<id>/end` |
| Deposits | `/deposits` | `/<id>` `/add` `/<id>/deduct` `/<id>/certificate.pdf` |
| Bills | `/bills` | `/` `/add` `/<id>/shares` |
| Invoices | `/invoices` | `/` `/generate` `/<id>` `/<id>/pdf` |
| Transactions | `/transactions` | `/` `/import` `/match/<import_id>` `/add` |
| Expenses | `/expenses` | `/` `/add` `/<id>/edit` |
| Reports | `/reports` | `/quickfile` `/export` |
| Compliance | `/compliance` | `/` `/<id>/edit` `/add` |
| Tasks | `/tasks` | `/` `/add` `/<id>/edit` `/<id>/complete` |
| Portal | `/portal` | `/dashboard` `/invoices` `/contract` `/messages` |
| Admin | `/admin` | `/users` `/add-landlord` |

---

## Bill Calculation Logic

**Pro-rata presence formula:**

```
days_present = (min(contract_end, period_end) - max(contract_start, period_start)).days + 1
total_days = (period_end - period_start).days + 1
tenant_share = (days_present / sum_of_all_tenant_days) * bill_amount
```

- Only tenants with an **active contract overlapping the billing period** are included
- Days are **inclusive** (01/07 → 31/07 = 31 days)
- Council tax is billed **in advance** for the current month (01/07 → 31/07)
- Gas/Electric follows its own cycle (not always 1st–end of month)
- Once a bill is entered, `bill_tenant_shares` rows are auto-created
- These shares are then pulled into invoice line items at invoice generation time

---

## Invoice Numbering

Format: `INV-YYYY-NNNN`
Example: `INV-2026-0001`

Sequential counter stored per landlord user. Resets to 0001 at start of each year. Invoice account number per tenant stored in `tenants.invoice_account_number`.

---

## Bank CSV Import Format

Expected columns from bank export:
```
Transaction Date, Transaction Type, Sort Code, Account Number, Transaction Description, Debit Amount, Credit Amount
```

Auto-match process:
1. Parse each row
2. Check `transaction_legend` for matching `description_pattern`
3. If matched → assign to tenant, flag as `auto`
4. If amount matches outstanding invoice exactly → link invoice
5. If amount doesn't match cleanly → flag for manual split or intervention
6. Unmatched rows → queued for manual review
7. Cash payments entered separately via manual entry form

---

## QuickFile Export Format

Output CSV mirrors bank statement format with corrected descriptions:
```
Transaction Date, Transaction Type, Sort Code, Account Number, Transaction Description, Debit Amount, Credit Amount
```

- Filtered by **property** and **tax year** (April–April)
- Descriptions use `preferred_description` from `transaction_legend` or charge type name
- Income rows (rent, bill shares received) as Credit
- Expense rows (bills paid, maintenance, etc.) as Debit

---

## Deposit Workflow States

```
held → deducting → returned
```

Trigger deduction workflow when:
- Tenant has moved out OR returned keys, AND
- Tenancy has NOT yet ended OR outstanding charges exist

Two paths:
- **Breach / insufficient notice:** Rent continues to end of notice period. Deposit covers rent owed + damages + utilities. Remainder returned.
- **Accepted early surrender:** Charge rent to agreed surrender date only. Assess utilities/damages. Return remainder.

---

## Security Notes

- Passwords hashed with Werkzeug `generate_password_hash`
- Flask-Login manages sessions
- Role-based access via decorators (`@landlord_required`, `@admin_required`)
- GDPR basis: **Contractual necessity** (tenancy agreement) + **Legal obligation** (Right to Rent, council tax notification)
- Tenant data fields: name, DOB, nationality, email, phone, student status, council refs
- Data access: each landlord sees only their own `user_id`-scoped records
- Uploaded files stored in `/app/static/uploads/` with randomised filenames
- `.env` file holds `SECRET_KEY`, `DATABASE_URL` — never committed to git

---

## Development Log Entries

### [2026] — SETUP — Initial project scaffold
- Project created at `C:\scripts\codeInst_projects\Project5\Prototype`
- Stack decided: Flask + UV + SQLite + Jinja2 + WeasyPrint
- Design: HMRC-inspired white and leaf green
- Two initial roles: admin, landlord. Tenant portal planned for later phase.
- Interview conducted to capture full system requirements
- README.md and TECHNICAL_LOG.md produced
- Full schema designed from existing prototype tables:
  - Tenant, TenantContracts, TransactionsTable, TransactionLegend
  - InvoiceItems, picklistCharges, picklistPaymentType
- Existing data migration to be handled manually by developer

---

### [03/11/2026] — SETUP — Project folder and file structure created
- All files initially saved flat into root `LandlordApp/` folder rather than subfolders
- Fixed by creating `app/` directory structure manually via PowerShell
- Moved `models.py`, `main.css`, `base.html`, `calculator.py`, `importer.py`, `quickfile.py` into correct subdirectories
- Blueprint `routes.py` files initially created with null bytes via PowerShell `Out-File`
- Fixed by writing all files via a Python script (`fix_files.py`) using UTF-8 encoding
- Lesson: always use Python to write project files on Windows, not PowerShell string output
- Project path confirmed as `C:\scripts\codeInst_projects\Project5\LandlordApp`

### [03/11/2026] — SCHEMA — Database initialised with Flask-Migrate
- `models.py` was not imported at migration time — added `from app import models` to `run.py`
- Ran `flask db init` → created `migrations/` folder
- Ran `flask db migrate -m "initial schema"` → detected all 20 tables
- Migration file: `migrations/versions/596431045e2f_initial_schema.py`
- Ran `flask db upgrade` → `instance/app.db` created with full schema
- All 20 tables confirmed: users, properties, rooms, tenants, tenant_contracts, deposits,
  bills, bill_tenant_shares, invoices, invoice_items, transactions, bank_imports,
  bank_import_rows, transaction_legend, expenses, picklist_charges, picklist_payment_types,
  compliance_documents, tasks, messages

### [03/11/2026] — FEATURE — Auth module built and working
- Built `app/auth/routes.py` with login, logout, register, change_password routes
- Login uses Flask-Login `login_user()` with remember-me support
- Passwords hashed with Werkzeug `generate_password_hash` / `check_password_hash`
- Register page validates: username unique, email unique, password min 8 chars, confirm match
- Role selection on register: landlord or admin
- Templates created: `login.html` (standalone, no sidebar), `register.html`, `change_password.html`
- Login page has its own standalone layout (no sidebar, centred card)
- `seed_admin.py` script used to create first admin user (username: admin)
- Admin password changed after first login via change_password page
- All 14 module stub pages load correctly showing "Under construction"
- Dashboard shows quick-link buttons and welcome message with username and role

### [03/11/2026] — SETUP — Run command confirmed
- Correct run command: `uv run python run.py`
- No need to set `FLASK_APP` environment variable
- Flask debug mode active in development — auto-reloads on file save
- App accessible at `http://127.0.0.1:5000`

---

### [04/11/2026] — SETUP — Project moved and UV resynced
- Project moved from `LandlordApp/` to `Prototype/HMO_Manager/` for naming consistency
- Moving the folder broke UV's internal path references (trampoline error)
- Fix: delete `.venv` and run `uv sync` in the new location to rebuild the virtual environment
- Lesson: always resync UV after moving a project folder

### [04/11/2026] — FEATURE — Properties & Rooms module built and working
- `app/properties/routes.py` — full CRUD for properties and rooms
- Routes: list, add, view, edit, delete for properties; add, edit, delete for rooms
- Property view shows room occupancy status and links to active tenant
- Room deletion blocked if occupied; property deletion blocked if rooms exist
- Templates: `index.html`, `view.html`, `add.html`, `edit.html`, `add_room.html`, `edit_room.html`
- Landlord scoping: each landlord sees only their own properties via `user_id` filter
- Admin role sees all properties across all landlords
- Real data entered: 4 HMO properties and rooms added successfully

### [04/11/2026] — FEATURE — Tenants module built and working
- `app/tenants/routes.py` — full tenant lifecycle management
- Routes: list (active/inactive toggle), add, view, edit, deactivate, reactivate
- Contract routes: add_contract, end_contract
- Tenant add flow redirects straight to contract creation after saving
- Contract creation: selects property → loads vacant rooms only
- Activating a contract marks room as occupied; ending marks room as vacant
- Multiple contracts per tenant supported (renewal history preserved)
- GDPR consent checkbox required on add — records consent date
- Fields tracked: personal details, student status, Right to Rent ref, council tax refs,
  council notification dates, home address, invoice account number
- Known issue noted: property dropdown in add_contract triggers form submit via
  `onchange` which fires validation errors for required fields — to be fixed in polish pass
- Templates: `index.html`, `view.html`, `add.html`, `edit.html`, `add_contract.html`

### [04/11/2026] — FEATURE — Bills module built and working
- `app/bills/routes.py` — shared bill entry and pro-rata calculation
- Routes: index, add, view (shares), by_property, delete
- Bill types supported: gas, electric, council_tax
- On bill save: finds all contracts overlapping billing period (active + ended within period)
- Calls `app/bills/calculator.py` → `calculate_shares()` for pro-rata split
- Pro-rata formula: inclusive day count, proportional to days present per tenant
- Last tenant absorbs any rounding difference to ensure total matches exactly
- `BillTenantShare` rows created automatically — one per tenant per bill
- Share view shows progress bar of % presence and amount per tenant
- Bills grouped by month on the by_property page
- Future work noted: council tax discount/landlord absorption for empty rooms during
  invoice generation — to be implemented in invoice module polish pass

### [04/11/2026] — FEATURE — Invoices module built and working
- `app/invoices/routes.py` — invoice generation, viewing, PDF download
- Routes: index, generate, view, update_status, add_item, delete, pdf
- Invoice numbering: sequential `INV-YYYY-NNNN` per landlord per year
- Generate flow: select property → active tenants load → choose period, dates, what to include
- Rent line item: uses contract amount or manual override
- Bill shares: pulls uninvoiced `BillTenantShare` rows for the period automatically
  and marks them as invoiced (`invoice_item_id` set) to prevent double-invoicing
- Arrears carried forward from tenant `rent_balance` + `bill_balance`
- One-off charges can be added to any invoice after generation
- Invoice statuses: draft → issued → paid → overdue (manually updated)
- Deleting an invoice releases bill shares back for re-invoicing
- Templates: `index.html`, `generate.html`, `view.html`, `pdf_template.html`
- `picklist_charges` seeded via one-off Python command (20 charge types with HMRC categories)

### [04/11/2026] — BUG — Invoice index error: Invoice has no attribute 'property'
- `Invoice` model was missing a SQLAlchemy relationship to `Property`
- Fix: added `property = db.relationship('Property', backref='invoices')` to `Invoice` model
- Note: attempted to add similar relationship to `Transaction` model — caused conflict,
  removed. Transaction→Property relationship to be handled via join in queries instead

### [04/11/2026] — BUG — generate.html: 'date' is undefined on GET request
- `date` object from Python `datetime` was only passed to template on POST path
- Fix: added `date=date` to all `render_template` calls in the `generate` route
  including GET, error paths, and the property-dropdown reload path

### [04/11/2026] — REFACTOR — PDF library switched from WeasyPrint to xhtml2pdf
- WeasyPrint requires GTK system libraries which are not available on Windows by default
- Error: `cannot load library 'libgobject-2.0-0': error 0x7e`
- Decision: replaced WeasyPrint with xhtml2pdf (pure Python, no system dependencies)
- Installed via: `uv add xhtml2pdf`
- Updated `pyproject.toml`: removed `weasyprint>=62.0`, added `xhtml2pdf>=0.2.11`
- PDF generation now working on Windows
- Known cosmetic issue: invoice details table text sizing inconsistent in PDF output
  — CSS tweak deferred to polish pass

---

### [06/11/2026] — FEATURE — Expenses module built and working
- `app/expenses/routes.py` — full expense recording and management
- Routes: index (with property filter), add, edit, delete
- Add expense optionally creates a matching debit transaction in the ledger simultaneously
- This is the key link between expenses and the transaction ledger for bank matching
- Expenses categorised by PicklistCharge with HMRC box references
- Sources: manual, bank, cash
- Summary cards on index show total and breakdown by charge category
- Expenses grouped by month with running total in footer
- Known issue noted: QuickFile export was picking up expenses from BOTH the Expense
  table AND debit Transaction records — duplicate lines. To fix in polish pass by
  excluding debit transactions that originated from an expense record

### [06/11/2026] — FEATURE — Transactions module built and working
- `app/transactions/routes.py` — ledger, CSV import, auto-matching, manual entry
- Routes: index, add, import_csv, match, legend, legend_add, legend_delete, imports
- Dual-entry accounting: every manual transaction creates both a credit and debit row
- Bank CSV import: parses standard bank export format, handles encoding (utf-8-sig, latin-1)
- Auto-match: compares bank description against TransactionLegend patterns (case-insensitive)
- Match review page: confirm auto-matched rows, manually assign unmatched, split payments
- Split payment: one bank row → two transaction records (e.g. JIJIN JOSE rent + bills)
  sets notes to "{description} {type}" for correct QuickFile description
- Cash payments entered via manual entry form with source='cash'
- Import history page shows all previous imports with match stats
- Legend rules: add/delete patterns linked to tenants and income/expense types
- `app/transactions/importer.py` updated: cleaner auto_match_rows, robust CSV parsing
- Known issue noted: auto-match correctly identifies patterns but tenant linking
  needs further testing with real data once expense flow is complete

### [06/11/2026] — FEATURE — QuickFile Export module built and working
- `app/reports/routes.py` and `app/reports/quickfile.py`
- Exports CSV in exact bank statement format matching QuickFile manual import
- Filtered by property and UK tax year (6 April to 5 April)
- Income rows: credit transactions with preferred description from legend
  e.g. "JIJIN JOSE Rent", "JIJIN JOSE Bills" as separate lines
- Expense rows: Expense table records for selected property as debit rows
- Sort code and account number configurable per export
- HMRC Self Assessment property income category reference table on export page
- Known issue: duplicate lines when expenses also exist as debit transactions
  — to fix in polish pass by joining Expense and Transaction tables to deduplicate
- Note logged: auto-match rule system currently supports one pattern per tenant
  per income type. Future work: multiple income types per pattern with amount-
  based logic to determine Rent vs Bills split automatically

### [06/11/2026] — FEATURE — Compliance Dashboard module built and working
- `app/compliance/routes.py` — certificate and document tracking per property
- Routes: index, add, edit, delete, download
- 14 document types pre-loaded: Gas Safety (1yr), EICR (5yr), EPC (10yr),
  HMO Licence (5yr), Fire Alarm, PAT, insurances, utility tariffs, broadband,
  Right to Rent, Other
- Dashboard view: all properties and all documents in one page
- Colour coded rows: red = expired, yellow = expiring within 60 days, green = current
- Alert banners at top summarise portfolio-wide expired and expiring-soon counts
- Auto-calculated expiry: picks issue date + renewal years − 1 day via JavaScript
- File upload: PDF/JPG/PNG stored in app/static/uploads/compliance/
- Secure filename generation with timestamp to prevent collisions
- Download route serves files from upload folder

### [06/11/2026] — FEATURE — Tasks module built and working
- `app/tasks/routes.py` — full task management system
- Routes: index, add, edit, complete, cancel, delete, rooms_for_property (AJAX)
- 6 categories: Quick Fix, Major Project, Reminder, Compliance, Admin, Maintenance
- 4 priorities: Urgent, High, Medium, Low — colour coded
- 4 statuses: Open, In Progress, Complete, Cancelled
- Repeat schedules: none, weekly, monthly, yearly
  On completion of a repeating task → next occurrence auto-created with calculated due date
- Time-bound flag for hard deadline tasks
- Linked to property, room (loads via AJAX), and/or tenant
- Filters: status, category, priority, property — all combinable via URL params
- Summary cards: overdue, urgent, open, in progress, reminders
- Overdue rows highlighted red, due within 7 days highlighted yellow
- Add form accepts URL query params for system-generated task pre-fill
- Schema addition: added category, repeat, time_bound columns to Task model
  via Flask-Migrate migration
- Notes for future work:
  - Frequency multiplier (e.g. 2 + weekly = every 2 weeks, 5 + yearly = every 5 years)
  - Advance reminder field (show task N days before due date)
  - System-generated tasks from compliance expiry and overdue rent

### [06/11/2026] — FEATURE — Admin Panel module built and working
- `app/admin/routes.py` — user management for all roles
- Routes: index, add_landlord, invite_tenant, edit_user, toggle_user, delete_user
- @admin_required decorator protects all admin routes
- Admin dashboard: system stats, three user sections (admins, landlords, tenants)
- Add Landlord: creates scoped landlord account — sees only own data
- Invite Tenant: creates portal account linked to existing Tenant record
  Only tenants without an existing portal_user_id shown in dropdown
  Role set to 'tenant' for portal-gated access
- Edit user: change username, email, role, active status, reset password
- Toggle active: disable login without deleting account or data
- Delete user: unlinks portal_user_id from Tenant record before deletion
- Landlord accounts: show property_count and tenant_count on dashboard
- Tenant portal accounts: show linked Tenant record name with link

### [06/11/2026] — FEATURE — Deposits module built and working
- `app/deposits/routes.py` — full deposit lifecycle management
- Routes: index, add, view, edit, certificate (PDF), download, contracts_for_tenant, delete
- Deposit ID formatted as DEP-0001 for clean referencing
- 5 statuses: Pending, Protected, Paid (returned), Deducting, Withdrawn
- 3 DPS schemes: Deposit Protection Service, MyDeposits, Tenancy Deposit Scheme
- File upload: DPS certificate stored in app/static/uploads/deposits/
  File path stored in notes field as "| file:filename" (schema workaround —
  add dedicated file_path column in polish pass migration)
- Contract linking: tenant dropdown loads contracts via AJAX /deposits/contracts/{id}
- Deduction workflow on edit page:
  - Early surrender accepted toggle with agreed surrender date
  - Deduction amount and reason fields
  - Amount returned and date returned
  - Quick calculation widget showing deposit − deductions = to return
- Certificate PDF (xhtml2pdf): A4 document with green header, tenant details,
  property address, DPS reference, legal notice about 30-day protection requirement
  Deduction summary included when status is deducting/paid/withdrawn
- Model relationships added to Deposit class:
  tenant = db.relationship('Tenant', backref='deposit_records')
  contract = db.relationship('TenantContract', backref='deposit')

### [06/11/2026] — MILESTONE — First pass complete — all 14 modules built
All planned modules delivered and working on local development server:
1.  ✅ Auth — login, logout, register, change password
2.  ✅ Dashboard — summary cards and quick links
3.  ✅ Properties & Rooms — full CRUD, occupancy tracking
4.  ✅ Tenants & Contracts — lifecycle, GDPR consent, Right to Rent
5.  ✅ Bills — pro-rata shared bill calculation (gas, electric, council tax)
6.  ✅ Invoices — generation, PDF download (xhtml2pdf), status tracking
7.  ✅ Transactions — dual-entry ledger, bank CSV import, auto-match, split payments
8.  ✅ Expenses — HMRC categorised, ledger integration, cash/bank/manual
9.  ✅ QuickFile Export — tax year CSV per property in bank statement format
10. ✅ Compliance — certificate dashboard, expiry tracking, file upload
11. ✅ Tasks — categories, priorities, repeating schedules, property/room/tenant links
12. ✅ Admin Panel — landlord and tenant portal account management
13. ✅ Deposits — DPS tracking, deduction workflow, certificate PDF
14. ✅ Tenant Portal — stub routes registered, ready for second pass build-out

Tech stack confirmed and stable:
- Python 3.14 · Flask 3 · UV · SQLite (instance/app.db) · SQLAlchemy · Flask-Migrate
- xhtml2pdf for PDF generation (WeasyPrint replaced — GTK not available on Windows)
- Jinja2 server-side templates · HMRC-inspired green/white CSS design system
- 20 database tables · Flask-Login auth · Role-based access (admin/landlord/tenant)

---

### [08/11/2026] — SETUP — Polish pass 1 begin
- Standing rule established: before any model changes, audit all existing
  backrefs first to prevent SQLAlchemy ArgumentError conflicts
- Decided to stop using Flask-Migrate for SQLite schema changes during
  development. Too many unnamed constraint issues with SQLite batch mode.
  Will use direct raw SQL for column additions instead.
  Flask-Migrate will work correctly on PostgreSQL at deployment time.

### [08/11/2026] — SCHEMA — Polish pass 1 model additions
- Added expense_id INTEGER to transactions table via raw SQL
- Added repeat_frequency INTEGER and remind_days_before INTEGER to tasks
  (already present from db.create_all — stamped migration c2de6083697e)
- Added file_path VARCHAR to deposits
  (already present from db.create_all — no migration needed)
- Added amount_paid NUMERIC to invoices
- Added invoice_payments table:
  id, invoice_id, transaction_id, amount, payment_date, notes
- Deposit model: fixed backref conflict — removed duplicate tenant/contract
  relationships, used foreign_keys string syntax with unique backref names
- Stamped migrations rather than running them where db.create_all had
  already created the columns

### [08/11/2026] — FEATURE — PicklistPaymentType seeded
- 9 payment types added via polish_pass_1_setup.py:
  Rent, Gas/Electric, Council Tax, Deposit, Advanced Rent,
  Key Replacement, Utility Bills, Maintenance Charge, Other Income

### [08/11/2026] — BUG — Contract dropdown validation errors fixed
- add_contract page used onchange form submit to reload rooms
  causing validation errors for all required fields
- Fix: replaced with AJAX endpoint GET /properties/{id}/vacant-rooms
  returning JSON list of vacant rooms for the selected property
- New route: properties_bp vacant_rooms() returns jsonify room list
- Template now uses fetch() to load rooms silently on property change
- DOMContentLoaded handler re-loads rooms if property already selected
  (handles page reload after a failed form submit)

### [08/11/2026] — FEATURE — Tenant account balance and invoice payment flow
- Invoices now have a formal financial lifecycle:
  draft → issued → partially_paid → paid / overdue
- When invoice is ISSUED: tenant rent_balance and bill_balance increase
  by the rent and bill portions respectively
- When invoice is DELETED: balances are reversed
- Invoice generate form now has "Issue immediately" checkbox (default on)
- invoice.amount_paid tracks cumulative payments against each invoice
- Invoice view shows: outstanding balance, payment history table,
  amount paid vs total due

### [08/11/2026] — FEATURE — Payment matching engine built
- New file: app/transactions/matcher.py
- auto_match_payment() function:
  1. Fetches outstanding invoices for tenant oldest-first
  2. Splits payment: rent portion first, then bills
  3. Creates Transaction credit rows with QuickFile-ready Notes:
     "{preferred_description} Rent" and "{preferred_description} Bills"
  4. Creates InvoicePayment records linking payments to invoices
  5. Updates invoice.amount_paid and status
  6. Updates tenant.rent_balance and tenant.bill_balance
  7. Handles surplus: checks for pending deposit record first
     (amount within £1.00 tolerance) → labels as "Deposit"
     Otherwise labels surplus as "Advanced Rent"
- Integrated into transactions match route:
  confirm_all action now calls auto_match_payment() for each auto-matched row
  manual_match action also routes through the engine for credit rows
- Debit rows (expenses) handled separately via _create_debit_transaction()

### [08/11/2026] — FEATURE — Auto-match legend page updated
- Clearer instructions explaining:
  Income/Expense Type can be left blank — engine auto-splits rent vs bills
  Preferred Description is the QuickFile export base (Rent/Bills appended)
  Surplus logic: deposit match first, then advanced rent
- Income Type dropdown now shows "Leave blank (auto-split)" as default
- Existing rules table shows "Auto-split" for blank income type

### [08/11/2026] — FEATURE — Rent Roll built
- New file: app/invoices/rent_roll.py — build_rent_roll() function
- New route: /invoices/rent-roll with property filter
- New template: invoices/rent_roll.html
- Shows per tenant: monthly rent, next due date, rent balance,
  bill balance, total owed, last payment date and amount, status
- Status logic:
  overdue  = has issued invoice with due_date < today
  outstanding = has issued invoice not yet overdue
  current  = no outstanding balance
  credit   = negative balance (tenant has overpaid)
- Sort order: overdue first, then outstanding, then current, then credit
- Row colours: red=overdue, yellow=outstanding, green=current/credit
- Summary cards: monthly rent roll total, total outstanding, overdue count
- Totals row in table footer shows portfolio-wide rent/bill/outstanding
- Rent roll link added to sidebar navigation under Finance section
- Next rent due date shows days until/since with colour coding

### [08/11/2026] — TOOL — Financial data reset script
- New file: reset_financial_data.py
- Safe reset for testing: clears all financial data, keeps structure
- Clears: transactions, bank imports/rows, invoices/items/payments,
  bill shares, bills, expenses
- Resets: all tenant rent_balance and bill_balance to £0.00
- Keeps: users, properties, rooms, tenants, contracts, compliance,
  tasks, transaction legend rules, picklists
- Requires typing YES to confirm before running
- Prints suggested test order after completion

---

*Add new entries above this line as development progresses.*
