"""How planned sessions went: which activity fulfilled each, and its execution score.
Shared by the calendar router, the coach's plans and the agent."""

import asyncio
import json
import logging

import aiosqlite
import pandas as pd

from backend._serialize import sanitize as _sanitize
from backend.scoring import compute_execution_score, has_targets, match_activity
from backend.services.stats_cache import stats_cache, zones_signature
from backend.services.zones import resolve_hr_zones
from zone2.core import Zone2

logger = logging.getLogger(__name__)

_SCORING_COLUMNS = ("id", "sport_type", "distance", "moving_time", "elapsed_time", "average_speed",
                    "start_date_local", "average_heartrate")


def _activity_row_to_dict(row: pd.Series | dict) -> dict:
    """Minimal activity dict for scoring. Streams are fetched separately
    via the cache's StreamsStore — not attached to this dict."""
    d = {}
    for col in _SCORING_COLUMNS:
        if col in row:
            d[col] = _sanitize(row[col])
    if d.get("distance") is not None:
        d["distance_km"] = round(d["distance"] / 1000, 3)
    return d


def activities_by_day(z2: Zone2, date_from: str, date_to: str) -> dict[str, list[dict]]:
    """Bucket cached activities within [date_from, date_to] (inclusive) by local day."""
    cache = z2.strava_activities_cache
    activities_df = cache.get_prepared_view()
    if activities_df.empty:
        return {}
    activities_df = activities_df[cache.days_mask(date_from, date_to)]

    activity_map: dict[str, list[dict]] = {}
    records = activities_df[[c for c in _SCORING_COLUMNS if c in activities_df.columns]].to_dict("records")
    for date_str, record in zip(activities_df["start_date_local"].dt.strftime("%Y-%m-%d"), records):
        activity_map.setdefault(date_str, []).append(_activity_row_to_dict(record))
    return activity_map


def session_matches(sessions: list[dict], activity_map: dict[str, list[dict]]) -> list[tuple[dict, dict]]:
    """(session, activity) for each session an activity on its day matches."""
    pairs = []
    for session in sessions:
        matched = match_activity(session, activity_map.get(session["date"], []))
        if matched is not None:
            pairs.append((session, matched))
    return pairs


def _score_key(z2: Zone2, session: dict, activity_id: int | None, zones: str) -> tuple:
    """What a score is computed from: the session as planned, the activity and whether its streams
    are stored (a backfill adds them without a new activities version), and the zones."""
    cache = z2.strava_activities_cache
    has_streams = activity_id is not None and cache.streams.has(activity_id)
    return ("session_score", json.dumps(session, sort_keys=True, default=str), activity_id, has_streams,
            cache.cache_version, zones)


def score_sessions(z2: Zone2, sessions: list[dict], date_from: str, date_to: str,
                    hr_zones: list | None) -> dict[int, dict | None]:
    """Execution score per session, None when no activity matches it. Scores are cached, so only
    the sessions scored for the first time load their activity's streams."""
    pairs = session_matches(sessions, activities_by_day(z2, date_from, date_to))
    zones = zones_signature(hr_zones)

    result: dict[int, dict | None] = {s["id"]: None for s in sessions}
    missing: list[tuple[dict, dict, int | None, tuple]] = []
    for session, matched in pairs:
        activity_id = int(matched["id"]) if matched.get("id") is not None else None
        key = _score_key(z2, session, activity_id, zones)
        cached = stats_cache.get(key)
        if cached is None:
            missing.append((session, matched, activity_id, key))
        else:
            result[session["id"]] = cached

    matched_ids = [activity_id for _, _, activity_id, _ in missing if activity_id is not None]
    streams_map = z2.strava_activities_cache.get_streams_bulk(matched_ids) if matched_ids else {}
    for session, matched, activity_id, key in missing:
        score = compute_execution_score(session, matched, hr_zones, streams_map.get(activity_id))
        stats_cache.set(key, score)
        result[session["id"]] = score
    return result


async def scores(z2: Zone2, db: aiosqlite.Connection, sessions: list[dict], date_from: str,
                 date_to: str) -> dict[int, dict | None]:
    """Execution score per session that has targets, in your HR zones when they resolve."""
    scorable = [s for s in sessions if has_targets(s)]
    if not scorable:
        return {}
    hr_zones = None
    try:
        hr_zones = (await resolve_hr_zones(z2, db))["zones"]
    except Exception as e:
        logger.debug("Could not load HR zones for scoring: %s", e)
    return await asyncio.to_thread(score_sessions, z2, scorable, date_from, date_to, hr_zones)


def accomplished(session: dict, day_activities: list[dict]) -> bool:
    """A session counts as done when an activity of its sport is on its day, or it was
    marked completed; a rest day, when nothing is."""
    if session["sport_type"].lower() == "rest":
        return not day_activities
    return bool(session["completed"]) or match_activity(session, day_activities) is not None
