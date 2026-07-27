import logging
from typing import Literal, TypedDict

import aiosqlite

from backend.services.zones import get_setting, set_setting  # noqa: F401  (re-exported for routers)
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
    """Zone-proxy resting HR (half of the Z2 lower bound), no API call. Mirrors
    the non-Garmin fallback in StravaAnalytics.get_rest_heart_rate."""
    try:
        zones = z2.strava_analytics.get_hr_zones()
        val = zones[1]["min"] / 2 if zones and len(zones) > 1 else 0
    except Exception as e:
        logger.warning("Estimated resting HR from zones failed: %s", e)
        val = 0
    return float(val) if val and val > 0 else _FALLBACK_RHR


async def resolve_resting_hr(z2: Zone2, db: aiosqlite.Connection) -> ResolvedRestingHr:
    """Return resting HR according to the user's selected source, with fallback.

    Sources:
      - "garmin": most recent measured Garmin resting HR. Falls back to estimated
        when no Garmin data is cached.
      - "manual": value saved in `user_settings`. Falls back to estimated if unset.
      - "estimated": zone-proxy from activity-derived HR zones (no API call).
    """
    requested = (await get_setting(db, "resting_hr_source")) or DEFAULT_SOURCE
    if requested not in ("garmin", "manual", "estimated"):
        requested = DEFAULT_SOURCE
    requested_source: Source = requested  # type: ignore[assignment]

    if requested_source == "garmin":
        measured = z2.strava_analytics._garmin_resting_hr()
        if measured is not None:
            return ResolvedRestingHr(value=float(measured), source="garmin",
                                     requested_source=requested_source, fallback_reason=None)
        return ResolvedRestingHr(value=_estimated_resting_hr(z2), source="estimated",
                                 requested_source=requested_source,
                                 fallback_reason="No Garmin resting HR cached")

    if requested_source == "manual":
        raw = await get_setting(db, "manual_resting_hr")
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
