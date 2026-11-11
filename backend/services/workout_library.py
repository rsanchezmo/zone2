"""Saved workouts (the Workouts page) as a library with one workout per set of
steps and sport: a session built from steps links to the saved workout with
the same steps, or saves a new one, so planning it again can pick it. Also the
steps and targets every structured write shares (sessions, workouts, races)."""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from backend.db import delete_row, get_row, insert_row, row_dict, update_row
from backend.errors import Conflict, Invalid
from backend.services import garmin_workouts
from backend.services.garmin_workouts import segment_steps, steps_hash, workout_name
from backend.services.zones import get_setting, set_setting
from zone2.core import Zone2
from zone2.utils import SportCategory, convert_speed, get_sport_category

if TYPE_CHECKING:
    from backend.services.sessions import Schedule

NAME_MAX = 60
LINKED_KEY = "workout_library_linked_upcoming"
JSON_COLS = ("segments",)
NOT_FOUND = "Template not found"

# A target in the unit z2 stores for the sport (convert_speed's), as the calendar shows it
PACE_UNIT = ("in the sport's unit: decimal minutes per km for runs and walks (4.5 means 4:30/km), "
             "decimal minutes per 100 m for swims (1.75 means 1:45/100m), km/h for rides, rowing and paddling")
PACE_LOW = "The range's lower number: a pace's fast end, a speed's slow end"
Pace = Annotated[float, Field(gt=0)]
# A run's pace in min/km; outside this it is another unit (seconds, km/h) by mistake
RUN_PACE_RANGE = (2.0, 15.0)
HrZone = Annotated[int, Field(ge=1, le=5)]
ZonePct = Annotated[float, Field(gt=0, le=100)]


class Step(BaseModel):
    """One step of a structured session. A `work` step with repetitions > 1 repeats with
    its recovery in between."""
    type: Literal["warmup", "work", "recovery", "cooldown", "rest"]
    distance_km: float | None = None
    duration_mins: float | None = None
    repetitions: int = 1
    recovery_distance_km: float | None = None
    recovery_duration_mins: float | None = None
    target_pace_min: Pace | None = Field(None, description=f"{PACE_LOW}, {PACE_UNIT}")
    target_pace_max: Pace | None = Field(None, description="The range's higher number")
    target_hr_zone: HrZone | None = None
    target_zone_pct: ZonePct | None = Field(None, description="Share of the step to spend in that HR zone, %")
    label: str | None = None


class WorkoutChanges(BaseModel):
    name: str | None = Field(None, description='How it shows in the library and on the watch, e.g. "6×1 km @ threshold"')
    sport_type: str | None = Field(None, description='A Strava sport type: "Run", "Ride", "Swim"…')
    description: str | None = None
    segments: list[Step] | None = Field(None, description="Its steps")


class NewWorkout(WorkoutChanges):
    name: str
    sport_type: str
    segments: list[Step]


def write_values(fields: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    """The columns to write, with steps holding only the fields they set."""
    values = fields.model_dump(mode="json", exclude_unset=exclude_unset)
    if values.get("segments"):
        values["segments"] = [{k: v for k, v in step.items() if v is not None} for step in values["segments"]]
    return values


def step_paces(segments: list[dict[str, Any]] | None) -> list[float | None]:
    return [step.get(k) for step in segments or [] for k in ("target_pace_min", "target_pace_max")]


def check_paces(sport_type: str, paces: Iterable[float | None]) -> None:
    """A run's paces are minutes per km; other sports have their own units."""
    if get_sport_category(sport_type) != SportCategory.RUNNING:
        return
    low, high = RUN_PACE_RANGE
    for pace in paces:
        if pace is not None and not low < pace < high:
            raise Invalid(f"A run's pace is decimal minutes per km, between {low:g} and {high:g}: {pace:g} isn't")


def check_kept_paces(sport_type: str, new_sport_type: str, kept: Iterable[float | None]) -> None:
    """Targets a change of sport keeps stay in the old sport's unit, so they must read the same in the new one's."""
    unit, new_unit = convert_speed(1.0, sport_type)[1], convert_speed(1.0, new_sport_type)[1]
    if unit != new_unit and any(pace is not None for pace in kept):
        raise Invalid(f"Its targets are in {unit} and a {new_sport_type}'s are in {new_unit}: give them in {new_unit} too")


def template_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return row_dict(row, json_cols=JSON_COLS)


async def get(db: aiosqlite.Connection, template_id: int) -> dict[str, Any]:
    return template_dict(await get_row(db, "workout_templates", template_id, NOT_FOUND))


async def library(z2: Zone2, db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Saved workouts, newest first, with the state of their Garmin copy (runs) and how many
    planned sessions use them."""
    templates = [template_dict(r) for r in await (await db.execute(
        "SELECT * FROM workout_templates ORDER BY created_at DESC")).fetchall()]
    uses = {r[0]: r[1] for r in await (await db.execute(
        "SELECT workout_template_id, COUNT(*) FROM training_sessions WHERE workout_template_id IS NOT NULL "
        "GROUP BY workout_template_id")).fetchall()}
    enabled = await garmin_workouts.is_enabled(z2, db)
    for t in templates:
        t["garmin_sync_state"] = garmin_workouts.library_state(t, enabled)
        t["uses"] = uses.get(t["id"], 0)
        del t["garmin_sync_hash"]
    return templates


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
        raise Conflict(f"Same steps as “{same['name']}”")


async def create(z2: Zone2, db: aiosqlite.Connection, workout: NewWorkout, schedule: Schedule) -> dict[str, Any]:
    """Save a workout; a run goes to the Garmin library too. Conflict when one has the same steps."""
    values = write_values(workout)
    check_paces(workout.sport_type, step_paces(values["segments"]))
    await _reject_duplicate(db, workout.sport_type, values["segments"])
    row = template_dict(await insert_row(db, "workout_templates", values, json_cols=JSON_COLS))
    schedule(garmin_workouts.sync_library, z2)
    return row


async def update(z2: Zone2, db: aiosqlite.Connection, template_id: int, changes: WorkoutChanges,
                 schedule: Schedule) -> dict[str, Any]:
    """Change a saved workout. Upcoming sessions planned from it take its new steps; past ones
    keep the steps they had."""
    values = write_values(changes, exclude_unset=True)
    if "segments" in values or "sport_type" in values:
        current = await (await db.execute("SELECT * FROM workout_templates WHERE id = ?", (template_id,))).fetchone()
        if current is not None:
            current = template_dict(current)
            sport_type = values.get("sport_type") or current["sport_type"]
            check_paces(sport_type, step_paces(values.get("segments")))
            if "segments" not in values:
                check_kept_paces(current["sport_type"], sport_type, step_paces(current["segments"]))
            await _reject_duplicate(db, sport_type, values.get("segments") or current["segments"] or [], template_id)
    row = template_dict(await update_row(db, "workout_templates", template_id, values, NOT_FOUND,
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


async def delete(z2: Zone2, db: aiosqlite.Connection, template_id: int, schedule: Schedule) -> dict[str, Any]:
    """Delete a saved workout and return it. Its Garmin copy is deleted, and Garmin takes the
    copy's calendar entries with it. Planned sessions stay in the calendar with their steps."""
    row = template_dict(await delete_row(db, "workout_templates", template_id, NOT_FOUND))
    await db.execute("UPDATE training_sessions SET workout_template_id = NULL, garmin_sync_state = NULL, "
                     "garmin_sync_error = NULL WHERE workout_template_id = ?", (template_id,))
    await db.commit()
    if row["garmin_workout_id"] is not None:
        schedule(garmin_workouts.delete_copy, z2, row["garmin_workout_id"])
    return row
