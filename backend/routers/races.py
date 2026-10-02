from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite

from backend.db import get_db
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


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "date": row["date"],
        "sport_type": row["sport_type"],
        "distance_km": row["distance_km"],
        "target_pace": row["target_pace"],
        "description": row["description"],
        "location": row["location"],
        "url": row["url"],
        "created_at": row["created_at"],
    }


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
    return [_row_to_dict(row) for row in rows]


@router.get("/upcoming")
async def upcoming_race_events(db: aiosqlite.Connection = Depends(get_db)):
    today = date.today().isoformat()
    cursor = await db.execute(
        "SELECT * FROM race_events WHERE date >= ? ORDER BY date",
        (today,),
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


@router.post("/", status_code=201)
async def create_race_event(race: RaceEventCreate, db: aiosqlite.Connection = Depends(get_db),
                            z2: Zone2 = Depends(get_z2)):
    cursor = await db.execute(
        "INSERT INTO race_events (name, date, sport_type, distance_km, target_pace, description, location, url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (race.name, race.date, race.sport_type, race.distance_km, race.target_pace,
         race.description, race.location, race.url),
    )
    await db.commit()
    await _races_changed(z2)
    new_id = cursor.lastrowid
    cursor = await db.execute("SELECT * FROM race_events WHERE id = ?", (new_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.put("/{race_id}")
async def update_race_event(
    race_id: int,
    update: RaceEventUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    cursor = await db.execute("SELECT * FROM race_events WHERE id = ?", (race_id,))
    existing = await cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Race event not found")

    fields = []
    values = []
    for field_name, value in update.model_dump(exclude_unset=True).items():
        fields.append(f"{field_name} = ?")
        values.append(value)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(race_id)
    await db.execute(f"UPDATE race_events SET {', '.join(fields)} WHERE id = ?", values)
    await db.commit()
    await _races_changed(z2)

    cursor = await db.execute("SELECT * FROM race_events WHERE id = ?", (race_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.delete("/{race_id}", status_code=204)
async def delete_race_event(race_id: int, db: aiosqlite.Connection = Depends(get_db),
                            z2: Zone2 = Depends(get_z2)):
    cursor = await db.execute("SELECT id FROM race_events WHERE id = ?", (race_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Race event not found")
    await db.execute("DELETE FROM race_events WHERE id = ?", (race_id,))
    await db.commit()
    await _races_changed(z2)
