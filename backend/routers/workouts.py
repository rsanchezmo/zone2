import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite

from backend._ttl_cache import TTLCache
from backend.db import get_db
from backend.dependencies import get_z2
from backend.services import garmin_workouts, workout_library
from zone2.core import Zone2
from zone2.garmin_client import GarminClient, GarminUnavailable

logger = logging.getLogger(__name__)

router = APIRouter()

# Parsed steps per (workout, Garmin version): they only change when the workout is edited
_garmin_steps_cache = TTLCache(maxsize=512, ttl_seconds=7 * 86400)


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


@router.get("")
async def list_templates(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """Saved workouts, newest first, with the state of their Garmin copy (runs)
    and how many planned sessions use them."""
    templates = [workout_library.template_dict(r) for r in await (await db.execute(
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


def _garmin_workouts(client: GarminClient, ours: set[int]) -> list[dict]:
    """The library's workouts other than z2's copies, newest first, with their
    steps as z2 segments (each fetched once per Garmin version)."""
    listed = garmin_workouts.library_listing.get("library")
    if listed is None:
        listed = sorted(client.list_workouts(), key=lambda w: w.get("createdDate") or "", reverse=True)
        garmin_workouts.library_listing.set("library", listed)
    workouts = []
    for w in listed:
        if w["workoutId"] in ours:
            continue
        key = (w["workoutId"], w.get("updateDate"))
        parsed = _garmin_steps_cache.get(key)
        if parsed is None:
            parsed = garmin_workouts.garmin_segments(client.get_workout(w["workoutId"]))
            _garmin_steps_cache.set(key, parsed)
        sport_type, segments = parsed
        workouts.append({
            "workout_id": w["workoutId"],
            "name": w.get("workoutName"),
            "sport_type": sport_type,
            "created_at": (w.get("createdDate") or "")[:10] or None,
            "distance_km": round(w["estimatedDistanceInMeters"] / 1000, 2) if w.get("estimatedDistanceInMeters") else None,
            "duration_s": w.get("estimatedDurationInSecs"),
            "segments": segments,
        })
    return workouts


@router.get("/garmin")
async def garmin_library(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """The Garmin library's other workouts (made in Garmin Connect), newest first."""
    if not z2.garmin_client.email:
        return []
    ours = {r[0] for r in await (await db.execute(
        "SELECT garmin_workout_id FROM workout_templates WHERE garmin_workout_id IS NOT NULL")).fetchall()}
    try:
        return await run_in_threadpool(_garmin_workouts, z2.garmin_client, ours)
    except GarminUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.warning("Garmin workout list failed: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=502, detail=f"Garmin Connect failed: {e}")


@router.post("", status_code=201)
async def create_template(
    template: WorkoutTemplateCreate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    return await workout_library.create(z2, db, template.model_dump(), tasks.add_task)


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    update: WorkoutTemplateUpdate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    return await workout_library.update(z2, db, template_id, update.model_dump(exclude_unset=True), tasks.add_task)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Its Garmin copy is deleted, and Garmin takes the copy's calendar entries
    with it. Planned sessions stay in the calendar with their steps."""
    await workout_library.delete(z2, db, template_id, tasks.add_task)
