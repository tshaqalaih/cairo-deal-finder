"""
Scoring pipeline stage.

For every eligible listing:
  1. Fetch child table records (installments, fees, recurring costs)
  2. Calculate cash-equivalent (NPV) at 20/25/30%
  3. Calculate data confidence
  4. Run eligibility gates
  5. Find comparables
  6. Calculate 100-point score
  7. Check Best Deal Stage 1 conditions
  8. Write scoring_run record
  9. Update listings table with latest scores
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime
import pytz

import config
from pipeline import run_lock
from scoring import npv as npv_mod
from scoring import confidence as conf_mod
from scoring import gates as gates_mod
from scoring import comparables as comp_mod
from scoring import scorer as scorer_mod
from db.client import get, get_reference_projects

log = logging.getLogger(__name__)

SCORING_MODEL_VERSION = "v1.0"


def _cairo_date() -> str:
    return datetime.now(pytz.timezone("Africa/Cairo")).strftime("%Y-%m-%d")


def _load_reference_lookup() -> tuple[dict, set, set]:
    """Load reference projects, blacklists, red-flags from DB."""
    db = get()

    projects = get_reference_projects()
    ref_lookup = {p["project_name"]: p for p in projects}

    blacklist_resp = (
        db.table("developer_blacklist")
        .select("developer_name, known_aliases")
        .eq("status", "active")
        .execute()
    )
    blacklist: set[str] = set()
    for row in (blacklist_resp.data or []):
        blacklist.add((row["developer_name"] or "").lower())
        for alias in (row.get("known_aliases") or []):
            blacklist.add((alias or "").lower())

    red_flag_resp = (
        db.table("project_red_flags")
        .select("project_name")
        .eq("status", "active")
        .execute()
    )
    red_flags: set[str] = {
        (r["project_name"] or "").lower()
        for r in (red_flag_resp.data or [])
    }

    return ref_lookup, blacklist, red_flags


def _fetch_child_records(db, listing_id: str) -> tuple[list, list, list]:
    """Fetch installments, upfront fees, recurring costs for a listing."""
    installments = (
        db.table("installment_schedules")
        .select("*")
        .eq("listing_id", listing_id)
        .order("payment_number")
        .execute()
    ).data or []

    fees = (
        db.table("upfront_transaction_fees")
        .select("*")
        .eq("listing_id", listing_id)
        .execute()
    ).data or []

    recurring = (
        db.table("recurring_ownership_costs")
        .select("*")
        .eq("listing_id", listing_id)
        .execute()
    ).data or []

    return installments, fees, recurring


def _write_scoring_run(db, listing_id: str, result: dict) -> None:
    db.table("scoring_runs").insert({
        "listing_id":           listing_id,
        "scored_at":            datetime.now(pytz.utc).isoformat(),
        "scoring_model_version": SCORING_MODEL_VERSION,
        **result,
    }).execute()


def _update_listing(db, listing_id: str, update: dict) -> None:
    db.table("listings").update(update).eq("id", listing_id).execute()


def _find_reference_project(project_name: str, ref_lookup: dict) -> dict | None:
    if not project_name:
        return None
    name_lower = project_name.lower()
    for canonical, rec in ref_lookup.items():
        if canonical.lower() in name_lower or name_lower in canonical.lower():
            return rec
        aliases = rec.get("known_aliases") or []
        if any((a or "").lower() in name_lower for a in aliases):
            return rec
    return None


def run() -> None:
    local_date = _cairo_date()
    stage      = "scoring"
    run_id: str | None = None

    log.info("Scoring stage — local date: %s", local_date)

    try:
        run_id = run_lock.acquire(local_date, stage)
    except run_lock.LockAcquireError as e:
        log.info("Lock not acquired: %s", e)
        sys.exit(0)

    db = get()
    scored = skipped = errors = 0

    try:
        # ── Load reference data once ────────────────────────────────────────
        ref_lookup, blacklist, red_flags = _load_reference_lookup()
        log.info(
            "Reference data: %d projects, %d blacklisted devs, %d red-flag projects",
            len(ref_lookup), len(blacklist), len(red_flags),
        )

        # ── Fetch all listings that need scoring ────────────────────────────
        # Score listings that are new, changed, or haven't been scored today
        resp = (
            db.table("listings")
            .select("*")
            .eq("normalization_status", "normalized")
            .limit(500)
            .execute()
        )
        listings = resp.data or []
        log.info("Scoring %d listings", len(listings))

        for listing in listings:
            try:
                _score_listing(
                    db, listing, ref_lookup, blacklist, red_flags
                )
                scored += 1
                if scored % 20 == 0:
                    run_lock.heartbeat(local_date, stage, run_id)
            except Exception as e:
                log.error("Scoring failed for %s: %s", listing.get("id"), e)
                errors += 1

        log.info("Scoring complete — scored: %d, skipped: %d, errors: %d",
                 scored, skipped, errors)
        run_lock.complete(local_date, stage, run_id)

    except Exception as e:
        log.exception("Scoring stage failed: %s", e)
        if run_id:
            run_lock.fail(local_date, stage, run_id, str(e))
        sys.exit(1)


def _score_listing(db, listing: dict, ref_lookup, blacklist, red_flags) -> None:
    listing_id = listing["id"]

    # ── Fetch child records ─────────────────────────────────────────────────
    installments, fees, recurring = _fetch_child_records(db, listing_id)

    schedule_is_unknown = (
        not installments
        and (listing.get("remaining_with_developer") or 0) > 0
        and listing.get("schedule_confidence") == "unknown"
    )

    # ── NPV calculation ─────────────────────────────────────────────────────
    npv_result = npv_mod.calculate(
        seller_cash_required_now   = listing.get("seller_cash_required_now"),
        installment_schedules      = installments,
        upfront_transaction_fees   = fees,
        known_overdue_amounts      = listing.get("known_overdue_amounts"),
        recurring_ownership_costs  = recurring,
        schedule_is_unknown        = schedule_is_unknown,
    )

    # ── Data confidence ─────────────────────────────────────────────────────
    confidence = conf_mod.calculate(
        listing              = listing,
        schedule_is_complete = bool(installments),
        schedule_is_unknown  = schedule_is_unknown,
    )

    # ── Eligibility gates ───────────────────────────────────────────────────
    ref_project = _find_reference_project(
        listing.get("project_name_raw", ""), ref_lookup
    )
    status, gate_reason = gates_mod.check(
        listing             = listing,
        npv_at_25           = npv_result.at_25,
        upfront_cash        = npv_result.upfront_cash,
        schedule_is_unknown = schedule_is_unknown,
        data_confidence     = confidence,
        developer_blacklist = blacklist,
        project_red_flags   = red_flags,
        reference_projects  = ref_lookup,
    )

    # ── Common update fields ────────────────────────────────────────────────
    listing_update: dict = {
        "eligibility_status":         status,
        "exclusion_reason":           gate_reason if status != "eligible" else None,
        "latest_data_confidence":     confidence,
        "latest_cash_equivalent_20":  npv_result.at_20,
        "latest_cash_equivalent_25":  npv_result.at_25,
        "latest_cash_equivalent_30":  npv_result.at_30,
        "latest_annual_ownership_cost": npv_result.annual_ownership_cost,
        "upfront_cash_required":      npv_result.upfront_cash,
        "upfront_exceeds_limit": (
            npv_result.upfront_cash > config.MAX_UPFRONT_CASH_EGP
            if npv_result.upfront_cash else None
        ),
    }

    scoring_record: dict = {
        "eligibility_status":    status,
        "exclusion_reason":      gate_reason if status != "eligible" else None,
        "data_confidence_score": confidence,
        "cash_equivalent_20":    npv_result.at_20,
        "cash_equivalent_25":    npv_result.at_25,
        "cash_equivalent_30":    npv_result.at_30,
        "annual_ownership_cost": npv_result.annual_ownership_cost,
        "upfront_cash_required": npv_result.upfront_cash,
        "upfront_exceeds_limit": listing_update["upfront_exceeds_limit"],
    }

    if status != "eligible":
        # Not eligible — write scoring run with gate result only
        _update_listing(db, listing_id, listing_update)
        _write_scoring_run(db, listing_id, scoring_record)
        log.debug("%s → %s: %s", listing_id[:8], status, gate_reason[:60])
        return

    # ── Comparables ─────────────────────────────────────────────────────────
    comp_result = comp_mod.find(listing, npv_result.at_25)

    # ── 100-point score ─────────────────────────────────────────────────────
    score_result = scorer_mod.score(
        listing            = listing,
        comparable_result  = comp_result,
        npv_result         = npv_result,
        reference_project  = ref_project,
    )

    # ── Best Deal Stage 1 check ─────────────────────────────────────────────
    stage1_eligible, stage1_failures = _check_stage1(
        score_result, comp_result, npv_result, confidence, listing
    )

    # ── Update listing with full scores ────────────────────────────────────
    listing_update["latest_score"] = score_result.total_score
    _update_listing(db, listing_id, listing_update)

    # ── Write full scoring run ──────────────────────────────────────────────
    scoring_record.update({
        "total_score":            score_result.total_score,
        "comparables_score":      score_result.comparables_score,
        "unit_quality_score":     score_result.unit_quality.total,
        "project_quality_score":  score_result.project_quality.total,
        "payment_terms_score":    score_result.payment_terms.total,
        "urgency_score":          score_result.urgency_score,
        # Unit sub-scores
        "uq_type_score":          score_result.unit_quality.type_score,
        "uq_size_score":          score_result.unit_quality.size_score,
        "uq_bedrooms_score":      score_result.unit_quality.bedrooms_score,
        "uq_view_score":          score_result.unit_quality.view_score,
        "uq_floor_outdoor_score": score_result.unit_quality.floor_outdoor_score,
        "uq_parking_score":       score_result.unit_quality.parking_score,
        "uq_finishing_score":     score_result.unit_quality.finishing_score,
        "uq_delivery_score":      score_result.unit_quality.delivery_score,
        # Project sub-scores
        "pq_developer_score":     score_result.project_quality.developer_score,
        "pq_maturity_score":      score_result.project_quality.maturity_score,
        "pq_delivery_cred_score": score_result.project_quality.delivery_cred_score,
        "pq_liquidity_score":     score_result.project_quality.liquidity_score,
        "pq_location_score":      score_result.project_quality.location_score,
        # Payment sub-scores
        "pt_cash_discount_score": score_result.payment_terms.cash_discount_score,
        "pt_upfront_burden_score": score_result.payment_terms.upfront_burden_score,
        "pt_monthly_burden_score": score_result.payment_terms.monthly_burden_score,
        "pt_schedule_conf_score": score_result.payment_terms.schedule_conf_score,
        # Comparables
        "comparable_cluster_count": comp_result.cluster_count,
        "comparable_median_25":   comp_result.median_cash_eq_25,
        "discount_to_median_pct": comp_result.discount_to_median_pct,
        # Stage 1
        "stage1_eligible":        stage1_eligible,
        "stage1_failure_reasons": stage1_failures,
        # Confidence sub-components
        "dc_field_completeness":  None,  # Populated by confidence module internals
        "dc_source_quality":      None,
        "dc_price_certainty":     None,
        "dc_duplicate_ambiguity": None,
    })
    _write_scoring_run(db, listing_id, scoring_record)

    log.info(
        "%s → score %d/100 (Stage1:%s) | %s %s",
        listing_id[:8],
        score_result.total_score,
        "✓" if stage1_eligible else "✗",
        listing.get("project_name_raw", "")[:25],
        f"EGP {npv_result.at_25:,.0f}" if npv_result.at_25 else "",
    )


def _check_stage1(
    score_result, comp_result, npv_result, confidence, listing
) -> tuple[bool, list[str]]:
    """
    Check Best Deal Stage 1 conditions — spec Section 14.
    Returns (is_eligible, list_of_failure_reasons).
    All conditions must pass.
    """
    failures = []

    if score_result.total_score < 80:
        failures.append(f"Score {score_result.total_score}/100 < 80")

    if confidence < 0.85:
        failures.append(f"Data confidence {confidence:.0%} < 85%")

    if not comp_result.has_enough:
        failures.append(f"Only {comp_result.cluster_count} comparable clusters (need ≥3)")

    if comp_result.discount_to_median_pct is not None:
        if comp_result.discount_to_median_pct > -10.0:
            failures.append(
                f"Discount {comp_result.discount_to_median_pct:.1f}% "
                "does not reach -10% below comparable median"
            )
    else:
        failures.append("Cannot calculate discount to comparable median")

    if not npv_result.is_complete:
        failures.append(f"Missing transaction legs: {', '.join(npv_result.missing_legs)}")

    upfront = npv_result.upfront_cash
    if upfront and upfront > config.MAX_UPFRONT_CASH_EGP:
        failures.append(
            f"Upfront cash EGP {upfront:,.0f} exceeds EGP {config.MAX_UPFRONT_CASH_EGP:,.0f} limit"
        )

    return len(failures) == 0, failures
