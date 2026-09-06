"""
Cairo Deal-Finder — configuration.
All values read from environment variables; no secrets in code.
"""
import os

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL      = os.environ["SUPABASE_URL"]       # https://hiiupqezpxtnmjlnakoy.supabase.co
SUPABASE_KEY      = os.environ["SUPABASE_KEY"]       # service_role key (not anon)

# ── AI model ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NORMALIZATION_MODEL = "claude-sonnet-4-6"

# ── Delivery (reporting) ─────────────────────────────────────────────────────
RESEND_API_KEY    = os.environ.get("RESEND_API_KEY", "")
REPORT_EMAIL_TO   = os.environ.get("REPORT_EMAIL_TO", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Buyer parameters (from spec Section 2) ───────────────────────────────────
MAX_CASH_EQUIVALENT_EGP = 7_000_000   # Total acquisition cost ceiling
MAX_UPFRONT_CASH_EGP    = 4_000_000   # Day-1 cash ceiling (flag, not gate)
NPV_DISCOUNT_RATE_DEFAULT = 0.25      # 25% annual; shown alongside 20% and 30%
MIN_BUA_SQM = 140                     # Minimum built-up area
MAX_BUA_SQM = 220                     # Maximum built-up area (raised from 210)

# ── Scraper behaviour ────────────────────────────────────────────────────────
SCRAPER_USER_AGENT = (
    "CairoDealFinder/1.0 (personal research tool; "
    "contact: info@example.com)"
)
SCRAPER_REQUEST_DELAY_S = 2.5         # Seconds between requests (polite)
SCRAPER_MAX_PAGES       = 50          # Safety ceiling; ~1,000 listings per run
SCRAPER_TIMEOUT_S       = 20

# Locations that match our gate (Arabic as displayed by Aqar Exit)
TARGET_LOCATIONS = {
    "التجمع الخامس",
    "القاهرة الجديدة",
    "New Cairo",
    "Fifth Settlement",
    "5th Settlement",
}

# ── Pipeline stages ───────────────────────────────────────────────────────────
PIPELINE_STAGES      = ["ingestion", "scoring", "reporting"]
STALE_LOCK_MINUTES   = 45            # Heartbeat threshold for stale-lock reclaim
MAX_STAGE_RETRIES    = 3             # Max retries on failed stage

# ── Aqar Exit URLs ────────────────────────────────────────────────────────────
AE_BASE             = "https://www.aqarexit.com"
AE_OPPORTUNITIES    = f"{AE_BASE}/en/opportunities"
AE_DETAIL_TEMPLATE  = f"{AE_BASE}/en/buy/opportunity/{{uuid}}"
AE_SOURCE_NAME      = "aqar_exit"
