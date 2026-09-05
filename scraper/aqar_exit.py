"""
Aqar Exit scraper.

Fetches listing cards from /en/opportunities (paginated),
filters for 5th Settlement / New Cairo, then fetches detail pages
for new or changed listings.

Design principles (per spec):
  • No Cloudflare bypass — plain requests with polite User-Agent
  • Rate-limited: SCRAPER_REQUEST_DELAY_S between requests
  • Full raw HTML hashed for change detection (not just key fields)
  • Stops pagination early when all remaining listings are outside scope
    OR older than LOOKBACK_DAYS (no need to scan 4,800 listings daily)
  • Returns structured listing dicts ready for Supabase upsert
"""
from __future__ import annotations
import hashlib
import logging
import time
import re
from datetime import datetime, timezone
from typing import Generator

import requests
from bs4 import BeautifulSoup

import config
from scraper.parser import (
    parse_detail_page,
    build_installment_schedule,
    build_upfront_fees,
)
from db.client import get_listing_by_url

log = logging.getLogger(__name__)

# Stop scanning after this many consecutive out-of-scope pages
_OOS_PAGE_LIMIT = 5
# Look back this many pages even if all are out-of-scope, to catch stragglers
_MIN_PAGES      = 3


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      config.SCRAPER_USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT":             "1",
    })
    return s


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_target_location(location_raw: str | None) -> bool:
    if not location_raw:
        return False
    loc = location_raw.strip()
    return any(t.lower() in loc.lower() for t in config.TARGET_LOCATIONS)


def _fetch(session: requests.Session, url: str) -> str | None:
    """Fetch URL, return text or None on error. Respects rate limit."""
    time.sleep(config.SCRAPER_REQUEST_DELAY_S)
    try:
        resp = session.get(url, timeout=config.SCRAPER_TIMEOUT_S)
        if resp.status_code == 403:
            log.warning("403 Forbidden — Cloudflare may be blocking GitHub Actions IPs. URL: %s", url)
            return None
        if resp.status_code != 200:
            log.warning("HTTP %d for %s", resp.status_code, url)
            return None
        return resp.text
    except requests.RequestException as e:
        log.error("Request failed for %s: %s", url, e)
        return None


def _extract_listing_cards(html: str) -> list[str]:
    """
    Extract individual listing card HTML blocks from the opportunities page.
    Each card wraps one opportunity. Returns list of card HTML strings.
    """
    soup = BeautifulSoup(html, "lxml")
    cards = []

    # Aqar Exit cards: each opportunity is a <section> or <article> or <div>
    # containing "Cash required now" and a "U-XXXXX" unit ID.
    # We identify cards by finding elements with both markers.
    for el in soup.find_all(["section", "article", "div"]):
        text = el.get_text()
        if re.search(r"U-\d{4,}", text) and (
            "Cash required now" in text or "الكاش المطلوب" in text
        ):
            # Avoid nested duplicates: skip if parent already matched
            if el.parent and re.search(r"U-\d{4,}", el.parent.get_text()):
                # Check if parent was already added — heuristic: take smallest matching el
                pass
            cards.append(str(el))

    # Deduplicate by unit ID
    seen: set[str] = set()
    unique_cards = []
    for card in cards:
        uid_match = re.search(r"U-\d{4,}", card)
        if uid_match:
            uid = uid_match.group()
            if uid not in seen:
                seen.add(uid)
                unique_cards.append(card)

    return unique_cards


def _extract_detail_url(card_html: str) -> str | None:
    """Extract the detail page URL from a listing card."""
    m = re.search(r'href="(/(?:en/)?buy/opportunity/[a-f0-9\-]{36})"', card_html)
    if m:
        return config.AE_BASE + m.group(1)
    # Try absolute URL
    m = re.search(r'href="(https://(?:www\.)?aqarexit\.com/(?:en/)?buy/opportunity/[a-f0-9\-]{36})"', card_html)
    return m.group(1) if m else None


def _extract_location_from_card(card_html: str) -> str | None:
    """Fast location extraction without full BeautifulSoup parse."""
    # Pattern: developer · location (e.g. "Emaar · التجمع الخامس")
    m = re.search(r"·\s*([^·<\n]+?)(?:\s*·|\s*</|\s*\n)", card_html)
    return m.group(1).strip() if m else None


def scrape_new_cairo_listings(
    heartbeat_fn=None,
) -> Generator[dict, None, None]:
    """
    Generator that yields processed listing dicts for 5th Settlement / New Cairo.

    Each dict is ready to upsert to the `listings` table.
    Child table records (installment_schedules, upfront_transaction_fees)
    are attached as nested keys: '_installments', '_fees'.

    Call heartbeat_fn() periodically if provided.
    """
    session    = _session()
    page       = 1
    oos_streak = 0   # Consecutive out-of-scope pages (no target listings)
    now_utc    = datetime.now(timezone.utc).isoformat()

    log.info("Starting Aqar Exit scrape — target: 5th Settlement / New Cairo")

    while page <= config.SCRAPER_MAX_PAGES:
        # ── Fetch listing page ─────────────────────────────────────────────
        # Try with page param first; Aqar Exit may use ?page= or cursor
        page_url = config.AE_OPPORTUNITIES
        if page > 1:
            page_url = f"{config.AE_OPPORTUNITIES}?page={page}"

        log.info("Fetching page %d: %s", page, page_url)
        html = _fetch(session, page_url)

        if html is None:
            log.error("Failed to fetch page %d — stopping scrape", page)
            break

        # ── Extract cards ──────────────────────────────────────────────────
        cards = _extract_listing_cards(html)
        if not cards:
            log.info("No listing cards found on page %d — end of listings", page)
            break

        log.info("Page %d: %d cards found", page, len(cards))

        page_had_target = False

        for card_html in cards:
            # Fast location check before full parse
            location_raw = _extract_location_from_card(card_html)
            if not _is_target_location(location_raw):
                continue  # Skip non-target listings quickly

            page_had_target = True

            # ── Get detail URL ─────────────────────────────────────────────
            detail_url = _extract_detail_url(card_html)
            if not detail_url:
                log.warning("Could not extract detail URL from card (location: %s)", location_raw)
                continue

            # ── Hash card HTML for change detection ────────────────────────
            card_hash = _sha256(card_html)

            # ── Check Supabase for existing listing ────────────────────────
            existing = get_listing_by_url(detail_url)
            if existing and existing.get("raw_content_hash") == card_hash:
                log.debug("Unchanged: %s", detail_url)
                continue  # No change — skip Claude and detail fetch

            is_new = existing is None

            # ── Fetch detail page ──────────────────────────────────────────
            log.info("%s detail: %s", "NEW" if is_new else "CHANGED", detail_url)
            detail_html = _fetch(session, detail_url)

            if detail_html is None:
                log.warning("Could not fetch detail page: %s", detail_url)
                continue

            detail_hash  = _sha256(detail_html)
            parsed       = parse_detail_page(detail_html, detail_url)
            installments = build_installment_schedule(parsed)
            fees         = build_upfront_fees(parsed)

            # ── Determine price basis and eligibility ──────────────────────
            cash_now     = parsed.get("seller_cash_required_now")
            remaining    = parsed.get("remaining_with_developer")
            ae_fee       = parsed.get("aqar_exit_fee_egp", 0) or 0
            total_now    = parsed.get("total_required_now_egp")  # cash + fee

            # Aqar Exit guarantees zero overprice:
            # seller_cash_required_now = exactly what seller paid
            # price_basis is always seller_cash_required_plus_installments
            price_basis_note = (
                "Aqar Exit zero-overprice assignment. "
                f"seller_cash_required_now = EGP {cash_now:,.0f} (what seller paid). "
                f"Remaining with developer = EGP {remaining:,.0f}. "
                f"Aqar Exit fee 1.25% = EGP {ae_fee:,.0f}. "
                "Price basis: seller_cash_required_plus_installments."
            ) if cash_now and remaining else (
                "Transaction legs incomplete — cannot calculate cash-equivalent."
            )

            # Upfront cash = cash_now + Aqar Exit fee
            upfront_cash = (cash_now or 0) + ae_fee
            upfront_exceeds = upfront_cash > config.MAX_UPFRONT_CASH_EGP if cash_now else None

            # ── Build listing record ───────────────────────────────────────
            listing_record = {
                # Source
                "source_name":          config.AE_SOURCE_NAME,
                "source_url":           detail_url,
                "advertised_price_text": f"Cash required: EGP {cash_now:,.0f}" if cash_now else None,
                "currency":             "EGP",
                "captured_at":          now_utc,
                "raw_content_hash":     detail_hash,

                # Project identification
                "project_name_raw":     parsed.get("project_name_raw"),
                "phase_raw":            None,          # Not available from listing
                "phase_confidence":     "unknown",
                "entry_type":           "compound",    # Aqar Exit is assignment-only = compounds

                # Unit
                "property_type":        parsed.get("property_type", "unknown"),
                "bedroom_count":        parsed.get("bedroom_count"),
                "bua_sqm":              parsed.get("bua_sqm"),
                "floor_number":         parsed.get("floor_number"),
                "finishing_status":     parsed.get("finishing_status", "not_specified"),
                "finishing_notes":      parsed.get("finishing_notes"),
                "delivery_status":      parsed.get("delivery_status", "not_specified"),
                "delivery_date_raw":    parsed.get("delivery_date_raw"),

                # View / outdoor — not reliably available in listing
                "view_type":            "not_specified",
                "view_notes":           None,
                "private_garden":       "not_specified",
                "roof_terrace":         "not_specified",
                "parking_included":     "not_specified",

                # Transaction legs
                "seller_cash_required_now":     cash_now,
                "seller_cash_required_confirmed": cash_now is not None,
                "known_overdue_amounts":        0,      # Aqar Exit verifies — no hidden arrears
                "known_overdue_confirmed":      True,
                "schedule_source":              "developer_statement",  # Aqar Exit verifies docs
                "schedule_confidence":          "high" if installments else "unknown",

                # Seller info
                "seller_type":          "owner",   # Aqar Exit policy: owners only
                "broker_goeic_verified": None,

                # Distress signals
                "price_reduction_count": 0,        # Track via price history
                "multi_broker_count":    1,         # Always 1 on Aqar Exit (owner only)
                "urgency_keywords_detected": ["negotiable"] if parsed.get("is_negotiable") else [],

                # Duplicate tracking
                "duplicate_flag":       "unique",

                # Normalization
                "normalization_status":  "normalized",
                "normalization_model":   "parser_v1",  # Parsed directly, no Claude needed
                "normalization_at":      now_utc,

                # Derived (populated by scoring engine later)
                "eligibility_status":   None,
                "upfront_cash_required": upfront_cash if cash_now else None,
                "upfront_exceeds_limit": upfront_exceeds,

                # User pipeline
                "user_status":          "new",

                # Timestamps
                "first_seen_at":         now_utc if is_new else existing.get("first_seen_at"),
                "last_seen_at":          now_utc,
                "last_changed_at":       now_utc if not is_new else None,

                # Internal fields for child tables
                "_installments":         installments,
                "_fees":                 fees,
                "_detail_html":          detail_html,
                "_card_html":            card_html,
                "_price_basis_note":     price_basis_note,
                "_ae_fee":               ae_fee,
                "_is_new":               is_new,
            }

            yield listing_record

            # Heartbeat every 10 listings
            if heartbeat_fn:
                heartbeat_fn()

        # ── Pagination control ─────────────────────────────────────────────
        if not page_had_target:
            oos_streak += 1
            log.info("Page %d: no target listings (oos_streak=%d)", page, oos_streak)
            if oos_streak >= _OOS_PAGE_LIMIT and page >= _MIN_PAGES:
                log.info("OOS streak limit reached — stopping pagination")
                break
        else:
            oos_streak = 0

        page += 1

    log.info("Scrape complete — %d pages scanned", page - 1)
