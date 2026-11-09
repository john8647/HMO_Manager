"""
Rent Charge Engine
==================
Generates internal rent charge debit entries for active contracts,
covering all periods from contract start up to and including today.

Key rules:
  - Only creates a debit charge if no rent credit already exists
    for that tenant in the same calendar month. This prevents
    double-charging when the tenant paid before the engine ran.
  - Each charge is a Transaction(credit_debit='db', type='Rent')
  - Updates tenant.rent_balance and contract.next_rent_due
  - dry_run=True returns what would be charged without writing

Month matching logic:
  A rent credit in August 2026 cancels the August 2026 debit charge.
  Month/year period is used (not exact date) so payment on 3rd Aug
  cancels a charge dated 1st Aug correctly.
"""

from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from app import db
from app.models import TenantContract, Transaction, Tenant


def advance_one_month(d: date) -> date:
    return d + relativedelta(months=1)


def period_key(d: date) -> str:
    """Return 'YYYY-MM' string for a date — used to match debits to credits."""
    return d.strftime('%Y-%m')


def get_paid_periods(tenant_id: int) -> set:
    """
    Return set of 'YYYY-MM' period keys where a rent credit already exists.
    These periods are considered paid — no debit charge needed.
    """
    credits = Transaction.query.filter_by(
        tenant_id=tenant_id,
        credit_debit='cr',
        type='Rent',
    ).all()
    return {period_key(t.transaction_date) for t in credits}


def get_charged_periods(tenant_id: int) -> set:
    """
    Return set of 'YYYY-MM' period keys where a rent debit already exists.
    Prevents duplicate charges.
    """
    debits = Transaction.query.filter_by(
        tenant_id=tenant_id,
        credit_debit='db',
        type='Rent',
    ).all()
    return {period_key(t.transaction_date) for t in debits}


def generate_rent_charges(user_id: int, dry_run: bool = False) -> list[dict]:
    """
    Generate all outstanding rent charges for a landlord's active contracts.

    For each active contract:
      - Walk from contract start (or next_rent_due) to today
      - Skip any month where a rent credit already exists
      - Skip any month where a rent debit already exists
      - Create a debit charge for each uncovered month
      - Update tenant.rent_balance and contract.next_rent_due

    Returns list of dicts describing each charge created or previewed.
    """
    today   = date.today()
    results = []

    contracts = TenantContract.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()

    # Auto-close any contracts whose end date has passed
    if not dry_run:
        from app.models import Room
        for contract in contracts:
            if contract.end_date and contract.end_date < today:
                contract.is_active = False
                room = Room.query.get(contract.room_id)
                if room:
                    room.is_occupied = False
        db.session.flush()
        # Reload — only keep contracts still active after auto-close
        contracts = TenantContract.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()
    else:
        # In dry_run mode filter out expired contracts for preview
        contracts = [
            c for c in contracts
            if not c.end_date or c.end_date >= today
        ]

    for contract in contracts:
        tenant = Tenant.query.get(contract.tenant_id)
        if not tenant:
            continue

        # Starting charge date
        charge_date = contract.start_date
        if not charge_date:
            continue

        # Cap charges at the contract end date if set
        # A tenant leaving 28 Oct should be charged up to and including October
        # but NOT November onwards
        charge_until = today
        if contract.end_date and contract.end_date < today:
            charge_until = contract.end_date

        paid_periods    = get_paid_periods(contract.tenant_id)
        charged_periods = get_charged_periods(contract.tenant_id)

        periods_charged  = 0
        last_charge_date = None

        while charge_date <= charge_until:
            pk = period_key(charge_date)

            # Skip if already paid for this month
            if pk in paid_periods:
                charge_date = advance_one_month(charge_date)
                continue

            # Skip if already charged for this month
            if pk in charged_periods:
                charge_date = advance_one_month(charge_date)
                continue

            # This period needs a charge
            month_year  = charge_date.strftime('%B %Y')
            description = (
                f'Rent — {contract.room.room_name} '
                f'({contract.property.address_line1}) '
                f'{charge_date.strftime("%d %b %Y")}'
            )

            results.append({
                'tenant':      tenant.full_name,
                'property':    contract.property.address_line1,
                'room':        contract.room.room_name,
                'amount':      Decimal(str(contract.monthly_rent)),
                'charge_date': charge_date,
                'period':      month_year,
                'contract_id': contract.id,
            })

            if not dry_run:
                t = Transaction(
                    tenant_id=contract.tenant_id,
                    contract_id=contract.id,
                    amount=Decimal(str(contract.monthly_rent)),
                    credit_debit='db',
                    transaction_date=charge_date,
                    user_id=user_id,
                    type='Rent',
                    month_year_period=month_year,
                    source='system',
                    is_matched=True,
                    notes=description,
                )
                db.session.add(t)
                tenant.rent_balance = (
                    Decimal(str(tenant.rent_balance or 0)) +
                    Decimal(str(contract.monthly_rent))
                )

            last_charge_date = charge_date
            periods_charged += 1
            charge_date = advance_one_month(charge_date)

        # Update next_rent_due only if contract is still active
        if not dry_run and periods_charged > 0 and contract.is_active:
            contract.next_rent_due = charge_date

    if not dry_run:
        db.session.commit()

    return results


def recalculate_tenant_balance(tenant_id: int) -> dict:
    """
    Recalculate a tenant's rent balance from scratch by comparing
    all rent debits against all rent credits.

    Total debits (charges) - Total credits (payments) = balance owed.
    Negative = tenant in credit (overpaid).

    This is used to correct any drift between the stored balance
    and the actual transaction history.
    """
    debits = Transaction.query.filter_by(
        tenant_id=tenant_id,
        credit_debit='db',
        type='Rent',
    ).all()

    credits = Transaction.query.filter_by(
        tenant_id=tenant_id,
        credit_debit='cr',
        type='Rent',
    ).all()

    total_charged = sum(Decimal(str(t.amount)) for t in debits)
    total_paid    = sum(Decimal(str(t.amount)) for t in credits)
    balance       = total_charged - total_paid

    tenant = Tenant.query.get(tenant_id)
    if tenant:
        tenant.rent_balance = balance
        db.session.commit()

    return {
        'tenant_id':     tenant_id,
        'total_charged': total_charged,
        'total_paid':    total_paid,
        'balance':       balance,
    }


def recalculate_all_balances(user_id: int) -> list[dict]:
    """
    Recalculate rent and bill balances for all active tenants
    from their raw transaction history. Corrects any drift.
    """
    tenants = Tenant.query.filter_by(user_id=user_id, is_active=True).all()
    results = []
    for tenant in tenants:
        result = recalculate_tenant_balance(tenant.id)
        results.append(result)
    return results
