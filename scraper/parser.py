"""
Aqar Exit HTML parser — v2.

Extracts structured data from detail pages.
Field extraction based on confirmed page structure:
  # Project Name          ← h1
  Developer · Location · Type   ← subtitle line with · separators
  U-XXXXX                ← unit ID
  Type / Area / Floor / Bedrooms / Bathrooms / Finishing / Completion ...
  Cash required now: EGP X
  Remaining with developer: EGP X
  Installment: EGP X · Frequency
  Instalments remaining: N years
  Annual installment: EGP X
  Delivery: YYYY
  Aqar Exit buyer's fee (1.25%): EGP X
  Total required from you now: EGP X
"""
from __future__ import annotations
import re
import logging
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Known open neighborhoods for entry_type inference
_NEIGHBORHOOD_KEYWORDS = {
    "بيت الوطن", "النرجس", "البنفسج", "اللوتس", "الأندلس", "andalos", "andalus",
    "المستثمرين الشمالية", "المستثمرين الجنوبية", "north investors", "south investors",
    "شرق الأكاديمية", "غرب اربيلا", "west arbella", "القرنفل", "الشويفات",
    "narges", "banafseg", "lotus", "beit al watan", "east academy",
}

_TYPE_MAP = {
    "شقة":        "apartment",
    "apartment":  "apartment",
    "دوبلكس":     "duplex",
    "duplex":     "duplex",
    "فيلا":       "villa",
    "villa":      "villa",
    "تاون هاوس":  "townhouse",
    "تاون هاوز":  "townhouse",
    "townhouse":  "townhouse",
    "توين هاوس":  "twinhouse",
    "twinhouse":  "twinhouse",
    "بنتهاوس":    "penthouse",
    "penthouse":  "penthouse",
    "شاليه":      "chalet",
    "مكتب":       "office",
    "محل":        "retail",
    "عيادة":      "clinic",
}

_FINISHING_MAP = {
    "تشطيب كامل":        "fully_finished",
    "fully finished":    "fully_finished",
    "نص تشطيب":          "semi_finished",
    "semi finished":     "semi_finished",
    "على الطوب":         "core_and_shell",   # ← important: Aqar Exit uses this
    "core and shell":    "core_and_shell",
    "بدون تشطيب":        "core_and_shell",
}

_DELIVERY_MAP = {
    "تحت الإنشاء":        "under_construction",
    "under construction": "under_construction",
    "جاهز للتسليم":       "ready_to_move",
    "ready":              "ready_to_move",
    "تم التسليم":         "delivered_not_finished",
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


def _egp(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[,EGPجنيه\s]", "", text)
    m = re.search(r"[\d]+(?:\.\d+)?", cleaned)
    return float(m.group()) if m else None


def _int_or_none(text: str | None) -> int | None:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def _infer_entry_type(project_name: str) -> str:
    """Infer entry_type from project name."""
    if not project_name:
        return "compound"
    name_lower = project_name.lower()
    for keyword in _NEIGHBORHOOD_KEYWORDS:
        if keyword.lower() in name_lower:
            return "neighborhood"
    return "compound"


def parse_detail_page(html: str, url: str) -> dict:
    """
    Parse a listing detail page. Returns dict with all extracted fields.

    Page structure (confirmed from live page):
      h1: project name only (e.g. "هايد بارك التجمع الخامس")
      subtitle: "Developer · Location · Type" (e.g. "هايد بارك · التجمع الخامس · شقة")
      Unit ID: U-XXXXX
      Spec table: Type, Area, Floor, Bedrooms, Bathrooms, Finishing, Completion
      Financial fields: Cash required now, Remaining, Installment, etc.
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict = {"source_url": url}

    # ── Project name from h1 ──────────────────────────────────────────────
    h1 = soup.find("h1")
    project_name = h1.get_text(strip=True) if h1 else None
    result["project_name_raw"] = project_name

    # ── Developer · Location · Type subtitle ─────────────────────────────
    # Find first element containing both · and the location
    developer_raw = None
    location_raw = None
    property_type_raw = None

    for el in soup.find_all(["p", "div", "span", "h2"]):
        text = el.get_text(strip=True)
        if "·" in text and len(text) < 200:
            parts = [p.strip() for p in text.split("·")]
            if len(parts) >= 2:
                # Likely: Developer · Location · Type
                developer_raw    = parts[0] if parts[0] else None
                location_raw     = parts[1] if len(parts) > 1 else None
                property_type_raw = parts[2] if len(parts) > 2 else None
                break

    result["developer_raw"]     = developer_raw
    result["location_raw"]      = location_raw
    result["property_type_raw"] = property_type_raw
    result["property_type"]     = _TYPE_MAP.get(
        (property_type_raw or "").strip().lower(), "unknown"
    )

    # Infer entry_type from project name + location
    combined = f"{project_name or ''} {location_raw or ''}".lower()
    result["entry_type"] = _infer_entry_type(combined)

    # ── Unit ID ────────────────────────────────────────────────────────────
    uid_el = soup.find(string=re.compile(r"U-\d{4,}"))
    result["unit_id"] = uid_el.strip().rstrip("⧉").strip() if uid_el else None

    # ── Spec table fields ─────────────────────────────────────────────────
    def _after_label(label_pattern: str) -> str | None:
        """Find label text and return the next sibling/nearby text."""
        el = soup.find(string=re.compile(label_pattern, re.IGNORECASE))
        if not el:
            return None
        parent = el.parent
        # Try next sibling
        nxt = parent.find_next_sibling()
        if nxt and nxt.get_text(strip=True):
            return nxt.get_text(strip=True)
        # Try parent's next sibling
        if parent.parent:
            nxt2 = parent.parent.find_next_sibling()
            if nxt2:
                return nxt2.get_text(strip=True)
        return None

    # Floor
    floor_raw = _after_label(r"^Floor$|^الدور$|^الطابق$")
    result["floor_number"] = floor_raw

    # Bedrooms
    beds_raw = _after_label(r"^Bedrooms$|^غرف النوم$|^الغرف$")
    result["bedroom_count"] = _int_or_none(beds_raw)

    # Bathrooms
    baths_raw = _after_label(r"^Bathrooms$|^الحمامات$")
    result["bathroom_count"] = _int_or_none(baths_raw)

    # Area
    area_raw = _after_label(r"^Area$|^المساحة$")
    result["bua_sqm"] = _egp(area_raw) if area_raw else None

    # Finishing
    finishing_raw = _after_label(r"^Finishing$|^التشطيب$")
    result["finishing_status"] = _FINISHING_MAP.get(
        (finishing_raw or "").strip().lower(), "not_specified"
    )
    result["finishing_notes"] = finishing_raw

    # Completion/delivery status
    completion_raw = _after_label(r"^Completion$|^الاكتمال$|^حالة الوحدة$")
    result["delivery_status"] = _DELIVERY_MAP.get(
        (completion_raw or "").strip().lower(), "not_specified"
    )

    # Contract year
    result["contract_year"] = _after_label(r"^Contract year$|^سنة العقد$")

    # ── Financial fields ───────────────────────────────────────────────────
    cash_raw = _after_label(r"Cash required now|الكاش المطلوب الآن|الكاش المطلوب")
    result["seller_cash_required_now"] = _egp(cash_raw)

    remaining_raw = _after_label(r"Remaining with developer|الباقي على المطور")
    result["remaining_with_developer"] = _egp(remaining_raw)

    # Installment amount and frequency
    inst_raw = _after_label(r"^Installment$|^القسط$")
    result["installment_amount_egp"] = _egp(inst_raw)
    if inst_raw:
        freq_m = re.search(
            r"(quarterly|semi-annual|monthly|annual|ربع سنوي|نصف سنوي|شهري|سنوي)",
            inst_raw, re.IGNORECASE
        )
        result["installment_frequency"] = _FREQUENCY_MAP.get(
            freq_m.group().lower() if freq_m else "", "unknown"
        )
    else:
        result["installment_frequency"] = "unknown"

    # Years remaining
    years_raw = _after_label(r"Instalments remaining|الأقساط المتبقية")
    result["installments_remaining_years"] = _int_or_none(years_raw)

    # Annual installment
    annual_raw = _after_label(r"Annual installment|القسط السنوي")
    result["annual_installment_egp"] = _egp(annual_raw)

    # Delivery year
    delivery_raw = _after_label(r"^Delivery$|^التسليم$|^موعد التسليم$")
    result["delivery_date_raw"] = delivery_raw

    # Aqar Exit fee
    fee_raw = _after_label(r"Aqar Exit buyer.s fee|عمولة عقار إكزت|عمولة المشتري")
    result["aqar_exit_fee_egp"] = _egp(fee_raw)

    # Total required now
    total_raw = _after_label(r"Total required from you now|إجمالي المطلوب منك الآن")
    result["total_required_now_egp"] = _egp(total_raw)

    # ── Flags ──────────────────────────────────────────────────────────────
    result["is_negotiable"]      = bool(soup.find(string=re.compile(r"Open to negotiation|قابل للتفاوض", re.IGNORECASE)))
    result["is_featured"]        = bool(soup.find(string=re.compile(r"Featured|مميز", re.IGNORECASE)))
    result["documents_verified"] = bool(soup.find(string=re.compile(r"Documents verified|موثق", re.IGNORECASE)))

    # ── Amenities ──────────────────────────────────────────────────────────
    amenities = []
    for el in soup.find_all(string=re.compile(r"✓")):
        text = el.strip().lstrip("✓").strip()
        if text:
            amenities.append(text)
    result["amenities_raw"] = amenities

    return result


def build_installment_schedule(parsed: dict) -> list[dict]:
    """Build installment schedule rows from parsed detail data."""
    if not parsed.get("remaining_with_developer"):
        return []

    amount = parsed.get("installment_amount_egp")
    freq   = parsed.get("installment_frequency", "unknown")
    years  = parsed.get("installments_remaining_years")

    if not amount or freq == "unknown" or not years:
        return []

    periods_per_year = {
        "monthly": 12, "quarterly": 4,
        "semi_annual": 2, "annual": 1,
    }.get(freq, 0)

    if not periods_per_year:
        return []

    total_payments = int(years * periods_per_year)
    return [
        {
            "payment_number":      i + 1,
            "payment_amount_egp":  amount,
            "due_date":            None,
            "due_date_confidence": "estimated",
            "notes": (
                f"~{freq} payment; approx {years} years remaining; "
                "exact due dates not available from listing"
            ),
        }
        for i in range(total_payments)
    ]


def build_upfront_fees(parsed: dict) -> list[dict]:
    """Build upfront_transaction_fees rows."""
    fees = []
    if parsed.get("aqar_exit_fee_egp"):
        fees.append({
            "fee_type":         "assignment_fee",
            "amount_egp":       parsed["aqar_exit_fee_egp"],
            "amount_confirmed": True,
            "notes": "Aqar Exit buyer commission 1.25% of contract value — confirmed on listing",
        })
    return fees
