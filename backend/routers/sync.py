from fastapi import APIRouter, Depends, BackgroundTasks, Query

from backend.dependencies import get_si
from backend.routers.stats import clear_stats_cache
from strava.strava_intelligence import StravaIntelligence

router = APIRouter()

_sync_status = {"running": False, "last_error": None}


def _run_sync(si: StravaIntelligence, full_sync: bool, include_streams: bool):
    global _sync_status
    _sync_status["running"] = True
    _sync_status["last_error"] = None
    try:
        si.sync_activities(full_sync=full_sync, include_streams=include_streams)
    except Exception as e:
        _sync_status["last_error"] = str(e)
    finally:
        _sync_status["running"] = False
        si.strava_analytics.invalidate_caches()
        clear_stats_cache()


@router.post("")
def trigger_sync(
    background_tasks: BackgroundTasks,
    full_sync: bool = Query(default=False),
    include_streams: bool = Query(default=False),
    si: StravaIntelligence = Depends(get_si),
):
    if _sync_status["running"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_sync, si, full_sync, include_streams)
    return {"status": "started"}


def _run_backfill_streams(si: StravaIntelligence):
    global _sync_status
    _sync_status["running"] = True
    _sync_status["last_error"] = None
    try:
        si.ensure_activities_with_streams()
    except Exception as e:
        _sync_status["last_error"] = str(e)
    finally:
        _sync_status["running"] = False
        si.strava_analytics.invalidate_caches()
        clear_stats_cache()


@router.post("/backfill-streams")
def backfill_streams(
    background_tasks: BackgroundTasks,
    si: StravaIntelligence = Depends(get_si),
):
    if _sync_status["running"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_backfill_streams, si)
    return {"status": "started"}


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
    return {
        "syncing": _sync_status["running"],
        "last_error": _sync_status["last_error"],
        "total_activities": cache.count_cached_activities(),
        "needs_sync": cache.needs_sync(),
        "last_activity_date": str(cache.get_last_activity_date()) if cache.get_last_activity_date() else None,
        "earliest_activity_date": str(cache.get_earliest_activity_date()) if cache.get_earliest_activity_date() else None,
        "athlete_name": athlete_name,
    }
