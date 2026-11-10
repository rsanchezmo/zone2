"""Training load and volume, shared by the stats router and the agent."""

import asyncio
from datetime import date, timedelta
from typing import Any

import aiosqlite

from backend.services.resting_hr import resolve_resting_hr
from backend.services.zones import resolve_hr_zones
from zone2.core import Zone2


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


def weekly_totals(z2: Zone2, weeks: int, sport_type: str | None = None) -> dict[str, Any]:
    """Total distance (km) and activity count per week (Monday to Sunday) for the
    last `weeks`, the current week included."""
    activities = z2.strava_activities_cache.get_prepared_view()
    if sport_type and not activities.empty:
        activities = activities[activities["sport_type"] == sport_type]
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
