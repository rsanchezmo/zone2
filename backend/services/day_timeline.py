"""One day of Garmin's intraday data on a single clock: heart rate, stress,
body battery, respiration and SpO2, the sleep around it and the day's
activities. Times are local wall-clock milliseconds, so they read the same
wherever the browser is: format them as UTC."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from zone2.core import Zone2

# Garmin's sleepLevels activityLevel codes
_SLEEP_STAGES = {0: "deep", 1: "light", 2: "rem", 3: "awake"}
_EPOCH = datetime(1970, 1, 1)


def _ms(s: str) -> int:
    """Milliseconds of a Garmin timestamp such as '2026-10-01T17:40:12.0', taken as written."""
    return int((datetime.fromisoformat(s) - _EPOCH).total_seconds() * 1000)


def _series(values: list | None, index: int, offset_ms: int) -> list[list[float]]:
    """[local ms, value] pairs; Garmin marks unmeasured samples as None or negative."""
    out = []
    for v in values or []:
        if isinstance(v, list) and len(v) > index and isinstance(v[index], (int, float)) and v[index] >= 0:
            out.append([v[0] + offset_ms, v[index]])
    return out


def _sleep(payload: dict | None, offset_ms: int, start: int, end: int) -> list[dict[str, Any]]:
    stages = []
    for level in (payload or {}).get("sleepLevels") or []:
        a, b = _ms(level["startGMT"]) + offset_ms, _ms(level["endGMT"]) + offset_ms
        if b > start and a < end:
            stages.append({"start": max(a, start), "end": min(b, end),
                           "stage": _SLEEP_STAGES.get(int(level.get("activityLevel", -1)), "awake")})
    return stages


def _activities(z2: Zone2, day: date) -> list[dict[str, Any]]:
    view = z2.strava_activities_cache.get_prepared_view()
    if view.empty:
        return []
    rows = view[view["start_date_local"].dt.date == day]
    out = []
    for _, r in rows.iterrows():
        # start_date_local is wall-clock time labelled UTC, which is the clock this view uses
        start = int(pd.Timestamp(r["start_date_local"]).value // 1_000_000)
        out.append({
            "id": int(r["id"]),
            "name": r.get("name"),
            "sport_type": r.get("sport_type"),
            "start": start,
            "end": start + int(float(r.get("elapsed_time") or 0) * 1000),
        })
    return out


def day_timeline(z2: Zone2, day: date) -> dict[str, Any] | None:
    """None when Garmin has no intraday data for the day."""
    cache = z2.garmin_cache
    heart = cache.get(day, "heart_rates") or {}
    stress = cache.get(day, "stress") or {}
    respiration = cache.get(day, "respiration") or {}
    spo2 = cache.get(day, "spo2") or {}
    # Each payload frames the day in GMT and local time; their gap is the day's UTC offset
    framed = next((p for p in (heart, stress, respiration) if p.get("startTimestampGMT") and p.get("startTimestampLocal")), None)
    if framed is None:
        return None
    start = _ms(framed["startTimestampLocal"])
    offset_ms = start - _ms(framed["startTimestampGMT"])
    end = start + int(timedelta(days=1).total_seconds() * 1000)
    series = {
        "heart_rate": _series(heart.get("heartRateValues"), 1, offset_ms),
        "stress": _series(stress.get("stressValuesArray"), 1, offset_ms),
        "body_battery": _series(stress.get("bodyBatteryValuesArray"), 2, offset_ms),
        "respiration": _series(respiration.get("respirationValuesArray"), 1, offset_ms),
        "spo2": _series(spo2.get("spO2HourlyAverages"), 1, offset_ms),
    }
    # Older watches framed the day but recorded nothing through it
    if not any(series.values()):
        return None
    # The night that ended this morning is filed under today, tonight's under tomorrow
    sleep = (_sleep(cache.get(day, "sleep"), offset_ms, start, end)
             + _sleep(cache.get(day + timedelta(days=1), "sleep"), offset_ms, start, end))
    return {
        "date": day.isoformat(),
        "start": start,
        "end": end,
        **series,
        "sleep": sleep,
        "activities": _activities(z2, day),
    }
