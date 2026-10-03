import functools
import json
from datetime import timedelta, date
from fastapi import APIRouter, Depends, Query, Response
from starlette.concurrency import run_in_threadpool
import aiosqlite

from backend._ttl_cache import TTLCache
from backend.db import get_db
from backend.dependencies import get_z2
from backend.services.zones import resolve_hr_zones
from backend.services.resting_hr import resolve_resting_hr
from zone2.core import Zone2
from zone2.utils import df_rows, get_sport_category, previous_week

router = APIRouter()

# Single TTL cache for all stats endpoints. Keys are tuples
# (endpoint, *params, cache_version) so entries self-invalidate when the
# underlying activities dataset changes.
_stats_cache = TTLCache(maxsize=256, ttl_seconds=900)


def _cached_json(endpoint):
    """Serve a sync endpoint's JSON from _stats_cache, keyed by its query
    parameters, the activities version and the day (results that count up to
    today roll over at midnight)."""
    @functools.wraps(endpoint)
    def cached(**kwargs) -> Response:
        z2: Zone2 = kwargs["z2"]
        params = tuple(sorted((k, v) for k, v in kwargs.items() if k != "z2"))
        key = (endpoint.__name__, params, z2.strava_activities_cache.cache_version, date.today())
        return _stats_cache.json_response(key, lambda: endpoint(**kwargs))
    return cached


async def _cached_json_in_threadpool(key: tuple, build) -> Response:
    """_stats_cache.json_response for async endpoints: the build is blocking
    pandas work, so it runs off the event loop."""
    return await run_in_threadpool(_stats_cache.json_response, key + (date.today(),), build)


def clear_stats_cache():
    """Call after sync to drop cached reports immediately (TTL + cache_version
    also handle this lazily — this just reclaims memory sooner)."""
    _stats_cache.clear()


def _serialize_enum_dict(d: dict) -> dict:
    """Convert StrEnum-keyed dicts to string-keyed for JSON."""
    return {str(k): v for k, v in d.items()}


def _zones_signature(hr_zones: list | None) -> str:
    """Stable fingerprint for the zones so the stats cache differentiates by source."""
    if not hr_zones:
        return "none"
    return json.dumps(hr_zones, sort_keys=True, separators=(",", ":"))


def _get_weekly_report_cached(
    z2: Zone2,
    week_start: str | None,
    cutoff_date: str | None = None,
    hr_zones: list | None = None,
) -> dict:
    key = ("weekly", week_start, cutoff_date, z2.strava_activities_cache.cache_version, _zones_signature(hr_zones))
    cached = _stats_cache.get(key)
    if cached is not None:
        return cached
    result = z2.strava_analytics.get_weekly_report(week_start, cutoff_date=cutoff_date, hr_zones=hr_zones)
    _stats_cache.set(key, result)
    return result


def _get_previous_weekly_report_cached(z2: Zone2, report: dict, hr_zones: list | None) -> dict | None:
    """The week before `report`'s, for deltas."""
    if not report.get("week_start"):
        return None
    prev_monday, cutoff = previous_week(report["week_start"])
    return _get_weekly_report_cached(z2, prev_monday, cutoff_date=cutoff, hr_zones=hr_zones)


@router.get("/weekly-report")
async def weekly_report(
    week_start: str | None = None,
    z2: Zone2 = Depends(get_z2),
    db: aiosqlite.Connection = Depends(get_db),
):
    resolved = await resolve_hr_zones(z2, db)
    hr_zones = resolved["zones"]

    def build() -> dict:
        report = _get_weekly_report_cached(z2, week_start, hr_zones=hr_zones)
        prev_report = _get_previous_weekly_report_cached(z2, report, hr_zones)

        return {
            "current": _serialize_enum_dict(report),
            "previous": _serialize_enum_dict(prev_report) if prev_report else None,
        }

    key = ("weekly_report_response", week_start, _zones_signature(hr_zones),
           z2.strava_activities_cache.cache_version)
    return await _cached_json_in_threadpool(key, build)


def _get_year_in_sport_cached(z2: Zone2, year: int, main_sport: str, cutoff):
    key = ("year_in_sport", year, main_sport, cutoff, z2.strava_activities_cache.cache_version)
    cached = _stats_cache.get(key)
    if cached is not None:
        return cached
    result = {
        "main": z2.strava_analytics.get_year_in_sport(year, main_sport, cutoff_month_day=cutoff),
        "all": z2.strava_analytics.get_all_year_in_sport(year, cutoff_month_day=cutoff),
    }
    _stats_cache.set(key, result)
    return result


@router.get("/year-in-sport")
@_cached_json
def year_in_sport(
    year: int | None = None,
    main_sport: str = Query(default="Run"),
    comparison_year: int | None = None,
    z2: Zone2 = Depends(get_z2),
):
    today = date.today()
    year = year or today.year
    is_current_year = year == today.year

    # Only apply cutoff when viewing the current (incomplete) year
    cutoff = (today.month, today.day) if is_current_year else None

    data = _get_year_in_sport_cached(z2, year, main_sport, cutoff)

    result = {
        "main_sport": _serialize_enum_dict(data["main"]),
        "all_sports": _serialize_enum_dict(data["all"]),
        "year": year,
        "sport": main_sport,
    }

    if comparison_year:
        comp_data = _get_year_in_sport_cached(z2, comparison_year, main_sport, cutoff)
        result["comparison"] = {
            "main_sport": _serialize_enum_dict(comp_data["main"]),
            "all_sports": _serialize_enum_dict(comp_data["all"]),
            "year": comparison_year,
        }

    return result


@router.get("/cumulative-distance")
@_cached_json
def cumulative_distance(
    year: int | None = None,
    main_sport: str = Query(default="Run"),
    comparison_year: int | None = None,
    yearly_target_km: float | None = None,
    z2: Zone2 = Depends(get_z2),
):
    """Daily cumulative distance for a year (optionally with comparison year and target)."""
    import calendar as cal

    year = year or date.today().year
    activities = z2.strava_activities_cache.get_prepared_view()

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
@_cached_json
def streaks(
    z2: Zone2 = Depends(get_z2),
):
    """Compute current and longest activity streaks (consecutive days with activities)."""
    activities = z2.strava_activities_cache.get_prepared_view()
    active_dates = sorted(activities["start_date_local"].dt.date.unique())

    if not len(active_dates):
        return {"current_streak": 0, "longest_streak": 0, "longest_streak_start": None, "longest_streak_end": None}

    today = date.today()
    # Build streaks
    longest = 1
    longest_start = active_dates[0]
    longest_end = active_dates[0]
    current = 1
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


def _compute_sport_totals(z2: Zone2) -> dict:
    """Compute total distance (km) and time (seconds) per sport category."""
    activities = z2.strava_activities_cache.activities_raw
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
    for row in df_rows(activities, "sport_type", "distance", "moving_time"):
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
@_cached_json
def personal_records(z2: Zone2 = Depends(get_z2)):
    """Personal records (best efforts) at standard distances for running, cycling, and swimming."""
    return z2.strava_analytics.get_personal_records()


@router.get("/sport-totals")
@_cached_json
def sport_totals(z2: Zone2 = Depends(get_z2)):
    """Overall totals (distance, time, count) per sport category."""
    return _compute_sport_totals(z2)


@router.get("/weekly-totals")
@_cached_json
def weekly_totals(
    weeks: int = Query(default=12, ge=1, le=52),
    sport_type: str | None = None,
    z2: Zone2 = Depends(get_z2),
):
    """Total distance (km) and activity count per week for the last N weeks."""
    activities = z2.strava_activities_cache.get_prepared_view()
    if activities.empty:
        return {"data": [], "weeks": weeks, "sport_type": sport_type}

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
@_cached_json
def race_predictions(
    sport_category: str = Query(default="running"),
    z2: Zone2 = Depends(get_z2),
):
    result = z2.strava_analytics.get_race_predictions(sport_category)
    return result


@router.get("/race-predictions/history")
@_cached_json
def race_predictions_history(
    sport_category: str = Query(default="running"),
    weeks: int = Query(default=52, ge=1, le=520),
    step_days: int = Query(default=7, ge=1, le=30),
    z2: Zone2 = Depends(get_z2),
):
    """Time series of race predictions across the last N weeks.

    For each step, recomputes predictions using the recent-bests window
    ending at that step's date. Used to drive the evolution chart on the
    Analytics page.
    """
    points = z2.strava_analytics.get_race_predictions_history(
        sport_category, weeks=weeks, step_days=step_days
    )
    result = {"sport_category": sport_category, "weeks": weeks, "points": points}
    return result


@router.get("/relative-effort/weekly")
async def relative_effort_weekly(
    sport_type: str | None = None,
    z2: Zone2 = Depends(get_z2),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Weekly Relative Effort with a personalized expected-range band, using the
    user-resolved HR zones and resting HR.

    Relative Effort is only meaningful for running/swimming. With no sport_type
    the two are combined; with a sport_type its category is used when it's run or
    swim, otherwise an empty series is returned (so the UI can hide the chart)."""
    if sport_type:
        cat = get_sport_category(sport_type)
        sports = (cat,) if cat in z2.strava_analytics.RE_SPORTS else ()
    else:
        sports = z2.strava_analytics.RE_SPORTS

    resolved_zones = await resolve_hr_zones(z2, db)
    resolved_rhr = await resolve_resting_hr(z2, db)
    key = (
        "relative_effort_weekly",
        sport_type or "",
        _zones_signature(resolved_zones["zones"]),
        round(resolved_rhr["value"], 1),
        z2.strava_activities_cache.cache_version,
    )
    return await _cached_json_in_threadpool(key, lambda: z2.strava_analytics.get_weekly_relative_effort(
        hr_zones=resolved_zones["zones"],
        hr_rest=resolved_rhr["value"],
        sports=sports,
    ))



@router.get("/fitness")
async def fitness_form(
    days: int = Query(default=180, ge=30, le=1095),
    z2: Zone2 = Depends(get_z2),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Fitness, fatigue and form over the last `days`, projected over the planned
    sessions ahead, with the races in that span and Garmin's own acute and
    chronic load alongside."""
    resolved_zones = await resolve_hr_zones(z2, db)
    resolved_rhr = await resolve_resting_hr(z2, db)
    today = date.today().isoformat()
    cur = await db.execute(
        "SELECT date, sport_type, planned_distance_km, planned_duration_mins FROM training_sessions WHERE date >= ?",
        (today,),
    )
    planned = [dict(r) for r in await cur.fetchall()]
    result = await run_in_threadpool(
        z2.strava_analytics.get_fitness_form,
        resolved_rhr["value"], resolved_zones["zones"], planned, days,
    )
    series = result["series"]
    if not series:
        return {**result, "races": [], "garmin": []}
    start, end = series[0]["date"], series[-1]["date"]
    cur = await db.execute(
        "SELECT date, name FROM race_events WHERE date BETWEEN ? AND ? ORDER BY date", (start, end),
    )
    races = [{"date": r["date"], "name": r["name"]} for r in await cur.fetchall()]
    garmin_rows = await run_in_threadpool(z2.garmin_cache.get_summary_range, "training_status", start, today)
    garmin = [
        {"date": r["date"], "acute": r["summary"].get("daily_load_acute"), "chronic": r["summary"].get("daily_load_chronic")}
        for r in garmin_rows
        if r["summary"].get("daily_load_chronic") is not None
    ]
    return {**result, "races": races, "garmin": garmin}
