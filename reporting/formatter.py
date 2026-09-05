"""
HTML email formatter for the daily report.

Produces a clean, readable HTML email with:
  1. Top 10 ranked opportunities
  2. Top 3 high-potential leads / verified Best Deals
  3. Comparables used per valuation
  4. Cash-equivalent at 20/25/30%
  5. Score breakdown
  6. Due diligence checklist reminder
  7. Needs-data queue
"""
from __future__ import annotations
import config


# ── Colour palette ────────────────────────────────────────────────────────────
C_BG       = "#f8f9fa"
C_CARD     = "#ffffff"
C_BORDER   = "#dee2e6"
C_PRIMARY  = "#1a1a2e"
C_ACCENT   = "#e63946"
C_GREEN    = "#2d6a4f"
C_AMBER    = "#d4a017"
C_MUTED    = "#6c757d"
C_UPFRONT_FLAG = "#fff3cd"   # Yellow — upfront exceeds limit


def _egp(amount) -> str:
    if amount is None:
        return "—"
    return f"EGP {amount:,.0f}"


def _pct(val) -> str:
    if val is None:
        return "—"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def _score_bar(score: int, max_score: int = 100) -> str:
    pct = min(100, int(score / max_score * 100))
    colour = C_GREEN if pct >= 80 else (C_AMBER if pct >= 60 else C_ACCENT)
    return (
        f'<div style="background:#e9ecef;border-radius:4px;height:8px;width:120px;display:inline-block;vertical-align:middle;">'
        f'<div style="background:{colour};width:{pct}%;height:8px;border-radius:4px;"></div></div>'
        f' <span style="color:{colour};font-weight:bold;">{score}/100</span>'
    )


def _label_badge(label: str) -> str:
    colour = C_GREEN if "Best Deal" in label else C_AMBER
    return (
        f'<span style="background:{colour};color:white;padding:2px 8px;'
        f'border-radius:12px;font-size:11px;font-weight:bold;">{label}</span>'
    )


def _listing_card(listing: dict, rank: int, is_lead: bool = False) -> str:
    s = listing.get("_scoring", {})

    project   = listing.get("project_name_raw") or "Unknown project"
    dev       = listing.get("developer_raw") or ""
    loc       = listing.get("location_raw") or ""
    ptype     = (listing.get("property_type") or "").capitalize()
    beds      = listing.get("bedroom_count") or "—"
    bua       = listing.get("bua_sqm") or "—"
    floor_raw = listing.get("floor_number") or "—"
    view      = (listing.get("view_type") or "not_specified").replace("_", " ")
    finish    = (listing.get("finishing_status") or "not_specified").replace("_", " ")
    delivery  = listing.get("delivery_date_raw") or "—"
    uid       = listing.get("unit_id") or ""
    url       = listing.get("source_url") or "#"

    cash_now  = listing.get("seller_cash_required_now")
    remaining = listing.get("remaining_with_developer")
    ae_fee    = listing.get("aqar_exit_fee_egp")
    total_now = listing.get("total_required_now_egp")
    upfront   = listing.get("upfront_cash_required")
    exceeds   = listing.get("upfront_exceeds_limit")

    ce20 = listing.get("latest_cash_equivalent_20")
    ce25 = listing.get("latest_cash_equivalent_25")
    ce30 = listing.get("latest_cash_equivalent_30")
    aoc  = listing.get("latest_annual_ownership_cost")

    score      = listing.get("latest_score") or 0
    confidence = s.get("data_confidence_score") or listing.get("latest_data_confidence")
    conf_pct   = f"{confidence:.0%}" if confidence else "—"
    discount   = s.get("discount_to_median_pct")
    clusters   = s.get("comparable_cluster_count") or 0

    negotiable = "✓ Open to negotiation" if listing.get("is_negotiable") else ""
    docs       = "✓ Documents verified" if listing.get("documents_verified") else ""

    border_colour = C_GREEN if is_lead else C_BORDER
    upfront_flag  = f"""
      <tr><td colspan="2" style="background:{C_UPFRONT_FLAG};padding:8px;border-radius:4px;font-size:12px;">
        ⚠ Upfront cash {_egp(upfront)} exceeds EGP 4M limit — flagged, not excluded
      </td></tr>""" if exceeds else ""

    return f"""
    <div style="border:2px solid {border_colour};border-radius:8px;padding:20px;margin-bottom:16px;background:{C_CARD};">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
        <div>
          <span style="color:{C_MUTED};font-size:12px;">#{rank}</span>
          {'&nbsp;' + _label_badge(listing.get("label","")) if is_lead else ""}
          <h3 style="margin:4px 0;color:{C_PRIMARY};">
            <a href="{url}" style="color:{C_PRIMARY};text-decoration:none;">{project}</a>
          </h3>
          <div style="color:{C_MUTED};font-size:13px;">{dev} · {loc} · {uid}</div>
        </div>
        <div style="text-align:right;">
          {_score_bar(score)}
          <div style="font-size:12px;color:{C_MUTED};margin-top:4px;">Confidence: {conf_pct}</div>
        </div>
      </div>

      <!-- Unit summary -->
      <div style="margin:12px 0;padding:12px;background:{C_BG};border-radius:6px;font-size:13px;">
        <strong>{ptype}</strong> · {beds} BR · {bua} m² · Floor {floor_raw} · {view} · {finish} · Delivery {delivery}
        {'&nbsp; <span style="color:' + C_GREEN + ';">' + negotiable + '</span>' if negotiable else ""}
        {'&nbsp; <span style="color:' + C_GREEN + ';">' + docs + '</span>' if docs else ""}
      </div>

      <!-- Financials table -->
      <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:12px;">
        <tr style="background:{C_BG};">
          <td style="padding:8px;font-weight:bold;color:{C_PRIMARY};">Cash to seller now</td>
          <td style="padding:8px;font-weight:bold;font-size:16px;">{_egp(cash_now)}</td>
          <td style="padding:8px;">Remaining with developer</td>
          <td style="padding:8px;">{_egp(remaining)}</td>
        </tr>
        <tr>
          <td style="padding:8px;">Aqar Exit fee (1.25%)</td>
          <td style="padding:8px;">{_egp(ae_fee)}</td>
          <td style="padding:8px;"><strong>Total required now</strong></td>
          <td style="padding:8px;font-weight:bold;">{_egp(total_now)}</td>
        </tr>
        {upfront_flag}
        <tr style="background:{C_BG};">
          <td style="padding:8px;">Annual ownership cost</td>
          <td style="padding:8px;">{_egp(aoc)} / year</td>
          <td style="padding:8px;">Comparable clusters</td>
          <td style="padding:8px;">{clusters} clusters</td>
        </tr>
      </table>

      <!-- Cash-equivalent sensitivity -->
      <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:12px;">
        <tr>
          <th style="text-align:left;padding:6px 8px;background:{C_PRIMARY};color:white;border-radius:4px 0 0 0;">Rate</th>
          <th style="text-align:right;padding:6px 8px;background:{C_PRIMARY};color:white;">Cash-equivalent</th>
          <th style="text-align:right;padding:6px 8px;background:{C_PRIMARY};color:white;border-radius:0 4px 0 0;">vs Median</th>
        </tr>
        <tr>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};">20% (conservative)</td>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};text-align:right;">{_egp(ce20)}</td>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};text-align:right;">—</td>
        </tr>
        <tr style="background:#e8f5e9;">
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};font-weight:bold;">25% (ranking rate)</td>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};text-align:right;font-weight:bold;">{_egp(ce25)}</td>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};text-align:right;font-weight:bold;">{_pct(discount)}</td>
        </tr>
        <tr>
          <td style="padding:6px 8px;">30% (aggressive)</td>
          <td style="padding:6px 8px;text-align:right;">{_egp(ce30)}</td>
          <td style="padding:6px 8px;text-align:right;">—</td>
        </tr>
      </table>

      <!-- Score breakdown -->
      <details style="margin-top:8px;">
        <summary style="cursor:pointer;color:{C_MUTED};font-size:12px;user-select:none;">
          Score breakdown (click to expand)
        </summary>
        <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:8px;">
          <tr>
            <td style="padding:4px 8px;">Value vs comparables</td>
            <td style="padding:4px 8px;text-align:right;">{s.get('comparables_score', 0):.1f} / 40</td>
          </tr>
          <tr style="background:{C_BG};">
            <td style="padding:4px 8px;">Unit quality</td>
            <td style="padding:4px 8px;text-align:right;">{s.get('unit_quality_score', 0):.1f} / 20</td>
          </tr>
          <tr>
            <td style="padding:4px 8px;">Project quality</td>
            <td style="padding:4px 8px;text-align:right;">{s.get('project_quality_score', 0):.1f} / 20</td>
          </tr>
          <tr style="background:{C_BG};">
            <td style="padding:4px 8px;">Payment terms</td>
            <td style="padding:4px 8px;text-align:right;">{s.get('payment_terms_score', 0):.1f} / 15</td>
          </tr>
          <tr>
            <td style="padding:4px 8px;">Seller urgency</td>
            <td style="padding:4px 8px;text-align:right;">{s.get('urgency_score', 0):.1f} / 5</td>
          </tr>
          <tr style="font-weight:bold;border-top:2px solid {C_BORDER};">
            <td style="padding:6px 8px;">Total</td>
            <td style="padding:6px 8px;text-align:right;">{score} / 100</td>
          </tr>
        </table>
      </details>

      <div style="margin-top:12px;font-size:12px;color:{C_MUTED};">
        <a href="{url}" style="color:{C_ACCENT};">View on Aqar Exit →</a>
      </div>
    </div>
    """


def _dd_checklist() -> str:
    """Compact due-diligence reminder for every shortlisted listing."""
    items = [
        ("[BD] Seller identity matches contract purchaser/assignee", True),
        ("[BD] Original contract verified against listing details", True),
        ("[BD] Official developer account statement obtained (not seller's claim)", True),
        ("[BD] Developer permits resale — assignment fee and timeline confirmed with CRM", True),
        ("[BD] Payment-plan transferability confirmed", True),
        ("No co-owner, divorce, lien, court dispute, or blocking claim", False),
        ("Realistic delivery date verified (not advertised date)", False),
        ("Broker/brokerage GOEIC registration verified where applicable", False),
        ("At least 3 comparable clusters obtained independently", False),
    ]
    rows = "".join(
        f'<li style="margin-bottom:4px;{"font-weight:bold;" if bd else ""}">{item}</li>'
        for item, bd in items
    )
    return f"""
    <div style="background:{C_BG};border:1px solid {C_BORDER};border-radius:6px;padding:16px;margin-bottom:24px;">
      <h4 style="margin:0 0 8px;color:{C_PRIMARY};">Due diligence checklist</h4>
      <p style="font-size:12px;color:{C_MUTED};margin:0 0 8px;">
        Items marked [BD] must be verified before any listing can be labelled Best Deal.
        Until verified: high-potential lead only.
      </p>
      <ul style="font-size:12px;margin:0;padding-left:20px;">{rows}</ul>
    </div>
    """


def _needs_data_section(listings: list[dict]) -> str:
    if not listings:
        return ""
    rows = "".join(
        f"""<tr>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};">
            <a href="{l.get('source_url','#')}" style="color:{C_ACCENT};">
              {l.get('project_name_raw','—')} {l.get('unit_id','')}
            </a>
          </td>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};">{l.get('property_type','')}</td>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};">{l.get('bedroom_count','—')} BR / {l.get('bua_sqm','—')} m²</td>
          <td style="padding:6px 8px;border-bottom:1px solid {C_BORDER};color:{C_MUTED};font-size:11px;">{l.get('exclusion_reason','')}</td>
        </tr>"""
        for l in listings
    )
    return f"""
    <h2 style="color:{C_PRIMARY};margin:32px 0 12px;">Needs data — potentially eligible</h2>
    <p style="color:{C_MUTED};font-size:13px;">
      These listings were not ranked because key fields are missing.
      Open each on Aqar Exit to complete the data manually via the intake form.
    </p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <tr style="background:{C_PRIMARY};color:white;">
        <th style="padding:8px;text-align:left;">Project</th>
        <th style="padding:8px;text-align:left;">Type</th>
        <th style="padding:8px;text-align:left;">Size</th>
        <th style="padding:8px;text-align:left;">Missing</th>
      </tr>
      {rows}
    </table>
    """


def build_html(data: dict) -> str:
    """Build complete HTML email body."""
    top10      = data["top10"]
    leads      = data["leads"]
    needs_data = data["needs_data"]
    run_dt     = data["run_datetime"]
    total      = data["total_eligible"]

    # ── Header ──────────────────────────────────────────────────────────────
    header = f"""
    <div style="background:{C_PRIMARY};color:white;padding:24px;border-radius:8px 8px 0 0;margin-bottom:24px;">
      <h1 style="margin:0;font-size:22px;">Cairo Deal-Finder</h1>
      <p style="margin:4px 0 0;opacity:0.7;font-size:13px;">
        Daily report · {run_dt} · {total} eligible listings in database
      </p>
    </div>
    """

    # ── Top 3 leads section ─────────────────────────────────────────────────
    has_verified = any(l.get("is_stage1_eligible") for l in leads)
    leads_title  = "Top 3 high-potential leads" if not has_verified else "Top 3 — includes verified Best Deal(s)"
    leads_html = f"<h2 style='color:{C_PRIMARY};margin-bottom:12px;'>{leads_title}</h2>"
    leads_html += "".join(
        _listing_card(l, i + 1, is_lead=True) for i, l in enumerate(leads)
    )
    leads_html += _dd_checklist()

    # ── Top 10 full list ────────────────────────────────────────────────────
    top10_html = f"<h2 style='color:{C_PRIMARY};margin:32px 0 12px;'>Top 10 ranked opportunities</h2>"
    top10_html += "".join(
        _listing_card(l, i + 1) for i, l in enumerate(top10)
    )

    # ── Needs data section ───────────────────────────────────────────────────
    nd_html = _needs_data_section(needs_data)

    # ── Footer ───────────────────────────────────────────────────────────────
    footer = f"""
    <div style="border-top:1px solid {C_BORDER};margin-top:32px;padding-top:16px;
                color:{C_MUTED};font-size:11px;text-align:center;">
      <p>Cash-equivalent uses 25% annual EGP discount rate for ranking.
      All comparables are active asking prices — not completed-sale values.</p>
      <p>A listing cannot be marked Best Deal until Stage 2 human verification is complete.</p>
      <p>Cairo Deal-Finder · Personal research tool · Not financial advice</p>
    </div>
    """

    body = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
                 max-width:680px;margin:0 auto;padding:16px;background:{C_BG};color:#212529;">
      {header}
      {leads_html}
      {top10_html}
      {nd_html}
      {footer}
    </body>
    </html>
    """
    return body


def build_subject(data: dict) -> str:
    leads  = data["leads"]
    top    = leads[0] if leads else None
    score  = top.get("latest_score", 0) if top else 0
    proj   = (top.get("project_name_raw") or "—") if top else "—"
    ce25   = top.get("latest_cash_equivalent_25") if top else None
    price  = f"EGP {ce25:,.0f}" if ce25 else "—"
    date   = data["run_date"]
    return f"[{date}] Top deal: {proj} — Score {score}/100 — {price}"
