"""
Data confidence scorer — spec Section 11.

data_confidence_score = weighted sum of four components:
  Required field completeness  40%
  Source / evidence quality    30%
  Price / schedule certainty   20%
  Duplicate ambiguity          10%

Returns a float 0.0–1.0.
"""
from __future__ import annotations

# Required fields that must be present for a listing to be scoreable
REQUIRED_FIELDS = [
    "project_name_raw", "property_type", "bedroom_count", "bua_sqm",
    "finishing_status", "delivery_status", "seller_cash_required_now",
    "floor_number", "view_type", "parking_included",
]

SOURCE_QUALITY_MAP = {
    "developer_statement": 1.0,
    "seller_claim":        0.6,
    "listing_text":        0.3,
    "unknown":             0.0,
}

DUPLICATE_FLAG_MAP = {
    "unique":              1.0,
    "possible_duplicate":  0.5,
    "likely_duplicate":    0.2,
    "confirmed_duplicate": 0.0,
}


def calculate(
    listing: dict,
    schedule_is_complete: bool,
    schedule_is_unknown: bool,
) -> float:
    """
    Calculate data confidence score (0.0 – 1.0).

    listing: dict of listing fields
    schedule_is_complete: True if installment schedule rows exist
    schedule_is_unknown: True if schedule could not be extracted at all
    """

    # ── Component 1: Required field completeness (40%) ─────────────────────
    present = sum(
        1 for f in REQUIRED_FIELDS
        if listing.get(f) not in (None, "unknown", "not_specified", "")
    )
    completeness = present / len(REQUIRED_FIELDS)

    # ── Component 2: Source quality (30%) ──────────────────────────────────
    source = SOURCE_QUALITY_MAP.get(
        listing.get("schedule_source", "unknown"), 0.0
    )

    # ── Component 3: Price / schedule certainty (20%) ──────────────────────
    cash_known     = listing.get("seller_cash_required_now") is not None
    overdue_known  = listing.get("known_overdue_amounts") is not None
    schedule_known = schedule_is_complete and not schedule_is_unknown

    if cash_known and overdue_known and schedule_known:
        certainty = 1.0
    elif cash_known and overdue_known and not schedule_is_unknown:
        certainty = 0.7  # partial — schedule present but may be estimated
    elif cash_known:
        certainty = 0.5
    else:
        certainty = 0.0

    # ── Component 4: Duplicate ambiguity (10%) ─────────────────────────────
    dup_score = DUPLICATE_FLAG_MAP.get(
        listing.get("duplicate_flag", "unique"), 1.0
    )

    score = (
        completeness * 0.40 +
        source       * 0.30 +
        certainty    * 0.20 +
        dup_score    * 0.10
    )

    return round(min(1.0, max(0.0, score)), 4)
