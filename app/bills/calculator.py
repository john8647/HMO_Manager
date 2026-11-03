"""
Bill pro-rata calculator.

Splits a shared bill proportionally by the number of days each tenant
was present (had an active contract overlapping the billing period).
Days are counted inclusively: 01/07 → 31/07 = 31 days.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP


def inclusive_days(start: date, end: date) -> int:
    """Return the number of inclusive days between two dates."""
    delta = (end - start).days + 1
    return max(delta, 0)


def tenant_days_in_period(contract_start: date, contract_end: date | None,
                           period_start: date, period_end: date) -> int:
    """
    Return how many days a tenant's contract overlaps with the billing period.
    contract_end=None means the contract is still active (use period_end as cap).
    """
    effective_end = contract_end if contract_end else period_end
    overlap_start = max(contract_start, period_start)
    overlap_end = min(effective_end, period_end)
    return inclusive_days(overlap_start, overlap_end)


def calculate_shares(bill_amount: Decimal, tenants: list[dict],
                     period_start: date, period_end: date) -> list[dict]:
    """
    Calculate each tenant's proportional share of a bill.

    tenants: list of dicts with keys:
        - tenant_id
        - contract_id
        - contract_start (date)
        - contract_end (date or None)

    Returns list of dicts:
        - tenant_id
        - contract_id
        - days_present
        - share_amount (Decimal, rounded to 2dp)
    """
    results = []
    total_days = 0

    for t in tenants:
        days = tenant_days_in_period(
            t['contract_start'],
            t.get('contract_end'),
            period_start,
            period_end
        )
        t['days_present'] = days
        total_days += days

    if total_days == 0:
        return []

    daily_rate = Decimal(str(bill_amount)) / Decimal(str(total_days))
    allocated = Decimal('0.00')

    for i, t in enumerate(tenants):
        if i == len(tenants) - 1:
            # Give any rounding remainder to the last tenant
            share = Decimal(str(bill_amount)) - allocated
        else:
            share = (daily_rate * t['days_present']).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            allocated += share

        results.append({
            'tenant_id': t['tenant_id'],
            'contract_id': t['contract_id'],
            'days_present': t['days_present'],
            'share_amount': share,
        })

    return results
