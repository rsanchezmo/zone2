"""Yearly goals and how far along each is (this week, month or year), shared by the goals
router and the agent."""

import calendar
from datetime import date, timedelta

import aiosqlite

from backend.db import row_dict
from zone2.core import Zone2

METRICS = ("distance_km", "time_hours", "activities", "elevation_m")
PERIODS = ("weekly", "monthly", "yearly")


async def progress(z2: Zone2, db: aiosqlite.Connection, ref: date) -> list[dict]:
    """Every goal of `ref`'s year, with its value so far in the week, month or year around `ref`."""
    # Only fetch goals for the year of the reference date
    cursor = await db.execute("SELECT * FROM goals WHERE year = ? ORDER BY id", (ref.year,))
    rows = await cursor.fetchall()
    goals = [row_dict(row) for row in rows]

    if not goals:
        return []

    activities = z2.strava_activities_cache.get_prepared_view()

    result = []
    for goal in goals:
        # Determine date range based on period
        if goal["period"] == "weekly":
            d_start = ref - timedelta(days=ref.weekday())
            d_end = d_start + timedelta(days=6)
        elif goal["period"] == "monthly":
            d_start = date(ref.year, ref.month, 1)
            d_end = date(ref.year, ref.month, calendar.monthrange(ref.year, ref.month)[1])
        elif goal["period"] == "yearly":
            d_start = date(ref.year, 1, 1)
            d_end = date(ref.year, 12, 31)
        else:
            continue

        # Filter activities
        mask = (
            (activities["start_date_local"].dt.date >= d_start)
            & (activities["start_date_local"].dt.date <= d_end)
        )
        if goal["sport_type"] != "__all__":
            mask = mask & (activities["sport_type"] == goal["sport_type"])

        filtered = activities[mask]

        # Compute current value based on metric
        metric = goal["metric"]
        if metric == "distance_km":
            current = float(filtered["distance"].sum()) / 1000.0
        elif metric == "time_hours":
            current = float(filtered["moving_time"].sum()) / 3600.0
        elif metric == "activities":
            current = float(len(filtered))
        elif metric == "elevation_m":
            current = float(filtered["total_elevation_gain"].sum())
        else:
            current = 0.0

        target = goal["target_value"]
        pct = (current / target * 100) if target > 0 else 0.0

        result.append({
            **goal,
            "current_value": round(current, 2),
            "percentage": round(pct, 1),
            "period_start": d_start.isoformat(),
            "period_end": d_end.isoformat(),
        })

    return result
