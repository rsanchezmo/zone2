from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
import aiosqlite

from backend.db import delete_row, get_db, insert_row, row_dict, update_row
from backend.dependencies import get_z2
from backend.services import goals as goals_service
from zone2.core import Zone2

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
    return [row_dict(row) for row in rows]


@router.post("/", status_code=201)
async def create_goal(goal: GoalCreate, db: aiosqlite.Connection = Depends(get_db)):
    return row_dict(await insert_row(db, "goals", goal.model_dump()))


@router.put("/{goal_id}")
async def update_goal(
    goal_id: int,
    update: GoalUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    return row_dict(await update_row(db, "goals", goal_id, update.model_dump(exclude_unset=True), "Goal not found"))


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await delete_row(db, "goals", goal_id, "Goal not found")


@router.get("/progress")
async def goal_progress(
    week_start: date,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Compute progress for all goals given a reference week_start (YYYY-MM-DD)."""
    return {"goals": await goals_service.progress(z2, db, week_start)}
