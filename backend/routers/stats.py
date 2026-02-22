from datetime import datetime, timedelta, date
from functools import lru_cache
from fastapi import APIRouter, Depends, Query
import pandas as pd
import numpy as np

from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence
from strava.strava_utils import convert_speed, get_sport_category

router = APIRouter()

# In-memory cache for stats (cleared on sync)
_weekly_report_cache: dict[str, dict] = {}
_year_in_sport_cache: dict[str, dict] = {}


def clear_stats_cache():
    """Call after sync to invalidate cached reports."""
    _weekly_report_cache.clear()
    _year_in_sport_cache.clear()


def _serialize_enum_dict(d: dict) -> dict:
    """Convert StrEnum-keyed dicts to string-keyed for JSON."""
    return {str(k): v for k, v in d.items()}


def _get_weekly_report_cached(si: StravaIntelligence, week_start: str | None, cutoff_date: str | None = None) -> dict:
    cache_key = f"{week_start}|{cutoff_date}"
    if cache_key in _weekly_report_cache:
        return _weekly_report_cache[cache_key]
    result = si.strava_analytics.get_weekly_report(week_start, cutoff_date=cutoff_date)
    _weekly_report_cache[cache_key] = result
    return result


@router.get("/weekly-report")
def weekly_report(
    week_start: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    report = _get_weekly_report_cached(si, week_start)
    # Previous week for deltas — with same day-of-week cutoff for fairness
    week_start_str = report.get("week_start")
    prev_report = None
    if week_start_str:
        current_monday = datetime.strptime(week_start_str, "%Y-%m-%d").date()
        prev_monday = current_monday - timedelta(days=7)

        # If this is the current (incomplete) week, truncate previous week to same day
        today = date.today()
        current_week_end = current_monday + timedelta(days=6)
        if today <= current_week_end:
            days_elapsed = (today - current_monday).days
            cutoff_day_prev = prev_monday + timedelta(days=days_elapsed)
            prev_report = _get_weekly_report_cached(
                si, prev_monday.strftime("%Y-%m-%d"),
                cutoff_date=cutoff_day_prev.strftime("%Y-%m-%d"),
            )
        else:
            prev_report = _get_weekly_report_cached(si, prev_monday.strftime("%Y-%m-%d"))

    return {
        "current": _serialize_enum_dict(report),
        "previous": _serialize_enum_dict(prev_report) if prev_report else None,
    }


def _get_year_in_sport_cached(si: StravaIntelligence, cache_key: str, year: int, main_sport: str, cutoff):
    if cache_key in _year_in_sport_cache:
        return _year_in_sport_cache[cache_key]
    result = {
        "main": si.strava_analytics.get_year_in_sport(year, main_sport, cutoff_month_day=cutoff),
        "all": si.strava_analytics.get_all_year_in_sport(year, cutoff_month_day=cutoff),
    }
    _year_in_sport_cache[cache_key] = result
    return result


@router.get("/year-in-sport")
def year_in_sport(
    year: int = Query(default=2026),
    main_sport: str = Query(default="Run"),
    comparison_year: int | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    today = date.today()
    is_current_year = year == today.year

    # Only apply cutoff when viewing the current (incomplete) year
    cutoff = (today.month, today.day) if is_current_year else None

    data = _get_year_in_sport_cached(si, f"{year}|{main_sport}|{cutoff}", year, main_sport, cutoff)

    result = {
        "main_sport": _serialize_enum_dict(data["main"]),
        "all_sports": _serialize_enum_dict(data["all"]),
        "year": year,
        "sport": main_sport,
    }

    if comparison_year:
        comp_data = _get_year_in_sport_cached(si, f"{comparison_year}|{main_sport}|{cutoff}", comparison_year, main_sport, cutoff)
        result["comparison"] = {
            "main_sport": _serialize_enum_dict(comp_data["main"]),
            "all_sports": _serialize_enum_dict(comp_data["all"]),
            "year": comparison_year,
        }

    return result


@router.get("/efficiency-factor")
def efficiency_factor(
    sport_type: str = Query(default="Run"),
    window: int = Query(default=14, ge=3, le=90),
    si: StravaIntelligence = Depends(get_si),
):
    activities = si.strava_activities_cache.activities_raw.copy()
    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])
    filtered = activities[activities["sport_type"] == sport_type].copy()

    if filtered.empty:
        return {"data": [], "sport_type": sport_type, "window": window}

    filtered = filtered.sort_values("start_date_local")

    # EF = normalized speed / average HR
    ef_data = []
    for _, row in filtered.iterrows():
        speed = row.get("average_speed")
        hr = row.get("average_heartrate")
        if speed and hr and not pd.isna(speed) and not pd.isna(hr) and hr > 0:
            ef = float(speed) / float(hr)
            ef_data.append({
                "date": row["start_date_local"].isoformat(),
                "ef": round(ef, 4),
                "speed": float(speed),
                "hr": float(hr),
                "name": row.get("name", ""),
            })

    # Rolling average
    if ef_data and len(ef_data) >= window:
        ef_series = pd.Series([d["ef"] for d in ef_data])
        rolling = ef_series.rolling(window=window, min_periods=1).mean()
        for i, d in enumerate(ef_data):
            d["ef_rolling"] = round(float(rolling.iloc[i]), 4)
    else:
        for d in ef_data:
            d["ef_rolling"] = d["ef"]

    return {"data": ef_data, "sport_type": sport_type, "window": window}


@router.get("/performance-frontier")
def performance_frontier(
    sport_types: str = Query(default="Run"),
    si: StravaIntelligence = Depends(get_si),
):
    sport_list = [s.strip() for s in sport_types.split(",")]
    activities = si.strava_activities_cache.activities_raw.copy()
    filtered = activities[activities["sport_type"].isin(sport_list)].copy()

    if filtered.empty:
        return {"data": [], "sport_types": sport_list}

    points = []
    for _, row in filtered.iterrows():
        dist_km = row.get("distance", 0) / 1000.0
        speed = row.get("average_speed", 0)
        if dist_km > 0 and speed > 0:
            pace_value, unit = convert_speed(speed, row.get("sport_type"))
            points.append({
                "distance_km": round(dist_km, 2),
                "pace": round(pace_value, 2),
                "speed_ms": round(float(speed), 3),
                "name": row.get("name", ""),
                "date": str(row.get("start_date_local", "")),
                "sport_type": row.get("sport_type", ""),
            })

    # Sort by distance for frontier
    points.sort(key=lambda p: p["distance_km"])

    # Compute frontier (best pace at each distance bin)
    category = get_sport_category(sport_list[0])
    is_pace_sport = category in ("running", "swimming")

    if points:
        distances = np.array([p["distance_km"] for p in points])
        paces = np.array([p["pace"] for p in points])
        # For pace sports, lower is better; for speed sports, higher is better
        n_bins = min(20, len(points))
        bins = np.linspace(distances.min(), distances.max(), n_bins + 1)
        frontier = []
        for i in range(n_bins):
            mask = (distances >= bins[i]) & (distances < bins[i + 1])
            if mask.any():
                best = paces[mask].min() if is_pace_sport else paces[mask].max()
                frontier.append({
                    "distance_km": round(float((bins[i] + bins[i + 1]) / 2), 2),
                    "pace": round(float(best), 2),
                })
    else:
        frontier = []

    return {"data": points, "frontier": frontier, "sport_types": sport_list}


@router.get("/activity-clock")
def activity_clock(
    sport_types: str = Query(default="Run"),
    si: StravaIntelligence = Depends(get_si),
):
    sport_list = [s.strip() for s in sport_types.split(",")]
    activities = si.strava_activities_cache.activities_raw.copy()
    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])
    filtered = activities[activities["sport_type"].isin(sport_list)].copy()

    if filtered.empty:
        return {"data": [], "sport_types": sport_list}

    points = []
    for _, row in filtered.iterrows():
        hour = row["start_date_local"].hour + row["start_date_local"].minute / 60
        dist_km = row.get("distance", 0) / 1000.0
        points.append({
            "hour": round(hour, 2),
            "distance_km": round(dist_km, 2),
            "name": row.get("name", ""),
            "sport_type": row.get("sport_type", ""),
            "date": row["start_date_local"].isoformat(),
        })

    return {"data": points, "sport_types": sport_list}
