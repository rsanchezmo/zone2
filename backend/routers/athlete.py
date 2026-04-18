import json
import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.db import get_db
from backend.dependencies import get_si
from backend.routers.stats import clear_stats_cache
from backend.services.zones import (
    DEFAULT_SOURCE,
    Source,
    get_setting,
    resolve_hr_zones,
    set_setting,
)
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
async def get_athlete_zones(
    si: StravaIntelligence = Depends(get_si),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return HR zones using the user-selected source (strava / estimated / manual)."""
    resolved = await resolve_hr_zones(si, db)
    return {
        "heart_rate": {
            "zones": resolved["zones"],
            "max_hr": resolved["max_hr"],
            "source": resolved["source"],
            "requested_source": resolved["requested_source"],
            "fallback_reason": resolved["fallback_reason"],
        }
    }


class ZoneBound(BaseModel):
    min: int = Field(ge=0, le=250)
    max: int = Field(ge=0, le=250)


class ZonesSettings(BaseModel):
    source: Source
    manual_zones: list[ZoneBound] | None = None


@router.get("/zones-settings")
async def get_zones_settings(db: aiosqlite.Connection = Depends(get_db)):
    source = (await get_setting(db, "hr_zones_source")) or DEFAULT_SOURCE
    raw = await get_setting(db, "manual_hr_zones")
    manual = None
    if raw:
        try:
            manual = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            manual = None
    return {"source": source, "manual_zones": manual}


@router.put("/zones-settings")
async def update_zones_settings(
    payload: ZonesSettings,
    db: aiosqlite.Connection = Depends(get_db),
    si: StravaIntelligence = Depends(get_si),
):
    # Validate + persist manual zones only when provided. Switching the source
    # on its own is always allowed; the resolver will fall back to estimated
    # if the user picks "manual" before saving any thresholds.
    if payload.manual_zones is not None:
        if len(payload.manual_zones) != 5:
            raise HTTPException(
                status_code=400,
                detail="Manual zones must be a list of exactly 5 {min, max} entries",
            )
        for i, z in enumerate(payload.manual_zones):
            if z.max <= z.min:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zone {i + 1}: max ({z.max}) must be greater than min ({z.min})",
                )
        for i in range(1, len(payload.manual_zones)):
            prev = payload.manual_zones[i - 1]
            cur = payload.manual_zones[i]
            if cur.min != prev.max:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zone {i + 1} min ({cur.min}) must equal zone {i} max ({prev.max})",
                )
        await set_setting(
            db,
            "manual_hr_zones",
            json.dumps([z.model_dump() for z in payload.manual_zones]),
        )
    await set_setting(db, "hr_zones_source", payload.source)

    # Drop caches so downstream analytics rebuild against the new source.
    si.strava_analytics._hr_zones_cache = None
    si.strava_analytics._training_load_cache = None
    clear_stats_cache()

    return {"source": payload.source}
