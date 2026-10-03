"""Saved workouts (the Workouts page) as a library with one workout per set of
steps and sport: a session built from steps links to the saved workout with
the same steps, or saves a new one, so planning it again can pick it."""
from __future__ import annotations

from datetime import date
from typing import Any

import aiosqlite

from backend.db import insert_row, row_dict
from backend.services.garmin_workouts import segment_steps, steps_hash, workout_name
from backend.services.zones import get_setting, set_setting

NAME_MAX = 60
LINKED_KEY = "workout_library_linked_upcoming"


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
