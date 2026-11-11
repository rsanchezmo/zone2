"""Activity lookups and their JSON shape, shared by the routers and the agent."""

import json

import numpy as np
import pandas as pd

from backend._serialize import sanitize as _sanitize
from zone2.core import Zone2
from zone2.drift import heart_rate_drift
from zone2.hr_recovery import heart_rate_recovery
from zone2.streams_store import columnar_to_points, detect_stops, grade_adjusted_speeds
from zone2.utils import SportCategory, format_pace_or_speed, get_sport_category

# Columns to serialize for JSON
_ACTIVITY_FIELDS = [
    "id", "name", "description", "sport_type", "distance", "moving_time", "elapsed_time",
    "total_elevation_gain", "start_date", "start_date_local", "timezone",
    "average_speed", "max_speed", "average_heartrate", "max_heartrate",
    "average_cadence", "elev_high", "elev_low", "start_latlng", "end_latlng",
    "kudos_count", "achievement_count", "suffer_score", "calories",
    "perceived_exertion", "total_photo_count", "device_name", "gear_id",
    "average_watts", "max_watts", "weighted_average_watts", "average_temp",
    "pr_count", "workout_type",
]


def activity_dict(row: pd.Series, include_streams: bool = False, streams: dict | None = None) -> dict:
    """Convert a pandas row to a JSON-safe dict.

    Streams (when requested) are loaded separately via the cache's StreamsStore
    and passed in as a columnar dict; this function reshapes them to the
    legacy list-of-dicts wire format the frontend consumes.
    """
    d = {}
    for col in _ACTIVITY_FIELDS:
        if col in row.index:
            d[col] = _sanitize(row[col])
        else:
            d[col] = None

    # Add formatted pace/speed
    if row.get("average_speed") and not pd.isna(row.get("average_speed")):
        d["formatted_pace"] = format_pace_or_speed(row["average_speed"], row.get("sport_type"))

    # Distance in km, meter precision — swims render this back as meters,
    # so 2 decimals would drift (3125 m → 3.12 km → 3120 m).
    if d.get("distance") is not None:
        d["distance_km"] = round(d["distance"] / 1000, 3)

    # Moving time formatted
    if d.get("moving_time") is not None:
        secs = int(d["moving_time"])
        h, remainder = divmod(secs, 3600)
        m, s = divmod(remainder, 60)
        d["moving_time_formatted"] = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    # Elapsed time formatted
    if d.get("elapsed_time") is not None:
        secs = int(d["elapsed_time"])
        h, remainder = divmod(secs, 3600)
        m, s = divmod(remainder, 60)
        d["elapsed_time_formatted"] = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    # Max speed formatted
    if row.get("max_speed") and not pd.isna(row.get("max_speed")):
        d["formatted_max_speed"] = format_pace_or_speed(row["max_speed"], row.get("sport_type"))

    # Summary polyline for list view maps
    if "map" in row.index and row["map"] is not None:
        try:
            map_data = row["map"] if isinstance(row["map"], dict) else json.loads(row["map"])
            d["summary_polyline"] = map_data.get("summary_polyline")
        except (json.JSONDecodeError, TypeError):
            d["summary_polyline"] = None

    if include_streams:
        is_run = bool(streams) and get_sport_category(row.get("sport_type")) == SportCategory.RUNNING
        gap = grade_adjusted_speeds(streams) if is_run else None
        if gap is not None:
            streams = {**streams, "grade_adjusted_speed": [None if np.isnan(v) else float(v) for v in gap]}
        d["streams"] = columnar_to_points(streams) if streams else None
        d["stops"] = detect_stops(streams) if streams else []
        d["drift"] = heart_rate_drift(streams, with_series=True) if is_run else None
        d["hr_recovery"] = heart_rate_recovery(streams) if is_run else None

        # Include detail-only fields when showing full activity
        for field in ("photos", "splits_metric", "best_efforts", "laps", "gear", "segment_efforts", "similar_activities"):
            if field in row.index and row[field] is not None:
                try:
                    val = row[field] if isinstance(row[field], (list, dict)) else json.loads(row[field])
                    d[field] = val
                except (json.JSONDecodeError, TypeError):
                    d[field] = None

    return d


def on_dates(z2: Zone2, dates: set[str]) -> list[dict]:
    """The activities whose local start falls on one of `dates` (YYYY-MM-DD), as activity dicts."""
    activities = z2.strava_activities_cache.get_prepared_view()
    if activities.empty:
        return []
    day = activities["start_date_local"].dt.strftime("%Y-%m-%d")
    subset = activities[day.isin(dates)]
    return [activity_dict(row) for _, row in subset.iterrows()]


def similar(z2: Zone2, activity_id: int, limit: int) -> pd.DataFrame | None:
    """The latest activities of the same sport within 10% of its distance and, when it climbs,
    20% of its elevation. None when there is no such activity."""
    target = z2.strava_activities_cache.get_activity_by_id(activity_id)
    if target is None:
        return None
    activities = z2.strava_activities_cache.activities_raw
    sport = target.get("sport_type")
    distance = target.get("distance")
    elevation = target.get("total_elevation_gain")
    if activities.empty or not sport or distance is None or pd.isna(distance):
        return activities.iloc[0:0]

    df = activities[(activities["sport_type"] == sport) & (activities["id"] != activity_id)]
    df = df[df["distance"].between(float(distance) * 0.9, float(distance) * 1.1)]
    if elevation is not None and not pd.isna(elevation) and float(elevation) > 0:
        df = df[df["total_elevation_gain"].fillna(0).between(float(elevation) * 0.8, float(elevation) * 1.2)]
    df = df.assign(start_date_local=pd.to_datetime(df["start_date_local"]))
    return df.sort_values("start_date_local", ascending=False).head(limit)
