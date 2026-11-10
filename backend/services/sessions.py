"""Planned training sessions: the calendar's reads and writes, shared by the calendar router and the agent."""

from collections.abc import Callable
from typing import Any

import aiosqlite

from backend.db import delete_row, insert_row, row_dict, update_row
from backend.services import garmin_workouts, workout_library
from zone2.core import Zone2

JSON_COLS = ("segments",)

# Queues work to run once the write is answered, like BackgroundTasks.add_task:
# the Garmin library and calendar pushes are slow live calls.
Schedule = Callable[..., Any]


def session_dict(row: aiosqlite.Row) -> dict:
    return row_dict(row, json_cols=JSON_COLS, bool_cols=("completed",))


async def between(db: aiosqlite.Connection, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    """The planned sessions between two days, inclusive (all of them without a range), each with
    `plan_name`, the coach's plan it belongs to."""
    where, params = ("WHERE s.date BETWEEN ? AND ?", (date_from, date_to)) if date_from and date_to else ("", ())
    cur = await db.execute(
        f"SELECT s.*, p.name AS plan_name FROM training_sessions s LEFT JOIN training_plans p ON p.id = s.plan_id "
        f"{where} ORDER BY s.date, s.id", params,
    )
    return [session_dict(r) for r in await cur.fetchall()]


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


async def create(z2: Zone2, db: aiosqlite.Connection, values: dict, schedule: Schedule) -> dict:
    values = {**values, "segments": values.get("segments") or None}
    row = session_dict(await insert_row(db, "training_sessions", values, json_cols=JSON_COLS))
    row = await _link_saved_workout(schedule, z2, db, row)
    return await _queue_watch_sync(schedule, z2, db, row)


async def update(z2: Zone2, db: aiosqlite.Connection, session_id: int, values: dict, schedule: Schedule) -> dict:
    before = await (await db.execute("SELECT date FROM training_sessions WHERE id = ?", (session_id,))).fetchone()
    row = session_dict(await update_row(db, "training_sessions", session_id, values, "Session not found",
                                        json_cols=JSON_COLS))
    # Only a change of steps relinks, so marking a session done can't resave a deleted workout
    if "segments" in values or "sport_type" in values:
        row = await _link_saved_workout(schedule, z2, db, row)
    return await _queue_watch_sync(schedule, z2, db, row, before["date"] if before else None)


async def delete(z2: Zone2, db: aiosqlite.Connection, session_id: int, schedule: Schedule) -> None:
    await delete_row(db, "training_sessions", session_id, "Session not found")
    schedule(garmin_workouts.forget_session, z2, session_id)
