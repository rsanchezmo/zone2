from fastapi import APIRouter, Depends

from backend.dependencies import get_z2
from backend.services import sync as strava_sync
from zone2.core import Zone2

router = APIRouter()


@router.get("")
def health(z2: Zone2 = Depends(get_z2)):
    """Liveness/readiness probe. Returns cache state so it's also useful for
    manual curl + Docker/Cloudflare readiness gates."""
    cache = z2.strava_activities_cache
    return {
        "status": "ok",
        "cache_loaded": cache._memory_cache is not None,
        "total_activities": cache.count_cached_activities(),
        "cache_version": cache.cache_version,
        "sync_running": strava_sync.status().running,
    }
