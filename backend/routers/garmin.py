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
- GET  /courses            — the user's courses (name, distance, start)
- GET  /courses/{id}/points — a course's line
- GET  /devices            — watches that take courses, the primary one first
"""

from __future__ import annotations

import logging
from datetime import date as date_t, timedelta
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from backend._ttl_cache import TTLCache
from backend.dependencies import get_z2
from zone2.garmin_client import GarminUnavailable
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


# ---------------------------------------------------------------------- /latest


# The stat cards read a few fields per metric; the payloads also carry
# intraday arrays (sleep alone ~200 KB) they never show.
_CARD_SUBTREES = {
    "sleep": ("dailySleepDTO",),
    "hrv": ("hrvSummary",),
    "training_status": ("mostRecentVO2Max", "mostRecentTrainingLoadBalance", "mostRecentTrainingStatus"),
}


def _card_fields(metric: str, payload: Any) -> Any:
    """The parts of a metric's payload the stat cards read: named subtrees, or
    everything but the top-level arrays."""
    if not isinstance(payload, dict):
        return payload
    keep = _CARD_SUBTREES.get(metric)
    if keep is not None:
        return {k: payload[k] for k in keep if k in payload}
    return {k: v for k, v in payload.items() if not isinstance(v, list)}


@router.get("/latest")
def latest(z2: Zone2 = Depends(get_z2)) -> dict[str, Any]:
    """Most-recent cached payload per metric, trimmed to what the stat-card row reads."""
    out: dict[str, Any] = {}
    for metric in z2.garmin_client.ALL_METRICS:
        entry = z2.garmin_cache.get_latest(metric)
        out[metric] = {**entry, "payload": _card_fields(metric, entry["payload"])} if entry else None
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


# ---------------------------------------------------------------------- /courses

# Live Garmin calls, cached briefly: courses change only through Connect or
# the planner (which clears this), a course's line never
_courses_cache = TTLCache(maxsize=64, ttl_seconds=300)
_course_points_cache = TTLCache(maxsize=64, ttl_seconds=24 * 3600)


def clear_courses_cache() -> None:
    _courses_cache.clear()


def _live(fn, *args):
    try:
        return fn(*args)
    except GarminUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.warning("Garmin %s failed: %s: %s", fn.__name__, type(e).__name__, e)
        raise HTTPException(status_code=502, detail=f"Garmin Connect failed: {e}")


def course_list(z2: Zone2) -> list[dict[str, Any]]:
    """The user's Garmin courses, newest first."""
    cached = _courses_cache.get("courses")
    if cached is None:
        cached = [
            {"course_id": c["courseId"], "name": c["courseName"],
             "distance_km": round((c.get("distanceInMeters") or 0) / 1000, 2),
             "start": [c.get("startLatitude"), c.get("startLongitude")],
             "sport": (c.get("activityType") or {}).get("typeKey"),
             "created_at": c.get("createdDateFormatted")}
            for c in sorted(_live(z2.garmin_client.list_courses), key=lambda c: c.get("createdDate") or 0, reverse=True)
        ]
        _courses_cache.set("courses", cached)
    return cached


def course_line(z2: Zone2, course_id: int) -> dict[str, Any]:
    """The course's line as [lon, lat] coordinates."""
    cached = _course_points_cache.get(course_id)
    if cached is None:
        points = _live(z2.garmin_client.course_points, course_id)
        cached = {"coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in points]}
        _course_points_cache.set(course_id, cached)
    return cached


@router.get("/courses/{course_id}/points")
def course_points(course_id: int, z2: Zone2 = Depends(get_z2)) -> dict[str, Any]:
    return course_line(z2, course_id)


@router.get("/devices")
def course_devices(z2: Zone2 = Depends(get_z2)) -> list[dict[str, Any]]:
    """Watches that take courses, the primary training device first."""
    cached = _courses_cache.get("devices")
    if cached is None:
        cached = sorted(_live(z2.garmin_client.course_devices), key=lambda d: not d["primary"])
        _courses_cache.set("devices", cached)
    return cached
