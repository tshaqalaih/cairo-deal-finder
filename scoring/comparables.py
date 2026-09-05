"""
Comparable cluster engine — spec Section 16.

Finds listings that are likely the same unit listed by different brokers
(for cross-broker dedup) and finds comparable units for valuation.

Key rules from spec:
  • Same unit across brokers → cluster as ONE comparable (not N)
  • Minimum 3 comparable CLUSTERS required (not 3 raw listings)
  • Comparison hierarchy: project → phase → type → size ±15sqm
    → delivery → finishing → view type
  • Results labelled "active asking comparables" — never "market value"
"""
from __future__ import annotations
import logging
from typing import NamedTuple

from db.client import get

log = logging.getLogger(__name__)


class ComparableResult(NamedTuple):
    cluster_count: int          # Number of distinct comparable clusters
    median_cash_eq_25: float | None
    discount_to_median_pct: float | None   # Negative = listing is cheaper
    comparables: list[dict]     # Summary of clusters used
    has_enough: bool            # True if cluster_count >= 3


def find(
    listing: dict,
    cash_eq_25: float | None,
) -> ComparableResult:
    """
    Find comparable listings from Supabase.
    Returns ComparableResult with cluster-deduplicated median.
    """
    if cash_eq_25 is None:
        return ComparableResult(0, None, None, [], False)

    project = (listing.get("project_name_raw") or "").strip()
    ptype   = listing.get("property_type", "unknown")
    bua     = listing.get("bua_sqm") or 0
    beds    = listing.get("bedroom_count")

    if not project:
        return ComparableResult(0, None, None, [], False)

    db = get()

    # ── Query eligible listings with similar characteristics ───────────────
    # Expand search hierarchy per spec: start narrow, widen if needed
    comparables = []

    for size_tolerance in (15, 30):     # Try tight then wider
        try:
            resp = (
                db.table("listings")
                .select(
                    "id, source_url, project_name_raw, property_type, "
                    "bua_sqm, finishing_status, delivery_status, view_type, "
                    "bedroom_count, latest_cash_equivalent_25, "
                    "duplicate_cluster_id, duplicate_flag"
                )
                .eq("eligibility_status", "eligible")
                .ilike("project_name_raw", f"%{project[:20]}%")
                .eq("property_type", ptype)
                .gte("bua_sqm", bua - size_tolerance)
                .lte("bua_sqm", bua + size_tolerance)
                .not_.is_("latest_cash_equivalent_25", "null")
                .neq("source_url", listing.get("source_url", ""))  # Exclude self
                .limit(50)
                .execute()
            )
            comparables = resp.data or []
        except Exception as e:
            log.error("Comparable query failed: %s", e)
            comparables = []

        if len(comparables) >= 3:
            break

    if not comparables:
        return ComparableResult(0, None, None, [], False)

    # ── Cluster deduplication ──────────────────────────────────────────────
    # Group listings suspected to be the same unit
    # Count each cluster as ONE comparable (not N)
    clusters: dict[str, list[dict]] = {}  # cluster_key → [listings]

    for comp in comparables:
        cluster_id = comp.get("duplicate_cluster_id")
        if cluster_id:
            key = str(cluster_id)
        else:
            # No cluster assigned — treat as its own cluster
            key = comp["id"]
        clusters.setdefault(key, []).append(comp)

    # ── Pick cluster representative (median price within cluster) ──────────
    cluster_representatives: list[dict] = []
    for key, members in clusters.items():
        prices = [
            m["latest_cash_equivalent_25"]
            for m in members
            if m.get("latest_cash_equivalent_25")
        ]
        if not prices:
            continue
        prices.sort()
        median_price = prices[len(prices) // 2]
        rep = members[0].copy()
        rep["cluster_median_25"] = median_price
        rep["cluster_size"]      = len(members)
        cluster_representatives.append(rep)

    cluster_count = len(cluster_representatives)
    if cluster_count == 0:
        return ComparableResult(0, None, None, [], False)

    # ── Overall comparable median ──────────────────────────────────────────
    all_prices = sorted(r["cluster_median_25"] for r in cluster_representatives)
    overall_median = all_prices[len(all_prices) // 2]

    # ── Discount to median ─────────────────────────────────────────────────
    discount_pct = None
    if overall_median and overall_median > 0:
        discount_pct = round(
            (cash_eq_25 - overall_median) / overall_median * 100, 1
        )   # Negative = listing is cheaper than comparables

    # ── Build summary for report ───────────────────────────────────────────
    summary = [
        {
            "project":        r.get("project_name_raw"),
            "type":           r.get("property_type"),
            "bua_sqm":        r.get("bua_sqm"),
            "finishing":      r.get("finishing_status"),
            "view":           r.get("view_type"),
            "cluster_size":   r.get("cluster_size", 1),
            "median_price_25": r.get("cluster_median_25"),
        }
        for r in cluster_representatives[:10]  # Cap report at 10
    ]

    return ComparableResult(
        cluster_count=cluster_count,
        median_cash_eq_25=round(overall_median, 2),
        discount_to_median_pct=discount_pct,
        comparables=summary,
        has_enough=cluster_count >= 3,
    )
