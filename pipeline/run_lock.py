"""
Atomic run lock — implements the spec v1.6 Section 6 design exactly.

Two distinct failure paths:
  • status = 'failed'        → retry with backoff, up to MAX_STAGE_RETRIES
  • status = 'running' + stale heartbeat → atomically reclaim lease

A zombie job that still holds the old run_id cannot mark a newer
retry as completed because every update requires WHERE run_id = <ours>.
"""
from __future__ import annotations
import uuid
import time
import logging
from datetime import datetime, timezone, timedelta
from db.client import get
import config

log = logging.getLogger(__name__)


class LockAcquireError(Exception):
    """Raised when we cannot acquire the run lock and should not retry."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_threshold(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def acquire(local_date: str, stage: str) -> str:
    """
    Try to acquire the run lock for (local_date, stage).
    Returns run_id on success.
    Raises LockAcquireError if the stage is already completed or
    another live job is running.
    Handles failed rows with exponential backoff retry.
    Reclaims stale-running rows atomically via run_id lease.
    """
    db = get()
    run_id = str(uuid.uuid4())

    for attempt in range(1, config.MAX_STAGE_RETRIES + 1):
        try:
            # Attempt atomic insert
            db.table("pipeline_runs").insert({
                "local_date":   local_date,
                "stage":        stage,
                "run_id":       run_id,
                "status":       "running",
                "started_at":   _now_utc(),
                "heartbeat_at": _now_utc(),
                "retry_count":  attempt - 1,
            }).execute()
            log.info("Lock acquired: %s/%s run_id=%s", local_date, stage, run_id)
            return run_id

        except Exception as insert_err:
            # Unique conflict: row already exists
            existing = (
                db.table("pipeline_runs")
                .select("*")
                .eq("local_date", local_date)
                .eq("stage", stage)
                .limit(1)
                .execute()
            ).data

            if not existing:
                # Transient error, not a conflict — re-raise
                raise

            row = existing[0]
            status = row["status"]
            old_run_id = row["run_id"]

            if status == "completed":
                raise LockAcquireError(f"{stage} already completed for {local_date}")

            if status == "failed":
                if attempt >= config.MAX_STAGE_RETRIES:
                    raise LockAcquireError(
                        f"{stage} failed {config.MAX_STAGE_RETRIES} times for {local_date}. "
                        "Manual intervention required."
                    )
                backoff = 2 ** attempt
                log.warning(
                    "Stage %s failed (attempt %d/%d). Retrying in %ds.",
                    stage, attempt, config.MAX_STAGE_RETRIES, backoff,
                )
                time.sleep(backoff)
                # Update failed row to running with new run_id
                db.table("pipeline_runs").update({
                    "run_id":       run_id,
                    "status":       "running",
                    "started_at":   _now_utc(),
                    "heartbeat_at": _now_utc(),
                    "retry_count":  attempt,
                    "error_message": None,
                }).eq("local_date", local_date).eq("stage", stage)\
                  .eq("status", "failed").execute()
                log.info("Retrying lock: %s/%s run_id=%s", local_date, stage, run_id)
                return run_id

            if status == "running":
                heartbeat_at = row.get("heartbeat_at") or row["started_at"]
                stale_threshold = _utc_threshold(config.STALE_LOCK_MINUTES)
                if heartbeat_at < stale_threshold:
                    log.warning(
                        "Stale lock detected for %s/%s (heartbeat %s). "
                        "Attempting atomic reclaim.",
                        local_date, stage, heartbeat_at,
                    )
                    # Atomic reclaim: WHERE run_id = old_run_id AND status = 'running'
                    resp = (
                        db.table("pipeline_runs").update({
                            "run_id":       run_id,
                            "status":       "running",
                            "started_at":   _now_utc(),
                            "heartbeat_at": _now_utc(),
                            "retry_count":  row.get("retry_count", 0) + 1,
                            "error_message": "Reclaimed stale lock",
                        }).eq("local_date", local_date)
                          .eq("stage", stage)
                          .eq("status", "running")
                          .eq("run_id", old_run_id)
                          .execute()
                    )
                    if resp.data:
                        log.info("Stale lock reclaimed: %s/%s run_id=%s", local_date, stage, run_id)
                        return run_id
                    else:
                        # Another job beat us to it
                        raise LockAcquireError(
                            f"{stage}: stale lock was reclaimed by another job concurrently"
                        )
                else:
                    raise LockAcquireError(
                        f"{stage} is already running (live heartbeat at {heartbeat_at})"
                    )

    raise LockAcquireError(f"Could not acquire lock for {stage} after {config.MAX_STAGE_RETRIES} attempts")


def heartbeat(local_date: str, stage: str, run_id: str) -> None:
    """Update heartbeat_at — call every ~2 minutes during long-running stages."""
    get().table("pipeline_runs").update({
        "heartbeat_at": _now_utc()
    }).eq("local_date", local_date).eq("stage", stage).eq("run_id", run_id).execute()


def complete(local_date: str, stage: str, run_id: str) -> None:
    """Mark stage completed. run_id guard prevents zombie jobs overwriting."""
    get().table("pipeline_runs").update({
        "status":       "completed",
        "completed_at": _now_utc(),
    }).eq("local_date", local_date).eq("stage", stage).eq("run_id", run_id).execute()
    log.info("Stage completed: %s/%s", local_date, stage)


def fail(local_date: str, stage: str, run_id: str, error: str) -> None:
    """Mark stage failed."""
    get().table("pipeline_runs").update({
        "status":        "failed",
        "completed_at":  _now_utc(),
        "error_message": error[:2000],
    }).eq("local_date", local_date).eq("stage", stage).eq("run_id", run_id).execute()
    log.error("Stage failed: %s/%s — %s", local_date, stage, error)
