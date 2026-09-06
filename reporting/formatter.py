"""
HTML email formatter for the daily report — v9.

Rebuilt from scratch with string concatenation (no large f-strings).
Uses only email-safe HTML: tables, divs, inline styles. No <details>, no flexbox.
Every section is built by a separate function that returns a plain string.
"""
from __future__ import annotations

# ── Palette ───────────────────────────────────────────────────────────────────
C_BG      = "#f8f9fa"
C_CARD    = "#ffffff"
C_BORDER  = "#dee2e6"
C_PRIMARY = "#1a1a2e"
C_ACCENT  = "#e63946"
C_GREEN   = "#2d6a4f"
C_AMBER   = "#d4a017"
C_MUTED   = "#6c757d"
C_FLAG    = "#fff3cd"
C_INTEL   = "#f0f4ff"
C_VERIFY  = "#fff8e1"


# ── Helpers ───────────────────────────────────────────────────────────────────

def egp(v) -> str:
    if v is None:
        return "—"
    try:
        return "EGP " + "{:,.0f}".format(float(v))
    except (TypeError, ValueError):
        return "—"


def pct(v) -> str:
    if v is None:
        return "—"
    try:
        v = float(v)
        sign = "+" if v >= 0 else ""
        return sign + "{:.1f}%".format(v)
    except (TypeError, ValueError):
        return "—"


def esc(text) -> str:
    """Escape HTML special characters."""
    if text is None:
        return ""
    s = str(text)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def score_colour(score: int) -> str:
    if score >= 80:
        return C_GREEN
    if score >= 60:
        return C_AMBER
    return C_ACCENT


def score_display(score: int) -> str:
    colour = score_colour(score)
    return ('<span style="color:' + colour + ';font-weight:bold;font-size:18px;">'
            + str(score) + '</span>'
            + '<span style="color:' + C_MUTED + ';font-size:12px;"> / 100</span>')


def row(label: str, value: str, bg: str = "") -> str:
    """One two-column table row."""
    style = ' style="background:' + bg + ';"' if bg else ""
    return ('<tr' + style + '>'
            '<td style="padding:5px 8px;font-size:12px;color:#555 !important;">' + label + '</td>'
            '<td style="padding:5px 8px;font-size:12px;text-align:right;font-weight:bold;color:#212529 !important;">' + value + '</td>'
            '</tr>')


def table(rows_html: str) -> str:
    return ('<table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;margin:8px 0;">'
            + rows_html + '</table>')


def section_box(title: str, body_html: str, bg: str, border: str) -> str:
    return ('<div style="margin-top:10px;padding:10px;background:' + bg
            + ' !important;border-left:3px solid ' + border + ';border-radius:0 4px 4px 0;font-size:12px;color:#212529 !important;">'
            '<div style="font-weight:bold;margin-bottom:6px;color:#1a1a2e !important;">' + title + '</div>'
            + body_html + '</div>')


def li(text: str) -> str:
    return '<li style="margin-bottom:3px;color:#212529 !important;">' + text + '</li>'


def ul(items: list) -> str:
    return '<ul style="margin:0;padding-left:16px;">' + "".join(items) + '</ul>'


# ── Sections ──────────────────────────────────────────────────────────────────

def build_intel_section(ref: dict | None) -> str:
    """Project intelligence from reference dataset."""
    if not ref:
        return ""
    maturity  = ref.get("project_maturity") or "unknown"
    liquidity = ref.get("liquidity_tier") or "unknown"
    delivery  = ref.get("delivery_track_record") or "unknown"
    notes     = ref.get("notes") or ""

    m_map = {
        "established":    "✅ Established community — people living there, amenities active",
        "emerging":       "🔄 Emerging — still developing, community not fully formed",
        "new_standalone": "⚠️ New standalone — no track record yet",
    }
    l_map = {
        "high":   "🟢 High resale liquidity — easy to sell if needed",
        "medium": "🟡 Medium resale liquidity",
        "low":    "🔴 Low resale liquidity — harder to exit",
    }
    d_map = {
        "excellent": "✅ Excellent delivery track record",
        "good":      "✅ Good delivery track record",
        "fair":      "⚠️ Fair delivery track record — some delays reported",
        "completed": "✅ Completed — fully delivered",
    }

    items = [
        li("Community: " + m_map.get(maturity, "❓ Unknown")),
        li("Resale liquidity: " + l_map.get(liquidity, "❓ Unknown")),
        li("Developer delivery: " + d_map.get(delivery, "❓ Unknown")),
    ]
    if notes:
        items.append(li("📝 " + esc(notes)))

    return section_box("Project intelligence", ul(items), C_INTEL, "#4361ee")


def build_verify_section(listing: dict) -> str:
    """Per-listing checks and estimated costs."""
    items = []

    if listing.get("view_type", "not_specified") == "not_specified":
        items.append(li("❓ View type unknown — ask seller or check on-site"))
    if listing.get("parking_included", "not_specified") == "not_specified":
        items.append(li("❓ Parking status unknown — confirm with seller"))
    if listing.get("finishing_status", "not_specified") == "not_specified":
        items.append(li("❓ Finishing status not specified — verify on-site"))

    overdue = listing.get("known_overdue_amounts") or 0
    try:
        overdue = float(overdue)
    except (TypeError, ValueError):
        overdue = 0
    if overdue > 0:
        items.append(li("⚠️ Overdue installments: " + egp(overdue) + " — must be cleared before transfer"))

    if listing.get("upfront_exceeds_limit"):
        items.append(li("⚠️ Day-1 cash exceeds your EGP 4M limit — confirm you can cover this"))

    delivery_raw = str(listing.get("delivery_date_raw") or "")
    if any(y in delivery_raw for y in ["2025", "2026"]):
        items.append(li("📋 Delivery " + esc(delivery_raw) + " — verify actual date directly with developer"))

    confidence = listing.get("latest_data_confidence") or 0
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 0.85:
        items.append(li("📋 Data confidence " + "{:.0%}".format(confidence) + " — some fields may be incomplete"))

    scoring = listing.get("_scoring") or {}
    if (scoring.get("comparable_cluster_count") or 0) == 0:
        items.append(li("📋 No comparable clusters yet — get 3 independent price quotes before committing"))

    # Estimated costs
    entry_type = listing.get("entry_type") or "compound"
    bua = listing.get("bua_sqm") or 0
    try:
        bua = float(bua)
    except (TypeError, ValueError):
        bua = 0
    project = str(listing.get("project_name_raw") or "").lower()

    premium = any(p in project for p in [
        "hyde park", "هايد بارك", "mivida", "ميفيدا", "palm hills", "بالم هيلز",
        "mountain view", "ماونتن فيو", "lake view", "swan lake", "eastown", "villette",
    ])
    if entry_type == "neighborhood":
        m_lo, m_hi = int(bua * 50), int(bua * 150)
        m_note = "~EGP {:,}–{:,}/year (open neighborhood estimate)".format(m_lo, m_hi)
        club = None
    elif premium:
        m_lo, m_hi = int(bua * 500), int(bua * 800)
        m_note = "~EGP {:,}–{:,}/year (premium compound estimate)".format(m_lo, m_hi)
        club = "Club membership: EGP 150,000–500,000 one-time (confirm with developer)"
    else:
        m_lo, m_hi = int(bua * 300), int(bua * 600)
        m_note = "~EGP {:,}–{:,}/year (compound estimate)".format(m_lo, m_hi)
        club = "Club membership: EGP 150,000–500,000 one-time (confirm with developer)"

    cash = float(listing.get("seller_cash_required_now") or 0)
    remaining = float(listing.get("remaining_with_developer") or 0)
    contract = cash + remaining
    if contract > 0:
        t_lo, t_hi = int(contract * 0.01), int(contract * 0.025)
        transfer = "Developer transfer fee: ~EGP {:,}–{:,} (1–2.5% of contract value — confirm with developer)".format(t_lo, t_hi)
    else:
        transfer = "Developer transfer fee: confirm with developer"

    cost_items = [li("💰 Maintenance: " + m_note)]
    if club:
        cost_items.append(li("💰 " + club))
    cost_items.append(li("💰 " + transfer))
    cost_items.append(li("💰 Legal/notarization: EGP 5,000–20,000"))

    body = ""
    if items:
        body += ul(items)
    body += ('<div style="font-weight:bold;margin:8px 0 4px;color:' + C_PRIMARY + ';">'
             'Estimated costs not in cash-equivalent</div>' + ul(cost_items))

    return section_box("What to check for this unit", body, C_VERIFY, "#f59e0b")


def build_score_section(listing: dict, score: int) -> str:
    s = listing.get("_scoring") or {}

    def f1(v):
        try:
            return "{:.1f}".format(float(v or 0))
        except (TypeError, ValueError):
            return "0.0"

    rows_html = (
        row("Value vs comparables", f1(s.get("comparables_score")) + " / 40")
        + row("Unit quality", f1(s.get("unit_quality_score")) + " / 20", C_BG)
        + row("Project quality", f1(s.get("project_quality_score")) + " / 20")
        + row("Payment terms", f1(s.get("payment_terms_score")) + " / 15", C_BG)
        + row("Seller urgency", f1(s.get("urgency_score")) + " / 5")
        + '<tr style="border-top:1px solid ' + C_BORDER + ';">'
          '<td style="padding:5px 8px;font-size:12px;font-weight:bold;">Total</td>'
          '<td style="padding:5px 8px;font-size:12px;text-align:right;font-weight:bold;">'
          + str(score) + ' / 100</td></tr>'
    )
    return ('<div style="margin-top:8px;">'
            '<div style="color:' + C_MUTED + ';font-size:11px;margin-bottom:2px;">Score breakdown</div>'
            + table(rows_html) + '</div>')


def build_financial_section(listing: dict) -> str:
    cash      = listing.get("seller_cash_required_now")
    remaining = listing.get("remaining_with_developer")
    ae_fee    = listing.get("aqar_exit_fee_egp")
    total     = listing.get("total_required_now_egp")
    upfront   = listing.get("upfront_cash_required")
    exceeds   = listing.get("upfront_exceeds_limit")
    aoc       = listing.get("latest_annual_ownership_cost")
    clusters  = (listing.get("_scoring") or {}).get("comparable_cluster_count") or 0

    ce20 = listing.get("latest_cash_equivalent_20")
    ce25 = listing.get("latest_cash_equivalent_25")
    ce30 = listing.get("latest_cash_equivalent_30")
    discount = (listing.get("_scoring") or {}).get("discount_to_median_pct")

    rows_html = (
        row("Cash to seller now", egp(cash), C_BG)
        + row("Remaining with developer", egp(remaining))
        + row("Aqar Exit fee (1.25%)", egp(ae_fee), C_BG)
        + row("Total required now", '<span style="font-size:14px;">' + egp(total) + '</span>')
    )
    if exceeds:
        rows_html += ('<tr><td colspan="2" style="padding:6px 8px;background:' + C_FLAG
                      + ';font-size:12px;">⚠ Upfront cash ' + egp(upfront)
                      + ' exceeds EGP 4M limit — flagged, not excluded</td></tr>')
    rows_html += (
        row("Annual ownership cost", egp(aoc) + " / year", C_BG)
        + row("Comparable clusters", str(clusters) + " clusters")
    )

    ce_rows = (
        '<tr style="background:' + C_PRIMARY + ';color:#fff;">'
        '<th style="padding:5px 8px;text-align:left;font-size:11px;">Rate</th>'
        '<th style="padding:5px 8px;text-align:right;font-size:11px;">Cash-equivalent</th>'
        '<th style="padding:5px 8px;text-align:right;font-size:11px;">vs Median</th></tr>'
        '<tr><td style="padding:5px 8px;font-size:12px;">20% (conservative)</td>'
        '<td style="padding:5px 8px;font-size:12px;text-align:right;">' + egp(ce20) + '</td>'
        '<td style="padding:5px 8px;font-size:12px;text-align:right;">—</td></tr>'
        '<tr style="background:#e8f5e9;"><td style="padding:5px 8px;font-size:12px;font-weight:bold;">25% (ranking rate)</td>'
        '<td style="padding:5px 8px;font-size:12px;text-align:right;font-weight:bold;">' + egp(ce25) + '</td>'
        '<td style="padding:5px 8px;font-size:12px;text-align:right;font-weight:bold;">' + pct(discount) + '</td></tr>'
        '<tr><td style="padding:5px 8px;font-size:12px;">30% (aggressive)</td>'
        '<td style="padding:5px 8px;font-size:12px;text-align:right;">' + egp(ce30) + '</td>'
        '<td style="padding:5px 8px;font-size:12px;text-align:right;">—</td></tr>'
    )

    return table(rows_html) + table(ce_rows)


def build_card(listing: dict, rank: int, is_lead: bool = False) -> str:
    """One listing card — email-safe HTML."""
    project = esc(listing.get("project_name_raw") or "Unknown project")
    dev_raw = str(listing.get("developer_raw") or "")
    dev = esc(dev_raw.split(" — ")[0].split(" · ")[0].strip()) if dev_raw else ""
    loc = esc(listing.get("location_raw") or "")
    uid = esc(listing.get("unit_id") or "")
    url = esc(listing.get("source_url") or "#")

    entry_type = listing.get("entry_type") or "compound"
    badge_map = {"compound": "🏘 Compound", "neighborhood": "🏙 Neighborhood", "small_compound": "🏠 Small Compound"}
    badge = badge_map.get(entry_type, "🏘 Compound")

    ptype    = esc(str(listing.get("property_type") or "").capitalize())
    beds     = esc(listing.get("bedroom_count") or "—")
    bua      = esc(listing.get("bua_sqm") or "—")
    floor    = esc(listing.get("floor_number") or "—")
    view     = esc(str(listing.get("view_type") or "not specified").replace("_", " "))
    finish   = esc(str(listing.get("finishing_status") or "not specified").replace("_", " "))
    delivery = esc(listing.get("delivery_date_raw") or "—")

    score = int(listing.get("latest_score") or 0)
    conf  = listing.get("latest_data_confidence")
    try:
        conf_pct = "{:.0%}".format(float(conf))
    except (TypeError, ValueError):
        conf_pct = "—"

    negotiable = listing.get("is_negotiable")
    docs       = listing.get("documents_verified")
    flags = []
    if negotiable:
        flags.append('<span style="color:' + C_GREEN + ';">✓ Open to negotiation</span>')
    if docs:
        flags.append('<span style="color:' + C_GREEN + ';">✓ Documents verified</span>')
    flags_html = ("&nbsp;&nbsp;" + " &nbsp; ".join(flags)) if flags else ""

    border = C_GREEN if is_lead else C_BORDER
    lead_label = ""
    if is_lead:
        label = listing.get("label") or "High-Potential Lead"
        lc = C_GREEN if "Best Deal" in label else C_AMBER
        lead_label = ('&nbsp;<span style="background:' + lc
                      + ';color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">'
                      + esc(label) + '</span>')

    ref = listing.get("_ref_project")

    html = (
        '<div style="border:2px solid ' + border + ';border-radius:8px;padding:16px;margin-bottom:16px;background:' + C_CARD + ' !important;color:#212529 !important;">'

        # Header row (table for email compatibility)
        '<table cellpadding="0" cellspacing="0" style="width:100%;">'
        '<tr>'
        '<td style="vertical-align:top;">'
        '<span style="color:' + C_MUTED + ';font-size:12px;">#' + str(rank) + '</span>' + lead_label +
        '<h3 style="margin:4px 0;color:' + C_PRIMARY + ';font-size:15px;">'
        '<a href="' + url + '" style="color:' + C_PRIMARY + ';text-decoration:none;">' + project + '</a></h3>'
        '<div style="font-size:12px;">'
        '<span style="background:#e8f5e9;color:' + C_GREEN + ';padding:2px 6px;border-radius:4px;font-size:11px;font-weight:bold;">' + badge + '</span>'
        + ('&nbsp;<strong>' + dev + '</strong>' if dev else "")
        + '<span style="color:' + C_MUTED + ';"> · ' + loc + ' · ' + uid + '</span>'
        '</div>'
        '</td>'
        '<td style="vertical-align:top;text-align:right;white-space:nowrap;">'
        + score_display(score) +
        '<div style="font-size:11px;color:' + C_MUTED + ';">Confidence: ' + conf_pct + '</div>'
        '</td>'
        '</tr>'
        '</table>'

        # Unit summary
        '<div style="margin:10px 0;padding:8px 10px;background:' + C_BG + ';border-radius:5px;font-size:12px;">'
        '<strong>' + ptype + '</strong> · ' + str(beds) + ' BR · ' + str(bua) + ' m² · Floor ' + str(floor)
        + ' · ' + view + ' · ' + finish + ' · Delivery ' + delivery + flags_html +
        '</div>'

        + build_financial_section(listing)
        + build_score_section(listing, score)
        + build_intel_section(ref)
        + build_verify_section(listing)

        + '<div style="margin-top:10px;font-size:12px;">'
        '<a href="' + url + '" style="color:' + C_ACCENT + ';">View on Aqar Exit →</a>'
        '</div>'
        '</div>'
    )
    return html


def build_dd_checklist() -> str:
    bd = [
        "Seller identity matches contract purchaser/assignee",
        "Original contract verified against listing details",
        "Official developer account statement obtained (not seller's claim)",
        "Developer permits resale — assignment fee and timeline confirmed with CRM",
        "Payment-plan transferability confirmed",
    ]
    other = [
        "No co-owner, divorce, lien, court dispute, or blocking claim",
        "Realistic delivery date verified (not advertised date)",
        "Broker/brokerage GOEIC registration verified where applicable",
        "At least 3 comparable clusters obtained independently",
    ]
    items = [li("<strong>[BD] " + esc(x) + "</strong>") for x in bd] + [li(esc(x)) for x in other]
    return ('<div style="background:' + C_BG + ';border:1px solid ' + C_BORDER
            + ';border-radius:6px;padding:14px;margin-bottom:24px;">'
            '<div style="font-weight:bold;margin-bottom:6px;color:' + C_PRIMARY + ';">Due diligence checklist</div>'
            '<div style="font-size:12px;color:' + C_MUTED + ';margin-bottom:8px;">'
            'Items marked [BD] must be verified before any listing can be labelled Best Deal. '
            'Until verified: high-potential lead only.</div>'
            '<ul style="font-size:12px;margin:0;padding-left:18px;">' + "".join(items) + '</ul>'
            '</div>')


def build_needs_data(listings: list) -> str:
    if not listings:
        return ""
    rows_html = ""
    for l in listings:
        name = esc(l.get("project_name_raw") or "—") + " " + esc(l.get("unit_id") or "")
        url  = esc(l.get("source_url") or "#")
        rows_html += (
            '<tr>'
            '<td style="padding:6px 8px;border-bottom:1px solid ' + C_BORDER + ';font-size:12px;">'
            '<a href="' + url + '" style="color:' + C_ACCENT + ';">' + name + '</a></td>'
            '<td style="padding:6px 8px;border-bottom:1px solid ' + C_BORDER + ';font-size:12px;">'
            + esc(l.get("property_type") or "") + '</td>'
            '<td style="padding:6px 8px;border-bottom:1px solid ' + C_BORDER + ';font-size:12px;">'
            + esc(l.get("bedroom_count") or "—") + ' BR / ' + esc(l.get("bua_sqm") or "—") + ' m²</td>'
            '<td style="padding:6px 8px;border-bottom:1px solid ' + C_BORDER + ';font-size:11px;color:' + C_MUTED + ';">'
            + esc(l.get("exclusion_reason") or "") + '</td>'
            '</tr>'
        )
    return (
        '<h2 style="color:' + C_PRIMARY + ';font-size:17px;margin:32px 0 10px;">Needs data — potentially eligible</h2>'
        '<p style="color:' + C_MUTED + ';font-size:12px;margin:0 0 10px;">'
        'These listings were not ranked because key fields are missing. '
        'Open each on Aqar Exit to complete the data manually via the intake form.</p>'
        '<table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">'
        '<tr style="background:' + C_PRIMARY + ';color:#fff;">'
        '<th style="padding:7px 8px;text-align:left;font-size:12px;">Project</th>'
        '<th style="padding:7px 8px;text-align:left;font-size:12px;">Type</th>'
        '<th style="padding:7px 8px;text-align:left;font-size:12px;">Size</th>'
        '<th style="padding:7px 8px;text-align:left;font-size:12px;">Missing</th>'
        '</tr>' + rows_html + '</table>'
    )


# ── Public API ────────────────────────────────────────────────────────────────

def build_html(data: dict) -> str:
    top10      = data.get("top10") or []
    leads      = data.get("leads") or []
    needs_data = data.get("needs_data") or []
    run_dt     = esc(data.get("run_datetime") or "")
    total      = data.get("total_eligible") or 0

    header = (
        '<div style="background:' + C_PRIMARY + ';color:#fff;padding:20px;border-radius:8px 8px 0 0;margin-bottom:20px;">'
        '<div style="font-size:20px;font-weight:bold;">Cairo Deal-Finder</div>'
        '<div style="font-size:12px;opacity:0.75;margin-top:4px;">Daily report · ' + run_dt
        + ' · ' + str(total) + ' eligible listings in database</div>'
        '</div>'
    )

    has_verified = any(l.get("is_stage1_eligible") for l in leads)
    leads_title = "Top 3 — includes verified Best Deal(s)" if has_verified else "Top 3 high-potential leads"
    leads_html = '<h2 style="color:' + C_PRIMARY + ';font-size:17px;margin-bottom:10px;">' + leads_title + '</h2>'
    for i, l in enumerate(leads):
        try:
            leads_html += build_card(l, i + 1, is_lead=True)
        except Exception as e:
            leads_html += ('<div style="color:red;padding:10px;">Card error #' + str(i + 1) + ': ' + esc(str(e)) + '</div>')

    leads_html += build_dd_checklist()

    top10_html = '<h2 style="color:' + C_PRIMARY + ';font-size:17px;margin:28px 0 10px;">Top 10 ranked opportunities</h2>'
    for i, l in enumerate(top10):
        try:
            top10_html += build_card(l, i + 1)
        except Exception as e:
            top10_html += ('<div style="color:red;padding:10px;">Card error #' + str(i + 1) + ': ' + esc(str(e)) + '</div>')

    nd_html = build_needs_data(needs_data)

    footer = (
        '<div style="border-top:1px solid ' + C_BORDER + ';margin-top:28px;padding-top:14px;'
        'color:' + C_MUTED + ';font-size:11px;text-align:center;">'
        '<p style="margin:4px 0;">Cash-equivalent uses 25% annual EGP discount rate for ranking. '
        'All comparables are active asking prices — not completed-sale values.</p>'
        '<p style="margin:4px 0;">A listing cannot be marked Best Deal until Stage 2 human verification is complete.</p>'
        '<p style="margin:4px 0;">Cairo Deal-Finder · Personal research tool · Not financial advice</p>'
        '</div>'
    )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
        'max-width:680px;margin:0 auto;padding:14px;background:' + C_BG + ' !important;color:#212529 !important;">'
        + header + leads_html + top10_html + nd_html + footer +
        '</body></html>'
    )


def build_subject(data: dict) -> str:
    leads = data.get("leads") or []
    top   = leads[0] if leads else None
    score = (top.get("latest_score") or 0) if top else 0
    proj  = (top.get("project_name_raw") or "—") if top else "—"
    ce25  = top.get("latest_cash_equivalent_25") if top else None
    price = egp(ce25) if ce25 else "—"
    run_dt = data.get("run_datetime") or data.get("run_date") or ""
    return "[" + str(run_dt) + "] Top deal: " + str(proj) + " — Score " + str(score) + "/100 — " + price
