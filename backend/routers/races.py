from fastapi import APIRouter, Depends
import aiosqlite

from backend.db import get_db
from backend.dependencies import get_z2
from backend.services import races
from backend.services.races import NewRace, RaceChanges
from zone2.core import Zone2

router = APIRouter()


@router.get("/")
async def list_race_events(
    date_from: str | None = None,
    date_to: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await races.races_between(db, date_from, date_to)


@router.get("/upcoming")
async def upcoming_race_events(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    return await races.upcoming(z2, db)


@router.post("/", status_code=201)
async def create_race_event(race: NewRace, db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    return await races.create(z2, db, race)


@router.put("/{race_id}")
async def update_race_event(
    race_id: int,
    update: RaceChanges,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    return await races.update(z2, db, race_id, update)


@router.delete("/{race_id}", status_code=204)
async def delete_race_event(race_id: int, db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    await races.delete(z2, db, race_id)
