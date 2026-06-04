"""Garmin Connect watch-stats router.

Strava remains the source of truth for activities; this router exposes the
daily wellness signals Strava doesn't carry (sleep, HRV, training readiness,
body battery, etc.).

Endpoints
---------
- GET  /status             — enabled flag, sync state, cache coverage
- POST /sync?full=false    — background task; default refreshes last 14 days,
                             full=true walks history backwards until empty
- GET  /daily-stats        — raw cached payloads for one metric over a window
- GET  /trends?days=30     — pre-shaped numeric series for charts (one call)
- GET  /latest             — most-recent cached payload per metric (stat cards)
"""

from __future__ import annotations

import logging
from datetime import date as date_t, timedelta
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from backend.dependencies import get_si
from strava.garmin_extractors import SUMMARY_METRICS
from strava.strava_intelligence import StravaIntelligence

logger = logging.getLogger(__name__)
router = APIRouter()

# Independent from Strava's sync lock — both can run concurrently.
_garmin_sync_status = {"running": False, "last_error": None, "last_summary": None}
_garmin_sync_lock = Lock()


def _try_claim() -> bool:
    with _garmin_sync_lock:
        if _garmin_sync_status["running"]:
            return False
        _garmin_sync_status["running"] = True
        _garmin_sync_status["last_error"] = None
        return True


def _release(error: str | None, summary: dict | None = None) -> None:
    with _garmin_sync_lock:
        _garmin_sync_status["running"] = False
        _garmin_sync_status["last_error"] = error
        if summary is not None:
            _garmin_sync_status["last_summary"] = summary


def _run_garmin_sync(si: StravaIntelligence, full: bool) -> None:
    err: str | None = None
    summary: dict | None = None
    try:
        if full:
            summary = si.garmin_cache.sync_full()
        else:
            rows = si.garmin_cache.sync_recent(days=14)
            summary = {"rows_written": rows}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.exception("Garmin sync failed")
    finally:
        _release(err, summary)


# ---------------------------------------------------------------------- /status


@router.get("/status")
def status(si: StravaIntelligence = Depends(get_si)) -> dict[str, Any]:
    coverage = si.garmin_cache.status()
    with _garmin_sync_lock:
        syncing = _garmin_sync_status["running"]
        last_error = _garmin_sync_status["last_error"]
        last_summary = _garmin_sync_status["last_summary"]
    return {
        "enabled": si.garmin_client.enabled,
        "client_error": si.garmin_client.last_error,
        "syncing": syncing,
        "last_error": last_error,
        "last_summary": last_summary,
        **coverage,
    }


# ---------------------------------------------------------------------- /sync


@router.post("/sync")
def trigger_sync(
    background_tasks: BackgroundTasks,
    full: bool = Query(default=False),
    si: StravaIntelligence = Depends(get_si),
):
    if not si.garmin_client.enabled and not si.garmin_client.ensure_logged_in():
        raise HTTPException(
            status_code=503,
            detail=si.garmin_client.last_error or "Garmin client not configured",
        )
    if not _try_claim():
        return {"status": "already_running"}
    background_tasks.add_task(_run_garmin_sync, si, full)
    return {"status": "started", "full": full}


@router.post("/sync/cancel")
def cancel_sync(si: StravaIntelligence = Depends(get_si)):
    """Ask a running sync (typically a long backfill) to stop at its next loop
    check. The partial result is cached, so a later sync resumes cheaply."""
    with _garmin_sync_lock:
        running = _garmin_sync_status["running"]
    if not running:
        return {"status": "not_running"}
    si.garmin_cache.request_cancel()
    return {"status": "cancelling"}


# ---------------------------------------------------------------------- /daily-stats


@router.get("/daily-stats")
def daily_stats(
    metric: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    si: StravaIntelligence = Depends(get_si),
) -> dict[str, Any]:
    return {
        "metric": metric,
        "start_date": start_date,
        "end_date": end_date,
        "rows": si.garmin_cache.get_range(metric, start_date, end_date),
    }


# ---------------------------------------------------------------------- /latest


@router.get("/latest")
def latest(si: StravaIntelligence = Depends(get_si)) -> dict[str, Any]:
    """Most-recent cached payload per metric — feeds the stat-card row."""
    out: dict[str, Any] = {}
    for metric in si.garmin_client.ALL_METRICS:
        out[metric] = si.garmin_cache.get_latest(metric)
    return out


# ---------------------------------------------------------------------- /trends


@router.get("/trends")
def trends(
    days: int = Query(default=30, ge=1, le=365),
    si: StravaIntelligence = Depends(get_si),
) -> dict[str, Any]:
    """Pre-shaped per-day numeric series across all metrics. One call powers
    every chart on the Garmin page. Reads the slim `garmin_daily_summary`
    projections written at sync time (see strava/garmin_extractors), so a 365d
    request touches a few hundred KB instead of deserializing ~135MB of fat
    payloads."""
    end = date_t.today()
    start = end - timedelta(days=days - 1)
    s_iso, e_iso = start.isoformat(), end.isoformat()

    # date axis (string) — frontend just plots whatever's present
    out: dict[str, Any] = {
        "start_date": s_iso,
        "end_date": e_iso,
        "days": days,
        "metrics": {},
    }
    for metric in SUMMARY_METRICS:
        rows = si.garmin_cache.get_summary_range(metric, s_iso, e_iso)
        out["metrics"][metric] = [
            {"date": r["date"], **r["summary"]} for r in rows
        ]
    return out
