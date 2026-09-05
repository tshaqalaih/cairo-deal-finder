"""
Fetches the data needed for the daily report from Supabase.
Returns structured dicts ready for formatting.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
import pytz

from db.client import get
import config

log = logging.getLogger(__name__)

CAIRO_TZ = pytz.timezone("Africa/Cairo")


def fetch_report_data() -> dict:
    """
    Returns a dict with:
      top10       — top 10 eligible listings by score
      leads       — top 3 high-potential leads (Stage 1 eligible if any)
      needs_data  — listings in needs-data queue (up to 10)
      run_date    — Cairo date string
      total_eligible — count of all eligible listings in DB
    """
    db     = get()
    now    = datetime.now(CAIRO_TZ)
    today  = now.strftime("%Y-%m-%d")

    # ── Top 10 eligible by score ───────────────────────────────────────────
    top10_resp = (
        db.table("listings")
        .select(
            "id, source_url, project_name_raw, developer_raw, location_raw, "
            "property_type, bedroom_count, bua_sqm, floor_number, "
            "view_type, finishing_status, delivery_status, delivery_date_raw, "
            "seller_cash_required_now, remaining_with_developer, "
            "installment_amount_egp, installment_frequency, "
            "installments_remaining_years, annual_installment_egp, "
            "aqar_exit_fee_egp, total_required_now_egp, "
            "latest_score, latest_data_confidence, "
            "latest_cash_equivalent_20, latest_cash_equivalent_25, latest_cash_equivalent_30, "
            "latest_annual_ownership_cost, upfront_cash_required, upfront_exceeds_limit, "
            "is_negotiable, documents_verified, unit_id, "
            "urgency_keywords_detected, price_reduction_count"
        )
        .eq("eligibility_status", "eligible")
        .not_.is_("latest_score", "null")
        .order("latest_score", desc=True)
        .limit(10)
        .execute()
    )
    top10 = top10_resp.data or []

    # ── Enrich with latest scoring run (for reasons + comparables) ─────────
    for listing in top10:
        _enrich_with_scoring_run(db, listing)

    # ── Top 3 leads: Stage 1 eligible first, then by score ─────────────────
    # Find Stage 1 eligible listings
    stage1_resp = (
        db.table("scoring_runs")
        .select("listing_id")
        .eq("stage1_eligible", True)
        .order("scored_at", desc=True)
        .limit(100)
        .execute()
    )
    stage1_ids = {r["listing_id"] for r in (stage1_resp.data or [])}

    # Mark listings as stage1 eligible
    stage1_leads = [l for l in top10 if l["id"] in stage1_ids]
    non_stage1   = [l for l in top10 if l["id"] not in stage1_ids]

    # Top 3: prefer Stage 1 eligible, fill with highest scored
    leads = (stage1_leads + non_stage1)[:3]
    for lead in leads:
        lead["is_stage1_eligible"] = lead["id"] in stage1_ids
        lead["label"] = "Verified Best Deal" if lead["is_stage1_eligible"] else "High-Potential Lead"

    # ── Needs-data queue ───────────────────────────────────────────────────
    needs_resp = (
        db.table("listings")
        .select(
            "id, source_url, project_name_raw, property_type, bedroom_count, "
            "bua_sqm, seller_cash_required_now, exclusion_reason, unit_id"
        )
        .eq("eligibility_status", "needs_data")
        .order("last_seen_at", desc=True)
        .limit(10)
        .execute()
    )
    needs_data = needs_resp.data or []

    # ── Total eligible count ───────────────────────────────────────────────
    count_resp = (
        db.table("listings")
        .select("id", count="exact")
        .eq("eligibility_status", "eligible")
        .execute()
    )
    total_eligible = count_resp.count or 0

    return {
        "top10":         top10,
        "leads":         leads,
        "needs_data":    needs_data,
        "run_date":      today,
        "run_datetime":  now.strftime("%d %b %Y, %H:%M Cairo time"),
        "total_eligible": total_eligible,
    }


def _enrich_with_scoring_run(db, listing: dict) -> None:
    """Attach the latest scoring run details to a listing dict."""
    resp = (
        db.table("scoring_runs")
        .select(
            "total_score, comparables_score, unit_quality_score, "
            "project_quality_score, payment_terms_score, urgency_score, "
            "comparable_cluster_count, comparable_median_25, discount_to_median_pct, "
            "stage1_eligible, stage1_failure_reasons, data_confidence_score"
        )
        .eq("listing_id", listing["id"])
        .eq("eligibility_status", "eligible")
        .order("scored_at", desc=True)
        .limit(1)
        .execute()
    )
    run = (resp.data or [{}])[0]
    listing["_scoring"] = run
