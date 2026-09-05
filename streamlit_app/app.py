"""
Cairo Deal-Finder — Streamlit Dashboard
Personal CRM for 5th Settlement property opportunities.

Pages:
  🏠 Dashboard   — search, filter, rank, mark status
  📋 Intake      — paste listing text → Claude normalizes → save to DB
  📊 Pipeline    — pipeline run status and stats
  ❓ Needs Data  — listings requiring manual completion
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
import anthropic
import json
import pytz
import pandas as pd
from datetime import datetime
from supabase import create_client

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Cairo Deal-Finder",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

CAIRO_TZ = pytz.timezone("Africa/Cairo")


# ── Auth ──────────────────────────────────────────────────────────────────────
def check_auth() -> bool:
    if st.session_state.get("authenticated"):
        return True
    pwd = st.text_input("Password", type="password", key="login_pwd")
    if st.button("Login"):
        if pwd == st.secrets.get("APP_PASSWORD", ""):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Wrong password")
    return False


# ── DB client (cached per session) ───────────────────────────────────────────
@st.cache_resource
def get_db():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


@st.cache_resource
def get_claude():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


# ── Helpers ───────────────────────────────────────────────────────────────────
def egp(v) -> str:
    if v is None: return "—"
    if v >= 1_000_000: return f"EGP {v/1_000_000:.2f}M"
    return f"EGP {v:,.0f}"


def score_colour(s: int) -> str:
    if s >= 80: return "🟢"
    if s >= 60: return "🟡"
    return "🔴"


def now_cairo() -> str:
    return datetime.now(CAIRO_TZ).isoformat()


# ── EXTRACTION PROMPT ─────────────────────────────────────────────────────────
EXTRACT_PROMPT = """You are a real estate data extraction engine for the Egyptian market.
Extract structured data from the listing text below.
Return valid JSON only — no explanation, no markdown, no preamble.

Schema:
{
  "project_name_raw": string or null,
  "entry_type": "compound"|"neighborhood"|"small_compound"|"unknown",
  "property_type": "apartment"|"duplex"|"ivilla"|"s_villa"|"quattro"|"villa"|"townhouse"|"twinhouse"|"penthouse"|"other"|"unknown",
  "bedroom_count": integer or null,
  "master_bedroom_ensuite": "yes"|"no"|"not_specified",
  "bua_sqm": number or null,
  "floor_number": string or null,
  "view_type": "garden_view"|"landscape_view"|"open_view"|"pool_view"|"street_view"|"internal_view"|"not_specified",
  "view_notes": string or null,
  "private_garden": "yes"|"no"|"not_specified",
  "roof_terrace": "yes"|"no"|"not_specified",
  "parking_included": "yes"|"no"|"separate_cost"|"not_specified",
  "parking_cost_egp": number or null,
  "finishing_status": "fully_finished"|"semi_finished"|"core_and_shell"|"not_specified",
  "finishing_notes": string or null,
  "delivery_status": "ready_to_move"|"delivered_not_finished"|"under_construction"|"not_specified",
  "delivery_date_raw": string or null,
  "seller_cash_required_now": number or null,
  "future_developer_payment_schedule": []|[{"amount":number,"due_date":string|null,"due_date_confidence":"confirmed"|"estimated"|"unknown","notes":string}]|"UNKNOWN",
  "upfront_transaction_fees": []|[{"fee_type":string,"amount_egp":number|null,"amount_confirmed":boolean,"notes":string}]|"UNKNOWN",
  "known_overdue_amounts": number or null,
  "recurring_ownership_costs": []|[{"cost_type":string,"amount_egp":number|null,"frequency":string,"notes":string}],
  "schedule_source": "developer_statement"|"seller_claim"|"listing_text"|"unknown",
  "schedule_confidence": "high"|"medium"|"low"|"unknown",
  "seller_type": "owner"|"broker"|"unknown",
  "urgency_keywords_detected": [],
  "price_basis_note": string,
  "data_flags": [],
  "contradictions_detected": []
}

Rules:
- BUA = internal area only. Never add garden/terrace to BUA.
- Bedroom count: nanny room is NOT a bedroom.
- seller_cash_required_now: null = unknown (not zero).
- future_developer_payment_schedule: [] = confirmed cash deal. "UNKNOWN" = exists but details not given.
- known_overdue_amounts: 0 = confirmed none. null = unknown.
- Never invent values. Never calculate totals from percentages.
- If price basis is ambiguous (cash OR installment), set seller_cash_required_now=null and schedule="UNKNOWN".
- Flag contradictions in contradictions_detected.

Listing text:
{listing_text}"""


# ════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

def page_dashboard():
    st.title("🏠 Deal Dashboard")
    db = get_db()

    # ── Filters sidebar ────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Filters")
        status_filter = st.multiselect(
            "Status", ["new", "watching", "contacted", "not_interested"],
            default=["new", "watching"],
        )
        min_score = st.slider("Minimum score", 0, 100, 50)
        max_upfront = st.number_input(
            "Max upfront cash (EGP M)", value=4.0, step=0.5
        ) * 1_000_000
        show_flagged = st.checkbox("Hide upfront >4M listings", value=False)
        project_search = st.text_input("Project name search")

    # ── Query ──────────────────────────────────────────────────────────────
    query = (
        db.table("listings")
        .select(
            "id, source_url, project_name_raw, developer_raw, location_raw, "
            "property_type, bedroom_count, bua_sqm, floor_number, view_type, "
            "finishing_status, delivery_date_raw, "
            "seller_cash_required_now, remaining_with_developer, "
            "installments_remaining_years, aqar_exit_fee_egp, "
            "latest_score, latest_cash_equivalent_25, latest_data_confidence, "
            "upfront_cash_required, upfront_exceeds_limit, "
            "user_status, is_negotiable, documents_verified, unit_id, "
            "first_seen_at, last_seen_at"
        )
        .eq("eligibility_status", "eligible")
        .gte("latest_score", min_score)
        .order("latest_score", desc=True)
        .limit(200)
    )

    if status_filter:
        query = query.in_("user_status", status_filter)
    if show_flagged:
        query = query.eq("upfront_exceeds_limit", False)
    if project_search:
        query = query.ilike("project_name_raw", f"%{project_search}%")

    resp     = query.execute()
    listings = resp.data or []

    # Local upfront filter (Supabase can't filter on null upfront)
    if max_upfront < 10_000_000:
        listings = [
            l for l in listings
            if (l.get("upfront_cash_required") or 0) <= max_upfront
            or l.get("upfront_cash_required") is None
        ]

    st.caption(f"{len(listings)} listings match your filters")

    if not listings:
        st.info("No listings match your filters. Try adjusting the minimum score or status.")
        return

    # ── Listing cards ──────────────────────────────────────────────────────
    for listing in listings:
        _render_listing_card(db, listing)


def _render_listing_card(db, listing: dict):
    lid       = listing["id"]
    project   = listing.get("project_name_raw") or "Unknown"
    dev       = listing.get("developer_raw") or ""
    ptype     = (listing.get("property_type") or "").capitalize()
    beds      = listing.get("bedroom_count") or "—"
    bua       = listing.get("bua_sqm") or "—"
    score     = listing.get("latest_score") or 0
    ce25      = listing.get("latest_cash_equivalent_25")
    upfront   = listing.get("upfront_cash_required")
    exceeds   = listing.get("upfront_exceeds_limit")
    status    = listing.get("user_status", "new")
    url       = listing.get("source_url") or "#"
    uid       = listing.get("unit_id") or ""
    negotiable = listing.get("is_negotiable")
    docs       = listing.get("documents_verified")
    floor_raw  = listing.get("floor_number") or "—"
    view       = (listing.get("view_type") or "").replace("_", " ")
    finish     = (listing.get("finishing_status") or "").replace("_", " ")
    delivery   = listing.get("delivery_date_raw") or "—"
    confidence = listing.get("latest_data_confidence") or 0
    rem_years  = listing.get("installments_remaining_years") or 0

    icon = score_colour(score)
    flag = " ⚠️ upfront >4M" if exceeds else ""

    with st.expander(
        f"{icon} **{project}** — {ptype} {beds}BR/{bua}m² — "
        f"Score {score}/100 — {egp(ce25)} @ 25%{flag}",
        expanded=False,
    ):
        col1, col2, col3 = st.columns([2, 2, 1])

        with col1:
            st.markdown(f"**{project}** · {dev}")
            st.caption(f"{uid} · {ptype} · {beds} BR · {bua} m² · Floor {floor_raw}")
            st.caption(f"View: {view} · Finish: {finish} · Delivery: {delivery}")
            badges = []
            if negotiable: badges.append("✅ Open to negotiation")
            if docs:       badges.append("✅ Docs verified")
            if badges: st.caption(" · ".join(badges))

        with col2:
            st.metric("Cash to seller", egp(listing.get("seller_cash_required_now")))
            st.metric("Remaining w/ developer", egp(listing.get("remaining_with_developer")))
            st.metric("Day-1 total required", egp(upfront))
            if rem_years:
                st.caption(f"~{rem_years} years installments remaining")
            st.metric("Cash-equiv @ 25%", egp(ce25))
            st.caption(f"Data confidence: {confidence:.0%}")

        with col3:
            st.markdown(f"**Score: {score}/100**")
            st.link_button("Open on Aqar Exit", url)

            # Status selector
            new_status = st.selectbox(
                "My status",
                ["new", "watching", "contacted", "not_interested"],
                index=["new","watching","contacted","not_interested"].index(status),
                key=f"status_{lid}",
            )
            if new_status != status:
                db.table("listings").update(
                    {"user_status": new_status}
                ).eq("id", lid).execute()
                st.success("Updated")
                st.rerun()

            # Notes
            current_notes = listing.get("user_notes") or ""
            notes = st.text_area("Notes", value=current_notes, key=f"notes_{lid}", height=80)
            if st.button("Save notes", key=f"savenotes_{lid}"):
                db.table("listings").update(
                    {"user_notes": notes}
                ).eq("id", lid).execute()
                st.success("Saved")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: INTAKE FORM
# ════════════════════════════════════════════════════════════════════════════

def page_intake():
    st.title("📋 Manual Listing Intake")
    st.caption(
        "Paste raw listing text (Arabic or English) — Claude extracts structured fields. "
        "Review and correct before saving to the database."
    )

    db     = get_db()
    claude = get_claude()

    raw_text = st.text_area(
        "Paste listing text here",
        height=200,
        placeholder=(
            "تاج سيتي - شقة 3 غرف - 165 متر\n"
            "المطلوب من المشتري 3,500,000 جنيه\n"
            "الباقي 7,100,000 أقساط...\n\n"
            "Or English listing text..."
        ),
    )

    source_url = st.text_input(
        "Source URL (optional)",
        placeholder="https://aqarexit.com/en/buy/opportunity/..."
    )

    col_extract, col_clear = st.columns([1, 5])
    with col_extract:
        extract_btn = st.button("🔍 Extract with Claude", type="primary", disabled=not raw_text)
    with col_clear:
        if st.button("Clear"):
            st.session_state.pop("extracted", None)
            st.rerun()

    if extract_btn and raw_text:
        with st.spinner("Extracting fields..."):
            try:
                resp = claude.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2000,
                    messages=[{
                        "role": "user",
                        "content": EXTRACT_PROMPT.format(listing_text=raw_text)
                    }],
                )
                raw_json = resp.content[0].text.strip()
                if raw_json.startswith("```"):
                    raw_json = raw_json.split("\n", 1)[1].rsplit("```", 1)[0]
                extracted = json.loads(raw_json)
                st.session_state["extracted"] = extracted
                st.session_state["raw_text"]  = raw_text
            except Exception as e:
                st.error(f"Extraction failed: {e}")

    if "extracted" in st.session_state:
        ext = st.session_state["extracted"]
        st.divider()
        st.subheader("Extracted fields — review and correct")

        # ── Flags and contradictions ───────────────────────────────────────
        flags = ext.get("data_flags") or []
        contras = ext.get("contradictions_detected") or []
        if flags or contras:
            with st.expander("⚠️ Flags and contradictions", expanded=True):
                for f in flags:    st.warning(f)
                for c in contras:  st.error(f"Contradiction: {c}")

        st.info(f"**Price basis note:** {ext.get('price_basis_note','—')}")

        # ── Editable fields ────────────────────────────────────────────────
        c1, c2 = st.columns(2)
        with c1:
            project    = st.text_input("Project name", value=ext.get("project_name_raw") or "")
            entry_type = st.selectbox("Entry type",
                ["compound","neighborhood","small_compound","unknown"],
                index=["compound","neighborhood","small_compound","unknown"].index(
                    ext.get("entry_type","unknown")
                ))
            ptype = st.selectbox("Property type",
                ["apartment","duplex","ivilla","s_villa","quattro","villa",
                 "townhouse","twinhouse","penthouse","other","unknown"],
                index=["apartment","duplex","ivilla","s_villa","quattro","villa",
                       "townhouse","twinhouse","penthouse","other","unknown"].index(
                    ext.get("property_type","unknown")
                ))
            beds      = st.number_input("Bedrooms", min_value=0, max_value=10,
                            value=int(ext.get("bedroom_count") or 0))
            bua       = st.number_input("BUA (sqm)", min_value=0.0,
                            value=float(ext.get("bua_sqm") or 0))
            floor_raw = st.text_input("Floor", value=str(ext.get("floor_number") or ""))
        with c2:
            finishing = st.selectbox("Finishing",
                ["fully_finished","semi_finished","core_and_shell","not_specified"],
                index=["fully_finished","semi_finished","core_and_shell","not_specified"].index(
                    ext.get("finishing_status","not_specified")
                ))
            delivery  = st.selectbox("Delivery status",
                ["ready_to_move","delivered_not_finished","under_construction","not_specified"],
                index=["ready_to_move","delivered_not_finished","under_construction","not_specified"].index(
                    ext.get("delivery_status","not_specified")
                ))
            delivery_raw = st.text_input("Delivery date (raw)",
                value=ext.get("delivery_date_raw") or "")
            view = st.selectbox("View type",
                ["open_view","garden_view","pool_view","landscape_view",
                 "street_view","internal_view","not_specified"],
                index=["open_view","garden_view","pool_view","landscape_view",
                       "street_view","internal_view","not_specified"].index(
                    ext.get("view_type","not_specified")
                ))
            parking = st.selectbox("Parking",
                ["yes","no","separate_cost","not_specified"],
                index=["yes","no","separate_cost","not_specified"].index(
                    ext.get("parking_included","not_specified")
                ))

        st.subheader("Transaction legs")
        c3, c4 = st.columns(2)
        with c3:
            cash_now = st.number_input(
                "Seller cash required now (EGP) — 0 if unknown",
                min_value=0, value=int(ext.get("seller_cash_required_now") or 0),
                step=10000,
            )
            cash_known = st.checkbox(
                "Cash amount is confirmed (not estimated)",
                value=ext.get("seller_cash_required_now") is not None,
            )
            overdue = st.number_input(
                "Known overdue amounts (EGP) — 0 if confirmed none",
                min_value=0, value=int(ext.get("known_overdue_amounts") or 0),
                step=1000,
            )
            overdue_confirmed = st.checkbox("Overdue confirmed (0 = confirmed none)", value=True)

        with c4:
            sched_raw = ext.get("future_developer_payment_schedule")
            schedule_unknown = (sched_raw == "UNKNOWN")
            sched_str = st.text_area(
                "Installment schedule (JSON array or 'UNKNOWN')",
                value=json.dumps(sched_raw, ensure_ascii=False, indent=2) if sched_raw else "[]",
                height=120,
            )
            sched_src = st.selectbox("Schedule source",
                ["developer_statement","seller_claim","listing_text","unknown"],
                index=["developer_statement","seller_claim","listing_text","unknown"].index(
                    ext.get("schedule_source","unknown")
                ))
            seller_type = st.selectbox("Seller type",
                ["owner","broker","unknown"],
                index=["owner","broker","unknown"].index(
                    ext.get("seller_type","unknown")
                ))

        # ── Save button ────────────────────────────────────────────────────
        st.divider()
        if st.button("💾 Save to database", type="primary"):
            try:
                sched_parsed = json.loads(sched_str)
            except Exception:
                sched_parsed = "UNKNOWN"

            record = {
                "source_name":                 "manual",
                "source_url":                  source_url or None,
                "advertised_price_text":       (st.session_state.get("raw_text") or "")[:500],
                "currency":                    "EGP",
                "captured_at":                 now_cairo(),
                "raw_content_hash":            __import__("hashlib").sha256(
                    (st.session_state.get("raw_text","")).encode()
                ).hexdigest(),
                "project_name_raw":            project or None,
                "entry_type":                  entry_type,
                "property_type":               ptype,
                "bedroom_count":               beds or None,
                "bua_sqm":                     bua or None,
                "floor_number":                floor_raw or None,
                "finishing_status":            finishing,
                "delivery_status":             delivery,
                "delivery_date_raw":           delivery_raw or None,
                "view_type":                   view,
                "parking_included":            parking,
                "seller_cash_required_now":    float(cash_now) if cash_known and cash_now else None,
                "seller_cash_required_confirmed": cash_known,
                "known_overdue_amounts":       float(overdue) if overdue_confirmed else None,
                "known_overdue_confirmed":     overdue_confirmed,
                "schedule_source":             sched_src,
                "schedule_confidence":         ext.get("schedule_confidence","unknown"),
                "seller_type":                 seller_type,
                "normalization_status":        "normalized",
                "normalization_model":         "claude-sonnet-4-6",
                "normalization_at":            now_cairo(),
                "user_status":                 "new",
                "first_seen_at":               now_cairo(),
                "last_seen_at":                now_cairo(),
                "urgency_keywords_detected":   ext.get("urgency_keywords_detected") or [],
                "duplicate_flag":              "unique",
                "multi_broker_count":          1,
                "price_reduction_count":       0,
            }

            try:
                # Upsert listing
                if source_url:
                    resp = db.table("listings").upsert(
                        record, on_conflict="source_url"
                    ).execute()
                else:
                    resp = db.table("listings").insert(record).execute()

                listing_id = resp.data[0]["id"] if resp.data else None

                # Save installment schedule
                if listing_id and isinstance(sched_parsed, list) and sched_parsed:
                    db.table("installment_schedules").delete().eq("listing_id", listing_id).execute()
                    rows = [{"listing_id": listing_id, "payment_number": i+1, **p}
                            for i, p in enumerate(sched_parsed)]
                    db.table("installment_schedules").insert(rows).execute()

                # Save raw capture
                if listing_id:
                    db.table("listing_raw_captures").insert({
                        "listing_id":       listing_id,
                        "captured_at":      now_cairo(),
                        "raw_content_hash": record["raw_content_hash"],
                        "raw_text":         st.session_state.get("raw_text","")[:50000],
                        "source_url":       source_url or None,
                    }).execute()

                st.success(f"✅ Saved! Listing ID: `{listing_id}`")
                st.info("The scoring engine will process this listing on the next pipeline run.")
                st.session_state.pop("extracted", None)

            except Exception as e:
                st.error(f"Save failed: {e}")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: NEEDS DATA
# ════════════════════════════════════════════════════════════════════════════

def page_needs_data():
    st.title("❓ Needs Data")
    st.caption(
        "Listings that passed initial filtering but lack required fields. "
        "Complete missing data manually — they will be re-scored on the next pipeline run."
    )

    db = get_db()
    resp = (
        db.table("listings")
        .select(
            "id, source_url, project_name_raw, developer_raw, property_type, "
            "bedroom_count, bua_sqm, seller_cash_required_now, "
            "exclusion_reason, unit_id, user_status, last_seen_at"
        )
        .eq("eligibility_status", "needs_data")
        .order("last_seen_at", desc=True)
        .limit(50)
        .execute()
    )
    listings = resp.data or []

    if not listings:
        st.success("No listings in the needs-data queue.")
        return

    for l in listings:
        with st.expander(
            f"{l.get('project_name_raw','—')} {l.get('unit_id','')} — "
            f"{l.get('exclusion_reason','?')[:80]}"
        ):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.caption(
                    f"Type: {l.get('property_type','—')} · "
                    f"Beds: {l.get('bedroom_count','—')} · "
                    f"BUA: {l.get('bua_sqm','—')} m² · "
                    f"Cash: {egp(l.get('seller_cash_required_now'))}"
                )
                st.warning(f"Missing: {l.get('exclusion_reason','—')}")
            with c2:
                url = l.get("source_url","")
                if url:
                    st.link_button("Open listing", url)
                # Mark as not interested to remove from queue
                if st.button("Dismiss", key=f"dismiss_{l['id']}"):
                    db.table("listings").update(
                        {"user_status": "not_interested"}
                    ).eq("id", l["id"]).execute()
                    st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# PAGE: PIPELINE STATUS
# ════════════════════════════════════════════════════════════════════════════

def page_pipeline():
    st.title("📊 Pipeline Status")

    db = get_db()

    # ── Recent pipeline runs ────────────────────────────────────────────────
    resp = (
        db.table("pipeline_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(20)
        .execute()
    )
    runs = resp.data or []

    if runs:
        df = pd.DataFrame(runs)
        df = df[["local_date","stage","status","started_at","completed_at","retry_count","error_message"]]
        df["started_at"] = pd.to_datetime(df["started_at"]).dt.strftime("%m-%d %H:%M")
        df["completed_at"] = pd.to_datetime(df["completed_at"]).dt.strftime("%H:%M").fillna("—")

        # Colour status
        def colour_status(s):
            if s == "completed": return "background-color: #d4edda"
            if s == "failed":    return "background-color: #f8d7da"
            return "background-color: #fff3cd"

        st.dataframe(
            df.style.applymap(colour_status, subset=["status"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No pipeline runs yet.")

    # ── DB stats ────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Database stats")

    col1, col2, col3, col4 = st.columns(4)

    def count(table, **filters):
        q = db.table(table).select("id", count="exact")
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute().count or 0

    with col1:
        st.metric("Total listings", count("listings"))
    with col2:
        st.metric("Eligible", count("listings", eligibility_status="eligible"))
    with col3:
        st.metric("Needs data", count("listings", eligibility_status="needs_data"))
    with col4:
        st.metric("Excluded", count("listings", eligibility_status="excluded"))

    col5, col6, col7 = st.columns(3)
    with col5:
        st.metric("Scoring runs", count("scoring_runs"))
    with col6:
        st.metric("Reference projects", count("reference_projects"))
    with col7:
        stage1 = (
            db.table("scoring_runs")
            .select("id", count="exact")
            .eq("stage1_eligible", True)
            .execute()
        ).count or 0
        st.metric("Stage 1 eligible", stage1)

    # ── Manual trigger hint ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Manual pipeline trigger")
    st.code(
        "# Run from your GitHub Actions tab:\n"
        "# Actions → Cairo Deal-Finder Daily Pipeline → Run workflow\n"
        "# Select stage: ingestion | scoring | reporting",
        language="bash",
    )


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    if not check_auth():
        st.stop()

    st.sidebar.title("Cairo Deal-Finder")
    st.sidebar.caption("5th Settlement · New Cairo")

    page = st.sidebar.radio(
        "Navigate",
        ["🏠 Dashboard", "📋 Intake", "❓ Needs Data", "📊 Pipeline"],
        label_visibility="hidden",
    )

    if page == "🏠 Dashboard":
        page_dashboard()
    elif page == "📋 Intake":
        page_intake()
    elif page == "❓ Needs Data":
        page_needs_data()
    elif page == "📊 Pipeline":
        page_pipeline()

    st.sidebar.divider()
    st.sidebar.caption(
        f"Last refreshed: {datetime.now(CAIRO_TZ).strftime('%H:%M Cairo')}"
    )
    if st.sidebar.button("🔄 Refresh"):
        st.rerun()


if __name__ == "__main__":
    main()
