"""
Aqar Exit HTML parser.

Extracts structured data from listing cards (opportunities page)
and detail pages. Because Aqar Exit pre-structures all key fields,
Claude normalization is NOT needed for the primary transaction legs.

Fields already structured by Aqar Exit:
  • seller_cash_required_now       ("Cash required now")
  • remaining_with_developer        ("Remaining with developer")
  • installment_amount + frequency  ("Installment EGP X · Quarterly")
  • installments_remaining_years    ("Instalments remaining: N years")
  • annual_installment              ("Annual installment: EGP X")
  • delivery_date                   ("Delivery: YYYY")
  • floor, bedrooms, bathrooms, area, type, finishing, completion
  • aqar_exit_fee_egp               (1.25% of contract value, shown on detail page)
  • total_required_now              (cash + Aqar Exit fee, shown on detail page)
  • unit_id (U-XXXXX)
  • is_negotiable, is_featured, documents_verified
"""
from __future__ import annotations
import re
import logging
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ── Arabic unit type mapping ──────────────────────────────────────────────────
_TYPE_MAP = {
    "شقة":      "apartment",
    "دوبلكس":   "duplex",
    "فيلا":     "villa",
    "تاون هاوس": "townhouse",
    "تاون هاوز": "townhouse",
    "تاون":     "townhouse",
    "توين هاوس": "twinhouse",
    "توين":     "twinhouse",
    "بنتهاوس":  "penthouse",
    "بنتهاوز":  "penthouse",
    "شاليه":    "chalet",
    "مكتب":     "office",
    "محل":      "retail",
    "عيادة":    "clinic",
    "apartment":  "apartment",
    "duplex":     "duplex",
    "villa":      "villa",
    "townhouse":  "townhouse",
    "penthouse":  "penthouse",
}

_FREQUENCY_MAP = {
    "quarterly":   "quarterly",
    "ربع سنوي":    "quarterly",
    "semi-annual": "semi_annual",
    "نصف سنوي":    "semi_annual",
    "monthly":     "monthly",
    "شهري":        "monthly",
    "annual":      "annual",
    "سنوي":        "annual",
}

_FINISHING_MAP = {
    "تشطيب كامل":        "fully_finished",
    "تشطيب":             "fully_finished",
    "fully finished":    "fully_finished",
    "نص تشطيب":          "semi_finished",
    "semi finished":     "semi_finished",
    "core and shell":    "core_and_shell",
    "بدون تشطيب":        "core_and_shell",
}

_DELIVERY_STATUS_MAP = {
    "تحت الإنشاء":       "under_construction",
    "under construction": "under_construction",
    "جاهز للتسليم":      "ready_to_move",
    "ready":             "ready_to_move",
    "تم التسليم":        "delivered_not_finished",
}


def _egp(text: str) -> float | None:
    """Extract first EGP number from a string. Returns None if not found."""
    if not text:
        return None
    cleaned = text.replace(",", "").replace("EGP", "").replace("جنيه", "").strip()
    m = re.search(r"[\d]+(?:\.\d+)?", cleaned)
    return float(m.group()) if m else None


def _int_or_none(text: str) -> int | None:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def parse_listing_card(card_html: str, base_url: str) -> dict | None:
    """
    Parse a single listing card from the opportunities listing page.
    Returns a dict with the fields extractable at list level,
    or None if the card is missing essential data.
    """
    soup = BeautifulSoup(card_html, "lxml")
    result: dict = {}

    # ── Unit ID ────────────────────────────────────────────────────────────────
    uid_el = soup.find(string=re.compile(r"U-\d+"))
    result["unit_id"] = uid_el.strip() if uid_el else None

    # ── Project name ───────────────────────────────────────────────────────────
    h2 = soup.find("h2")
    result["project_name_raw"] = h2.get_text(strip=True) if h2 else None

    # ── Developer and location ─────────────────────────────────────────────────
    # Pattern: "Developer · Location" in a single text node
    dev_loc_el = soup.find(string=re.compile(r"·"))
    if dev_loc_el:
        parts = [p.strip() for p in dev_loc_el.split("·")]
        result["developer_raw"]    = parts[0] if len(parts) > 0 else None
        result["location_raw"]     = parts[1] if len(parts) > 1 else None
    else:
        result["developer_raw"]    = None
        result["location_raw"]     = None

    # ── Type / bedrooms / bathrooms / area ────────────────────────────────────
    # Pattern: "شقة · 3 غرف · 2 حمام · 169 م²"
    spec_el = soup.find(string=re.compile(r"غرف|م²|bedroom|m²", re.IGNORECASE))
    if spec_el:
        spec = spec_el.strip()
        parts = [p.strip() for p in spec.split("·")]
        result["property_type_raw"] = parts[0] if parts else None
        result["property_type"]     = _TYPE_MAP.get(
            (parts[0] or "").strip().lower(), "unknown"
        )
        for part in parts[1:]:
            p = part.lower()
            if "غرف" in p or "br" in p or "bedroom" in p:
                result["bedroom_count"] = _int_or_none(part)
            elif "حمام" in p or "bath" in p:
                result["bathroom_count"] = _int_or_none(part)
            elif "م²" in p or "m²" in p:
                result["bua_sqm"] = _egp(part)
    else:
        result["property_type"]  = "unknown"
        result["bedroom_count"]  = None
        result["bathroom_count"] = None
        result["bua_sqm"]        = None

    # ── Cash required now ─────────────────────────────────────────────────────
    cash_el = soup.find(string=re.compile(r"Cash required now|الكاش المطلوب", re.IGNORECASE))
    if cash_el:
        # Value is usually the next sibling element
        parent = cash_el.parent
        nxt = parent.find_next_sibling() if parent else None
        val_text = nxt.get_text() if nxt else ""
        result["seller_cash_required_now"] = _egp(val_text)
    else:
        result["seller_cash_required_now"] = None

    # ── Remaining with developer ───────────────────────────────────────────────
    rem_el = soup.find(string=re.compile(r"Remaining with developer|الباقي على المطور", re.IGNORECASE))
    if rem_el:
        parent = rem_el.parent
        nxt = parent.find_next_sibling() if parent else None
        result["remaining_with_developer"] = _egp(nxt.get_text() if nxt else "")
    else:
        result["remaining_with_developer"] = None

    # ── Installment amount and frequency ──────────────────────────────────────
    inst_el = soup.find(string=re.compile(r"Installment|قسط", re.IGNORECASE))
    if inst_el:
        parent = inst_el.parent
        nxt = parent.find_next_sibling() if parent else None
        inst_text = nxt.get_text() if nxt else ""
        # "EGP 83,500 · Quarterly" or "EGP 83,500 · ربع سنوي"
        result["installment_amount_egp"]    = _egp(inst_text)
        freq_match = re.search(
            r"(quarterly|semi-annual|monthly|annual|ربع سنوي|نصف سنوي|شهري|سنوي)",
            inst_text, re.IGNORECASE
        )
        result["installment_frequency"] = _FREQUENCY_MAP.get(
            freq_match.group().lower() if freq_match else "", "unknown"
        )
    else:
        result["installment_amount_egp"]  = None
        result["installment_frequency"]   = "unknown"

    # ── Delivery year ─────────────────────────────────────────────────────────
    del_el = soup.find(string=re.compile(r"Delivery|تسليم", re.IGNORECASE))
    if del_el:
        parent = del_el.parent
        nxt = parent.find_next_sibling() if parent else None
        result["delivery_date_raw"] = nxt.get_text(strip=True) if nxt else None
    else:
        result["delivery_date_raw"] = None

    # ── Flags ─────────────────────────────────────────────────────────────────
    result["is_negotiable"]        = bool(soup.find(string=re.compile(r"قابل للتفاوض|Open to negotiation", re.IGNORECASE)))
    result["is_featured"]          = bool(soup.find(string=re.compile(r"Featured|مميز", re.IGNORECASE)))
    result["documents_verified"]   = bool(soup.find(string=re.compile(r"Documents verified|موثق", re.IGNORECASE)))

    # ── Detail URL ────────────────────────────────────────────────────────────
    detail_link = soup.find("a", href=re.compile(r"/buy/opportunity/"))
    if detail_link:
        href = detail_link["href"]
        result["source_url"] = href if href.startswith("http") else base_url + href
    else:
        result["source_url"] = None

    return result if result.get("project_name_raw") else None


def parse_detail_page(html: str, url: str) -> dict:
    """
    Parse a listing detail page. Returns a dict with all available fields.
    Supplements the card-level data with floor, finishing, completion,
    Aqar Exit fee, total required now, and installment year details.
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict = {"source_url": url}

    def _field_value(label_pattern: str) -> str | None:
        """Find a label by pattern and return the next sibling's text."""
        el = soup.find(string=re.compile(label_pattern, re.IGNORECASE))
        if not el:
            return None
        parent = el.parent
        nxt = parent.find_next_sibling() if parent else None
        return nxt.get_text(strip=True) if nxt else None

    # ── Unit ID ────────────────────────────────────────────────────────────────
    uid = soup.find(string=re.compile(r"U-\d+"))
    result["unit_id"] = uid.strip() if uid else None

    # ── Title (project + developer + location + type) ─────────────────────────
    h1 = soup.find("h1")
    result["project_name_raw"] = h1.get_text(strip=True) if h1 else None

    # Developer · Location · Type line
    dev_loc_el = soup.find(string=re.compile(r"·"))
    if dev_loc_el:
        parts = [p.strip() for p in str(dev_loc_el).split("·")]
        result["developer_raw"] = parts[0] if len(parts) > 0 else None
        result["location_raw"]  = parts[1] if len(parts) > 1 else None
        result["property_type_raw"] = parts[2] if len(parts) > 2 else None
        result["property_type"] = _TYPE_MAP.get(
            (parts[2] if len(parts) > 2 else "").strip().lower(), "unknown"
        )

    # ── Explicit detail fields ─────────────────────────────────────────────────
    result["floor_number"]    = _field_value(r"^Floor$|^الدور$")
    result["bedroom_count"]   = _int_or_none(_field_value(r"^Bedrooms$|^غرف النوم$") or "")
    result["bathroom_count"]  = _int_or_none(_field_value(r"^Bathrooms$|^الحمامات$") or "")

    area_raw = _field_value(r"^Area$|^المساحة$")
    result["bua_sqm"] = _egp(area_raw) if area_raw else None

    finishing_raw = _field_value(r"^Finishing$|^التشطيب$")
    result["finishing_status"] = _FINISHING_MAP.get(
        (finishing_raw or "").strip().lower(), "not_specified"
    )
    result["finishing_notes"] = finishing_raw

    completion_raw = _field_value(r"^Completion$|^الاكتمال$")
    result["delivery_status"] = _DELIVERY_STATUS_MAP.get(
        (completion_raw or "").strip().lower(), "not_specified"
    )

    result["contract_year"]      = _field_value(r"^Contract year$|^سنة العقد$")
    result["price_per_sqm_raw"]  = _field_value(r"Price per m²|سعر المتر")

    # ── Transaction legs ──────────────────────────────────────────────────────
    cash_raw = _field_value(r"Cash required now|الكاش المطلوب")
    result["seller_cash_required_now"] = _egp(cash_raw)

    remaining_raw = _field_value(r"Remaining with developer|الباقي على المطور")
    result["remaining_with_developer"] = _egp(remaining_raw)

    inst_amount_raw = _field_value(r"^Installment$|^القسط$")
    result["installment_amount_egp"] = _egp(inst_amount_raw)
    freq_match = re.search(
        r"(quarterly|semi-annual|monthly|annual|ربع سنوي|نصف سنوي|شهري|سنوي)",
        inst_amount_raw or "", re.IGNORECASE
    )
    result["installment_frequency"] = _FREQUENCY_MAP.get(
        freq_match.group().lower() if freq_match else "", "unknown"
    )

    remaining_years_raw = _field_value(r"Instalments remaining|الأقساط المتبقية")
    result["installments_remaining_years"] = _int_or_none(remaining_years_raw or "")

    annual_raw = _field_value(r"Annual installment|القسط السنوي")
    result["annual_installment_egp"] = _egp(annual_raw)

    result["delivery_date_raw"] = _field_value(r"^Delivery$|^التسليم$")

    # ── Aqar Exit fee and total ────────────────────────────────────────────────
    fee_raw = _field_value(r"Aqar Exit buyer.s fee|عمولة عقار إكزت")
    result["aqar_exit_fee_egp"] = _egp(fee_raw)

    total_raw = _field_value(r"Total required from you now|إجمالي المطلوب")
    result["total_required_now_egp"] = _egp(total_raw)

    # ── Flags ─────────────────────────────────────────────────────────────────
    result["is_negotiable"]      = bool(soup.find(string=re.compile(r"قابل للتفاوض|Open to negotiation", re.IGNORECASE)))
    result["is_featured"]        = bool(soup.find(string=re.compile(r"Featured|مميز", re.IGNORECASE)))
    result["documents_verified"] = bool(soup.find(string=re.compile(r"Documents verified|موثق", re.IGNORECASE)))

    # ── Amenities / notes ─────────────────────────────────────────────────────
    # Collect all checkmark items (✓ ... )
    amenities = []
    for el in soup.find_all(string=re.compile(r"✓")):
        amenities.append(el.strip().lstrip("✓").strip())
    result["amenities_raw"] = amenities

    return result


def build_installment_schedule(parsed: dict) -> list[dict]:
    """
    Build installment_schedule rows from detail page data.
    We know: amount per period, frequency, total years remaining.
    Exact due dates are not available — stored as estimated.
    Returns [] for confirmed cash deals (no remaining).
    Returns [] with a flag if data is insufficient.
    """
    if not parsed.get("remaining_with_developer"):
        # No remaining installments — cash deal or not stated
        return []

    amount   = parsed.get("installment_amount_egp")
    freq     = parsed.get("installment_frequency", "unknown")
    years    = parsed.get("installments_remaining_years")

    if not amount or freq == "unknown" or not years:
        return []  # Insufficient data — caller marks as UNKNOWN

    periods_per_year = {
        "monthly": 12, "quarterly": 4,
        "semi_annual": 2, "annual": 1,
    }.get(freq, 0)

    if not periods_per_year:
        return []

    total_payments = int(years * periods_per_year)
    return [
        {
            "payment_number":    i + 1,
            "payment_amount_egp": amount,
            "due_date":          None,       # Not available from listing
            "due_date_confidence": "estimated",
            "notes": (
                f"~{freq} payment; approx {years} years remaining; "
                "exact due dates not available from listing"
            ),
        }
        for i in range(total_payments)
    ]


def build_upfront_fees(parsed: dict) -> list[dict]:
    """
    Build upfront_transaction_fees rows.
    Aqar Exit fee is always 1.25% — shown explicitly on detail page.
    """
    fees = []
    if parsed.get("aqar_exit_fee_egp"):
        fees.append({
            "fee_type":        "assignment_fee",
            "amount_egp":      parsed["aqar_exit_fee_egp"],
            "amount_confirmed": True,
            "notes": "Aqar Exit buyer commission 1.25% of contract value — confirmed on listing",
        })
    return fees
