import logging
from threading import Lock

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Query

from backend.dependencies import get_si
from backend.routers.exports import clear_export_cache
from backend.routers.gear import clear_gear_cache
from backend.routers.stats import clear_stats_cache
from strava.strava_intelligence import StravaIntelligence

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


def _finalize_sync(si: StravaIntelligence, error: str | None) -> str | None:
    """Invalidate/warm dependent caches and always release the sync slot."""
    try:
        si.strava_analytics.invalidate_caches()
        clear_stats_cache()
        clear_export_cache()
        clear_gear_cache()
        # Eagerly warm the in-memory cache so the first post-sync read doesn't
        # pay the full parquet reload cost on the user's request.
        si.strava_activities_cache._load_to_memory()
    except Exception as e:
        logger.exception("Sync cleanup failed")
        cleanup_error = f"cleanup failed: {type(e).__name__}: {e}"
        error = f"{error}; {cleanup_error}" if error else cleanup_error
    finally:
        _release_sync(error)
    return error


def _run_sync(si: StravaIntelligence, full_sync: bool, include_streams: bool):
    err: str | None = None
    try:
        si.sync_activities(full_sync=full_sync, include_streams=include_streams)
    except Exception as e:
        err = str(e)
    finally:
        _finalize_sync(si, err)


@router.post("")
def trigger_sync(
    background_tasks: BackgroundTasks,
    full_sync: bool = Query(default=False),
    include_streams: bool = Query(default=False),
    si: StravaIntelligence = Depends(get_si),
):
    if not _try_claim_sync():
        return {"status": "already_running"}
    background_tasks.add_task(_run_sync, si, full_sync, include_streams)
    return {"status": "started"}


def _run_backfill_streams(si: StravaIntelligence):
    err: str | None = None
    try:
        si.ensure_activities_with_streams()
    except Exception as e:
        err = str(e)
    finally:
        _finalize_sync(si, err)


@router.post("/backfill-streams")
def backfill_streams(
    background_tasks: BackgroundTasks,
    si: StravaIntelligence = Depends(get_si),
):
    if not _try_claim_sync():
        return {"status": "already_running"}
    background_tasks.add_task(_run_backfill_streams, si)
    return {"status": "started"}


@router.post("/activity/{activity_id}")
def resync_activity(
    activity_id: int,
    include_streams: bool = Query(default=False),
    si: StravaIntelligence = Depends(get_si),
):
    """Refresh a single activity from Strava (e.g., to pick up a renamed activity)."""
    if not _try_claim_sync():
        return {"status": "already_running"}
    err: str | None = None
    found = False
    try:
        found = si.strava_activities_cache.resync_activity(
            activity_id=activity_id,
            strava_endpoint=si.strava_endpoint,
            include_streams=include_streams,
        )
    except Exception as e:
        err = str(e)
    finally:
        err = _finalize_sync(si, err)
    if err:
        raise HTTPException(status_code=502, detail=err)
    if not found:
        raise HTTPException(status_code=404, detail="Activity not found or no detail returned")
    return {"status": "success"}


@router.get("/cache-completeness")
def cache_completeness(si: StravaIntelligence = Depends(get_si)):
    return si.strava_activities_cache.get_cache_completeness()


@router.get("/status")
def sync_status(si: StravaIntelligence = Depends(get_si)):
    cache = si.strava_activities_cache
    try:
        profile = si.strava_user_cache.get_athlete_profile()
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
    }
