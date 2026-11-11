"""The stats endpoints' response cache and the weekly reports it holds, shared so the PNG
exports reuse them and anything that changes what they report (a sync, the zones, the race
calendar) can drop them, from a router or the agent."""

import json
from datetime import date, datetime, timezone

from backend._ttl_cache import TTLCache
from zone2.core import Zone2
from zone2.utils import SportCategory, previous_week

# Keys hold everything their value is computed from: (endpoint, *params, cache_version), and
# today_key() for results that count up to today. So entries never expire; the one set longest ago
# goes once the cache is full.
stats_cache = TTLCache(maxsize=512, ttl_seconds=None)


def today_key() -> tuple[date, date]:
    """Today, local and UTC: the analytics count up to either (the current week and the race
    predictions' recency go by UTC), so a key with both rolls over with each."""
    return date.today(), datetime.now(timezone.utc).date()


def clear_stats_cache() -> None:
    """Drop cached reports now, for changes their keys don't see (the zones, resting HR and race
    calendar behind the analytics), and to reclaim the memory of superseded versions."""
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
    # Without a week_start the report is the current week's
    key = ("weekly", week_start, cutoff_date, today_key() if week_start is None else None,
           z2.strava_activities_cache.cache_version, zones_signature(hr_zones))
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


def get_race_predictions_history_cached(z2: Zone2, sport: SportCategory, weeks: int, step_days: int) -> list[dict]:
    """The race predictions' history (see StravaAnalytics.get_race_predictions_history), whose
    last step is today."""
    key = ("race_predictions_history", sport, weeks, step_days, z2.strava_activities_cache.cache_version, today_key())
    cached = stats_cache.get(key)
    if cached is not None:
        return cached
    result = z2.strava_analytics.get_race_predictions_history(sport, weeks=weeks, step_days=step_days)
    stats_cache.set(key, result)
    return result
