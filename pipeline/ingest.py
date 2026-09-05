"""
Ingestion pipeline stage.

Orchestrates:
  1. Acquire run lock
  2. Scrape Aqar Exit for 5th Settlement listings
  3. Upsert to Supabase (listings + child tables)
  4. Store raw captures for evidence
  5. Track price history on changes
  6. Release lock (completed or failed)
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime
import pytz

import config
from pipeline import run_lock
from scraper.aqar_exit import scrape_new_cairo_listings
from db import client as db

log = logging.getLogger(__name__)


def _cairo_date() -> str:
    cairo_tz = pytz.timezone("Africa/Cairo")
    return datetime.now(cairo_tz).strftime("%Y-%m-%d")


def run() -> None:
    local_date = _cairo_date()
    stage      = "ingestion"
    run_id: str | None = None

    log.info("Ingestion stage — local date: %s", local_date)

    try:
        run_id = run_lock.acquire(local_date, stage)
    except run_lock.LockAcquireError as e:
        log.info("Lock not acquired: %s", e)
        sys.exit(0)

    ingested = changed = skipped = errors = 0

    def _heartbeat():
        if run_id:
            run_lock.heartbeat(local_date, stage, run_id)

    try:
        for listing in scrape_new_cairo_listings(heartbeat_fn=_heartbeat):
            try:
                _process_listing(listing)
                if listing.get("_is_new"):
                    ingested += 1
                else:
                    changed += 1
            except Exception as e:
                log.error("Failed to process listing %s: %s", listing.get("source_url"), e)
                errors += 1

        log.info(
            "Ingestion complete — new: %d, changed: %d, skipped: %d, errors: %d",
            ingested, changed, skipped, errors,
        )
        run_lock.complete(local_date, stage, run_id)

    except Exception as e:
        log.exception("Ingestion stage failed: %s", e)
        if run_id:
            run_lock.fail(local_date, stage, run_id, str(e))
        sys.exit(1)


def _process_listing(listing: dict) -> None:
    """
    Upsert a single listing to Supabase including all child table records.
    """
    # ── Strip internal keys before upsert ─────────────────────────────────
    installments  = listing.pop("_installments", [])
    fees          = listing.pop("_fees", [])
    detail_html   = listing.pop("_detail_html", "")
    card_html     = listing.pop("_card_html", "")
    price_note    = listing.pop("_price_basis_note", "")
    ae_fee        = listing.pop("_ae_fee", 0)
    is_new        = listing.pop("_is_new", True)

    # ── Upsert listing row ─────────────────────────────────────────────────
    row = db.upsert_listing(listing)
    listing_id = row.get("id")
    if not listing_id:
        raise ValueError(f"Upsert returned no id for {listing.get('source_url')}")

    # ── Raw capture (evidence) ─────────────────────────────────────────────
    db.insert_raw_capture({
        "listing_id":        listing_id,
        "captured_at":       listing["captured_at"],
        "raw_content_hash":  listing["raw_content_hash"],
        "raw_text":          detail_html[:50_000] if detail_html else None,
        "source_url":        listing["source_url"],
    })

    # ── Price history on change ────────────────────────────────────────────
    change_type = "initial" if is_new else "price_change"
    db.insert_price_history({
        "listing_id":                listing_id,
        "recorded_at":               listing["captured_at"],
        "seller_cash_required_now":  listing.get("seller_cash_required_now"),
        "advertised_price_text":     listing.get("advertised_price_text"),
        "change_type":               change_type,
        "change_notes":              price_note,
    })

    # ── Child tables ───────────────────────────────────────────────────────
    if installments:
        db.upsert_installment_schedule(listing_id, installments)

    fees_with_extras = fees.copy()
    if ae_fee:
        # Aqar Exit fee already in fees from build_upfront_fees()
        pass

    if fees_with_extras:
        db.upsert_upfront_fees(listing_id, fees_with_extras)

    log.debug(
        "Processed %s: %s installments, %s fees",
        listing.get("source_url", "")[-40:],
        len(installments),
        len(fees_with_extras),
    )
