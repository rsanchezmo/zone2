import json
import logging
from typing import Literal, TypedDict

import aiosqlite

from zone2.core import Zone2

logger = logging.getLogger(__name__)

Source = Literal["strava", "estimated", "manual"]
DEFAULT_SOURCE: Source = "estimated"


class ResolvedZones(TypedDict):
    zones: list[dict]          # [{min, max}] * 5
    max_hr: int | None
    source: Source             # the source actually used
    requested_source: Source   # what the user asked for (may differ from `source` on fallback)
    fallback_reason: str | None


async def get_setting(db: aiosqlite.Connection, key: str) -> str | None:
    cursor = await db.execute("SELECT value FROM user_settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def set_setting(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        (key, value),
    )
    await db.commit()


def _max_hr_from_zones(zones: list[dict], fallback: int | None) -> int | None:
    """Z5 max is the top of the zone ladder, i.e. the effective max HR for
    display. Falls back to the estimator when zones look malformed."""
    if zones and len(zones) >= 5:
        z5_max = zones[4].get("max")
        if isinstance(z5_max, (int, float)) and z5_max > 0:
            return int(z5_max)
    return fallback


async def resolve_hr_zones(z2: Zone2, db: aiosqlite.Connection) -> ResolvedZones:
    """Return HR zones according to the user's selected source, with fallback.

    Sources:
      - "strava": use Strava's custom zones. Falls back to estimated if user hasn't
        configured custom zones on Strava.
      - "estimated": infer zones from activity data (current default behaviour).
      - "manual": use zones saved in `user_settings`. Falls back to estimated if
        none have been saved yet.
    """
    requested = (await get_setting(db, "hr_zones_source")) or DEFAULT_SOURCE
    if requested not in ("strava", "estimated", "manual"):
        requested = DEFAULT_SOURCE
    requested_source: Source = requested  # type: ignore[assignment]

    estimated_max_hr = z2.strava_analytics.get_max_heart_rate()

    if requested_source == "manual":
        raw = await get_setting(db, "manual_hr_zones")
        if raw:
            try:
                manual_zones = json.loads(raw)
                if isinstance(manual_zones, list) and len(manual_zones) == 5:
                    return ResolvedZones(
                        zones=manual_zones,
                        max_hr=_max_hr_from_zones(manual_zones, estimated_max_hr),
                        source="manual",
                        requested_source=requested_source,
                        fallback_reason=None,
                    )
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Invalid manual_hr_zones JSON in settings: %s", e)
        estimated_zones = z2.strava_analytics.get_hr_zones()
        return ResolvedZones(
            zones=estimated_zones,
            max_hr=_max_hr_from_zones(estimated_zones, estimated_max_hr),
            source="estimated",
            requested_source=requested_source,
            fallback_reason="No manual zones saved yet",
        )

    if requested_source == "strava":
        try:
            strava = z2.strava_user_cache.get_athlete_zones()
            hr = strava.get("heart_rate", {}) if isinstance(strava, dict) else {}
            if hr.get("custom_zones") and isinstance(hr.get("zones"), list):
                # Strava's zone 5 may have max=null; normalise to estimated max_hr.
                normalised = []
                for i, z in enumerate(hr["zones"]):
                    zmax = z.get("max")
                    if zmax in (None, -1) and i == len(hr["zones"]) - 1:
                        zmax = estimated_max_hr or 0
                    normalised.append({"min": z.get("min", 0), "max": zmax or 0})
                return ResolvedZones(
                    zones=normalised,
                    max_hr=_max_hr_from_zones(normalised, estimated_max_hr),
                    source="strava",
                    requested_source=requested_source,
                    fallback_reason=None,
                )
        except Exception as e:
            logger.warning("Failed to fetch Strava zones: %s", e)
        estimated_zones = z2.strava_analytics.get_hr_zones()
        return ResolvedZones(
            zones=estimated_zones,
            max_hr=_max_hr_from_zones(estimated_zones, estimated_max_hr),
            source="estimated",
            requested_source=requested_source,
            fallback_reason="No custom zones set on Strava",
        )

    # default: estimated
    estimated_zones = z2.strava_analytics.get_hr_zones()
    return ResolvedZones(
        zones=estimated_zones,
        max_hr=_max_hr_from_zones(estimated_zones, estimated_max_hr),
        source="estimated",
        requested_source=requested_source,
        fallback_reason=None,
    )
