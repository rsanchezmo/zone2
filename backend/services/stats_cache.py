"""The stats endpoints' response cache and the weekly reports it holds, shared so the PNG
exports reuse them and anything that changes what they report (a sync, the zones, the race
calendar) can drop them, from a router or the agent."""

import json

from backend._ttl_cache import TTLCache
from zone2.core import Zone2
from zone2.utils import previous_week

# Keys are tuples (endpoint, *params, cache_version) so entries self-invalidate when the
# underlying activities dataset changes.
stats_cache = TTLCache(maxsize=256, ttl_seconds=900)


def clear_stats_cache() -> None:
    """Drop cached reports now (TTL and cache_version also handle this lazily; this just
    reclaims memory sooner, and covers changes the activities version doesn't see)."""
    stats_cache.clear()


def zones_signature(hr_zones: list | None) -> str:
    """Stable fingerprint for the zones so the stats cache differentiates by source."""
    if not hr_zones:
        return "none"
    return json.dumps(hr_zones, sort_keys=True, separators=(",", ":"))


def get_weekly_report_cached(
    z2: Zone2,
    week_start: str | None,
    cutoff_date: str | None = None,
    hr_zones: list | None = None,
) -> dict:
    key = ("weekly", week_start, cutoff_date, z2.strava_activities_cache.cache_version, zones_signature(hr_zones))
    cached = stats_cache.get(key)
    if cached is not None:
        return cached
    result = z2.strava_analytics.get_weekly_report(week_start, cutoff_date=cutoff_date, hr_zones=hr_zones)
    stats_cache.set(key, result)
    return result


def get_previous_weekly_report_cached(z2: Zone2, report: dict, hr_zones: list | None) -> dict | None:
    """The week before `report`'s, for deltas."""
    if not report.get("week_start"):
        return None
    prev_monday, cutoff = previous_week(report["week_start"])
    return get_weekly_report_cached(z2, prev_monday, cutoff_date=cutoff, hr_zones=hr_zones)
