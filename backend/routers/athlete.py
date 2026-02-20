import logging

from fastapi import APIRouter, Depends

from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/profile")
def get_athlete_profile(si: StravaIntelligence = Depends(get_si)):
    return si.strava_user_cache.get_athlete_profile()


@router.get("/zones")
def get_athlete_zones(si: StravaIntelligence = Depends(get_si)):
    return si.strava_user_cache.get_athlete_zones()
