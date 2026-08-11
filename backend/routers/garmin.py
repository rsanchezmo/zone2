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
- GET  /events?days=14     — Move IQ auto-detected activities over a window
"""

from __future__ import annotations

import logging
from datetime import date as date_t, timedelta
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from backend.dependencies import get_z2
from zone2.garmin_extractors import SUMMARY_METRICS
from zone2.core import Zone2

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


def _run_garmin_sync(z2: Zone2, full: bool) -> None:
    err: str | None = None
    summary: dict | None = None
    try:
        if full:
            summary = z2.garmin_cache.sync_full()
        else:
            rows = z2.garmin_cache.sync_recent(days=14)
            summary = {"rows_written": rows}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.exception("Garmin sync failed")
    finally:
        _release(err, summary)


# ---------------------------------------------------------------------- /status


@router.get("/status")
def status(z2: Zone2 = Depends(get_z2)) -> dict[str, Any]:
    coverage = z2.garmin_cache.status()
    with _garmin_sync_lock:
        syncing = _garmin_sync_status["running"]
        last_error = _garmin_sync_status["last_error"]
        last_summary = _garmin_sync_status["last_summary"]
    return {
        "enabled": z2.garmin_client.enabled,
        "client_error": z2.garmin_client.last_error,
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
    z2: Zone2 = Depends(get_z2),
):
    if not z2.garmin_client.enabled and not z2.garmin_client.ensure_logged_in():
        raise HTTPException(
            status_code=503,
            detail=z2.garmin_client.last_error or "Garmin client not configured",
        )
    if not _try_claim():
        return {"status": "already_running"}
    background_tasks.add_task(_run_garmin_sync, z2, full)
    return {"status": "started", "full": full}


@router.post("/sync/cancel")
def cancel_sync(z2: Zone2 = Depends(get_z2)):
    """Ask a running sync (typically a long backfill) to stop at its next loop
    check. The partial result is cached, so a later sync resumes cheaply."""
    with _garmin_sync_lock:
        running = _garmin_sync_status["running"]
    if not running:
        return {"status": "not_running"}
    z2.garmin_cache.request_cancel()
    return {"status": "cancelling"}


# ---------------------------------------------------------------------- /daily-stats


@router.get("/daily-stats")
def daily_stats(
    metric: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    z2: Zone2 = Depends(get_z2),
) -> dict[str, Any]:
    return {
        "metric": metric,
        "start_date": start_date,
        "end_date": end_date,
        "rows": z2.garmin_cache.get_range(metric, start_date, end_date),
    }


# ---------------------------------------------------------------------- /latest


@router.get("/latest")
def latest(z2: Zone2 = Depends(get_z2)) -> dict[str, Any]:
    """Most-recent cached payload per metric — feeds the stat-card row."""
    out: dict[str, Any] = {}
    for metric in z2.garmin_client.ALL_METRICS:
        out[metric] = z2.garmin_cache.get_latest(metric)
    return out


# ---------------------------------------------------------------------- /events


@router.get("/events")
def events(
    days: int = Query(default=14, ge=1, le=90),
    z2: Zone2 = Depends(get_z2),
) -> dict[str, Any]:
    """Move IQ auto-detected activities (walking, biking, …) the watch spotted
    without a recorded activity. Reads the cached `all_day_events` payloads and
    flattens them into slim event dicts, newest first."""
    end = date_t.today()
    start = end - timedelta(days=days - 1)
    rows = z2.garmin_cache.get_range("all_day_events", start, end)

    out: list[dict[str, Any]] = []
    for r in rows:
        for e in r["payload"] or []:
            out.append({
                "date": e.get("calendarDate") or r["date"],
                "activity_type": e.get("activityType"),
                "activity_sub_type": e.get("activitySubType"),
                "start_local": e.get("startTimestampLocal"),
                "end_local": e.get("endTimestampLocal"),
                "duration_mins": e.get("duration"),
                "moderate_mins": e.get("moderateIntensityMinutes"),
                "vigorous_mins": e.get("vigorousIntensityMinutes"),
            })
    out.sort(key=lambda e: e["start_local"] or "", reverse=True)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": days,
        "events": out,
    }


# ---------------------------------------------------------------------- /trends


@router.get("/trends")
def trends(
    days: int = Query(default=30, ge=1, le=365),
    z2: Zone2 = Depends(get_z2),
) -> dict[str, Any]:
    """Pre-shaped per-day numeric series across all metrics. One call powers
    every chart on the Garmin page. Reads the slim `garmin_daily_summary`
    projections written at sync time (see zone2/garmin_extractors), so a 365d
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
        rows = z2.garmin_cache.get_summary_range(metric, s_iso, e_iso)
        out["metrics"][metric] = [
            {"date": r["date"], **r["summary"]} for r in rows
        ]
    return out
