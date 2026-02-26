import logging

from fastapi import APIRouter, Depends

from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/profile")
def get_athlete_profile(si: StravaIntelligence = Depends(get_si)):
    return si.strava_user_cache.get_athlete_profile()


@router.get("/rate-limits")
def get_rate_limits(si: StravaIntelligence = Depends(get_si)):
    return si.strava_endpoint.get_rate_limits()


@router.get("/zones")
def get_athlete_zones(si: StravaIntelligence = Depends(get_si)):
    """Return HR zones using smart estimation (activity data) instead of raw Strava zones."""
    zones = si.strava_analytics.get_hr_zones()
    hr_max = si.strava_analytics.get_max_heart_rate()
    # Check if user has custom Strava zones
    custom = False
    if si.strava_user_cache._zones_cache is not None:
        custom = si.strava_user_cache._zones_cache.get('heart_rate', {}).get('custom_zones', False)
    return {
        "heart_rate": {
            "zones": zones,
            "custom_zones": custom,
            "max_hr": hr_max,
        }
    }
