import functools
import json
from datetime import timedelta, date
from fastapi import APIRouter, Depends, Query, Response
from starlette.concurrency import run_in_threadpool
import aiosqlite

from backend.db import get_db
from backend.dependencies import get_z2
from backend.services import training
from backend.services.stats_cache import stats_cache as _stats_cache
from backend.services.zones import resolve_hr_zones
from backend.services.resting_hr import resolve_resting_hr
from zone2.core import Zone2
from zone2.utils import get_sport_category, previous_week

router = APIRouter()



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

    data = training.year_in_sport(z2, year, main_sport, cutoff)

    result = {
        "main_sport": _serialize_enum_dict(data["main"]),
        "all_sports": _serialize_enum_dict(data["all"]),
        "year": year,
        "sport": main_sport,
    }

    if comparison_year:
        comp_data = training.year_in_sport(z2, comparison_year, main_sport, cutoff)
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
    return training.streaks(z2)


@router.get("/personal-records")
@_cached_json
def personal_records(z2: Zone2 = Depends(get_z2)):
    """Personal records (best efforts) at standard distances for running, cycling, and swimming."""
    return z2.strava_analytics.get_personal_records()


@router.get("/sport-totals")
@_cached_json
def sport_totals(z2: Zone2 = Depends(get_z2)):
    """Overall totals (distance, time, count) per sport category."""
    return training.sport_totals(z2)


@router.get("/weekly-totals")
@_cached_json
def weekly_totals(
    weeks: int = Query(default=12, ge=1, le=52),
    sport_type: str | None = None,
    z2: Zone2 = Depends(get_z2),
):
    """Total distance (km) and activity count per week for the last N weeks."""
    return training.weekly_totals(z2, weeks, sport_type)


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
    """Fitness, fatigue and form over the last `days` (see `training.fitness_form`)."""
    return await training.fitness_form(z2, db, days)
