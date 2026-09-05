"""
Thin wrapper around supabase-py.
All DB access goes through this module so the rest of the code
never imports supabase directly.
"""
from __future__ import annotations
from supabase import create_client, Client
import config

_client: Client | None = None


def get() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


# ── convenience helpers ───────────────────────────────────────────────────────

def upsert_listing(record: dict) -> dict:
    """
    Upsert a listing record. Conflict key: source_url.
    Returns the upserted row.
    """
    result = (
        get().table("listings")
        .upsert(record, on_conflict="source_url")
        .execute()
    )
    return result.data[0] if result.data else {}


def get_listing_by_url(url: str) -> dict | None:
    result = (
        get().table("listings")
        .select("id, raw_content_hash, last_seen_at")
        .eq("source_url", url)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def insert_price_history(record: dict) -> None:
    get().table("listing_price_history").insert(record).execute()


def insert_raw_capture(record: dict) -> None:
    get().table("listing_raw_captures").insert(record).execute()


def upsert_installment_schedule(listing_id: str, payments: list[dict]) -> None:
    """Replace the installment schedule for a listing."""
    get().table("installment_schedules").delete().eq("listing_id", listing_id).execute()
    if payments:
        rows = [{"listing_id": listing_id, **p} for p in payments]
        get().table("installment_schedules").insert(rows).execute()


def upsert_upfront_fees(listing_id: str, fees: list[dict]) -> None:
    get().table("upfront_transaction_fees").delete().eq("listing_id", listing_id).execute()
    if fees:
        rows = [{"listing_id": listing_id, **f} for f in fees]
        get().table("upfront_transaction_fees").insert(rows).execute()


def get_reference_projects() -> list[dict]:
    result = (
        get().table("reference_projects")
        .select("*")
        .eq("active", True)
        .execute()
    )
    return result.data or []
