from datetime import datetime, timedelta, date
from functools import lru_cache
import json
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


_race_predictions_cache: dict[str, dict] = {}
_training_load_cache: dict | None = None
_fitness_chart_cache: dict[str, dict] = {}
_fitness_trend_cache: dict[str, dict] = {}


def clear_stats_cache():
    """Call after sync to invalidate cached reports."""
    global _personal_records_cache, _training_load_cache
    _weekly_report_cache.clear()
    _year_in_sport_cache.clear()
    _personal_records_cache = None
    _race_predictions_cache.clear()
    _training_load_cache = None
    _fitness_chart_cache.clear()
    _fitness_trend_cache.clear()


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


@router.get("/cumulative-distance")
def cumulative_distance(
    year: int = Query(default=2026),
    main_sport: str = Query(default="Run"),
    comparison_year: int | None = None,
    yearly_target_km: float | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    """Daily cumulative distance for a year (optionally with comparison year and target)."""
    import calendar as cal

    activities = si.strava_activities_cache.activities_raw.copy()
    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])

    days_in_year = 366 if cal.isleap(year) else 365

    def build_cumulative(yr: int) -> list[dict]:
        mask = (activities["start_date_local"].dt.year == yr) & (activities["sport_type"] == main_sport)
        filtered = activities[mask].copy()
        if filtered.empty:
            return []
        filtered["date"] = filtered["start_date_local"].dt.date
        daily = filtered.groupby("date")["distance"].sum().sort_index()
        # Build day-of-year cumulative series
        start = date(yr, 1, 1)
        cumulative = 0.0
        result = []
        for day_offset in range(366):
            d = start + timedelta(days=day_offset)
            if d.year != yr:
                break
            km_today = float(daily.get(d, 0)) / 1000.0
            cumulative += km_today
            point: dict = {
                "day": day_offset + 1,
                "date": d.isoformat(),
                "km": round(cumulative, 2),
            }
            if yearly_target_km is not None and yr == year:
                point["target"] = round(yearly_target_km * (day_offset + 1) / days_in_year, 2)
            result.append(point)
        return result

    result = {"year": year, "sport": main_sport, "data": build_cumulative(year)}
    if comparison_year:
        result["comparison"] = {"year": comparison_year, "data": build_cumulative(comparison_year)}
    return result


@router.get("/streaks")
def streaks(
    si: StravaIntelligence = Depends(get_si),
):
    """Compute current and longest activity streaks (consecutive days with activities)."""
    activities = si.strava_activities_cache.activities_raw.copy()
    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])
    active_dates = sorted(activities["start_date_local"].dt.date.unique())

    if not len(active_dates):
        return {"current_streak": 0, "longest_streak": 0, "longest_streak_start": None, "longest_streak_end": None}

    today = date.today()
    # Build streaks
    longest = 1
    longest_start = active_dates[0]
    longest_end = active_dates[0]
    current = 1
    current_start = active_dates[0]
    streak_start = active_dates[0]

    for i in range(1, len(active_dates)):
        if (active_dates[i] - active_dates[i - 1]).days == 1:
            current += 1
        else:
            if current > longest:
                longest = current
                longest_start = streak_start
                longest_end = active_dates[i - 1]
            current = 1
            streak_start = active_dates[i]

    # Final check
    if current > longest:
        longest = current
        longest_start = streak_start
        longest_end = active_dates[-1]

    # Current streak: must include today or yesterday
    last_active = active_dates[-1]
    if (today - last_active).days > 1:
        current_streak = 0
    else:
        current_streak = 1
        for i in range(len(active_dates) - 2, -1, -1):
            if (active_dates[i + 1] - active_dates[i]).days == 1:
                current_streak += 1
            else:
                break

    # ── Week streaks (consecutive ISO weeks with at least 1 activity) ──
    active_weeks = sorted({d.isocalendar()[:2] for d in active_dates})  # (year, week)

    def week_diff(a: tuple, b: tuple) -> int:
        """Return the number of ISO weeks between two (year, week) tuples."""
        d_a = date.fromisocalendar(a[0], a[1], 1)
        d_b = date.fromisocalendar(b[0], b[1], 1)
        return (d_b - d_a).days // 7

    longest_week = 0
    longest_week_start = None
    longest_week_end = None
    current_week_streak = 0

    if active_weeks:
        cur = 1
        cur_start = active_weeks[0]
        for i in range(1, len(active_weeks)):
            if week_diff(active_weeks[i - 1], active_weeks[i]) == 1:
                cur += 1
            else:
                if cur > longest_week:
                    longest_week = cur
                    longest_week_start = cur_start
                    longest_week_end = active_weeks[i - 1]
                cur = 1
                cur_start = active_weeks[i]
        if cur > longest_week:
            longest_week = cur
            longest_week_start = cur_start
            longest_week_end = active_weeks[-1]

        # Current week streak: must include this week or last week
        this_week = today.isocalendar()[:2]
        last_week_date = today - timedelta(days=7)
        last_week = last_week_date.isocalendar()[:2]
        last_active_week = active_weeks[-1]
        if last_active_week >= last_week:
            current_week_streak = 1
            for i in range(len(active_weeks) - 2, -1, -1):
                if week_diff(active_weeks[i], active_weeks[i + 1]) == 1:
                    current_week_streak += 1
                else:
                    break

    def week_label(yw: tuple | None) -> str | None:
        if yw is None:
            return None
        return date.fromisocalendar(yw[0], yw[1], 1).isoformat()

    return {
        "current_streak": current_streak,
        "longest_streak": longest,
        "longest_streak_start": longest_start.isoformat() if longest_start else None,
        "longest_streak_end": longest_end.isoformat() if longest_end else None,
        "current_week_streak": current_week_streak,
        "longest_week_streak": longest_week,
        "longest_week_streak_start": week_label(longest_week_start),
        "longest_week_streak_end": week_label(longest_week_end),
    }


_personal_records_cache: dict | None = None


def _compute_sport_totals(si: StravaIntelligence) -> dict:
    """Compute total distance (km) and time (seconds) per sport category."""
    activities = si.strava_activities_cache.activities
    if activities.empty:
        return {}
    RUNNING_TYPES = {"run", "trailrun", "virtualrun"}
    CYCLING_TYPES = {"ride", "virtualride", "ebikeride", "gravelride", "mountainbikeride", "emountainbikeride", "handcycle", "velomobile"}
    SWIMMING_TYPES = {"swim"}

    def _category(sport_type: str | None) -> str | None:
        st = (sport_type or "").lower().replace(" ", "")
        if st in RUNNING_TYPES:
            return "running"
        if st in CYCLING_TYPES:
            return "cycling"
        if st in SWIMMING_TYPES:
            return "swimming"
        return None

    totals: dict[str, dict] = {}
    for _, row in activities.iterrows():
        cat = _category(row.get("sport_type"))
        if cat is None:
            continue
        if cat not in totals:
            totals[cat] = {"distance_km": 0.0, "time_s": 0.0, "count": 0}
        totals[cat]["distance_km"] += (row.get("distance") or 0) / 1000.0
        totals[cat]["time_s"] += row.get("moving_time") or 0
        totals[cat]["count"] += 1
    # Round values
    for cat in totals:
        totals[cat]["distance_km"] = round(totals[cat]["distance_km"], 1)
        totals[cat]["time_s"] = round(totals[cat]["time_s"])
    return totals


@router.get("/personal-records")
def personal_records(
    si: StravaIntelligence = Depends(get_si),
    bust_cache: bool = Query(default=False),
):
    """Personal records (best efforts) at standard distances for running, cycling, and swimming."""
    global _personal_records_cache
    if _personal_records_cache is not None and not bust_cache:
        return _personal_records_cache
    result = si.strava_analytics.get_personal_records()
    _personal_records_cache = result
    return result


@router.get("/sport-totals")
def sport_totals(si: StravaIntelligence = Depends(get_si)):
    """Overall totals (distance, time, count) per sport category."""
    return _compute_sport_totals(si)


@router.get("/weekly-totals")
def weekly_totals(
    weeks: int = Query(default=12, ge=1, le=52),
    sport_type: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    """Total distance (km) and activity count per week for the last N weeks."""
    activities = si.strava_activities_cache.activities_raw.copy()
    if activities.empty:
        return {"data": [], "weeks": weeks, "sport_type": sport_type}

    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])

    if sport_type:
        activities = activities[activities["sport_type"] == sport_type]
        if activities.empty:
            return {"data": [], "weeks": weeks, "sport_type": sport_type}

    today = date.today()
    # Find Monday of the current week
    current_monday = today - timedelta(days=today.weekday())
    # Go back N-1 weeks (current week counts as week 1)
    start_monday = current_monday - timedelta(weeks=weeks - 1)

    result = []
    monday = start_monday
    for _ in range(weeks):
        sunday = monday + timedelta(days=6)
        mask = (activities["start_date_local"].dt.date >= monday) & (
            activities["start_date_local"].dt.date <= sunday
        )
        week_acts = activities[mask]
        result.append({
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            "week_label": monday.strftime("%b %d"),
            "total_distance_km": round(float(week_acts["distance"].sum() / 1000.0), 2),
            "total_activities": int(len(week_acts)),
        })
        monday += timedelta(weeks=1)

    return {"data": result, "weeks": weeks, "sport_type": sport_type}


@router.get("/race-predictions")
def race_predictions(
    sport_category: str = Query(default="running"),
    si: StravaIntelligence = Depends(get_si),
):
    if sport_category in _race_predictions_cache:
        return _race_predictions_cache[sport_category]
    result = si.strava_analytics.get_race_predictions(sport_category)
    _race_predictions_cache[sport_category] = result
    return result


@router.get("/training-load")
def training_load(
    start_date: str | None = None,
    end_date: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    data = si.strava_analytics.get_daily_training_load()
    if start_date or end_date:
        filtered = data
        if start_date:
            filtered = [d for d in filtered if d["date"] >= start_date]
        if end_date:
            filtered = [d for d in filtered if d["date"] <= end_date]
        return {"data": filtered}
    return {"data": data}


@router.get("/fitness-chart")
def fitness_chart(
    start_date: str | None = None,
    end_date: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    cache_key = f"{start_date}|{end_date}"
    if cache_key in _fitness_chart_cache:
        return _fitness_chart_cache[cache_key]
    result = si.strava_analytics.get_pmc_chart(start_date, end_date)
    _fitness_chart_cache[cache_key] = result
    return result


@router.get("/fitness-trend")
def fitness_trend(
    sport_type: str = Query(default="Run"),
    start_date: str | None = None,
    end_date: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    cache_key = f"{sport_type}|{start_date}|{end_date}"
    if cache_key in _fitness_trend_cache:
        return _fitness_trend_cache[cache_key]
    result = si.strava_analytics.get_fitness_trend(sport_type, start_date, end_date)
    _fitness_trend_cache[cache_key] = result
    return result
