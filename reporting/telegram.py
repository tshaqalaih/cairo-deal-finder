"""
Sends the daily Top 3 push notification via Telegram Bot API.
Plain text — readable on phone in seconds.
"""
from __future__ import annotations
import logging
import requests
import config

log = logging.getLogger(__name__)

TG_API = "https://api.telegram.org/bot{token}/sendMessage"


def _egp(amount) -> str:
    if amount is None:
        return "—"
    if amount >= 1_000_000:
        return f"EGP {amount/1_000_000:.2f}M"
    return f"EGP {amount:,.0f}"


def _pct(val) -> str:
    if val is None:
        return ""
    sign = "+" if val >= 0 else ""
    return f" ({sign}{val:.1f}% vs median)"


def _format_lead(rank: int, listing: dict) -> str:
    project  = listing.get("project_name_raw") or "Unknown"
    ptype    = (listing.get("property_type") or "").capitalize()
    beds     = listing.get("bedroom_count") or "—"
    bua      = listing.get("bua_sqm") or "—"
    score    = listing.get("latest_score") or 0
    ce25     = listing.get("latest_cash_equivalent_25")
    upfront  = listing.get("upfront_cash_required")
    discount = listing.get("_scoring", {}).get("discount_to_median_pct")
    label    = listing.get("label", "High-Potential Lead")
    exceeds  = listing.get("upfront_exceeds_limit")
    url      = listing.get("source_url", "")

    flag = " ⚠️ upfront >4M" if exceeds else ""
    best = " ⭐" if "Best Deal" in label else ""

    return (
        f"#{rank}{best} {project}\n"
        f"{ptype} · {beds} BR · {bua}m²\n"
        f"Score: {score}/100\n"
        f"Cash-equiv (25%): {_egp(ce25)}{_pct(discount)}\n"
        f"Day-1 cash: {_egp(upfront)}{flag}\n"
        f"{url}\n"
    )


def send(data: dict) -> bool:
    """
    Send Top 3 leads as a Telegram message.
    Returns True on success.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping push notification")
        return False

    leads    = data["leads"]
    run_dt   = data["run_datetime"]
    total    = data["total_eligible"]

    if not leads:
        message = f"🏠 Cairo Deal-Finder · {run_dt}\n\nNo eligible listings found today."
    else:
        parts = [f"🏠 Cairo Deal-Finder · {run_dt}\n{total} eligible listings\n"]
        for i, lead in enumerate(leads):
            parts.append(_format_lead(i + 1, lead))
        parts.append("⭐ = Verified Best Deal (Stage 2 complete)")
        message = "\n".join(parts)

    url = TG_API.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        resp = requests.post(url, json={
            "chat_id":    config.TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": None,   # Plain text — no markdown escaping issues
            "disable_web_page_preview": True,
        }, timeout=10)
        if resp.ok:
            log.info("Telegram push sent")
            return True
        else:
            log.error("Telegram API error: %s %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False
