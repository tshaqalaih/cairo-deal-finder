"""
Eligibility gate checker — spec Section 8.

Returns (status, reason) where status is:
  'eligible'   — passes all gates, enters scorer
  'excluded'   — hard exclusion (drop)
  'needs_data' — soft exclusion (route to needs-data queue)

Gates are evaluated in order; first failure returns immediately.
"""
from __future__ import annotations
from typing import Literal

import config

Status = Literal["eligible", "excluded", "needs_data"]

# Property types accepted (spec Section 8)
ACCEPTED_TYPES = {
    "apartment", "duplex", "ivilla", "s_villa", "quattro",
    "villa", "townhouse", "twinhouse", "penthouse",
}

# Location strings that indicate 5th Settlement / New Cairo
TARGET_LOCATIONS = config.TARGET_LOCATIONS

# Developer blacklist and project red-flags are loaded from DB at runtime
# (passed in as sets to avoid repeated DB calls per listing)


def check(
    listing: dict,
    npv_at_25: float | None,           # Cash-equivalent at 25% rate
    upfront_cash: float | None,        # Cash + fees at signing + overdue
    schedule_is_unknown: bool,         # True if installment schedule missing
    data_confidence: float,            # 0.0–1.0
    developer_blacklist: set[str],     # Lower-cased developer names
    project_red_flags: set[str],       # Lower-cased project names
    reference_projects: dict,          # {canonical_name: project_record}
) -> tuple[Status, str]:
    """
    Run all eligibility gates in order.
    Returns (status, reason_text).
    """

    # ── 1. Location ────────────────────────────────────────────────────────
    loc = (listing.get("location_raw") or "").strip()
    if not any(t.lower() in loc.lower() for t in TARGET_LOCATIONS):
        return "excluded", f"Location not in target area: '{loc}'"

    # ── 2. Property type ───────────────────────────────────────────────────
    ptype = (listing.get("property_type") or "unknown").lower()
    if ptype not in ACCEPTED_TYPES:
        return "excluded", f"Property type not accepted: '{ptype}'"

    # ── 3. Bedrooms ────────────────────────────────────────────────────────
    beds = listing.get("bedroom_count")
    if beds is None:
        return "needs_data", "Bedroom count unknown"
    if beds < 3:
        return "excluded", f"Fewer than 3 bedrooms: {beds}"

    # ── 4. Area ────────────────────────────────────────────────────────────
    bua = listing.get("bua_sqm")
    if bua is None:
        return "needs_data", "BUA / area unknown"
    if bua < config.MIN_BUA_SQM:
        return "excluded", f"BUA {bua} sqm below {config.MIN_BUA_SQM} sqm minimum"
    if bua > config.MAX_BUA_SQM:
        return "excluded", f"BUA {bua} sqm above {config.MAX_BUA_SQM} sqm maximum"

    # ── 5. Price basis / seller cash ──────────────────────────────────────
    if listing.get("seller_cash_required_now") is None:
        return "needs_data", "seller_cash_required_now unknown"

    # ── 6. Installment schedule ────────────────────────────────────────────
    if schedule_is_unknown:
        return "needs_data", "Installment schedule unknown — cannot calculate cash-equivalent"

    # ── 7. Known overdue amounts ───────────────────────────────────────────
    if listing.get("known_overdue_amounts") is None:
        return "needs_data", "Overdue amounts unknown (not confirmed as zero)"

    # ── 8. Cash-equivalent total ───────────────────────────────────────────
    if npv_at_25 is None:
        return "needs_data", "Cash-equivalent cannot be calculated — missing transaction legs"
    if npv_at_25 > config.MAX_CASH_EQUIVALENT_EGP:
        return "excluded", (
            f"Cash-equivalent EGP {npv_at_25:,.0f} exceeds "
            f"EGP {config.MAX_CASH_EQUIVALENT_EGP:,.0f} gate"
        )

    # ── 9. Data confidence ─────────────────────────────────────────────────
    if data_confidence < 0.60:
        return "needs_data", f"Data confidence {data_confidence:.0%} below 60% threshold"

    # ── 10. Known legal red flags ──────────────────────────────────────────
    if listing.get("_has_legal_red_flag"):
        return "excluded", "Known legal red flag flagged during normalization"

    # ── 11. Project maturity — new_standalone excluded ─────────────────────
    project_name = (listing.get("project_name_raw") or "").lower()
    ref = _find_reference(project_name, reference_projects)
    if ref and ref.get("project_maturity") == "new_standalone":
        return "excluded", f"Project '{ref['project_name']}' classified as new_standalone"
    if ref and ref.get("blacklisted"):
        return "excluded", f"Project '{ref['project_name']}' is on the red-flag list"

    # ── 12. Developer blacklist ────────────────────────────────────────────
    dev = (listing.get("developer_raw") or "").lower()
    if any(bl in dev for bl in developer_blacklist):
        return "excluded", f"Developer '{dev}' is blacklisted"

    # ── 13. Project red-flag list ──────────────────────────────────────────
    if any(rf in project_name for rf in project_red_flags):
        return "excluded", f"Project '{project_name}' is on the red-flag list"

    # ── 14. Ground floor / no garden ──────────────────────────────────────
    floor_raw = str(listing.get("floor_number") or "").lower()
    garden    = listing.get("private_garden", "not_specified")
    if floor_raw in ("ground", "0", "g") and garden == "no":
        return "excluded", "Ground floor confirmed with no private garden"

    # ── 15. View — internal/zero excluded ─────────────────────────────────
    view = listing.get("view_type", "not_specified")
    if view == "internal_view":
        return "excluded", "Internal/zero view confirmed"

    return "eligible", "Passed all gates"


def _find_reference(project_name_lower: str, reference_projects: dict) -> dict | None:
    """Find a reference project by fuzzy name match."""
    if not project_name_lower:
        return None
    for name, rec in reference_projects.items():
        if name.lower() in project_name_lower or project_name_lower in name.lower():
            return rec
        aliases = rec.get("known_aliases") or []
        if any(
            (alias or "").lower() in project_name_lower
            or project_name_lower in (alias or "").lower()
            for alias in aliases
        ):
            return rec
    return None
