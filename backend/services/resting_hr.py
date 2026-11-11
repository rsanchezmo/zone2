import logging
from typing import Literal, TypedDict

import aiosqlite

from backend.services.zones import get_setting, set_setting  # noqa: F401  (re-exported for routers)
from backend.services.zones import cached_resolution, get_settings, strava_zones_signature
from zone2.core import Zone2

logger = logging.getLogger(__name__)

Source = Literal["garmin", "manual", "estimated"]
DEFAULT_SOURCE: Source = "garmin"
_FALLBACK_RHR = 60.0


class ResolvedRestingHr(TypedDict):
    value: float
    source: Source             # the source actually used
    requested_source: Source   # what the user asked for (may differ on fallback)
    fallback_reason: str | None


def _estimated_resting_hr(z2: Zone2) -> float:
    """Zone-proxy resting HR (half of the Z2 lower bound), no API call."""
    try:
        zones = z2.strava_analytics.get_hr_zones()
        val = zones[1]["min"] / 2 if zones and len(zones) > 1 else 0
    except Exception as e:
        logger.warning("Estimated resting HR from zones failed: %s", e)
        val = 0
    return float(val) if val and val > 0 else _FALLBACK_RHR


RESTING_HR_SETTINGS = ("resting_hr_source", "manual_resting_hr")


def _requested(settings: dict[str, str | None]) -> Source:
    requested = settings["resting_hr_source"] or DEFAULT_SOURCE
    return requested if requested in ("garmin", "manual", "estimated") else DEFAULT_SOURCE  # type: ignore[return-value]


async def _garmin_resting_hr_stamp(db: aiosqlite.Connection) -> tuple[str, str] | None:
    """When Garmin's latest daily heart rates, the measured resting HR's source, were fetched."""
    row = await (await db.execute(
        "SELECT date, fetched_at FROM garmin_daily_stats WHERE metric = 'heart_rates' ORDER BY date DESC LIMIT 1",
    )).fetchone()
    return (row[0], row[1]) if row else None


async def resolve_resting_hr(z2: Zone2, db: aiosqlite.Connection) -> ResolvedRestingHr:
    """Return resting HR according to the user's selected source, with fallback.

    Sources:
      - "garmin": most recent measured Garmin resting HR. Falls back to estimated
        when no Garmin data is cached.
      - "manual": value saved in `user_settings`. Falls back to estimated if unset.
      - "estimated": zone-proxy from activity-derived HR zones (no API call).

    Cached by the settings it reads, Garmin's latest heart rates, the activities and the
    Strava zones fetched so far.
    """
    settings = await get_settings(db, RESTING_HR_SETTINGS)
    garmin = await _garmin_resting_hr_stamp(db) if _requested(settings) == "garmin" else None
    key = ("resting_hr", tuple(settings.items()), garmin, z2.strava_activities_cache.cache_version,
           strava_zones_signature(z2))
    return await cached_resolution(key, lambda: _resolve_resting_hr(z2, settings))


def _resolve_resting_hr(z2: Zone2, settings: dict[str, str | None]) -> ResolvedRestingHr:
    """resolve_resting_hr's work: blocking, since it reads Garmin's payloads and the activities."""
    requested_source = _requested(settings)

    if requested_source == "garmin":
        measured = z2.strava_analytics._garmin_resting_hr()
        if measured is not None:
            return ResolvedRestingHr(value=float(measured), source="garmin",
                                     requested_source=requested_source, fallback_reason=None)
        return ResolvedRestingHr(value=_estimated_resting_hr(z2), source="estimated",
                                 requested_source=requested_source,
                                 fallback_reason="No Garmin resting HR cached")

    if requested_source == "manual":
        raw = settings["manual_resting_hr"]
        if raw:
            try:
                val = float(raw)
                if 25 <= val <= 120:
                    return ResolvedRestingHr(value=val, source="manual",
                                             requested_source=requested_source, fallback_reason=None)
            except (TypeError, ValueError):
                logger.warning("Invalid manual_resting_hr in settings: %r", raw)
        return ResolvedRestingHr(value=_estimated_resting_hr(z2), source="estimated",
                                 requested_source=requested_source,
                                 fallback_reason="No manual resting HR saved yet")

    return ResolvedRestingHr(value=_estimated_resting_hr(z2), source="estimated",
                             requested_source=requested_source, fallback_reason=None)
