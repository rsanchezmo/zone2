"""What an activity cost, from the Garmin data around it: the body battery it
used, the recovery time Garmin set right after it, and how the night after
went against your normal. Reads cached Garmin payloads only."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

import pandas as pd

from zone2.core import Zone2

# A Garmin activity event belongs to the activity starting within this of it
_MATCH_S = 10 * 60
# Garmin takes its post-exercise readiness snapshot a moment after saving the activity
_SNAPSHOT_SLACK = timedelta(minutes=5)
_SLEEP_NORMAL_DAYS = 30


def _gmt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _activity_events(body_battery: dict | None) -> list[dict]:
    return [e for e in (body_battery or {}).get("bodyBatteryActivityEvent") or []
            if e.get("eventType") == "ACTIVITY" and e.get("eventStartTimeGmt")]


def _matching_event(events: list[dict], start: datetime) -> dict | None:
    gaps = [(abs((_gmt(e["eventStartTimeGmt"]) - start).total_seconds()), e) for e in events]
    gap, event = min(gaps, key=lambda g: g[0], default=(None, None))
    return event if gap is not None and gap <= _MATCH_S else None


def _level(values: list, at: datetime, after: bool) -> int | None:
    """Body battery level at `at`: the last reading before it, or the first one after."""
    ms = at.timestamp() * 1000
    readings = [(v[0], v[2]) for v in values or [] if isinstance(v, list) and len(v) > 2 and v[2] is not None]
    if after:
        return next((lvl for ts, lvl in readings if ts >= ms), None)
    return next((lvl for ts, lvl in reversed(readings) if ts <= ms), None)


def _recovery_hours(readiness: dict | None, end: datetime, events: list[dict]) -> int | None:
    """Recovery time from the day's last readiness snapshot, when it's the one
    Garmin took after this activity (no other activity in between)."""
    if not readiness or readiness.get("inputContext") != "AFTER_POST_EXERCISE_RESET" or not readiness.get("timestamp"):
        return None
    taken = _gmt(readiness["timestamp"])
    if taken < end - _SNAPSHOT_SLACK:
        return None
    if any(end < _gmt(e["eventStartTimeGmt"]) < taken for e in events):
        return None
    minutes = readiness.get("recoveryTime")
    return round(minutes / 60) if minutes else None


def _night(z2: Zone2, day: date) -> dict[str, Any] | None:
    """The night after `day`, which Garmin files under the next date."""
    cache = z2.garmin_cache
    night = day + timedelta(days=1)

    def summary(metric: str) -> dict:
        rows = cache.get_summary_range(metric, night, night)
        return rows[0]["summary"] if rows else {}

    sleep, hrv, heart = summary("sleep"), summary("hrv"), summary("heart_rates")
    if sleep.get("score") is None and hrv.get("last_night_avg") is None:
        return None
    past = cache.get_summary_range("sleep", night - timedelta(days=_SLEEP_NORMAL_DAYS), day)
    past_scores = [r["summary"]["score"] for r in past if r["summary"].get("score") is not None]
    sleep_event = next((e for e in (cache.get(night, "body_battery") or {}).get("bodyBatteryActivityEvent") or []
                        if e.get("eventType") == "SLEEP"), None)
    readiness = cache.get(night, "training_readiness") or {}
    wakeup = readiness.get("wakeup") or (readiness if readiness.get("inputContext") == "AFTER_WAKEUP_RESET" else {})
    return {
        "date": night.isoformat(),
        "sleep_score": sleep.get("score"),
        "sleep_score_normal": round(mean(past_scores)) if past_scores else None,
        "sleep_seconds": sleep.get("total_seconds"),
        "hrv": hrv.get("last_night_avg"),
        "hrv_balanced_low": hrv.get("balanced_low"),
        "hrv_balanced_upper": hrv.get("balanced_upper"),
        "hrv_status": hrv.get("status"),
        "resting_hr": heart.get("resting"),
        "resting_hr_normal": heart.get("last_7d_avg_resting"),
        "body_battery_charged": sleep_event.get("bodyBatteryImpact") if sleep_event else None,
        "readiness": wakeup.get("score"),
        "readiness_level": wakeup.get("level"),
    }


def activity_cost(z2: Zone2, activity_id: int) -> dict[str, Any] | None:
    """None when the activity doesn't exist; every part is None when Garmin has
    nothing for it."""
    row = z2.strava_activities_cache.get_activity_by_id(activity_id)
    if row is None:
        return None
    # start_date_local is wall-clock time despite its Z; Garmin's events are in GMT
    local = pd.Timestamp(row["start_date_local"]).tz_localize(None)
    offset = row.get("utc_offset")
    start = (local - pd.Timedelta(seconds=float(offset) if pd.notna(offset) else 0)).tz_localize("UTC").to_pydatetime()
    day = local.date()
    cache = z2.garmin_cache
    events = _activity_events(cache.get(day, "body_battery"))
    event = _matching_event(events, start)
    if event:
        start = _gmt(event["eventStartTimeGmt"])
        end = start + timedelta(milliseconds=event.get("durationInMilliseconds") or 0)
    else:
        end = start + timedelta(seconds=float(row.get("elapsed_time") or 0))

    body_battery = None
    if event:
        levels = (cache.get(day, "stress") or {}).get("bodyBatteryValuesArray")
        body_battery = {
            "impact": event.get("bodyBatteryImpact"),
            "start": _level(levels, start, after=False),
            "end": _level(levels, end, after=True),
            "effect": event.get("shortFeedback"),
        }
    return {
        "body_battery": body_battery,
        "recovery_hours": _recovery_hours(cache.get(day, "training_readiness"), end, events),
        "night": _night(z2, day),
    }
