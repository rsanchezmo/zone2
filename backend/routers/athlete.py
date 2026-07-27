import json
import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.db import get_db
from backend.dependencies import get_z2
from backend.routers.exports import clear_export_cache
from backend.routers.stats import clear_stats_cache
from backend.services.zones import (
    DEFAULT_SOURCE,
    Source,
    get_setting,
    resolve_hr_zones,
    set_setting,
)
from backend.services.gear import resolve_gear_catalog
from backend.services.resting_hr import (
    DEFAULT_SOURCE as RHR_DEFAULT_SOURCE,
    Source as RestingHrSource,
    resolve_resting_hr,
)
from zone2.core import Zone2

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/profile")
def get_athlete_profile(z2: Zone2 = Depends(get_z2)):
    profile = dict(z2.strava_user_cache.get_athlete_profile())

    catalog = resolve_gear_catalog(z2).values()
    profile["shoes"] = [g for g in catalog if g["kind"] == "shoes"]
    profile["bikes"] = [g for g in catalog if g["kind"] == "bikes"]

    return profile


@router.get("/rate-limits")
def get_rate_limits(refresh: bool = False, z2: Zone2 = Depends(get_z2)):
    return z2.strava_endpoint.get_rate_limits(refresh=refresh)


@router.get("/zones")
async def get_athlete_zones(
    z2: Zone2 = Depends(get_z2),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return HR zones using the user-selected source (strava / estimated / manual)."""
    resolved = await resolve_hr_zones(z2, db)
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
    z2: Zone2 = Depends(get_z2),
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
    z2.strava_analytics._hr_zones_cache = None
    z2.strava_analytics._training_load_cache = {}
    clear_stats_cache()
    clear_export_cache()

    return {"source": payload.source}


@router.get("/resting-hr")
async def get_resting_hr(
    z2: Zone2 = Depends(get_z2),
    db: aiosqlite.Connection = Depends(get_db),
):
    """Return the resting HR using the user-selected source (garmin / manual / estimated)."""
    resolved = await resolve_resting_hr(z2, db)
    return {
        "value": resolved["value"],
        "source": resolved["source"],
        "requested_source": resolved["requested_source"],
        "fallback_reason": resolved["fallback_reason"],
    }


class RestingHrSettings(BaseModel):
    source: RestingHrSource
    manual_resting_hr: float | None = Field(default=None, ge=25, le=120)


@router.get("/resting-hr-settings")
async def get_resting_hr_settings(db: aiosqlite.Connection = Depends(get_db)):
    source = (await get_setting(db, "resting_hr_source")) or RHR_DEFAULT_SOURCE
    raw = await get_setting(db, "manual_resting_hr")
    manual = None
    if raw:
        try:
            manual = float(raw)
        except (TypeError, ValueError):
            manual = None
    return {"source": source, "manual_resting_hr": manual}


@router.put("/resting-hr-settings")
async def update_resting_hr_settings(
    payload: RestingHrSettings,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    if payload.manual_resting_hr is not None:
        await set_setting(db, "manual_resting_hr", str(payload.manual_resting_hr))
    await set_setting(db, "resting_hr_source", payload.source)

    # Resting HR feeds daily TRIMP → PMC / fitness trend / relative effort.
    z2.strava_analytics._training_load_cache = {}
    z2.strava_analytics._pmc_cache = {}
    z2.strava_analytics._fitness_trend_cache = {}
    clear_stats_cache()
    clear_export_cache()

    return {"source": payload.source}
