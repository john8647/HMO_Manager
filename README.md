# HMO LandlordApp

A full-stack Flask web application for managing Houses in Multiple Occupation (HMO) rental properties. Built for private landlords to track tenants, contracts, rent, bills, invoices, and deposits — with a self-service tenant portal.

---

## Features Overview

### Landlord Dashboard
- Summary cards: active tenants, properties, outstanding rent, overdue invoices
- Quick-action links to common tasks
- Recent activity feed

### Properties & Rooms
- Add and manage multiple properties with address, postcode, and EPC details
- Define rooms per property (room name, floor, en-suite, monthly rent)
- Room occupancy status tracked automatically via active contracts

### Tenants
- Tenant profiles: name, email, phone, emergency contact, notes
- Link tenants to rooms via contracts
- View full tenancy history per tenant

### Contracts
- Create contracts with start/end dates, monthly rent, deposit amount, and notice period
- Contract closure types: **Notice Period** and **Early Surrender**
  - Notice Period: records notice end date
  - Early Surrender: records agreed surrender date
- Contract status tracked (`is_active` flag)
- Landlord can record closure type and dates when ending a contract

### Rent Roll
- Live summary of all active tenants: rent balance, bills balance, total balance, next rent due
- Colour-coded status badges: Paid, Outstanding, Overdue, Partial
- **Show Ended Tenants** toggle: reveals tenants with closed contracts for deposit settlement review
- Ended tenants display: contract end date, closure type badge, live balances, deposit held + status, Settle button

### Transactions
- Manual rent charge and payment recording
- Bill charge allocation per tenant
- Transaction history with running balance
- Supports credit entries (advance payments, overpayments)

### Invoices
- Create invoices with line items, period dates, issue date, due date
- One-off charge addition to existing invoices
- Status workflow: Draft → Issued → Partially Paid → Paid / Overdue
  - **badge-blue** for Issued, green for Paid, red for Overdue, yellow for Partial
- PDF generation via xhtml2pdf; PDFs saved to `app/static/uploads/invoices/`
- Payment recording with notes and date
- Arrears carried forward field

### Deposits
- Record deposit amount, scheme, scheme reference, protection date, status
- Status values: Received, Protected, Deducting, Paid, Withdrawn
- **Deposit Settlement Workflow** (accessible from Rent Roll and Deposit view):
  - Live balance tiles: Total, Rent, Bills, Deposit Held
  - Contract closure summary with deduction rules card
  - Pre-populated deduction amount (from live transaction balance)
  - Pre-populated deduction reason (from closure type, dates, and balances)
  - Auto-calculated amount returned (Deposit − Deduction, via JS)
  - Returned date and status dropdown
  - Defaults to `Deducting` if balance > 0, `Paid` if zero balance

### Tasks
- Landlord task list for follow-ups, maintenance notes, and tenant requests
- Tasks linked to tenants; status: Pending, In Progress, Completed
- Task description/notes field

### Tenant Portal
- Separate login flow for tenants (`/portal`)
- **My Account**: rent balance summary, recent transactions, active (or most recent) contract details
- **My Contracts**: full contract history; "Give Notice / End Contract" button
  - **End Contract Request form**: choose Notice or Early Surrender; Early Surrender requires a future surrender date (validated client- and server-side); request appended to task description
  - Button replaced by "Notice Pending…" indicator once a request is submitted (until landlord resolves task)
- **My Invoices**: list of all invoices with status badges (blue=Issued, green=Paid, etc.); PDF download button — serves landlord-generated PDF from disk or generates on the fly
- **My Rent Roll**: tenant's own balance view (read-only)

### Auto-Logout (Inactivity Timeout)
- Idle timer: 5 minutes of inactivity triggers a 60-second countdown warning (toast, bottom-right)
- Warning shows remaining seconds live; resets on any mouse, keyboard, touch, or scroll activity
- Redirects to logout at zero — applies to all authenticated users (landlord and tenant)

### Authentication
- Separate landlord and tenant login
- Role-based access control via `@landlord_required` / `@tenant_required` decorators
- Password hashing via Werkzeug

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| ORM | SQLAlchemy (Flask-SQLAlchemy) |
| Database | SQLite (dev) |
| Templating | Jinja2 |
| PDF Generation | xhtml2pdf |
| Auth | Flask-Login |
| Migrations | Flask-Migrate (Alembic) |
| Frontend | Vanilla HTML/CSS/JS (custom design system) |
| File Storage | Local filesystem (`app/static/uploads/`) |

---

## Project Structure

```
app/
├── auth/           # Login, logout, role decorators
├── dashboard/      # Landlord home
├── properties/     # Property & room CRUD
├── tenants/        # Tenant profiles
├── contracts/      # Contract management
├── invoices/       # Invoices, rent roll, PDF generation
├── deposits/       # Deposit records, settlement workflow
├── tasks/          # Task management
├── portal/         # Tenant self-service portal
├── models.py       # SQLAlchemy models
├── static/
│   ├── css/main.css
│   └── uploads/invoices/   # Generated PDFs
└── templates/
    ├── base.html   # Shared layout, nav, idle-logout JS
    └── [blueprint]/
```

---

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask db upgrade
python seed_admin.py
flask run
```

---

## Notes

- `app/static/uploads/invoices/` accumulates generated PDFs — add to `.gitignore`
- SQLite database file should also be in `.gitignore`
- Tenant logins are created by the landlord (no self-registration)
