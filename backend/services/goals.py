"""Yearly goals and how far along each is (this week, month or year), shared by the goals
router and the agent."""

import calendar
from datetime import date, timedelta
from typing import Annotated, Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from backend.db import delete_row, insert_row, row_dict, update_row
from zone2.core import Zone2

NOT_FOUND = "Goal not found"
SPORT_TYPE = ('A Strava sport type ("Run", "Ride", "Swim"…), which counts that type only ("Run" leaves out '
              'TrailRun and VirtualRun), or "__all__" for every sport')
GoalMetric = Literal["distance_km", "time_hours", "activities", "elevation_m"]
GoalPeriod = Literal["weekly", "monthly", "yearly"]
Target = Annotated[float, Field(gt=0)]


class GoalChanges(BaseModel):
    year: int | None = None
    sport_type: str | None = Field(None, description=SPORT_TYPE)
    metric: GoalMetric | None = None
    period: GoalPeriod | None = None
    target_value: Target | None = None


class NewGoal(GoalChanges):
    year: int
    sport_type: str = Field(description=SPORT_TYPE)
    metric: GoalMetric
    period: GoalPeriod
    target_value: Target


async def goals_of(db: aiosqlite.Connection, year: int | None = None) -> list[dict[str, Any]]:
    """The goals of a year, or all of them."""
    if year is None:
        cursor = await db.execute("SELECT * FROM goals ORDER BY id")
    else:
        cursor = await db.execute("SELECT * FROM goals WHERE year = ? ORDER BY id", (year,))
    return [row_dict(row) for row in await cursor.fetchall()]


async def create(db: aiosqlite.Connection, goal: NewGoal) -> dict[str, Any]:
    return row_dict(await insert_row(db, "goals", goal.model_dump(mode="json")))


async def update(db: aiosqlite.Connection, goal_id: int, changes: GoalChanges) -> dict[str, Any]:
    return row_dict(await update_row(db, "goals", goal_id, changes.model_dump(mode="json", exclude_unset=True),
                                     NOT_FOUND))


async def delete(db: aiosqlite.Connection, goal_id: int) -> dict[str, Any]:
    """Delete a goal and return it."""
    return row_dict(await delete_row(db, "goals", goal_id, NOT_FOUND))


async def progress(z2: Zone2, db: aiosqlite.Connection, ref: date) -> list[dict]:
    """Every goal of `ref`'s year, with its value so far in the week, month or year around `ref`."""
    goals = await goals_of(db, ref.year)

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
