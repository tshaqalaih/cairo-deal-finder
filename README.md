# Cairo Deal-Finder

Personal daily deal-finder for 5th Settlement / New Cairo property assignments.

## Architecture

```
GitHub Actions (6 UTC triggers)
  ↓
Python pipeline (main.py --stage ingestion|scoring|reporting)
  ↓
Aqar Exit scraper (requests + BeautifulSoup — SSR confirmed)
  ↓
Supabase PostgreSQL (cairo-deal-finder project)
  ↓
Scoring engine → Resend email + Telegram push
```

## Key design facts

- **No Playwright needed** — Aqar Exit serves full HTML server-side
- **No Claude normalization needed** for most fields — data is pre-structured
- **Data quality**: Aqar Exit verifies contracts and payment receipts before listing
- **seller_cash_required_now** maps exactly to "Cash required now"
- **Aqar Exit fee** (1.25%) is shown explicitly on every detail page
- **"Total required from you now"** = cash + fee — pre-calculated

## Setup

### 1. GitHub repository secrets

Add these under Settings → Secrets → Actions:

| Secret | Value |
|---|---|
| `SUPABASE_URL` | `https://hiiupqezpxtnmjlnakoy.supabase.co` |
| `SUPABASE_KEY` | Supabase service_role key |
| `ANTHROPIC_API_KEY` | Claude API key |
| `RESEND_API_KEY` | Resend.com API key |
| `REPORT_EMAIL_TO` | Your email address |
| `TELEGRAM_BOT_TOKEN` | From BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### 2. Get Supabase service_role key

Supabase dashboard → Project Settings → API → service_role secret

### 3. Create Telegram bot

1. Message @BotFather on Telegram → `/newbot`
2. Copy the token
3. Start a chat with your bot, then visit:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Copy your `chat.id`

### 4. Test locally

```bash
cp .env.example .env   # fill in your values
pip install -r requirements.txt
python main.py --stage ingestion
```

### 5. Test on GitHub Actions

Push to your repo → Actions tab → Run workflow → select stage: ingestion

## Directory structure

```
cairo_deal_finder/
├── config.py                    # All configuration (env vars)
├── main.py                      # Entry point
├── requirements.txt
├── scraper/
│   ├── aqar_exit.py             # Main scraper
│   └── parser.py                # HTML field extraction
├── db/
│   └── client.py                # Supabase wrapper
├── pipeline/
│   ├── run_lock.py              # Atomic stage lock
│   └── ingest.py                # Ingestion orchestrator
└── .github/workflows/
    └── pipeline.yml             # 6-trigger GitHub Actions workflow
```

## Buyer parameters (config.py)

- `MAX_CASH_EQUIVALENT_EGP` = 7,000,000 (total acquisition ceiling)
- `MAX_UPFRONT_CASH_EGP` = 4,000,000 (day-1 cash — flag, not gate)
- `NPV_DISCOUNT_RATE_DEFAULT` = 0.25 (25% annual)

## What's not yet built

- Scoring engine (next step)
- Email report (after scoring)
- Telegram push (after scoring)  
- Streamlit dashboard (parallel)
