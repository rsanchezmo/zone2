import json
from fastapi import APIRouter, Depends, HTTPException, Query
import pandas as pd
import numpy as np

from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence
from strava.strava_utils import format_pace_or_speed


def _sanitize(val):
    """Convert numpy/pandas types to native Python types for JSON serialization."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val

router = APIRouter()

# Columns to exclude from list view (heavy data)
_EXCLUDE_FROM_LIST = {"streams", "map"}

# Columns to serialize for JSON
_ACTIVITY_FIELDS = [
    "id", "name", "sport_type", "distance", "moving_time", "elapsed_time",
    "total_elevation_gain", "start_date", "start_date_local", "timezone",
    "average_speed", "max_speed", "average_heartrate", "max_heartrate",
    "average_cadence", "elev_high", "elev_low", "start_latlng", "end_latlng",
    "kudos_count", "achievement_count", "suffer_score",
]


def _activity_to_dict(row: pd.Series, include_streams: bool = False) -> dict:
    """Convert a pandas row to a JSON-safe dict."""
    d = {}
    for col in _ACTIVITY_FIELDS:
        if col in row.index:
            d[col] = _sanitize(row[col])
        else:
            d[col] = None

    # Add formatted pace/speed
    if row.get("average_speed") and not pd.isna(row.get("average_speed")):
        d["formatted_pace"] = format_pace_or_speed(row["average_speed"], row.get("sport_type"))

    # Distance in km
    if d.get("distance") is not None:
        d["distance_km"] = round(d["distance"] / 1000, 2)

    # Moving time formatted
    if d.get("moving_time") is not None:
        secs = int(d["moving_time"])
        h, remainder = divmod(secs, 3600)
        m, s = divmod(remainder, 60)
        d["moving_time_formatted"] = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    # Summary polyline for list view maps
    if "map" in row.index and row["map"] is not None:
        try:
            map_data = row["map"] if isinstance(row["map"], dict) else json.loads(row["map"])
            d["summary_polyline"] = map_data.get("summary_polyline")
        except (json.JSONDecodeError, TypeError):
            d["summary_polyline"] = None

    if include_streams and "streams" in row.index and row["streams"] is not None:
        try:
            streams = row["streams"] if isinstance(row["streams"], (list, dict)) else json.loads(row["streams"])
            d["streams"] = streams
        except (json.JSONDecodeError, TypeError):
            d["streams"] = None

    return d


@router.get("")
def list_activities(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sport_type: str | None = None,
    year: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    activities = si.strava_activities_cache.activities.copy()
    if activities.empty:
        return {"items": [], "total": 0, "page": page, "per_page": per_page}

    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])

    if sport_type:
        activities = activities[activities["sport_type"] == sport_type]
    if year:
        activities = activities[activities["start_date_local"].dt.year == year]
    if date_from:
        dt_from = pd.to_datetime(date_from)
        if activities["start_date_local"].dt.tz is not None:
            dt_from = dt_from.tz_localize(activities["start_date_local"].dt.tz)
        activities = activities[activities["start_date_local"] >= dt_from]
    if date_to:
        dt_to = pd.to_datetime(date_to) + pd.Timedelta(days=1)  # inclusive
        if activities["start_date_local"].dt.tz is not None:
            dt_to = dt_to.tz_localize(activities["start_date_local"].dt.tz)
        activities = activities[activities["start_date_local"] < dt_to]

    # Sort newest first
    activities = activities.sort_values("start_date_local", ascending=False)
    total = len(activities)

    start = (page - 1) * per_page
    end = start + per_page
    page_df = activities.iloc[start:end]

    items = [_activity_to_dict(row) for _, row in page_df.iterrows()]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/sport-types")
def get_sport_types(si: StravaIntelligence = Depends(get_si)):
    activities = si.strava_activities_cache.activities
    if activities.empty:
        return []
    return sorted(activities["sport_type"].unique().tolist())


@router.get("/years")
def get_years(si: StravaIntelligence = Depends(get_si)):
    activities = si.strava_activities_cache.activities
    if activities.empty:
        return []
    dates = pd.to_datetime(activities["start_date_local"])
    return sorted(dates.dt.year.unique().tolist(), reverse=True)


@router.get("/polylines")
def get_polylines(
    sport_type: str | None = None,
    year: int | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    """Return lightweight polyline data for all activities (for world map view)."""
    activities = si.strava_activities_cache.activities.copy()
    if activities.empty:
        return []

    activities["start_date_local"] = pd.to_datetime(activities["start_date_local"])

    if sport_type:
        activities = activities[activities["sport_type"] == sport_type]
    if year:
        activities = activities[activities["start_date_local"].dt.year == year]

    results = []
    for _, row in activities.iterrows():
        polyline_str = None
        if "map" in row.index and row["map"] is not None:
            try:
                map_data = row["map"] if isinstance(row["map"], dict) else json.loads(row["map"])
                polyline_str = map_data.get("summary_polyline")
            except (json.JSONDecodeError, TypeError):
                pass
        if polyline_str:
            results.append({
                "id": _sanitize(row["id"]),
                "sport_type": row.get("sport_type", ""),
                "polyline": polyline_str,
                "name": row.get("name", ""),
            })
    return results


@router.get("/{activity_id}")
def get_activity(activity_id: int, si: StravaIntelligence = Depends(get_si)):
    activities = si.strava_activities_cache.activities
    match = activities[activities["id"] == activity_id]
    if match.empty:
        raise HTTPException(status_code=404, detail="Activity not found")
    return _activity_to_dict(match.iloc[0], include_streams=True)
