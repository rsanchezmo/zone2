"""The race calendar: its reads and writes, shared by the races router and the agent, and the
activity of each race, which the analytics count as races."""

import asyncio
import datetime
import sqlite3
from contextlib import closing
from typing import Any

import aiosqlite
import pandas as pd
from pydantic import BaseModel, Field

from backend.db import DB_PATH, delete_row, get_row, insert_row, row_dict, update_row
from backend.services.stats_cache import clear_stats_cache
from backend.services.workout_library import PACE_UNIT, Pace, check_kept_paces, check_paces
from zone2.core import Zone2
from zone2.utils import get_sport_category

NOT_FOUND = "Race event not found"
SPORT_TYPE = 'A Strava sport type: "Run", "Ride", "Swim"…'


class RaceChanges(BaseModel):
    name: str | None = None
    date: datetime.date | None = None
    sport_type: str | None = Field(None, description=SPORT_TYPE)
    distance_km: float | None = None
    target_pace: Pace | None = Field(None, description=f"Goal pace or speed, {PACE_UNIT}")
    location: str | None = None
    url: str | None = Field(None, description="The race's public page. Never a registration link with a personal "
                                               "token: race links go out in the calendar feed.")
    description: str | None = None


class NewRace(RaceChanges):
    name: str
    date: datetime.date
    sport_type: str = Field("Run", description=SPORT_TYPE)

# An event's activity is within this share of the event's distance: GPS
# over- and under-reads a course by a few percent, a warm-up is far shorter.
RACE_DISTANCE_TOLERANCE = 0.25


def race_activity_ids(activities: pd.DataFrame, events: list[tuple[str, str, float | None]]) -> frozenset[int]:
    """The activity of each race event (date, sport_type, distance_km): the one
    that day of the event's sport whose distance is closest to the event's."""
    if activities.empty or not events:
        return frozenset()
    days = activities['start_date_local'].dt.strftime('%Y-%m-%d')
    categories = activities['sport_type'].map(get_sport_category)
    ids = set()
    for day, sport_type, distance_km in events:
        candidates = activities[(days == day) & (categories == get_sport_category(sport_type))]
        if distance_km:
            off = (candidates['distance'] / 1000 - distance_km).abs()
            candidates = candidates[off <= RACE_DISTANCE_TOLERANCE * distance_km]
            off = off[candidates.index]
        else:
            off = -candidates['distance']   # no distance given: the longest that day
        if not candidates.empty:
            ids.add(int(candidates.loc[off.idxmin(), 'id']))
    return frozenset(ids)


async def races_changed(z2: Zone2) -> None:
    """After a race calendar change: re-point the analytics at the races, and drop the stats
    built on the old set."""
    if await asyncio.to_thread(refresh_race_activities, z2):
        clear_stats_cache()


def refresh_race_activities(z2: Zone2) -> bool:
    """Point the analytics at the activities of the user's race calendar, so a
    race counts as one without being flagged on Strava. Returns whether the
    set changed (race-based stats then need recomputing)."""
    with closing(sqlite3.connect(DB_PATH)) as c:
        events = c.execute("SELECT date, sport_type, distance_km FROM race_events").fetchall()
    ids = race_activity_ids(z2.strava_activities_cache.get_prepared_view(), events)
    return z2.strava_analytics.set_race_activity_ids(ids)


async def races_between(db: aiosqlite.Connection, date_from: str | None = None,
                        date_to: str | None = None) -> list[dict[str, Any]]:
    """The races between two days, inclusive (all of them without a range), by date."""
    if date_from and date_to:
        cursor = await db.execute("SELECT * FROM race_events WHERE date >= ? AND date <= ? ORDER BY date",
                                  (date_from, date_to))
    else:
        cursor = await db.execute("SELECT * FROM race_events ORDER BY date")
    return [row_dict(row) for row in await cursor.fetchall()]


async def upcoming(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """The races from today on, by date."""
    cursor = await db.execute("SELECT * FROM race_events WHERE date >= ? ORDER BY date",
                              (datetime.date.today().isoformat(),))
    return [row_dict(row) for row in await cursor.fetchall()]


async def get(db: aiosqlite.Connection, race_id: int) -> dict[str, Any]:
    return row_dict(await get_row(db, "race_events", race_id, NOT_FOUND))


async def create(z2: Zone2, db: aiosqlite.Connection, race: NewRace) -> dict[str, Any]:
    check_paces(race.sport_type, [race.target_pace])
    row = row_dict(await insert_row(db, "race_events", race.model_dump(mode="json")))
    await races_changed(z2)
    return row


async def update(z2: Zone2, db: aiosqlite.Connection, race_id: int, changes: RaceChanges) -> dict[str, Any]:
    values = changes.model_dump(mode="json", exclude_unset=True)
    current = await (await db.execute("SELECT sport_type, target_pace FROM race_events WHERE id = ?",
                                      (race_id,))).fetchone()
    if current is not None:
        sport_type = values.get("sport_type") or current["sport_type"]
        check_paces(sport_type, [values.get("target_pace")])
        check_kept_paces(current["sport_type"], sport_type, [] if "target_pace" in values else [current["target_pace"]])
    row = row_dict(await update_row(db, "race_events", race_id, values, NOT_FOUND))
    await races_changed(z2)
    return row


async def delete(z2: Zone2, db: aiosqlite.Connection, race_id: int) -> dict[str, Any]:
    """Delete a race and return it."""
    row = row_dict(await delete_row(db, "race_events", race_id, NOT_FOUND))
    await races_changed(z2)
    return row
