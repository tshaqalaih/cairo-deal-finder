"""
100-point scoring engine — spec Sections 9–15.

Exact sub-weights:
  Value vs comparables    40pts
  Unit quality            20pts  (8 sub-factors)
  Project quality         20pts  (5 sub-factors)
  Payment terms           15pts  (4 sub-factors)
  Seller urgency           5pts

Only clean listings (eligibility_status='eligible') reach the scorer.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

import config

log = logging.getLogger(__name__)


# ── Sub-score dataclasses ─────────────────────────────────────────────────────

@dataclass
class UnitQualityScore:
    type_score:           float = 0.0   # max 3
    size_score:           float = 0.0   # max 3
    bedrooms_score:       float = 0.0   # max 3
    view_score:           float = 0.0   # max 3
    floor_outdoor_score:  float = 0.0   # max 3
    parking_score:        float = 0.0   # max 2
    finishing_score:      float = 0.0   # max 2
    delivery_score:       float = 0.0   # max 1
    total: float = 0.0                  # max 20


@dataclass
class ProjectQualityScore:
    developer_score:      float = 0.0   # max 5
    maturity_score:       float = 0.0   # max 5
    delivery_cred_score:  float = 0.0   # max 4
    liquidity_score:      float = 0.0   # max 3
    location_score:       float = 0.0   # max 3
    total: float = 0.0                  # max 20


@dataclass
class PaymentTermsScore:
    cash_discount_score:  float = 0.0   # max 5
    upfront_burden_score: float = 0.0   # max 4
    monthly_burden_score: float = 0.0   # max 3
    schedule_conf_score:  float = 0.0   # max 3
    total: float = 0.0                  # max 15


@dataclass
class ScoreResult:
    total_score:          int   = 0
    comparables_score:    float = 0.0
    unit_quality:         UnitQualityScore  = field(default_factory=UnitQualityScore)
    project_quality:      ProjectQualityScore = field(default_factory=ProjectQualityScore)
    payment_terms:        PaymentTermsScore  = field(default_factory=PaymentTermsScore)
    urgency_score:        float = 0.0
    reasons:              list[str] = field(default_factory=list)


# ── Main scorer ───────────────────────────────────────────────────────────────

def score(
    listing: dict,
    comparable_result: Any,    # ComparableResult namedtuple
    npv_result: Any,           # CashEquivalentResult namedtuple
    reference_project: dict | None,
) -> ScoreResult:
    """
    Calculate the 100-point score for an eligible listing.
    """
    result = ScoreResult()
    reasons: list[str] = []

    # ── 1. Value vs active asking comparables (40pts) ─────────────────────
    comp_score = _comparables_score(
        comparable_result, npv_result.at_25, reasons
    )
    result.comparables_score = comp_score

    # ── 2. Unit quality (20pts) ───────────────────────────────────────────
    uq = _unit_quality_score(listing, reasons)
    result.unit_quality = uq

    # ── 3. Project quality (20pts) ────────────────────────────────────────
    pq = _project_quality_score(listing, reference_project, reasons)
    result.project_quality = pq

    # ── 4. Payment terms (15pts) ──────────────────────────────────────────
    pt = _payment_terms_score(listing, npv_result, reasons)
    result.payment_terms = pt

    # ── 5. Seller urgency (5pts) ──────────────────────────────────────────
    urg = _urgency_score(listing, reasons)
    result.urgency_score = urg

    total_raw = (
        comp_score
        + uq.total
        + pq.total
        + pt.total
        + urg
    )
    result.total_score = min(100, max(0, round(total_raw)))
    result.reasons = reasons
    return result


# ── Criterion scorers ─────────────────────────────────────────────────────────

def _comparables_score(comp, cash_eq_25, reasons) -> float:
    """
    40 points based on discount to active asking comparable median.
    Scaling: each % below median ≈ 2pts (linear, capped at 40).
    At parity (0% discount): ~20pts.
    """
    if not comp.has_enough or comp.median_cash_eq_25 is None or cash_eq_25 is None:
        reasons.append(f"Comparables: {comp.cluster_count} clusters found (need ≥3) — score 0/40")
        return 0.0

    discount_pct = comp.discount_to_median_pct  # Negative = listing is cheaper

    # Linear scale: -20% below median → 40pts, 0% → 20pts, +20% above → 0pts
    score = 20.0 + (-discount_pct) * 1.0   # 1pt per % below median
    score = max(0.0, min(40.0, score))

    reasons.append(
        f"Comparables: {comp.cluster_count} clusters; "
        f"median EGP {comp.median_cash_eq_25:,.0f}; "
        f"{'below' if discount_pct < 0 else 'above'} median by "
        f"{abs(discount_pct):.1f}% → {score:.1f}/40"
    )
    return round(score, 2)


def _unit_quality_score(listing: dict, reasons: list[str]) -> UnitQualityScore:
    uq = UnitQualityScore()

    # ── Type (max 3) ───────────────────────────────────────────────────────
    ptype = (listing.get("property_type") or "").lower()
    if ptype in ("ivilla", "s_villa"):
        uq.type_score = 3.0
    elif ptype in ("duplex", "quattro", "twinhouse", "townhouse"):
        uq.type_score = 2.0
    else:
        uq.type_score = 1.0
    reasons.append(f"Type {ptype}: {uq.type_score}/3")

    # ── Size (max 3) ────────────────────────────────────────────────────────
    bua = listing.get("bua_sqm") or 0
    if 160 <= bua <= 185:
        uq.size_score = 3.0
    elif 140 <= bua < 160 or 185 < bua <= 220:
        uq.size_score = 2.0
    else:
        uq.size_score = 0.0
    reasons.append(f"Size {bua}sqm: {uq.size_score}/3")

    # ── Bedrooms (max 3) ────────────────────────────────────────────────────
    beds = listing.get("bedroom_count") or 0
    ensuite = listing.get("master_bedroom_ensuite", "not_specified")
    if beds >= 4:
        uq.bedrooms_score = 3.0
    elif beds == 3:
        uq.bedrooms_score = 2.0
    else:
        uq.bedrooms_score = 1.0
    if ensuite == "yes":
        uq.bedrooms_score = min(3.0, uq.bedrooms_score + 0.5)
    reasons.append(f"Bedrooms {beds}BR (ensuite:{ensuite}): {uq.bedrooms_score}/3")

    # ── View (max 3) ────────────────────────────────────────────────────────
    view = listing.get("view_type", "not_specified")
    view_scores = {
        "pool_view": 3.0, "garden_view": 3.0,
        "landscape_view": 3.0, "open_view": 3.0,
        "street_view": 1.0, "not_specified": 0.0,
        "internal_view": 0.0,  # Should be excluded at gate
    }
    uq.view_score = view_scores.get(view, 0.0)
    reasons.append(f"View {view}: {uq.view_score}/3")

    # ── Floor and outdoor space (max 3) ────────────────────────────────────
    floor_raw   = str(listing.get("floor_number") or "").lower()
    roof        = listing.get("roof_terrace", "not_specified")
    garden      = listing.get("private_garden", "not_specified")

    if roof == "yes":
        uq.floor_outdoor_score = 3.0
    elif garden == "yes":
        uq.floor_outdoor_score = 2.0
    elif view in ("open_view", "landscape_view") and floor_raw not in ("ground", "0", "g", ""):
        uq.floor_outdoor_score = 2.0
    else:
        uq.floor_outdoor_score = 1.0
    reasons.append(f"Floor/outdoor (roof:{roof}, garden:{garden}): {uq.floor_outdoor_score}/3")

    # ── Parking (max 2) ─────────────────────────────────────────────────────
    parking = listing.get("parking_included", "not_specified")
    if parking == "yes":
        uq.parking_score = 2.0
    elif parking == "separate_cost":
        uq.parking_score = 1.0
    else:
        uq.parking_score = 0.0
    reasons.append(f"Parking {parking}: {uq.parking_score}/2")

    # ── Finishing (max 2) ───────────────────────────────────────────────────
    finishing = listing.get("finishing_status", "not_specified")
    finishing_scores = {
        "fully_finished": 2.0, "semi_finished": 1.0,
        "core_and_shell": 0.0, "not_specified": 0.0,
    }
    uq.finishing_score = finishing_scores.get(finishing, 0.0)
    reasons.append(f"Finishing {finishing}: {uq.finishing_score}/2")

    # ── Delivery status (max 1) ──────────────────────────────────────────────
    delivery = listing.get("delivery_status", "not_specified")
    delivery_scores = {
        "ready_to_move": 1.0, "delivered_not_finished": 0.5,
        "under_construction": 0.0, "not_specified": 0.0,
    }
    uq.delivery_score = delivery_scores.get(delivery, 0.0)
    reasons.append(f"Delivery {delivery}: {uq.delivery_score}/1")

    uq.total = round(
        uq.type_score + uq.size_score + uq.bedrooms_score + uq.view_score
        + uq.floor_outdoor_score + uq.parking_score + uq.finishing_score
        + uq.delivery_score, 2
    )
    reasons.append(f"Unit quality total: {uq.total}/20")
    return uq


def _project_quality_score(
    listing: dict,
    ref: dict | None,
    reasons: list[str],
) -> ProjectQualityScore:
    pq = ProjectQualityScore()

    maturity = (ref.get("project_maturity") if ref else None) or "unknown"
    liquidity = (ref.get("liquidity_tier") if ref else None) or "unknown"
    rw_nw = (ref.get("ring_road_nw_access") if ref else None) or "unknown"
    s90   = (ref.get("southern_90th_proximity") if ref else None) or "unknown"

    # ── Developer track record (max 5) ─────────────────────────────────────
    dev_known = ref is not None and ref.get("developer")
    if dev_known:
        # Basic heuristic: established projects = trusted developer
        if maturity == "established":
            pq.developer_score = 5.0
        elif maturity == "emerging":
            pq.developer_score = 3.0
        else:
            pq.developer_score = 2.0
    else:
        pq.developer_score = 2.0   # Unknown developer = uncertain
    reasons.append(f"Developer track record: {pq.developer_score}/5")

    # ── Project maturity / community life (max 5) ─────────────────────────
    maturity_scores = {"established": 5.0, "emerging": 3.0, "new_standalone": 0.0, "unknown": 2.0}
    pq.maturity_score = maturity_scores.get(maturity, 2.0)
    reasons.append(f"Project maturity ({maturity}): {pq.maturity_score}/5")

    # ── Delivery credibility (max 4) ───────────────────────────────────────
    delivery = listing.get("delivery_status", "not_specified")
    if delivery == "ready_to_move":
        pq.delivery_cred_score = 4.0
    elif delivery == "delivered_not_finished":
        pq.delivery_cred_score = 3.0
    elif delivery == "under_construction" and maturity == "established":
        pq.delivery_cred_score = 3.0   # Established developer = higher credibility
    elif delivery == "under_construction":
        pq.delivery_cred_score = 1.5
    else:
        pq.delivery_cred_score = 1.0
    reasons.append(f"Delivery credibility: {pq.delivery_cred_score}/4")

    # ── Resale liquidity (max 3) ───────────────────────────────────────────
    liq_scores = {"high": 3.0, "medium": 2.0, "low": 1.0, "unknown": 1.5}
    pq.liquidity_score = liq_scores.get(liquidity, 1.5)
    reasons.append(f"Liquidity ({liquidity}): {pq.liquidity_score}/3")

    # ── Location within 5th Settlement (max 3) ────────────────────────────
    # Score based on Ring Road NW access + Southern 90th proximity
    loc_map = {"high": 1.5, "medium": 1.0, "low": 0.5, "unknown": 0.5}
    rw_score = loc_map.get(rw_nw, 0.5)
    s90_score = loc_map.get(s90, 0.5)
    pq.location_score = min(3.0, rw_score + s90_score)
    reasons.append(
        f"Location (RW NW:{rw_nw}, S90:{s90}): {pq.location_score}/3"
    )

    pq.total = round(
        pq.developer_score + pq.maturity_score + pq.delivery_cred_score
        + pq.liquidity_score + pq.location_score, 2
    )
    reasons.append(f"Project quality total: {pq.total}/20")
    return pq


def _payment_terms_score(listing: dict, npv, reasons: list[str]) -> PaymentTermsScore:
    pt = PaymentTermsScore()

    cash_now   = listing.get("seller_cash_required_now") or 0
    cash_eq_25 = npv.at_25 or 0
    freq       = listing.get("installment_frequency", "unknown")
    years_rem  = listing.get("installments_remaining_years") or 0
    sched_src  = listing.get("schedule_source", "unknown")

    # ── Cash discount (max 5) — how much of the deal is cash-efficient ─────
    # Is there any developer installment at all?
    has_installments = (listing.get("remaining_with_developer") or 0) > 0
    if not has_installments:
        pt.cash_discount_score = 5.0
        reasons.append("Payment: full cash (no developer installments): 5/5")
    elif years_rem <= 1:
        pt.cash_discount_score = 4.0
    elif years_rem <= 1.5:
        pt.cash_discount_score = 3.0
    elif years_rem <= 3:
        pt.cash_discount_score = 2.0
    else:
        pt.cash_discount_score = 1.0
    reasons.append(f"Cash discount (remaining ~{years_rem}y): {pt.cash_discount_score}/5")

    # ── Upfront burden (max 4) — seller cash as % of total ────────────────
    if cash_eq_25 > 0 and cash_now >= 0:
        upfront_pct = cash_now / cash_eq_25
        if upfront_pct <= 0.20:
            pt.upfront_burden_score = 4.0
        elif upfront_pct <= 0.35:
            pt.upfront_burden_score = 3.0
        elif upfront_pct <= 0.50:
            pt.upfront_burden_score = 2.0
        else:
            pt.upfront_burden_score = 1.0
    else:
        pt.upfront_burden_score = 1.0
    reasons.append(f"Upfront burden: {pt.upfront_burden_score}/4")

    # ── Monthly/quarterly burden (max 3) ──────────────────────────────────
    annual_inst = listing.get("annual_installment_egp") or 0
    if annual_inst == 0 and not has_installments:
        pt.monthly_burden_score = 3.0
    elif annual_inst > 0 and cash_eq_25 > 0:
        burden_pct = annual_inst / cash_eq_25
        if burden_pct <= 0.08:
            pt.monthly_burden_score = 3.0
        elif burden_pct <= 0.15:
            pt.monthly_burden_score = 2.0
        else:
            pt.monthly_burden_score = 1.0
    else:
        pt.monthly_burden_score = 0.0
    reasons.append(f"Payment burden: {pt.monthly_burden_score}/3")

    # ── Schedule confidence (max 3) ────────────────────────────────────────
    conf_scores = {
        "developer_statement": 3.0, "seller_claim": 2.0,
        "listing_text": 1.0, "unknown": 0.0,
    }
    pt.schedule_conf_score = conf_scores.get(sched_src, 0.0)
    reasons.append(f"Schedule confidence ({sched_src}): {pt.schedule_conf_score}/3")

    pt.total = round(
        pt.cash_discount_score + pt.upfront_burden_score
        + pt.monthly_burden_score + pt.schedule_conf_score, 2
    )
    reasons.append(f"Payment terms total: {pt.total}/15")
    return pt


def _urgency_score(listing: dict, reasons: list[str]) -> float:
    """
    5 points — signal only, never primary ranking factor.
    Based on: price reductions, multi-broker count, urgency keywords,
    listing age, negotiability.
    """
    score = 0.0

    if listing.get("is_negotiable"):
        score += 1.5
    if listing.get("price_reduction_count", 0) >= 1:
        score += 1.5
    keywords = listing.get("urgency_keywords_detected") or []
    if keywords:
        score += 1.0
    if listing.get("multi_broker_count", 1) > 1:
        score += 0.5

    score = min(5.0, score)
    reasons.append(f"Urgency signals: {score}/5 (signal only)")
    return round(score, 2)
