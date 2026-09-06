"""
Aqar Exit scraper — v2.
Fetches /en/opportunities, finds 5th Settlement listings by UUID proximity to location text.
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

# UUIDs that appear in site-wide nav/footer on every page — skip them
_GLOBAL_UUIDS = {
    "3a7b175a-6932-40b7-af3a-099b06f2451e",
}


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


def _extract_target_uuids(html: str) -> list[tuple[str, str]]:
    """
    Find UUIDs for listings in target locations.
    Finds location text first, then locates nearest UUID within 50000 chars.
    """
    results = []
    seen: set[str] = set(_GLOBAL_UUIDS)

    location_positions = []
    for target in config.TARGET_LOCATIONS:
        for m in re.finditer(re.escape(target), html):
            location_positions.append(m.start())

    if not location_positions:
        return []

    uuid_positions = [(m.start(), m.group(1)) for m in _UUID_RE.finditer(html)]

    for loc_pos in location_positions:
        context_start = max(0, loc_pos - 25000)
        context_end   = min(len(html), loc_pos + 25000)

        best_uuid = None
        best_dist = 999999

        for upos, uuid in uuid_positions:
            if uuid in seen:
                continue
            if context_start <= upos <= context_end:
                dist = abs(upos - loc_pos)
                if dist < best_dist:
                    best_dist = dist
                    best_uuid = uuid

        if best_uuid and best_uuid not in seen:
            seen.add(best_uuid)
            context = html[context_start:context_end]
            results.append((best_uuid, context))

    log.info("Found %d target location occurrences -> %d unique UUIDs",
             len(location_positions), len(results))
    return results


def scrape_new_cairo_listings(heartbeat_fn=None) -> Generator[dict, None, None]:
    session = _session()
    page    = 1
    now_utc = datetime.now(timezone.utc).isoformat()
    oos_streak = 0

    log.info("Starting Aqar Exit scrape v2 — target: 5th Settlement / New Cairo")

    while page <= config.SCRAPER_MAX_PAGES:
        page_url = config.AE_OPPORTUNITIES if page == 1 else f"{config.AE_OPPORTUNITIES}?page={page}"
        log.info("Fetching page %d: %s", page, page_url)

        time.sleep(config.SCRAPER_REQUEST_DELAY_S)
        try:
            resp = session.get(page_url, timeout=config.SCRAPER_TIMEOUT_S)
        except Exception as e:
            log.error("Request failed: %s", e)
            break

        if resp.status_code == 403:
            log.warning("403 Forbidden — stopping")
            break
        if resp.status_code != 200:
            log.warning("HTTP %d — stopping", resp.status_code)
            break

        html = resp.text
        all_uuids = len(_UUID_RE.findall(html))

        if all_uuids == 0:
            log.info("No listings on page %d — end of pages", page)
            break

        target_items = _extract_target_uuids(html)
        log.info("Page %d: %d total, %d target", page, all_uuids, len(target_items))

        if not target_items:
            oos_streak += 1
            if oos_streak >= 5 and page >= 2:
                log.info("OOS limit reached — stopping")
                break
        else:
            oos_streak = 0

        for uuid, context in target_items:
            detail_url = config.AE_DETAIL_TEMPLATE.format(uuid=uuid)

            existing = get_listing_by_url(detail_url)
            context_hash = _sha256(context)
            if existing and existing.get("raw_content_hash") == context_hash:
                log.debug("Unchanged: %s", uuid)
                continue

            is_new = existing is None
            log.info("%s: %s", "NEW" if is_new else "CHANGED", uuid)

            time.sleep(config.SCRAPER_REQUEST_DELAY_S)
            try:
                detail_resp = session.get(detail_url, timeout=config.SCRAPER_TIMEOUT_S)
                detail_html = detail_resp.text if detail_resp.status_code == 200 else ""
            except Exception as e:
                log.warning("Detail fetch failed: %s", e)
                continue

            parsed       = parse_detail_page(detail_html, detail_url)
            installments = build_installment_schedule(parsed)
            fees         = build_upfront_fees(parsed)

            location_raw = None
            for target in config.TARGET_LOCATIONS:
                idx = context.find(target)
                if idx >= 0:
                    location_raw = target
                    break

            cash_now  = parsed.get("seller_cash_required_now")
            remaining = parsed.get("remaining_with_developer")
            ae_fee    = parsed.get("aqar_exit_fee_egp", 0) or 0
            total_now = parsed.get("total_required_now_egp")
            upfront   = (cash_now or 0) + ae_fee

            yield {
                "source_name":           config.AE_SOURCE_NAME,
                "source_url":            detail_url,
                "advertised_price_text": f"Cash required: EGP {cash_now:,.0f}" if cash_now else None,
                "currency":              "EGP",
                "captured_at":           now_utc,
                "raw_content_hash":      _sha256(detail_html),
                "project_name_raw":      parsed.get("project_name_raw"),
                "developer_raw":         parsed.get("developer_raw"),
                "location_raw":          location_raw or parsed.get("location_raw"),
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
                "view_type":             "not_specified",
                "private_garden":        "not_specified",
                "roof_terrace":          "not_specified",
                "parking_included":      "not_specified",
                "seller_cash_required_now":     cash_now,
                "seller_cash_required_confirmed": cash_now is not None,
                "remaining_with_developer":     remaining,
                "installment_amount_egp":       parsed.get("installment_amount_egp"),
                "installment_frequency":        parsed.get("installment_frequency"),
                "installments_remaining_years": parsed.get("installments_remaining_years"),
                "annual_installment_egp":       parsed.get("annual_installment_egp"),
                "aqar_exit_fee_egp":            ae_fee or None,
                "total_required_now_egp":       total_now,
                "known_overdue_amounts":        0,
                "known_overdue_confirmed":      True,
                "schedule_source":              "developer_statement",
                "schedule_confidence":          "high" if installments else "unknown",
                "seller_type":                  "owner",
                "is_negotiable":                bool(re.search(r"Open to negotiation|قابل للتفاوض", context)),
                "documents_verified":           bool(re.search(r"Documents verified|موثق", context)),
                "normalization_status":         "normalized",
                "normalization_model":          "parser_v2",
                "normalization_at":             now_utc,
                "user_status":                  "new",
                "eligibility_status":           None,
                "upfront_cash_required":        upfront if cash_now else None,
                "upfront_exceeds_limit":        upfront > config.MAX_UPFRONT_CASH_EGP if cash_now else None,
                "duplicate_flag":               "unique",
                "urgency_keywords_detected":    [],
                "price_reduction_count":        0,
                "multi_broker_count":           1,
                "first_seen_at":                now_utc if is_new else (existing or {}).get("first_seen_at", now_utc),
                "last_seen_at":                 now_utc,
                "_installments":                installments,
                "_fees":                        fees,
                "_detail_html":                 detail_html,
                "_price_basis_note":            f"Cash: {cash_now}, Remaining: {remaining}, Fee: {ae_fee}",
                "_ae_fee":                      ae_fee,
                "_is_new":                      is_new,
            }

            if heartbeat_fn:
                heartbeat_fn()

        page += 1

    log.info("Scrape complete — %d pages scanned", page - 1)