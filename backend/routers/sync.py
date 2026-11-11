import asyncio
import logging
from datetime import datetime, timedelta
from threading import Lock

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Query

from backend.agent import reviews
from backend.dependencies import get_z2
from backend.routers.coverage import sync_all_cities
from backend.routers.exports import clear_export_cache
from backend.services.gear import clear_gear_cache
from backend.services.stats_cache import clear_stats_cache
from backend.services.races import refresh_race_activities
from zone2.core import Zone2

router = APIRouter()
logger = logging.getLogger(__name__)

# BackgroundTasks run in a thread pool while the status/trigger handlers run
# on the event loop. A threading.Lock works for both.
_sync_status = {"running": False, "last_error": None}
_sync_lock = Lock()


def _try_claim_sync() -> bool:
    """Atomic check-and-set. Returns True if the caller now owns the sync slot."""
    with _sync_lock:
        if _sync_status["running"]:
            return False
        _sync_status["running"] = True
        _sync_status["last_error"] = None
        return True


def _release_sync(error: str | None) -> None:
    with _sync_lock:
        _sync_status["running"] = False
        _sync_status["last_error"] = error


def _finalize_sync(z2: Zone2, error: str | None, version_before: int) -> str | None:
    """Invalidate/warm dependent caches when the sync changed the data (its
    version moved past `version_before`), and always release the sync slot."""
    try:
        if z2.strava_activities_cache.cache_version == version_before:
            logger.info("Sync changed nothing: caches kept")
            return error
        clear_stats_cache()
        clear_export_cache()
        clear_gear_cache()
        # Eagerly warm the in-memory cache so the first post-sync read doesn't
        # pay the full parquet reload cost on the user's request.
        z2.strava_activities_cache._load_to_memory()
        # A new activity may be the one of a race event
        refresh_race_activities(z2)
    except Exception as e:
        logger.exception("Sync cleanup failed")
        cleanup_error = f"cleanup failed: {type(e).__name__}: {e}"
        error = f"{error}; {cleanup_error}" if error else cleanup_error
    else:
        try:
            z2.strava_analytics.warm_caches()
        except Exception:
            logger.exception("Warming the stats caches after the sync failed")
    finally:
        _release_sync(error)
    return error


def _sync_activities(z2: Zone2, full_sync: bool, include_streams: bool) -> str | None:
    """Fetch and store new activities, refresh what depends on them, free the sync slot and
    queue the new ones for the coach to review. Returns the error, if any."""
    err: str | None = None
    version = z2.strava_activities_cache.cache_version
    before: set[int] = set()
    try:
        before = reviews.activity_ids(z2)
        z2.sync_activities(full_sync=full_sync, include_streams=include_streams)
    except Exception as e:
        logger.exception("Strava sync failed")
        err = str(e)
    err = _finalize_sync(z2, err, version)
    if err is None and z2.strava_activities_cache.cache_version != version:
        try:
            reviews.queue_new(z2, before)
        except Exception:
            logger.exception("Queueing the new activities for review failed")
    return err


def _sync_coverage(z2: Zone2) -> None:
    # New runs show up on the coverage map without a manual per-city sync
    try:
        sync_all_cities(z2)
    except Exception:
        logger.exception("Coverage sync after the Strava sync failed")


def _run_sync(z2: Zone2, full_sync: bool, include_streams: bool):
    if _sync_activities(z2, full_sync, include_streams) is None:
        _sync_coverage(z2)


# The catch-up running now, which a later caller waits for instead of starting another
_catching_up: asyncio.Future[str | None] | None = None


def catch_up(z2: Zone2, max_age: timedelta) -> asyncio.Future[str | None] | None:
    """An incremental sync, with the new activities' streams, when the last one is older than
    `max_age` and no other sync is running, or the catch-up already running. The future
    resolves once the new activities are stored and the caches refreshed; the coverage sync
    carries on after it."""
    global _catching_up
    if _catching_up is not None and not _catching_up.done():
        return _catching_up
    last = z2.strava_activities_cache.get_last_sync_time()
    if last is not None and datetime.now() - last < max_age:
        return None
    if not _try_claim_sync():
        return None
    loop = asyncio.get_running_loop()
    started = loop.time()
    # Executor futures keep running when the caller stops waiting, unlike a dropped task
    synced = loop.run_in_executor(None, _sync_activities, z2, False, True)

    def then_coverage(done: asyncio.Future[str | None]) -> None:
        logger.info("Strava catch-up took %.1fs", loop.time() - started)
        if not done.cancelled() and done.result() is None:
            loop.run_in_executor(None, _sync_coverage, z2)

    synced.add_done_callback(then_coverage)
    _catching_up = synced
    return synced


@router.post("")
def trigger_sync(
    background_tasks: BackgroundTasks,
    full_sync: bool = Query(default=False),
    include_streams: bool = Query(default=False),
    z2: Zone2 = Depends(get_z2),
):
    if not _try_claim_sync():
        return {"status": "already_running"}
    background_tasks.add_task(_run_sync, z2, full_sync, include_streams)
    return {"status": "started"}


def _run_backfill_streams(z2: Zone2):
    err: str | None = None
    version = z2.strava_activities_cache.cache_version
    try:
        z2.ensure_activities_with_streams()
    except Exception as e:
        logger.exception("Stream backfill failed")
        err = str(e)
    finally:
        _finalize_sync(z2, err, version)


@router.post("/backfill-streams")
def backfill_streams(
    background_tasks: BackgroundTasks,
    z2: Zone2 = Depends(get_z2),
):
    if not _try_claim_sync():
        return {"status": "already_running"}
    background_tasks.add_task(_run_backfill_streams, z2)
    return {"status": "started"}


def _resync_activity(z2: Zone2, activity_id: int, include_streams: bool) -> tuple[bool, str | None]:
    """Fetch one activity again, in the sync slot the caller claimed: whether Strava returned
    it, and the error, if any."""
    err: str | None = None
    found = False
    version = z2.strava_activities_cache.cache_version
    try:
        found = z2.strava_activities_cache.resync_activity(
            activity_id=activity_id,
            strava_endpoint=z2.strava_endpoint,
            include_streams=include_streams,
        )
    except Exception as e:
        logger.exception("Resyncing activity %s failed", activity_id)
        err = str(e)
    return found, _finalize_sync(z2, err, version)


@router.post("/activity/{activity_id}")
def resync_activity(
    activity_id: int,
    include_streams: bool = Query(default=False),
    z2: Zone2 = Depends(get_z2),
):
    """Refresh a single activity from Strava (e.g., to pick up a renamed activity)."""
    if not _try_claim_sync():
        return {"status": "already_running"}
    found, err = _resync_activity(z2, activity_id, include_streams)
    if err:
        raise HTTPException(status_code=502, detail=err)
    if not found:
        raise HTTPException(status_code=404, detail="Activity not found or no detail returned")
    return {"status": "success"}


async def sync_now(z2: Zone2, activity_id: int | None = None) -> str | None:
    """Sync Strava now, or fetch one activity again with its streams, and wait for it.
    Returns what went wrong, if anything."""
    if activity_id is not None:
        if not _try_claim_sync():
            return "A sync is already running; try again in a minute."
        found, err = await asyncio.to_thread(_resync_activity, z2, activity_id, True)
        return err or (None if found else f"Strava has no activity {activity_id}.")
    strava = catch_up(z2, timedelta(0))
    if strava is None:
        return "A sync is already running; try again in a minute."
    return await strava


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
    with _sync_lock:
        syncing = _sync_status["running"]
        last_error = _sync_status["last_error"]
    return {
        "syncing": syncing,
        "last_error": last_error,
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
