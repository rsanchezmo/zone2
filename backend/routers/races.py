from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite

from backend.db import delete_row, get_db, insert_row, row_dict, update_row
from backend.dependencies import get_z2
from backend.routers.stats import clear_stats_cache
from backend.services.races import refresh_race_activities
from zone2.core import Zone2

router = APIRouter()


class RaceEventCreate(BaseModel):
    name: str
    date: str  # YYYY-MM-DD
    sport_type: str
    distance_km: float | None = None
    target_pace: float | None = None
    description: str | None = None
    location: str | None = None
    url: str | None = None


class RaceEventUpdate(BaseModel):
    name: str | None = None
    date: str | None = None
    sport_type: str | None = None
    distance_km: float | None = None
    target_pace: float | None = None
    description: str | None = None
    location: str | None = None
    url: str | None = None


async def _races_changed(z2: Zone2) -> None:
    """Race events decide which activities count as races for the predictions."""
    if await run_in_threadpool(refresh_race_activities, z2):
        clear_stats_cache()


@router.get("/")
async def list_race_events(
    date_from: str | None = None,
    date_to: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    if date_from and date_to:
        cursor = await db.execute(
            "SELECT * FROM race_events WHERE date >= ? AND date <= ? ORDER BY date",
            (date_from, date_to),
        )
    else:
        cursor = await db.execute("SELECT * FROM race_events ORDER BY date")
    rows = await cursor.fetchall()
    return [row_dict(row) for row in rows]


@router.get("/upcoming")
async def upcoming_race_events(db: aiosqlite.Connection = Depends(get_db)):
    today = date.today().isoformat()
    cursor = await db.execute(
        "SELECT * FROM race_events WHERE date >= ? ORDER BY date",
        (today,),
    )
    rows = await cursor.fetchall()
    return [row_dict(row) for row in rows]


@router.post("/", status_code=201)
async def create_race_event(race: RaceEventCreate, db: aiosqlite.Connection = Depends(get_db),
                            z2: Zone2 = Depends(get_z2)):
    row = await insert_row(db, "race_events", race.model_dump())
    await _races_changed(z2)
    return row_dict(row)


@router.put("/{race_id}")
async def update_race_event(
    race_id: int,
    update: RaceEventUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    row = await update_row(db, "race_events", race_id, update.model_dump(exclude_unset=True), "Race event not found")
    await _races_changed(z2)
    return row_dict(row)


@router.delete("/{race_id}", status_code=204)
async def delete_race_event(race_id: int, db: aiosqlite.Connection = Depends(get_db),
                            z2: Zone2 = Depends(get_z2)):
    await delete_row(db, "race_events", race_id, "Race event not found")
    await _races_changed(z2)
