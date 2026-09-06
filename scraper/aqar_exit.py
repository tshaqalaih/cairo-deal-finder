"""
Aqar Exit scraper — v3.

Uses the filtered opportunities URL with areas and beds parameters
to fetch only 5th Settlement 3BR+ listings in a single request.
No pagination needed — all target listings fit on one page (~48 unique).
"""
from __future__ import annotations
import hashlib
import logging
import time
import re
from datetime import datetime, timezone
from typing import Generator

import requests

import config
from scraper.parser import parse_detail_page, build_installment_schedule, build_upfront_fees
from db.client import get_listing_by_url

log = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"/(?:en/)?buy/opportunity/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})"
)

# Filtered URL — returns only 5th Settlement listings with 3+ bedrooms
AE_FILTERED_URL = (
    "https://www.aqarexit.com/en/opportunities"
    "?areas=%D8%A7%D9%84%D8%AA%D8%AC%D9%85%D8%B9+%D8%A7%D9%84%D8%AE%D8%A7%D9%85%D8%B3"
    "&beds=3"
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      config.SCRAPER_USER_AGENT,
        "Accept-Language": "ar,en;q=0.9",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "DNT":             "1",
        "Referer":         "https://www.aqarexit.com/en/opportunities",
    })
    return s


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fetch(session: requests.Session, url: str) -> str | None:
    time.sleep(config.SCRAPER_REQUEST_DELAY_S)
    try:
        resp = session.get(url, timeout=config.SCRAPER_TIMEOUT_S)
        if resp.status_code == 403:
            log.warning("403 Forbidden — Cloudflare blocking. URL: %s", url)
            return None
        if resp.status_code != 200:
            log.warning("HTTP %d for %s", resp.status_code, url)
            return None
        return resp.text
    except requests.RequestException as e:
        log.error("Request failed for %s: %s", url, e)
        return None


def scrape_new_cairo_listings(heartbeat_fn=None) -> Generator[dict, None, None]:
    """
    Fetch the filtered 5th Settlement 3BR+ listings page.
    Deduplicate UUIDs, visit each detail page, yield listing records.
    """
    session = _session()
    now_utc = datetime.now(timezone.utc).isoformat()

    log.info("Starting Aqar Exit scrape v3 — filtered URL: 5th Settlement 3BR+")

    # Fetch the filtered listings page
    html = _fetch(session, AE_FILTERED_URL)
    if html is None:
        log.error("Failed to fetch filtered listings page — stopping")
        return

    # Extract unique UUIDs (each appears twice in HTML)
    all_uuids = _UUID_RE.findall(html)
    unique_uuids = list(dict.fromkeys(all_uuids))  # preserves order, deduplicates

    log.info("Filtered page: %d raw UUIDs -> %d unique listings", len(all_uuids), len(unique_uuids))

    for i, uuid in enumerate(unique_uuids):
        detail_url = config.AE_DETAIL_TEMPLATE.format(uuid=uuid)

        # Check if listing already exists and is unchanged
        existing     = get_listing_by_url(detail_url)
        is_new       = existing is None

        # Fetch detail page
        log.info("[%d/%d] %s: %s", i + 1, len(unique_uuids),
                 "NEW" if is_new else "CHECK", uuid)
        detail_html = _fetch(session, detail_url)
        if detail_html is None:
            log.warning("Could not fetch detail: %s", uuid)
            continue

        detail_hash = _sha256(detail_html)

        # Skip if unchanged
        if existing and existing.get("raw_content_hash") == detail_hash:
            log.debug("Unchanged: %s", uuid)
            continue

        if not is_new:
            log.info("CHANGED: %s", uuid)

        parsed       = parse_detail_page(detail_html, detail_url)
        installments = build_installment_schedule(parsed)
        fees         = build_upfront_fees(parsed)

        cash_now  = parsed.get("seller_cash_required_now")
        remaining = parsed.get("remaining_with_developer")
        ae_fee    = parsed.get("aqar_exit_fee_egp", 0) or 0
        total_now = parsed.get("total_required_now_egp")
        upfront   = (cash_now or 0) + ae_fee

        # Check for overdue amounts in the detail HTML
        overdue_amount = None
        overdue_match = re.search(
            r"overdue[^E]*EGP\s*([\d,]+)",
            detail_html, re.IGNORECASE
        )
        if overdue_match:
            overdue_amount = float(overdue_match.group(1).replace(",", ""))
            log.info("Overdue detected: EGP %s", overdue_match.group(1))

        # Extract negotiable and verified flags from detail HTML
        is_negotiable     = bool(re.search(r"Open to negotiation|قابل للتفاوض", detail_html))
        docs_verified     = bool(re.search(r"Documents verified|موثق", detail_html))
        is_featured       = bool(re.search(r"Featured|مميز", detail_html))

        yield {
            # Source
            "source_name":           config.AE_SOURCE_NAME,
            "source_url":            detail_url,
            "advertised_price_text": f"Cash required: EGP {cash_now:,.0f}" if cash_now else None,
            "currency":              "EGP",
            "captured_at":           now_utc,
            "raw_content_hash":      detail_hash,

            # Project / unit
            "project_name_raw":      parsed.get("project_name_raw"),
            "developer_raw":         parsed.get("developer_raw"),
            "location_raw":          parsed.get("location_raw") or "التجمع الخامس",
            "unit_id":               parsed.get("unit_id"),
            "entry_type":            "compound",
            "property_type":         parsed.get("property_type", "unknown"),
            "bedroom_count":         parsed.get("bedroom_count"),
            "bua_sqm":               parsed.get("bua_sqm"),
            "floor_number":          parsed.get("floor_number"),
            "finishing_status":      parsed.get("finishing_status", "not_specified"),
            "finishing_notes":       parsed.get("finishing_notes"),
            "delivery_status":       parsed.get("delivery_status", "not_specified"),
            "delivery_date_raw":     parsed.get("delivery_date_raw"),

            # View / outdoor
            "view_type":             "not_specified",
            "private_garden":        "not_specified",
            "roof_terrace":          "not_specified",
            "parking_included":      "not_specified",

            # Transaction legs
            "seller_cash_required_now":      cash_now,
            "seller_cash_required_confirmed": cash_now is not None,
            "remaining_with_developer":      remaining,
            "installment_amount_egp":        parsed.get("installment_amount_egp"),
            "installment_frequency":         parsed.get("installment_frequency"),
            "installments_remaining_years":  parsed.get("installments_remaining_years"),
            "annual_installment_egp":        parsed.get("annual_installment_egp"),
            "aqar_exit_fee_egp":             ae_fee or None,
            "total_required_now_egp":        total_now,
            "known_overdue_amounts":         overdue_amount if overdue_amount else 0,
            "known_overdue_confirmed":       True,
            "schedule_source":               "developer_statement",
            "schedule_confidence":           "high" if installments else "unknown",

            # Seller
            "seller_type":                   "owner",
            "is_negotiable":                 is_negotiable,
            "documents_verified":            docs_verified,

            # Normalization
            "normalization_status":          "normalized",
            "normalization_model":           "parser_v3",
            "normalization_at":              now_utc,

            # User pipeline
            "user_status":                   "new",
            "eligibility_status":            None,
            "upfront_cash_required":         upfront if cash_now else None,
            "upfront_exceeds_limit":         (upfront > config.MAX_UPFRONT_CASH_EGP) if cash_now else None,
            "duplicate_flag":                "unique",
            "urgency_keywords_detected":     ["negotiable"] if is_negotiable else [],
            "price_reduction_count":         0,
            "multi_broker_count":            1,

            # Timestamps
            "first_seen_at":                 now_utc if is_new else (existing or {}).get("first_seen_at", now_utc),
            "last_seen_at":                  now_utc,

            # Internal keys — stripped by ingest.py before DB upsert
            "_installments":                 installments,
            "_fees":                         fees,
            "_detail_html":                  detail_html,
            "_price_basis_note":             (
                f"Aqar Exit zero-overprice. Cash: EGP {cash_now:,.0f}. "
                f"Remaining: EGP {remaining:,.0f}. Fee: EGP {ae_fee:,.0f}."
                if cash_now and remaining else "Transaction legs incomplete."
            ),
            "_ae_fee":                       ae_fee,
            "_is_new":                       is_new,
        }

        if heartbeat_fn:
            heartbeat_fn()

    log.info("Scrape complete — %d unique listings processed", len(unique_uuids))
