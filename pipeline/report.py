"""
Reporting pipeline stage.

Fetches scored data → formats → sends Telegram push → sends email.
Sends Telegram first (faster, phone notification) then email (full detail).
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime
import pytz

from pipeline import run_lock
from reporting.fetcher import fetch_report_data
from reporting.formatter import build_html, build_subject
from reporting.email import send as send_email
from reporting.telegram import send as send_telegram

log = logging.getLogger(__name__)


def _cairo_date() -> str:
    return datetime.now(pytz.timezone("Africa/Cairo")).strftime("%Y-%m-%d")


def run() -> None:
    local_date = _cairo_date()
    stage      = "reporting"
    run_id: str | None = None

    log.info("Reporting stage — local date: %s", local_date)

    try:
        run_id = run_lock.acquire(local_date, stage)
    except run_lock.LockAcquireError as e:
        log.info("Lock not acquired: %s", e)
        sys.exit(0)

    try:
        # ── Fetch report data ────────────────────────────────────────────────
        log.info("Fetching report data from Supabase...")
        data = fetch_report_data()

        log.info(
            "Report data: %d top10, %d leads, %d needs-data",
            len(data["top10"]),
            len(data["leads"]),
            len(data["needs_data"]),
        )

        if not data["top10"] and not data["leads"]:
            log.info("No eligible listings to report — sending empty notification")

        # ── Telegram push (first — fastest delivery) ─────────────────────────
        tg_ok = send_telegram(data)
        log.info("Telegram: %s", "sent" if tg_ok else "skipped/failed")

        # ── Email report ─────────────────────────────────────────────────────
        subject  = build_subject(data)
        html     = build_html(data)
        email_ok = send_email(subject, html)
        log.info("Email: %s | subject: %s", "sent" if email_ok else "skipped/failed", subject)

        run_lock.complete(local_date, stage, run_id)
        log.info("Reporting stage complete")

    except Exception as e:
        log.exception("Reporting stage failed: %s", e)
        if run_id:
            run_lock.fail(local_date, stage, run_id, str(e))
        sys.exit(1)
