from fastapi import APIRouter, Depends, Query
import pandas as pd
import numpy as np

from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence
from strava.strava_utils import convert_speed, get_sport_category

router = APIRouter()


def _serialize_enum_dict(d: dict) -> dict:
    """Convert StrEnum-keyed dicts to string-keyed for JSON."""
    return {str(k): v for k, v in d.items()}


@router.get("/weekly-report")
def weekly_report(
    week_start: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    report = si.strava_analytics.get_weekly_report(week_start)
    # Previous week for deltas — with same day-of-week cutoff for fairness
    from datetime import datetime, timedelta, date
    week_start_str = report.get("week_start")
    prev_report = None
    if week_start_str:
        current_monday = datetime.strptime(week_start_str, "%Y-%m-%d").date()
        prev_monday = current_monday - timedelta(days=7)
        prev_report = si.strava_analytics.get_weekly_report(prev_monday.strftime("%Y-%m-%d"))

        # If this is the current (incomplete) week, truncate previous week to same day
        today = date.today()
        current_week_end = current_monday + timedelta(days=6)
        if today <= current_week_end:
            # Days elapsed in current week (0=Mon only, 6=full week)
            days_elapsed = (today - current_monday).days
            cutoff_day_prev = prev_monday + timedelta(days=days_elapsed)
            prev_report = si.strava_analytics.get_weekly_report(
                prev_monday.strftime("%Y-%m-%d"),
                cutoff_date=cutoff_day_prev.strftime("%Y-%m-%d"),
            )

    return {
        "current": _serialize_enum_dict(report),
        "previous": _serialize_enum_dict(prev_report) if prev_report else None,
    }


@router.get("/year-in-sport")
def year_in_sport(
    year: int = Query(default=2026),
    main_sport: str = Query(default="Run"),
    comparison_year: int | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    from datetime import date
    today = date.today()
    is_current_year = year == today.year

    # Only apply cutoff when viewing the current (incomplete) year
    cutoff = (today.month, today.day) if is_current_year else None

    main = si.strava_analytics.get_year_in_sport(year, main_sport, cutoff_month_day=cutoff)
    all_sports = si.strava_analytics.get_all_year_in_sport(year, cutoff_month_day=cutoff)

    result = {
        "main_sport": _serialize_enum_dict(main),
        "all_sports": _serialize_enum_dict(all_sports),
        "year": year,
        "sport": main_sport,
    }

    if comparison_year:
        # Same cutoff for comparison year so we compare the same period
        comp_main = si.strava_analytics.get_year_in_sport(comparison_year, main_sport, cutoff_month_day=cutoff)
        comp_all = si.strava_analytics.get_all_year_in_sport(comparison_year, cutoff_month_day=cutoff)
        result["comparison"] = {
            "main_sport": _serialize_enum_dict(comp_main),
            "all_sports": _serialize_enum_dict(comp_all),
            "year": comparison_year,
        }

    return result


@router.get("/efficiency-factor")
def efficiency_factor(
    sport_type: str = Query(default="Run"),
    window: int = Query(default=14, ge=3, le=90),
    si: StravaIntelligence = Depends(get_si),
):
    activities = si.strava_activities_cache.activities.copy()
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
    activities = si.strava_activities_cache.activities.copy()
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
    activities = si.strava_activities_cache.activities.copy()
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
