from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Query

from backend.dependencies import get_z2
from backend.services import sync as strava_sync
from zone2.core import Zone2

router = APIRouter()


@router.post("")
def trigger_sync(
    background_tasks: BackgroundTasks,
    full_sync: bool = Query(default=False),
    include_streams: bool = Query(default=False),
    z2: Zone2 = Depends(get_z2),
):
    if not strava_sync.try_claim():
        return {"status": "already_running"}
    background_tasks.add_task(strava_sync.run, z2, full_sync, include_streams)
    return {"status": "started"}


@router.post("/backfill-streams")
def backfill_streams(
    background_tasks: BackgroundTasks,
    z2: Zone2 = Depends(get_z2),
):
    if not strava_sync.try_claim():
        return {"status": "already_running"}
    background_tasks.add_task(strava_sync.backfill_streams, z2)
    return {"status": "started"}


@router.post("/activity/{activity_id}")
def resync_activity(
    activity_id: int,
    include_streams: bool = Query(default=False),
    z2: Zone2 = Depends(get_z2),
):
    """Refresh a single activity from Strava (e.g., to pick up a renamed activity)."""
    if not strava_sync.try_claim():
        return {"status": "already_running"}
    found, err = strava_sync.resync_activity(z2, activity_id, include_streams)
    if err:
        raise HTTPException(status_code=502, detail=err)
    if not found:
        raise HTTPException(status_code=404, detail="Activity not found or no detail returned")
    return {"status": "success"}


@router.get("/cache-completeness")
def cache_completeness(z2: Zone2 = Depends(get_z2)):
    return z2.strava_activities_cache.get_cache_completeness()


@router.get("/status")
def sync_status(z2: Zone2 = Depends(get_z2)):
    cache = z2.strava_activities_cache
    try:
        profile = z2.strava_user_cache.get_athlete_profile()
        athlete_name = f"{profile.get('firstname', '')} {profile.get('lastname', '')}".strip() or None
    except Exception:
        athlete_name = None
    slot = strava_sync.status()
    return {
        "syncing": slot.running,
        "last_error": slot.last_error,
        "last_sync_at": cache.get_last_sync_time().isoformat() if cache.get_last_sync_time() else None,
        "total_activities": cache.count_cached_activities(),
        "needs_sync": cache.needs_sync(),
        "last_activity_date": str(cache.get_last_activity_date()) if cache.get_last_activity_date() else None,
        "earliest_activity_date": str(cache.get_earliest_activity_date()) if cache.get_earliest_activity_date() else None,
        "athlete_name": athlete_name,
        # Moves whenever the cached activities change: a sync that leaves it
        # alone changed nothing the app shows
        "cache_version": cache.cache_version,
    }
