from datetime import datetime, timedelta, date
import calendar

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import aiosqlite
import pandas as pd

from backend.db import get_db
from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence

router = APIRouter()


class GoalCreate(BaseModel):
    year: int
    sport_type: str  # e.g. "Run", "Ride", or "__all__"
    metric: str  # "distance_km", "time_hours", "activities", "elevation_m"
    period: str  # "weekly", "monthly", "yearly"
    target_value: float


class GoalUpdate(BaseModel):
    year: int | None = None
    sport_type: str | None = None
    metric: str | None = None
    period: str | None = None
    target_value: float | None = None


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "year": row["year"],
        "sport_type": row["sport_type"],
        "metric": row["metric"],
        "period": row["period"],
        "target_value": row["target_value"],
        "created_at": row["created_at"],
    }


@router.get("/")
async def list_goals(
    year: int | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    if year is not None:
        cursor = await db.execute("SELECT * FROM goals WHERE year = ? ORDER BY id", (year,))
    else:
        cursor = await db.execute("SELECT * FROM goals ORDER BY id")
    rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


@router.post("/", status_code=201)
async def create_goal(goal: GoalCreate, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute(
        "INSERT INTO goals (year, sport_type, metric, period, target_value) VALUES (?, ?, ?, ?, ?)",
        (goal.year, goal.sport_type, goal.metric, goal.period, goal.target_value),
    )
    await db.commit()
    new_id = cursor.lastrowid
    cursor = await db.execute("SELECT * FROM goals WHERE id = ?", (new_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.put("/{goal_id}")
async def update_goal(
    goal_id: int,
    update: GoalUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT * FROM goals WHERE id = ?", (goal_id,))
    existing = await cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Goal not found")

    fields = []
    values = []
    for field_name, value in update.model_dump(exclude_unset=True).items():
        fields.append(f"{field_name} = ?")
        values.append(value)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(goal_id)
    await db.execute(f"UPDATE goals SET {', '.join(fields)} WHERE id = ?", values)
    await db.commit()

    cursor = await db.execute("SELECT * FROM goals WHERE id = ?", (goal_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: int, db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT id FROM goals WHERE id = ?", (goal_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Goal not found")
    await db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    await db.commit()


@router.get("/progress")
async def goal_progress(
    week_start: str,
    db: aiosqlite.Connection = Depends(get_db),
    si: StravaIntelligence = Depends(get_si),
):
    """Compute progress for all goals given a reference week_start (YYYY-MM-DD)."""
    ref = datetime.strptime(week_start, "%Y-%m-%d").date()

    # Only fetch goals for the year of the reference date
    cursor = await db.execute("SELECT * FROM goals WHERE year = ? ORDER BY id", (ref.year,))
    rows = await cursor.fetchall()
    goals = [_row_to_dict(row) for row in rows]

    if not goals:
        return {"goals": []}

    activities = si.strava_activities_cache.activities_raw.copy()
    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])

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

    return {"goals": result}
