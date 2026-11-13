# Technical Development Log — HMO LandlordApp

Chronological record of design decisions, implementation notes, and fixes.

---

## Architecture

### Blueprint Structure
The app is organised into Flask blueprints: `auth`, `dashboard`, `properties`, `tenants`, `contracts`, `invoices`, `deposits`, `tasks`, `portal`. Each blueprint has its own `routes.py` and corresponding `templates/<blueprint>/` folder.

### Role-Based Access
Two user roles: `landlord` and `tenant`. Enforced via custom decorators (`@landlord_required`, `@tenant_required`) applied at the route level. Tenants access everything through the `/portal` prefix; landlord routes have no prefix.

### Models
All data lives in `app/models.py`. Key relationships:
- `User` → `TenantProfile` (one-to-one for tenants)
- `TenantProfile` → `TenantContract` (one-to-many)
- `TenantContract` → `Property`, `Room` (many-to-one each)
- `TenantProfile` → `Transaction` (one-to-many)
- `TenantProfile` → `Invoice` → `InvoiceItem`, `InvoicePayment`
- `TenantProfile` → `Deposit` (linked to contract)
- `TenantProfile` → `Task`

---

## Feature Implementation Notes

### Rent Roll (`app/invoices/rent_roll.py`)
`build_rent_roll(user_id, property_id=None, show_ended=False)` assembles a row dict per tenant:
- Queries `is_active=True` tenants by default
- With `show_ended=True`: queries all tenants, falls back to most recent contract if no active one
- Balance calculated from raw `Transaction` rows (debit minus credit)
- `contract_active` bool distinguishes active vs ended rows
- Ended rows get `status='ended'`, `next_rent_due=None`, sorted last (status_order=4)
- Rent roll route passes `active_rows` and `ended_rows` separately to the template

### Deposit Settlement Workflow
Route: `GET/POST /deposits/<id>/settle`

**GET**: 
- `_live_balance(tenant_id)` queries transactions to return `(rent_bal, bill_bal, total_bal)`
- `suggested_deduction = max(total_bal, 0)` — never negative
- `suggested_returned = max(deposit.amount - suggested_deduction, 0)`
- `default_reason` built from `contract.closure_type`:
  - surrender: `'Early surrender accepted — vacated DD Mon YYYY. Rent balance: £X. Bills balance: £Y.'`
  - notice: `'Notice period ended DD Mon YYYY. Rent balance: £X. Bills balance: £Y.'`
- Status dropdown defaults: `deducting` if balance > 0, else `paid`

**POST**: saves `deduction_amount`, `deduction_reason`, `amount_returned`, `returned_date`, `status` to deposit record.

**Template JS**: `calcReturned()` updates `amount_returned` live as deduction changes.

### Contract Closure Types
`TenantContract` has fields: `closure_type` (notice/surrender), `notice_end_date`, `surrender_date`.
- Surrender date captured in portal end-contract request form; appended to task description as text
- Landlord reads it from task and records on contract when processing

### Tenant Portal — Contract End Request
Route: `GET/POST /portal/end-contract/<contract_id>`

- GET: checks for existing pending "End Contract Request" task; redirects with message if found (prevents duplicate requests)
- POST: validates `request_type`; if `surrender`, validates `surrender_date` is present and in the future (server-side); appends `Requested surrender date: DD Mon YYYY.` to task description
- Template: radio `onchange` triggers `toggleSurrenderDate()` JS; shows/hides date field and toggles `required`

### Portal — Give Notice Button State
`portal.contracts()` queries for pending tasks of type "End Contract Request" linked to the tenant. Passes `has_pending_end_request` bool to template. Template renders either the button or a greyed-out "Notice Pending…" span.

### Portal — My Account (Contract Fallback)
`_latest_contract(tenant)` helper returns most recent contract regardless of `is_active`, so tenants with ended contracts still see their payment history and contract details rather than "No active contract found".

### Invoice PDF Generation
Extracted `_generate_invoice_pdf(invoice)` helper in `app/invoices/routes.py`:
1. Renders `invoices/pdf_template.html` via Jinja2
2. Runs xhtml2pdf to produce PDF bytes
3. Saves to `app/static/uploads/invoices/invoice_<number>.pdf`
4. Updates `invoice.pdf_path` and commits (best-effort — never blocks download)
5. Returns `(pdf_bytes, filename)`

Landlord `pdf` route now calls the helper, so every landlord download automatically caches a copy for tenants.

### Tenant PDF Download
Route: `GET /portal/invoices/<id>/pdf`
- Tenant-scoped (checks `invoice.tenant_id == tenant.id`)
- Serves from `pdf_path` on disk if exists
- Falls back to `_generate_invoice_pdf()` on the fly
- Falls back to flash error if generation fails (xhtml2pdf not available etc.)

### Auto-Logout (Idle Timer)
Implemented in `base.html`, wrapped in `{% if current_user.is_authenticated %}`:
- `IDLE_MINUTES = 5`, `WARN_SECONDS = 60`
- Activity events: `mousemove`, `mousedown`, `keypress`, `touchstart`, `scroll`, `click`
- Each event calls `resetIdleTimer()`: clears timeout + interval, hides warning, sets new timeout
- After idle period: `startCountdown()` shows toast, starts 1s interval decrementing `secondsLeft`
- At zero: `window.location.href = LOGOUT_URL`
- Logout URL passed safely via `{{ url_for('auth.logout') | tojson }}`

### CSS Badge System
Semantic badge classes in `main.css`:
```css
.badge-green  { background: #d4edda; color: #155724; }
.badge-red    { background: #f8d7da; color: #721c24; }
.badge-yellow { background: #fff3cd; color: #856404; }
.badge-blue   { background: #ddeeff; color: #1a5a99; }  /* Issued invoices */
.badge-grey   { background: #e9ecef; color: #495057; }
```
Applied consistently: invoices (index, view, portal), deposits (view, settle), contracts, rent roll.

---

## Bugs Fixed

### "No active contract found" in portal My Account
**Problem**: Portal `account()` route queried `filter_by(is_active=True)` — tenants with ended contracts saw empty page.  
**Fix**: `_latest_contract(tenant)` helper queries by `tenant_id` ordered by `start_date desc`, returning the most recent contract regardless of active status.

### Rent Roll "No active tenants found" for ended contracts
**Problem**: `build_rent_roll()` only included `is_active=True` tenants; ended tenants were invisible even though balances remained for deposit settlement.  
**Fix**: Added `show_ended` flag; queries all tenants; ended rows included in a separate section with Settle button.

### Portal invoice page linking to non-existent route
**Problem**: `portal/invoices.html` referenced `invoices.download_pdf` (landlord route, `@landlord_required`).  
**Fix**: New `portal.download_invoice_pdf` route at `/portal/invoices/<id>/pdf`; PDF saved on landlord download so tenant can retrieve it.

### Duplicate end-contract requests
**Problem**: Tenant could submit multiple "Give Notice" requests if they navigated back to the form.  
**Fix**: GET handler checks for existing pending task; redirects with info flash if found. Button replaced by "Notice Pending…" indicator in template.

### Edit tool "file not read" error (dev session)
**Problem**: Attempted edit on `portal/contracts.html` without prior Read call.  
**Fix**: Read file first, then edit. Workflow reinforced: always Read before Edit when file content is not in context.

---

## File Index (key files)

| File | Purpose |
|---|---|
| `app/models.py` | All SQLAlchemy models |
| `app/invoices/rent_roll.py` | `build_rent_roll()` with show_ended support |
| `app/invoices/routes.py` | Invoice CRUD, PDF generation, rent roll view |
| `app/deposits/routes.py` | Deposit CRUD + `settle` workflow |
| `app/portal/routes.py` | All tenant portal routes |
| `app/static/css/main.css` | Global stylesheet inc. badge system |
| `app/templates/base.html` | Shared layout, nav, idle-logout JS |
| `app/templates/invoices/rent_roll.html` | Rent roll with ended tenants section |
| `app/templates/deposits/settle.html` | Deposit settlement form |
| `app/templates/portal/invoices.html` | Tenant invoice list + PDF download |
| `app/templates/portal/end_contract_request.html` | Give notice / surrender form |
| `app/templates/portal/contracts.html` | Contract list with pending notice state |

---

## .gitignore Recommendations

```
*.db
*.sqlite3
app/static/uploads/invoices/
app/static/uploads/deposits/
__pycache__/
*.pyc
.env
venv/
instance/
```
