import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Literal, TypedDict

import aiosqlite

from backend.db import connect_db
from zone2.core import Zone2

logger = logging.getLogger(__name__)

Source = Literal["strava", "estimated", "manual", "garmin"]
DEFAULT_SOURCE: Source = "estimated"

# Garmin's zones as last fetched, so resolving them never waits on Garmin
GARMIN_ZONES_KEY = "garmin_hr_zones"


class ResolvedZones(TypedDict):
    zones: list[dict]          # [{min, max}] * 5
    max_hr: int | None
    source: Source             # the source actually used
    requested_source: Source   # what the user asked for (may differ from `source` on fallback)
    fallback_reason: str | None
    threshold_hr: int | None   # lactate threshold the zones are built on (Garmin only)


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


def _resolved(zones: list[dict], source: Source, requested: Source, estimated_max_hr: int | None,
              fallback_reason: str | None = None, threshold_hr: int | None = None) -> ResolvedZones:
    return ResolvedZones(
        zones=zones,
        max_hr=_max_hr_from_zones(zones, estimated_max_hr),
        source=source,
        requested_source=requested,
        fallback_reason=fallback_reason,
        threshold_hr=threshold_hr,
    )


def zones_from_garmin(payload: list[dict]) -> tuple[list[dict], int | None] | None:
    """Garmin's running zones (its default ones when running has none) as five
    {min, max} bands, and the lactate threshold HR when they're built on it.
    Zone 1 starts at 0 like the other sources: below its floor still counts as Z1."""
    by_sport = {z.get("sport"): z for z in payload if isinstance(z, dict)} if isinstance(payload, list) else {}
    garmin = by_sport.get("RUNNING") or by_sport.get("DEFAULT")
    if garmin is None:
        return None
    bounds = [0, *(garmin.get(f"zone{i}Floor") for i in range(2, 6)), garmin.get("maxHeartRateUsed")]
    if not all(isinstance(b, (int, float)) for b in bounds) or any(b >= a for b, a in zip(bounds, bounds[1:])):
        return None
    zones = [{"min": int(bounds[i]), "max": int(bounds[i + 1])} for i in range(5)]
    threshold = garmin.get("lactateThresholdHeartRateUsed") if garmin.get("trainingMethod") == "LACTATE_THRESHOLD" else None
    return zones, int(threshold) if isinstance(threshold, (int, float)) else None


async def refresh_garmin_zones(z2: Zone2) -> bool:
    """Fetch Garmin's zones and store them; True when they changed. Garmin
    updates them itself as the watch detects a new lactate threshold."""
    if not z2.garmin_client.email:
        return False
    try:
        parsed = zones_from_garmin(await asyncio.to_thread(z2.garmin_client.hr_zones))
    except Exception as e:
        logger.warning("Fetching Garmin HR zones failed: %s: %s", type(e).__name__, e)
        return False
    if parsed is None:
        logger.warning("Garmin returned no usable HR zones")
        return False
    zones, threshold_hr = parsed
    async with connect_db() as db:
        raw = await get_setting(db, GARMIN_ZONES_KEY)
        before = json.loads(raw) if raw else {}
        await set_setting(db, GARMIN_ZONES_KEY, json.dumps({
            "zones": zones,
            "threshold_hr": threshold_hr,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }))
    return (before.get("zones"), before.get("threshold_hr")) != (zones, threshold_hr)


async def resolve_hr_zones(z2: Zone2, db: aiosqlite.Connection) -> ResolvedZones:
    """Return HR zones according to the user's selected source, with fallback.

    Sources:
      - "strava": use Strava's custom zones. Falls back to estimated if user hasn't
        configured custom zones on Strava.
      - "estimated": infer zones from activity data (current default behaviour).
      - "manual": use zones saved in `user_settings`. Falls back to estimated if
        none have been saved yet.
      - "garmin": the zones Garmin Connect (and so the watch) uses, as last
        fetched. Falls back to estimated until they've been fetched once.
    """
    requested = (await get_setting(db, "hr_zones_source")) or DEFAULT_SOURCE
    if requested not in ("strava", "estimated", "manual", "garmin"):
        requested = DEFAULT_SOURCE
    requested_source: Source = requested  # type: ignore[assignment]

    estimated_max_hr = z2.strava_analytics.get_max_heart_rate()

    def estimated(reason: str | None = None) -> ResolvedZones:
        return _resolved(z2.strava_analytics.get_hr_zones(), "estimated", requested_source, estimated_max_hr, reason)

    if requested_source == "garmin":
        raw = await get_setting(db, GARMIN_ZONES_KEY)
        if raw:
            stored = json.loads(raw)
            return _resolved(stored["zones"], "garmin", requested_source, estimated_max_hr,
                             threshold_hr=stored.get("threshold_hr"))
        return estimated("Garmin isn't connected" if not z2.garmin_client.email else "No zones fetched from Garmin yet")

    if requested_source == "manual":
        raw = await get_setting(db, "manual_hr_zones")
        if raw:
            try:
                manual_zones = json.loads(raw)
                if isinstance(manual_zones, list) and len(manual_zones) == 5:
                    return _resolved(manual_zones, "manual", requested_source, estimated_max_hr)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Invalid manual_hr_zones JSON in settings: %s", e)
        return estimated("No manual zones saved yet")

    if requested_source == "strava":
        try:
            # Refetches from Strava once the cached zones are a day old; off the
            # event loop so that request can't stall every other one.
            strava = await asyncio.to_thread(z2.strava_user_cache.get_athlete_zones)
            hr = strava.get("heart_rate", {}) if isinstance(strava, dict) else {}
            if hr.get("custom_zones") and isinstance(hr.get("zones"), list):
                # Strava's zone 5 may have max=null; normalise to estimated max_hr.
                normalised = []
                for i, z in enumerate(hr["zones"]):
                    zmax = z.get("max")
                    if zmax in (None, -1) and i == len(hr["zones"]) - 1:
                        zmax = estimated_max_hr or 0
                    normalised.append({"min": z.get("min", 0), "max": zmax or 0})
                return _resolved(normalised, "strava", requested_source, estimated_max_hr)
        except Exception as e:
            logger.warning("Failed to fetch Strava zones: %s", e)
        return estimated("No custom zones set on Strava")

    return estimated()
