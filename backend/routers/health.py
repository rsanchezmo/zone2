from fastapi import APIRouter, Depends

from backend.dependencies import get_si
from backend.routers.sync import _sync_status, _sync_lock
from strava.strava_intelligence import StravaIntelligence

router = APIRouter()


@router.get("")
def health(si: StravaIntelligence = Depends(get_si)):
    """Liveness/readiness probe. Returns cache state so it's also useful for
    manual curl + Docker/Cloudflare readiness gates."""
    cache = si.strava_activities_cache
    with _sync_lock:
        sync_running = _sync_status["running"]
    return {
        "status": "ok",
        "cache_loaded": cache._memory_cache is not None,
        "total_activities": cache.count_cached_activities(),
        "cache_version": cache.cache_version,
        "sync_running": sync_running,
    }
