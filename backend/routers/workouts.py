import json
import logging
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite

from backend._ttl_cache import TTLCache
from backend.db import delete_row, get_db, insert_row, row_dict, update_row
from backend.dependencies import get_z2
from backend.services import garmin_workouts
from backend.services.workout_library import find_same
from zone2.core import Zone2
from zone2.garmin_client import GarminUnavailable

logger = logging.getLogger(__name__)

_JSON_COLS = ("segments",)

router = APIRouter()

_garmin_library_cache = TTLCache(maxsize=1, ttl_seconds=600)


class WorkoutTemplateCreate(BaseModel):
    name: str
    sport_type: str
    description: str | None = None
    segments: list[dict]


class WorkoutTemplateUpdate(BaseModel):
    name: str | None = None
    sport_type: str | None = None
    description: str | None = None
    segments: list[dict] | None = None


def _template(row: aiosqlite.Row) -> dict:
    return row_dict(row, json_cols=("segments",))


async def _reject_duplicate(db: aiosqlite.Connection, sport_type: str, segments: list[dict],
                            exclude_id: int | None = None) -> None:
    same = await find_same(db, sport_type, segments, exclude_id)
    if same is not None:
        raise HTTPException(status_code=409, detail=f"Same steps as “{same['name']}”")


@router.get("")
async def list_templates(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """Saved workouts, newest first, with the state of their Garmin copy (runs)
    and how many planned sessions use them."""
    templates = [_template(r) for r in await (await db.execute(
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


@router.get("/garmin")
async def garmin_library(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """The Garmin library's other workouts (made in Garmin Connect), newest first."""
    if not z2.garmin_client.email:
        return []
    workouts = _garmin_library_cache.get("library")
    if workouts is None:
        try:
            raw = await run_in_threadpool(z2.garmin_client.list_workouts)
        except GarminUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            logger.warning("Garmin workout list failed: %s: %s", type(e).__name__, e)
            raise HTTPException(status_code=502, detail=f"Garmin Connect failed: {e}")
        workouts = [{
            "workout_id": w["workoutId"],
            "name": w.get("workoutName"),
            "sport": (w.get("sportType") or {}).get("sportTypeKey"),
            "created_at": (w.get("createdDate") or "")[:10] or None,
            "distance_km": round(w["estimatedDistanceInMeters"] / 1000, 2) if w.get("estimatedDistanceInMeters") else None,
            "duration_s": w.get("estimatedDurationInSecs"),
        } for w in sorted(raw, key=lambda w: w.get("createdDate") or "", reverse=True)]
        _garmin_library_cache.set("library", workouts)
    ours = {r[0] for r in await (await db.execute(
        "SELECT garmin_workout_id FROM workout_templates WHERE garmin_workout_id IS NOT NULL")).fetchall()}
    return [w for w in workouts if w["workout_id"] not in ours]


@router.post("", status_code=201)
async def create_template(
    template: WorkoutTemplateCreate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    await _reject_duplicate(db, template.sport_type, template.segments)
    row = _template(await insert_row(db, "workout_templates", template.model_dump(), json_cols=_JSON_COLS))
    tasks.add_task(garmin_workouts.sync_library, z2)
    return row


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    update: WorkoutTemplateUpdate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    values = update.model_dump(exclude_unset=True)
    if "segments" in values or "sport_type" in values:
        current = await (await db.execute("SELECT * FROM workout_templates WHERE id = ?", (template_id,))).fetchone()
        if current is not None:
            current = _template(current)
            await _reject_duplicate(db, values.get("sport_type") or current["sport_type"],
                                    values.get("segments") or current["segments"] or [], template_id)
    row = _template(await update_row(db, "workout_templates", template_id, values, "Template not found",
                                     json_cols=_JSON_COLS))
    if "segments" in values:
        # Upcoming sessions planned from it follow; past ones keep the steps they had
        await db.execute("UPDATE training_sessions SET segments = ? WHERE workout_template_id = ? AND date >= ?",
                         (json.dumps(row["segments"]), template_id, date.today().isoformat()))
        await db.commit()
    if row["garmin_workout_id"] is not None and not garmin_workouts.is_run_workout(row):
        await db.execute("UPDATE workout_templates SET garmin_workout_id = NULL, garmin_sync_hash = NULL WHERE id = ?",
                         (template_id,))
        await db.commit()
        tasks.add_task(garmin_workouts.delete_copy, z2, row["garmin_workout_id"])
    tasks.add_task(garmin_workouts.sync_library, z2)
    return row


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Its Garmin copy is deleted, and Garmin takes the copy's calendar entries
    with it. Planned sessions stay in the calendar with their steps."""
    row = await (await db.execute("SELECT garmin_workout_id FROM workout_templates WHERE id = ?",
                                  (template_id,))).fetchone()
    await delete_row(db, "workout_templates", template_id, "Template not found")
    await db.execute("UPDATE training_sessions SET workout_template_id = NULL, garmin_sync_state = NULL, "
                     "garmin_sync_error = NULL WHERE workout_template_id = ?", (template_id,))
    await db.commit()
    if row["garmin_workout_id"] is not None:
        _garmin_library_cache.clear()
        tasks.add_task(garmin_workouts.delete_copy, z2, row["garmin_workout_id"])
