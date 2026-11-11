from datetime import date

from fastapi import APIRouter, Depends
import aiosqlite

from backend.db import get_db
from backend.dependencies import get_z2
from backend.services import goals
from backend.services.goals import GoalChanges, NewGoal
from zone2.core import Zone2

router = APIRouter()


@router.get("/")
async def list_goals(
    year: int | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await goals.goals_of(db, year)


@router.post("/", status_code=201)
async def create_goal(goal: NewGoal, db: aiosqlite.Connection = Depends(get_db)):
    return await goals.create(db, goal)


@router.put("/{goal_id}")
async def update_goal(
    goal_id: int,
    update: GoalChanges,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await goals.update(db, goal_id, update)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await goals.delete(db, goal_id)


@router.get("/progress")
async def goal_progress(
    week_start: date,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Compute progress for all goals given a reference week_start (YYYY-MM-DD)."""
    return {"goals": await goals.progress(z2, db, week_start)}
