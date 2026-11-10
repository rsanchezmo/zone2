"""Saved workouts (the Workouts page) as a library with one workout per set of
steps and sport: a session built from steps links to the saved workout with
the same steps, or saves a new one, so planning it again can pick it."""
from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any

import aiosqlite
from fastapi import HTTPException

from backend.db import delete_row, insert_row, row_dict, update_row
from backend.services import garmin_workouts
from backend.services.garmin_workouts import segment_steps, steps_hash, workout_name
from backend.services.zones import get_setting, set_setting
from zone2.core import Zone2

if TYPE_CHECKING:
    from backend.services.sessions import Schedule

NAME_MAX = 60
LINKED_KEY = "workout_library_linked_upcoming"
JSON_COLS = ("segments",)


def template_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return row_dict(row, json_cols=JSON_COLS)


async def find_same(db: aiosqlite.Connection, sport_type: str, segments: list[dict[str, Any]],
                    exclude_id: int | None = None) -> dict[str, Any] | None:
    """The saved workout of this sport with these steps, if any."""
    key = steps_hash(segment_steps(segments))
    rows = await (await db.execute("SELECT * FROM workout_templates WHERE sport_type = ? AND id IS NOT ? ORDER BY id",
                                   (sport_type, exclude_id))).fetchall()
    for t in (row_dict(r, json_cols=("segments",)) for r in rows):
        if t["segments"] and steps_hash(segment_steps(t["segments"])) == key:
            return t
    return None


async def link_session(db: aiosqlite.Connection, session: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Point a session built from steps at the saved workout with the same steps,
    saving one (named after its description, else its main set) when there is
    none. Returns the session and whether a workout was saved."""
    template_id, created = None, False
    if session.get("segments"):
        same = await find_same(db, session["sport_type"], session["segments"])
        if same is None:
            name = (session.get("description") or "").strip()[:NAME_MAX] or workout_name(session)
            same = row_dict(await insert_row(db, "workout_templates", {
                "name": name, "sport_type": session["sport_type"], "segments": session["segments"],
            }, json_cols=("segments",)))
            created = True
        template_id = same["id"]
    if template_id != session.get("workout_template_id"):
        await db.execute("UPDATE training_sessions SET workout_template_id = ? WHERE id = ?", (template_id, session["id"]))
        await db.commit()
        session = {**session, "workout_template_id": template_id}
    return session, created


async def link_upcoming_once(db: aiosqlite.Connection) -> None:
    """Link the upcoming sessions built from steps, once, for those planned
    before sessions were linked on save."""
    if await get_setting(db, LINKED_KEY):
        return
    rows = await (await db.execute("SELECT * FROM training_sessions WHERE date >= ? AND segments IS NOT NULL",
                                   (date.today().isoformat(),))).fetchall()
    for r in rows:
        await link_session(db, row_dict(r, json_cols=("segments",)))
    await set_setting(db, LINKED_KEY, "1")


async def _reject_duplicate(db: aiosqlite.Connection, sport_type: str, segments: list[dict[str, Any]],
                            exclude_id: int | None = None) -> None:
    same = await find_same(db, sport_type, segments, exclude_id)
    if same is not None:
        raise HTTPException(status_code=409, detail=f"Same steps as “{same['name']}”")


async def create(z2: Zone2, db: aiosqlite.Connection, values: dict[str, Any], schedule: Schedule) -> dict[str, Any]:
    """Save a workout; a run goes to the Garmin library too. 409 when one has the same steps."""
    await _reject_duplicate(db, values["sport_type"], values["segments"])
    row = template_dict(await insert_row(db, "workout_templates", values, json_cols=JSON_COLS))
    schedule(garmin_workouts.sync_library, z2)
    return row


async def update(z2: Zone2, db: aiosqlite.Connection, template_id: int, values: dict[str, Any],
                 schedule: Schedule) -> dict[str, Any]:
    """Change a saved workout. Upcoming sessions planned from it take its new steps; past ones
    keep the steps they had."""
    if "segments" in values or "sport_type" in values:
        current = await (await db.execute("SELECT * FROM workout_templates WHERE id = ?", (template_id,))).fetchone()
        if current is not None:
            current = template_dict(current)
            await _reject_duplicate(db, values.get("sport_type") or current["sport_type"],
                                    values.get("segments") or current["segments"] or [], template_id)
    row = template_dict(await update_row(db, "workout_templates", template_id, values, "Template not found",
                                         json_cols=JSON_COLS))
    if "segments" in values:
        await db.execute("UPDATE training_sessions SET segments = ? WHERE workout_template_id = ? AND date >= ?",
                         (json.dumps(row["segments"]), template_id, date.today().isoformat()))
        await db.commit()
    if row["garmin_workout_id"] is not None and not garmin_workouts.is_run_workout(row):
        await db.execute("UPDATE workout_templates SET garmin_workout_id = NULL, garmin_sync_hash = NULL WHERE id = ?",
                         (template_id,))
        await db.commit()
        schedule(garmin_workouts.delete_copy, z2, row["garmin_workout_id"])
    schedule(garmin_workouts.sync_library, z2)
    return row


async def delete(z2: Zone2, db: aiosqlite.Connection, template_id: int, schedule: Schedule) -> None:
    """Its Garmin copy is deleted, and Garmin takes the copy's calendar entries with it.
    Planned sessions stay in the calendar with their steps."""
    row = await (await db.execute("SELECT garmin_workout_id FROM workout_templates WHERE id = ?",
                                  (template_id,))).fetchone()
    await delete_row(db, "workout_templates", template_id, "Template not found")
    await db.execute("UPDATE training_sessions SET workout_template_id = NULL, garmin_sync_state = NULL, "
                     "garmin_sync_error = NULL WHERE workout_template_id = ?", (template_id,))
    await db.commit()
    if row["garmin_workout_id"] is not None:
        schedule(garmin_workouts.delete_copy, z2, row["garmin_workout_id"])
