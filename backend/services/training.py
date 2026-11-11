"""Training load, volume, years and streaks, shared by the stats router and the agent."""

import asyncio
from datetime import date, timedelta
from typing import Any

import aiosqlite

from backend.services.resting_hr import resolve_resting_hr
from backend.services.stats_cache import stats_cache
from backend.services.zones import resolve_hr_zones
from zone2.core import Zone2
from zone2.utils import SportCategory, df_rows, get_sport_category


async def fitness_form(z2: Zone2, db: aiosqlite.Connection, days: int) -> dict[str, Any]:
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
    result = await asyncio.to_thread(
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
    garmin_rows = await asyncio.to_thread(z2.garmin_cache.get_summary_range, "training_status", start, today)
    garmin = [
        {"date": r["date"], "acute": r["summary"].get("daily_load_acute"), "chronic": r["summary"].get("daily_load_chronic")}
        for r in garmin_rows
        if r["summary"].get("daily_load_chronic") is not None
    ]
    return {**result, "races": races, "garmin": garmin}


def weekly_totals(z2: Zone2, weeks: int, sport_type: str | None = None,
                  category: SportCategory | None = None) -> dict[str, Any]:
    """Total distance (km) and activity count per week (Monday to Sunday) for the
    last `weeks`, the current week included, of a Strava sport type or a sport
    category when given."""
    activities = z2.strava_activities_cache.get_prepared_view()
    if sport_type and not activities.empty:
        activities = activities[activities["sport_type"] == sport_type]
    if category and not activities.empty:
        activities = activities[activities["sport_type"].map(get_sport_category) == category]
    if activities.empty:
        return {"data": [], "weeks": weeks, "sport_type": sport_type}

    current_monday = date.today() - timedelta(days=date.today().weekday())
    monday = current_monday - timedelta(weeks=weeks - 1)
    day = activities["start_date_local"].dt.date
    result = []
    for _ in range(weeks):
        sunday = monday + timedelta(days=6)
        week_acts = activities[(day >= monday) & (day <= sunday)]
        result.append({
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            "week_label": monday.strftime("%b %d"),
            "total_distance_km": round(float(week_acts["distance"].sum() / 1000.0), 2),
            "total_activities": int(len(week_acts)),
        })
        monday += timedelta(weeks=1)
    return {"data": result, "weeks": weeks, "sport_type": sport_type}


def year_in_sport(z2: Zone2, year: int, main_sport: str, cutoff: tuple[int, int] | None) -> dict[str, Any]:
    """A year's totals for its main sport and for all sports, up to `cutoff` (month, day) when
    given, so a year in progress compares like for like."""
    key = ("year_in_sport", year, main_sport, cutoff, z2.strava_activities_cache.cache_version)
    cached = stats_cache.get(key)
    if cached is not None:
        return cached
    result = {
        "main": z2.strava_analytics.get_year_in_sport(year, main_sport, cutoff_month_day=cutoff),
        "all": z2.strava_analytics.get_all_year_in_sport(year, cutoff_month_day=cutoff),
    }
    stats_cache.set(key, result)
    return result


def streaks(z2: Zone2) -> dict[str, Any]:
    """Current and longest streaks of consecutive days, and of consecutive weeks, with an activity."""
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


TOTALS_SPORTS = (SportCategory.RUNNING, SportCategory.CYCLING, SportCategory.SWIMMING)


def sport_totals(z2: Zone2) -> dict[SportCategory, dict[str, Any]]:
    """All-time distance (km), moving time (s) and count per sport category: running, cycling, swimming."""
    activities = z2.strava_activities_cache.activities_raw
    if activities.empty:
        return {}
    totals: dict[SportCategory, dict] = {}
    for row in df_rows(activities, "sport_type", "distance", "moving_time"):
        cat = get_sport_category(row.get("sport_type"))
        if cat not in TOTALS_SPORTS:
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
