"""Planned training sessions: the calendar's reads and writes, shared by the calendar router and the agent."""

import datetime
from collections.abc import Callable
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from backend.db import delete_row, get_row, insert_row, row_dict, update_row
from backend.errors import Invalid, NotFound
from backend.services import garmin_workouts, workout_library
from backend.services.workout_library import (
    PACE_LOW, PACE_UNIT, HrZone, Pace, Step, ZonePct, check_kept_paces, check_paces, distance_after_steps, step_paces,
    write_values,
)
from zone2.core import Zone2

JSON_COLS = ("segments",)
NOT_FOUND = "Session not found"
SPORT_TYPE = 'A Strava sport type: "Run", "Ride", "Swim", "WeightTraining", "Rest"…'

# Queues work to run once the write is answered, like BackgroundTasks.add_task:
# the Garmin library and calendar pushes are slow live calls.
Schedule = Callable[..., Any]


class SessionFields(BaseModel):
    title: str | None = None
    sport_type: str | None = Field(None, description=SPORT_TYPE)
    description: str | None = None
    planned_distance_km: float | None = None
    planned_duration_mins: float | None = None
    planned_intensity: Literal["easy", "moderate", "hard", "race"] | None = None
    target_avg_pace: Pace | None = Field(None, description=f"Target pace or speed, {PACE_UNIT}")
    target_pace_min: Pace | None = Field(None, description=f"{PACE_LOW}, in the same unit")
    target_pace_max: Pace | None = Field(None, description="The range's higher number")
    target_hr_zone: HrZone | None = None
    target_zone_pct: ZonePct | None = Field(None, description="Share of the session to spend in that HR zone, %")
    segments: list[Step] | None = Field(None, description="Steps, for a structured session such as intervals")
    workout_template_id: int | None = Field(None, description="A saved workout of its sport to plan it from: "
                                                              "without segments, the session takes its steps")


class NewSession(SessionFields):
    plan_id: int | None = Field(None, description="The plan the session belongs to")
    date: datetime.date
    title: str
    sport_type: str = Field(description=SPORT_TYPE)


class SessionChanges(SessionFields):
    date: datetime.date | None = None
    completed: bool | None = None


def session_dict(row: aiosqlite.Row) -> dict:
    return row_dict(row, json_cols=JSON_COLS, bool_cols=("completed",))


def _paces(values: dict[str, Any]) -> list[float | None]:
    return [values.get("target_avg_pace"), values.get("target_pace_min"), values.get("target_pace_max"),
            *step_paces(values.get("segments"))]


async def get(db: aiosqlite.Connection, session_id: int) -> dict[str, Any]:
    return session_dict(await get_row(db, "training_sessions", session_id, NOT_FOUND))


async def between(db: aiosqlite.Connection, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """The planned sessions between two days, inclusive (all of them without a range), each with
    `plan_name`, the coach's plan it belongs to."""
    where, params = ("WHERE s.date BETWEEN ? AND ?", (date_from, date_to)) if date_from and date_to else ("", ())
    cur = await db.execute(
        f"SELECT s.*, p.name AS plan_name FROM training_sessions s LEFT JOIN training_plans p ON p.id = s.plan_id "
        f"{where} ORDER BY s.date, s.id", params,
    )
    return [session_dict(r) for r in await cur.fetchall()]


async def from_workout(db: aiosqlite.Connection, workout_template_id: int, until: str, limit: int) -> list[dict]:
    """The sessions planned from a saved workout up to `until`, latest first: id, date, title and sport."""
    rows = await (await db.execute(
        "SELECT id, date, title, sport_type FROM training_sessions WHERE workout_template_id = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        (workout_template_id, until, limit),
    )).fetchall()
    return [dict(r) for r in rows]


async def _plan_from_workout(db: aiosqlite.Connection, values: dict[str, Any], sport_type: str) -> None:
    """A write that names a saved workout of the session's sport and no steps takes the
    workout's steps, as the calendar does when one is picked from the library, so linking keeps it."""
    template_id = values.get("workout_template_id")
    if template_id is None or values.get("segments"):
        return
    try:
        workout = await workout_library.get(db, template_id)
    except NotFound as e:
        raise Invalid(f"There is no saved workout {template_id}") from e
    if workout["sport_type"] != sport_type:
        raise Invalid(f"Saved workout {template_id} is a {workout['sport_type']} workout and the session a "
                      f"{sport_type}: give the session its sport too")
    values["segments"] = workout["segments"]


async def _link_saved_workout(schedule: Schedule, z2: Zone2, db: aiosqlite.Connection, session: dict) -> dict:
    """Link the session to its saved workout, saving a new one to the library (and Garmin) when needed."""
    session, created = await workout_library.link_session(db, session)
    if created:
        schedule(garmin_workouts.sync_library, z2)
    return session


async def _queue_watch_sync(schedule: Schedule, z2: Zone2, db: aiosqlite.Connection, session: dict,
                            previous_date: str | None = None) -> dict:
    """Queue the change the session's Garmin calendar entry needs, if any, and return the session as it now stands."""
    if await garmin_workouts.mark_pending(z2, db, session, previous_date):
        schedule(garmin_workouts.sync_session, z2, session["id"])
        return {**session, "garmin_sync_state": garmin_workouts.SyncState.PENDING}
    return session


async def create(z2: Zone2, db: aiosqlite.Connection, session: NewSession, schedule: Schedule) -> dict:
    values = write_values(session)
    values["segments"] = values["segments"] or None
    await _plan_from_workout(db, values, session.sport_type)
    check_paces(session.sport_type, _paces(values))
    row = session_dict(await insert_row(db, "training_sessions", values, json_cols=JSON_COLS))
    row = await _link_saved_workout(schedule, z2, db, row)
    return await _queue_watch_sync(schedule, z2, db, row)


async def update(z2: Zone2, db: aiosqlite.Connection, session_id: int, changes: SessionChanges,
                 schedule: Schedule) -> dict:
    values = write_values(changes, exclude_unset=True)
    found = await (await db.execute("SELECT * FROM training_sessions WHERE id = ?", (session_id,))).fetchone()
    before = session_dict(found) if found is not None else None
    if before is not None:
        sport_type = values.get("sport_type") or before["sport_type"]
        # Naming the workout it already follows keeps its steps: a past session keeps the ones it had
        if values.get("workout_template_id") != before["workout_template_id"] or not before["segments"]:
            await _plan_from_workout(db, values, sport_type)
        if "segments" in values and "planned_distance_km" not in values:
            values["planned_distance_km"] = distance_after_steps(before["planned_distance_km"], before["segments"],
                                                                 values["segments"])
        check_paces(sport_type, _paces(values))
        check_kept_paces(before["sport_type"], sport_type, _paces({k: v for k, v in before.items() if k not in values}))
    row = session_dict(await update_row(db, "training_sessions", session_id, values, NOT_FOUND, json_cols=JSON_COLS))
    # Only a change of steps relinks, so marking a session done can't resave a deleted workout
    if "segments" in values or "sport_type" in values:
        row = await _link_saved_workout(schedule, z2, db, row)
    return await _queue_watch_sync(schedule, z2, db, row, before["date"] if before else None)


async def delete(z2: Zone2, db: aiosqlite.Connection, session_id: int, schedule: Schedule) -> dict:
    """Delete a session and return it; an upcoming entry on the watch goes too."""
    row = session_dict(await delete_row(db, "training_sessions", session_id, NOT_FOUND))
    schedule(garmin_workouts.forget_session, z2, session_id)
    return row
