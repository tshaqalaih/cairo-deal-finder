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



def _build_verify_section(listing: dict, overdue_amount: str) -> str:
    """Build a per-listing 'What to check' section."""
    items = []

    # Missing fields that affect the score
    if listing.get("view_type", "not_specified") == "not_specified":
        items.append(("❓", "View type unknown — ask seller or check on-site"))
    if listing.get("parking_included", "not_specified") == "not_specified":
        items.append(("❓", "Parking status unknown — confirm with seller"))
    if listing.get("finishing_status", "not_specified") == "not_specified":
        items.append(("❓", "Finishing status not specified — verify on-site"))
    if listing.get("floor_number") in (None, "not_specified", "—"):
        items.append(("❓", "Floor number unknown"))

    # Overdue amounts — always flag if present
    overdue = listing.get("known_overdue_amounts", 0) or 0
    if overdue > 0:
        items.append(("⚠️", f"Overdue installments: EGP {overdue:,.0f} — must be cleared before transfer"))

    # Upfront exceeds limit
    if listing.get("upfront_exceeds_limit"):
        items.append(("⚠️", "Day-1 cash exceeds your EGP 4M limit — confirm you can cover this"))

    # Delivery soon or passed
    delivery_raw = listing.get("delivery_date_raw") or ""
    if delivery_raw and any(y in delivery_raw for y in ["2025", "2026"]):
        items.append(("📋", f"Delivery {delivery_raw} — verify actual date directly with developer"))

    # Data confidence
    confidence = listing.get("latest_data_confidence") or 0
    if confidence < 0.85:
        items.append(("📋", f"Data confidence {confidence:.0%} — some fields may be incomplete"))

    # No comparables
    scoring = listing.get("_scoring", {})
    if scoring.get("comparable_cluster_count", 0) == 0:
        items.append(("📋", "No comparable clusters yet — get 3 independent price quotes before committing"))

    # Estimated unknown costs
    entry_type = listing.get("entry_type", "compound")
    bua = listing.get("bua_sqm") or 0
    project = (listing.get("project_name_raw") or "").lower()

    # Maintenance estimate based on entry type and known projects
    if entry_type == "compound":
        # Known high-maintenance compounds
        if any(p in project for p in ["hyde park", "هايد بارك", "mivida", "ميفيدا", "palm hills", "بالم هيلز", "mountain view", "lake view", "swan lake", "eastown", "villette"]):
            maint_low  = int(bua * 500)
            maint_high = int(bua * 800)
        else:
            maint_low  = int(bua * 300)
            maint_high = int(bua * 600)
        maint_note = f"~EGP {maint_low:,}–{maint_high:,}/year (compound maintenance estimate)"
    elif entry_type == "neighborhood":
        maint_low  = int(bua * 50)
        maint_high = int(bua * 150)
        maint_note = f"~EGP {maint_low:,}–{maint_high:,}/year (open neighborhood estimate)"
    else:
        maint_low  = int(bua * 200)
        maint_high = int(bua * 500)
        maint_note = f"~EGP {maint_low:,}–{maint_high:,}/year (estimate)"

    # Club membership
    if entry_type == "compound":
        club_note = "Club membership: EGP 150,000–500,000 one-time (confirm with developer)"
    else:
        club_note = None

    # Developer transfer fee
    cash_now = listing.get("seller_cash_required_now") or 0
    remaining = listing.get("remaining_with_developer") or 0
    contract_value = cash_now + remaining
    if contract_value > 0:
        transfer_low  = int(contract_value * 0.01)
        transfer_high = int(contract_value * 0.025)
        transfer_note = f"Developer transfer fee: ~EGP {transfer_low:,}–{transfer_high:,} (1–2.5% of contract value — confirm with developer)"
    else:
        transfer_note = "Developer transfer fee: confirm with developer"

    if not items and not maint_note:
        return ""

    rows = "".join(
        f'<li style="margin-bottom:3px;">'
        f'<span style="margin-right:4px;">{icon}</span>{text}</li>'
        for icon, text in items
    )

    cost_rows = f'<li style="margin-bottom:3px;">💰 Maintenance: {maint_note}</li>'
    if club_note:
        cost_rows += f'<li style="margin-bottom:3px;">💰 {club_note}</li>'
    cost_rows += f'<li style="margin-bottom:3px;">💰 {transfer_note}</li>'
    cost_rows += f'<li style="margin-bottom:3px;">💰 Legal/notarization: EGP 5,000–20,000</li>'

    return f"""
      <div style="margin-top:12px;padding:10px;background:#fff8e1;border-left:3px solid #f59e0b;border-radius:0 4px 4px 0;font-size:12px;">
        <div style="font-weight:bold;margin-bottom:6px;color:#92400e;">What to check for this unit</div>
        {f'<ul style="margin:0 0 8px 0;padding-left:16px;color:#78350f;">{rows}</ul>' if items else ''}
        <div style="font-weight:bold;margin:6px 0 4px;color:#92400e;">Estimated costs not in cash-equivalent</div>
        <ul style="margin:0;padding-left:16px;color:#78350f;">{cost_rows}</ul>
      </div>"""


def _build_project_intel(listing: dict, ref_project: dict | None) -> str:
    """Build project intelligence section from reference dataset."""
    if not ref_project:
        return ""

    maturity   = ref_project.get("project_maturity", "unknown")
    liquidity  = ref_project.get("liquidity_tier", "unknown")
    delivery   = ref_project.get("delivery_track_record", "unknown")
    notes      = ref_project.get("notes", "")

    maturity_labels = {
        "established": ("✅", "Established community — people living there, amenities active"),
        "emerging":    ("🔄", "Emerging — still developing, community not yet fully formed"),
        "new_standalone": ("⚠️", "New standalone — no track record yet"),
        "unknown":     ("❓", "Community status unknown"),
    }
    liquidity_labels = {
        "high":    ("🟢", "High resale liquidity — easy to sell if needed"),
        "medium":  ("🟡", "Medium resale liquidity"),
        "low":     ("🔴", "Low resale liquidity — harder to exit"),
        "unknown": ("❓", "Resale liquidity unknown"),
    }
    delivery_labels = {
        "excellent": ("✅", "Excellent delivery track record"),
        "good":      ("✅", "Good delivery track record"),
        "fair":      ("⚠️", "Fair delivery track record — some delays reported"),
        "completed": ("✅", "Completed — fully delivered"),
        "unknown":   ("❓", "Delivery track record unknown"),
    }

    m_icon, m_text = maturity_labels.get(maturity, ("❓", maturity))
    l_icon, l_text = liquidity_labels.get(liquidity, ("❓", liquidity))
    d_icon, d_text = delivery_labels.get(delivery, ("❓", delivery))

    notes_html = f'<li style="margin-bottom:3px;">📝 {notes}</li>' if notes else ""

    return f"""
      <div style="margin-top:10px;padding:10px;background:#f0f4ff;border-left:3px solid #4361ee;border-radius:0 4px 4px 0;font-size:12px;">
        <div style="font-weight:bold;margin-bottom:6px;color:#1a1a2e;">Project intelligence</div>
        <ul style="margin:0;padding-left:16px;color:#333;">
          <li style="margin-bottom:3px;">{m_icon} Community: {m_text}</li>
          <li style="margin-bottom:3px;">{l_icon} Resale liquidity: {l_text}</li>
          <li style="margin-bottom:3px;">{d_icon} Developer delivery: {d_text}</li>
          {notes_html}
        </ul>
      </div>"""

def _listing_card(listing: dict, rank: int, is_lead: bool = False, ref_project: dict | None = None) -> str:
    s = listing.get("_scoring", {})

    project    = listing.get("project_name_raw") or "Unknown project"
    dev_raw    = listing.get("developer_raw") or ""
    # Strip page title artifacts — dev_raw may contain "Project — Type size" format
    # Keep only the part before " — " and before the first "·"
    dev        = dev_raw.split(" — ")[0].split(" · ")[0].strip() if dev_raw else "" 
    loc        = listing.get("location_raw") or ""
    entry_type = listing.get("entry_type", "compound")
    entry_labels = {"compound": "🏘 Compound", "neighborhood": "🏙 Neighborhood", "small_compound": "🏠 Small Compound"}
    entry_badge  = entry_labels.get(entry_type, "🏘 Compound")
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
    overdue_egp = listing.get("known_overdue_amounts", 0) or 0
    overdue_str = f"EGP {overdue_egp:,.0f}" if overdue_egp else ""
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
          <div style="font-size:13px;margin-top:2px;">
            <span style="background:#e8f5e9;color:#2d6a4f;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:bold;">{entry_badge}</span>
            {'&nbsp;<strong>' + dev + '</strong>' if dev else ''}
            <span style="color:{C_MUTED};"> · {loc} · {uid}</span>
          </div>
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

      {_build_project_intel(listing, ref_project) or ''}
      {_build_verify_section(listing, overdue_str)}

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
        _listing_card(l, i + 1, is_lead=True, ref_project=l.get("_ref_project")) for i, l in enumerate(leads)
    )
    leads_html += _dd_checklist()

    # ── Top 10 full list ────────────────────────────────────────────────────
    top10_html = f"<h2 style='color:{C_PRIMARY};margin:32px 0 12px;'>Top 10 ranked opportunities</h2>"
    top10_html += "".join(
        _listing_card(l, i + 1, ref_project=l.get("_ref_project")) for i, l in enumerate(top10)
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
