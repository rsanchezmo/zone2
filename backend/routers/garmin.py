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
- GET  /activity-cost/{id} — body battery used, recovery time and the night after
- GET  /day/{date}         — one day's intraday series, sleep stages and activities
"""

from __future__ import annotations

from datetime import date as date_t, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from backend.dependencies import get_z2
from backend.services import garmin_sync
from backend.services.activity_cost import activity_cost
from backend.services.day_timeline import day_timeline
from backend.services.garmin_courses import course_devices, course_line
from zone2.garmin_extractors import SUMMARY_METRICS
from zone2.core import Zone2

router = APIRouter()


# ---------------------------------------------------------------------- /status


@router.get("/status")
def status(z2: Zone2 = Depends(get_z2)) -> dict[str, Any]:
    coverage = z2.garmin_cache.status()
    slot = garmin_sync.status()
    return {
        "enabled": z2.garmin_client.enabled,
        "client_error": z2.garmin_client.last_error,
        "syncing": slot.running,
        "last_error": slot.last_error,
        "last_summary": slot.last_summary,
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
    if not garmin_sync.try_claim():
        return {"status": "already_running"}
    background_tasks.add_task(garmin_sync.run, z2, full)
    return {"status": "started", "full": full}


@router.post("/sync/cancel")
def cancel_sync(z2: Zone2 = Depends(get_z2)):
    """Ask a running sync (typically a long backfill) to stop at its next loop
    check. The partial result is cached, so a later sync resumes cheaply."""
    if not garmin_sync.status().running:
        return {"status": "not_running"}
    z2.garmin_cache.request_cancel()
    return {"status": "cancelling"}


# ---------------------------------------------------------------------- /activity-cost


@router.get("/activity-cost/{activity_id}")
def get_activity_cost(activity_id: int, z2: Zone2 = Depends(get_z2)):
    cost = activity_cost(z2, activity_id)
    if cost is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return cost


# ---------------------------------------------------------------------- /day


@router.get("/day/{day}")
def get_day(day: date_t, z2: Zone2 = Depends(get_z2)):
    timeline = day_timeline(z2, day)
    if timeline is None:
        raise HTTPException(status_code=404, detail="No Garmin data for this day")
    return timeline


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
    end = z2.clock.today()
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
    days: int = Query(default=30, ge=1, le=3650),
    metrics: str | None = Query(default=None, description="Comma-separated subset of the summary metrics"),
    z2: Zone2 = Depends(get_z2),
) -> dict[str, Any]:
    """Pre-shaped per-day numeric series across all metrics. One call powers
    every chart on the Garmin page. Reads the slim `garmin_daily_summary`
    projections written at sync time (see zone2/garmin_extractors), so a 365d
    request touches a few hundred KB instead of deserializing ~135MB of fat
    payloads."""
    end = z2.clock.today()
    start = end - timedelta(days=days - 1)
    s_iso, e_iso = start.isoformat(), end.isoformat()

    # date axis (string) — frontend just plots whatever's present
    out: dict[str, Any] = {
        "start_date": s_iso,
        "end_date": e_iso,
        "days": days,
        "metrics": {},
    }
    wanted = SUMMARY_METRICS if metrics is None else tuple(
        m for m in (m.strip() for m in metrics.split(",")) if m in SUMMARY_METRICS
    )
    for metric in wanted:
        rows = z2.garmin_cache.get_summary_range(metric, s_iso, e_iso)
        out["metrics"][metric] = [
            {"date": r["date"], **r["summary"]} for r in rows
        ]
    return out


# ---------------------------------------------------------------------- /courses


@router.get("/courses/{course_id}/points")
def course_points(course_id: int, z2: Zone2 = Depends(get_z2)) -> dict[str, Any]:
    return course_line(z2, course_id)


@router.get("/devices")
def devices(z2: Zone2 = Depends(get_z2)) -> list[dict[str, Any]]:
    """Watches that take courses, the primary training device first."""
    return course_devices(z2)
