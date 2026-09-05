"""
Sends the daily report email via Resend.
"""
from __future__ import annotations
import logging
import resend
import config

log = logging.getLogger(__name__)


def send(subject: str, html_body: str) -> bool:
    """
    Send the daily report email.
    Returns True on success, False on failure.
    """
    if not config.RESEND_API_KEY or not config.REPORT_EMAIL_TO:
        log.warning("Resend API key or recipient email not configured — skipping email")
        return False

    resend.api_key = config.RESEND_API_KEY

    try:
        resp = resend.Emails.send({
            "from":    "Cairo Deal-Finder <report@yourdomain.com>",
            "to":      [config.REPORT_EMAIL_TO],
            "subject": subject,
            "html":    html_body,
        })
        log.info("Email sent — id: %s", resp.get("id"))
        return True
    except Exception as e:
        log.error("Failed to send email: %s", e)
        return False
