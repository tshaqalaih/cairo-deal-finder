"""
Cash-equivalent (NPV) calculator.

Implements the spec formula:
  cash_equivalent =
      seller_cash_required_now
    + PV(future_developer_payment_schedule, rate)
    + sum(upfront_transaction_fees)
    + known_overdue_amounts

Recurring ownership costs are NOT included — shown separately.

Three rates always calculated: 20%, 25%, 30%.
Ranking driven by 25% (configurable in config.py).
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import NamedTuple

import config


class CashEquivalentResult(NamedTuple):
    at_20: float | None
    at_25: float | None
    at_30: float | None
    upfront_cash: float | None        # cash + fees at signing + overdue
    annual_ownership_cost: float | None
    is_complete: bool                 # False if any required leg is missing
    missing_legs: list[str]           # which legs are unknown


def _pv(payments: list[dict], annual_rate: float) -> float:
    """
    Discount a list of {amount, due_date} payments to present value.
    due_date: ISO date string or None.
    If due_date is None, uses estimated position based on frequency/sequence.
    """
    now = datetime.now(timezone.utc)
    total = 0.0

    for i, p in enumerate(payments):
        amount    = p.get("payment_amount_egp", 0) or 0
        due_date  = p.get("due_date")
        frequency = p.get("frequency", "quarterly")

        if due_date:
            try:
                dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days = max(0, (dt - now).days)
            except (ValueError, AttributeError):
                days = _estimated_days(i, frequency)
        else:
            days = _estimated_days(i, frequency)

        years = days / 365.0
        pv    = amount / ((1 + annual_rate) ** years)
        total += pv

    return total


def _estimated_days(index: int, frequency: str) -> int:
    """
    Estimate days from now for a payment at position `index`
    when exact due date is unknown.
    """
    days_per_period = {
        "monthly":    30,
        "quarterly":  91,
        "semi_annual": 182,
        "annual":     365,
    }.get(frequency, 91)
    return (index + 1) * days_per_period


def _annual_ownership_cost(recurring_costs: list[dict]) -> float | None:
    """Sum recurring costs, normalised to annual EGP."""
    if not recurring_costs:
        return None
    total = 0.0
    for cost in recurring_costs:
        amount = cost.get("amount_egp") or cost.get("amount_annual_egp")
        if not amount:
            continue
        freq   = cost.get("frequency", "annual")
        mult   = {"monthly": 12, "quarterly": 4, "semi_annual": 2, "annual": 1}.get(freq, 1)
        total += amount * mult
    return total if total > 0 else None


def calculate(
    seller_cash_required_now:    float | None,
    installment_schedules:       list[dict],   # rows from DB
    upfront_transaction_fees:    list[dict],   # rows from DB
    known_overdue_amounts:       float | None,
    recurring_ownership_costs:   list[dict],   # rows from DB
    schedule_is_unknown:         bool = False, # True if schedule couldn't be extracted
) -> CashEquivalentResult:
    """
    Calculate cash-equivalent at three discount rates.

    Returns CashEquivalentResult with is_complete=False and missing_legs
    if any required leg is None (unknown).
    """
    missing: list[str] = []

    if seller_cash_required_now is None:
        missing.append("seller_cash_required_now")

    if schedule_is_unknown:
        missing.append("future_developer_payment_schedule")

    if known_overdue_amounts is None:
        missing.append("known_overdue_amounts")

    # upfront_transaction_fees can be [] (confirmed none) — not a missing leg
    fees_total = sum(f.get("amount_egp", 0) or 0 for f in upfront_transaction_fees)

    upfront_cash = None
    if seller_cash_required_now is not None and known_overdue_amounts is not None:
        upfront_cash = seller_cash_required_now + fees_total + known_overdue_amounts

    annual_ownership = _annual_ownership_cost(recurring_ownership_costs)

    if missing:
        return CashEquivalentResult(
            at_20=None, at_25=None, at_30=None,
            upfront_cash=upfront_cash,
            annual_ownership_cost=annual_ownership,
            is_complete=False,
            missing_legs=missing,
        )

    # All legs known — calculate
    base = seller_cash_required_now + fees_total + known_overdue_amounts

    results = {}
    for rate in (0.20, 0.25, 0.30):
        pv = _pv(installment_schedules, rate)
        results[rate] = round(base + pv, 2)

    return CashEquivalentResult(
        at_20=results[0.20],
        at_25=results[0.25],
        at_30=results[0.30],
        upfront_cash=round(upfront_cash, 2) if upfront_cash is not None else None,
        annual_ownership_cost=round(annual_ownership, 2) if annual_ownership else None,
        is_complete=True,
        missing_legs=[],
    )
