# HMO Landlord Management System

## What is this system?

This is a private web-based management tool designed for HMO (House in Multiple Occupation) landlords. It helps you run the day-to-day financial and administrative side of your room-renting business from one place.

You can use it to:

- Record and track tenants, rooms, and contracts across all your properties
- Automatically calculate each tenant's fair share of shared bills (gas, electricity, council tax)
- Generate and download professional PDF invoices for tenants each month
- Upload your bank statement CSV and match payments to tenants
- Record business expenses and cash payments
- Export a clean financial statement for QuickFile (for your Self Assessment tax return)
- Store and track safety certificates, compliance documents, and key filing dates
- Manage jobs and tasks linked to specific properties, rooms, or tenants
- Keep deposit records with DPS references and generate deposit certificates

---

## Who can use it?

| Role | What they can do |
|---|---|
| **Administrator** | Full access to everything — all landlords, all properties, all finances |
| **Landlord** | Access to their own properties, tenants, finances, and documents only |
| **Tenant (Portal)** | View their own invoices, payments, contract, and send messages or raise tasks |

---

## How to start the system (on your PC)

> You need to have **Python** and **UV** installed. Your developer will set this up for you initially.

1. Open a terminal (Command Prompt or PowerShell)
2. Navigate to the project folder:
   ```
   cd C:\scripts\codeInst_projects\Project5\Prototype
   ```
3. Start the application:
   ```
   uv run flask run
   ```
4. Open your web browser and go to:
   ```
   http://localhost:5000
   ```
5. Log in with your username and password.

---

## How to use the system

### Adding a Property and Rooms
1. Go to **Properties** in the left menu
2. Click **Add Property** and fill in the address details
3. Inside the property, click **Add Room** for each lettable room

### Adding a Tenant
1. Go to **Tenants** → **Add Tenant**
2. Fill in their personal details, contact information, and Right to Rent reference
3. Assign them to a property and room
4. Create their **Contract** with start date, rent amount, and billing date
5. Record their **Deposit** amount and DPS reference number

### Entering Monthly Bills
1. Go to **Bills** and select the property
2. Enter the gas/electricity bill with its exact date range (e.g. 15 Sep – 14 Oct)
3. Enter the council tax amount for the period
4. The system automatically calculates each active tenant's fair share based on how many days they were present during that billing period
5. Invoice line items are created automatically ready for the next invoice run

### Generating Invoices
1. Go to **Invoices** → **Generate Invoices**
2. Select the property and the billing month
3. Review each tenant's invoice — it will include rent, their bill shares, any one-off charges, and any outstanding balance carried forward
4. Download the PDF for each tenant

### Uploading Your Bank Statement
1. Go to **Transactions** → **Import Bank Statement**
2. Upload your CSV file downloaded from your bank
3. The system will attempt to auto-match transactions to tenants using the transaction description
4. Review and confirm matched payments, or manually assign unmatched ones
5. Split payments (e.g. a tenant paying rent and bills in one transfer) can be divided and labelled

### Recording Cash Payments
1. Go to **Transactions** → **Add Manual Entry**
2. Select the tenant, amount, type (rent/bill), and date
3. This will appear in the ledger alongside bank-matched payments

### Exporting for QuickFile
1. Go to **Reports** → **QuickFile Export**
2. Select the tax year period (April to April) and property
3. Download the CSV file — it uses the same format as your bank statement with corrected descriptions ready to import into QuickFile

### Compliance & Safety Certificates
1. Go to **Compliance Dashboard**
2. You will see all certificates and documents for each property (gas safety, electrical, EPC, insurance, tariffs, etc.)
3. Click any record to upload a PDF, update the date, or set the next expiry date
4. Approaching expiry dates are highlighted on your main dashboard

### Managing Tasks
1. Go to **Tasks** → **Add Task**
2. Give it a title, priority level, and link it to a property, room, or tenant
3. Tasks appear in your task list and can be marked complete at any time

---

## Important notes

- **Your data is private.** Each landlord user can only see their own properties and tenants.
- **GDPR:** Tenant personal data is held lawfully under the terms of their tenancy contract and UK legal obligations (Right to Rent, council tax registration). Tenants can request to see their data at any time.
- **Backups:** The database is stored as a single file (`app.db`) in the project folder. Copy this file regularly to keep a backup of all your data.

---

## Getting help

If something is not working, check the **Technical Development Log** document for known issues and recent changes. For any major problems, contact your developer.
