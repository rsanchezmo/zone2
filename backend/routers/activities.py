import json
from fastapi import APIRouter, Depends, HTTPException, Query
import pandas as pd

from backend._serialize import sanitize as _sanitize
from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence
from strava.strava_utils import format_pace_or_speed
from strava.streams_store import columnar_to_points

router = APIRouter()

# Columns to exclude from list view (heavy data)
_EXCLUDE_FROM_LIST = {"map"}

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


def _activity_to_dict(row: pd.Series, include_streams: bool = False, streams: dict | None = None) -> dict:
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

    # Distance in km
    if d.get("distance") is not None:
        d["distance_km"] = round(d["distance"] / 1000, 2)

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
        d["streams"] = columnar_to_points(streams) if streams else None

        # Include detail-only fields when showing full activity
        for field in ("photos", "splits_metric", "best_efforts", "laps", "gear", "segment_efforts", "similar_activities"):
            if field in row.index and row[field] is not None:
                try:
                    val = row[field] if isinstance(row[field], (list, dict)) else json.loads(row[field])
                    d[field] = val
                except (json.JSONDecodeError, TypeError):
                    d[field] = None

    return d


_SORT_FIELDS = {"date", "distance", "moving_time", "total_elevation_gain", "average_speed"}


@router.get("")
def list_activities(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sport_type: str | None = None,
    year: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    gear_id: str | None = None,
    search: str | None = Query(None),
    sort_by: str = Query("date"),
    sort_dir: str = Query("desc"),
    si: StravaIntelligence = Depends(get_si),
):
    activities = si.strava_activities_cache.get_prepared_view()
    if activities.empty:
        return {"items": [], "total": 0, "page": page, "per_page": per_page}

    # Build the filter mask without materializing intermediates. This keeps
    # the prepared view immutable (it's the live cache) and avoids a df.copy()
    # per request.
    sdl = activities["start_date_local"]
    mask = pd.Series(True, index=activities.index)
    if search:
        mask &= activities["name"].str.contains(search, case=False, na=False)
    if sport_type:
        mask &= activities["sport_type"] == sport_type
    if gear_id and "gear_id" in activities.columns:
        mask &= activities["gear_id"] == gear_id
    if year:
        mask &= sdl.dt.year == year
    tz = sdl.dt.tz
    if date_from:
        dt_from = pd.to_datetime(date_from)
        if tz is not None:
            dt_from = dt_from.tz_localize(tz)
        mask &= sdl >= dt_from
    if date_to:
        dt_to = pd.to_datetime(date_to) + pd.Timedelta(days=1)
        if tz is not None:
            dt_to = dt_to.tz_localize(tz)
        mask &= sdl < dt_to
    activities = activities[mask]

    # Sort
    sort_col = "start_date_local" if sort_by not in _SORT_FIELDS or sort_by == "date" else sort_by
    ascending = sort_dir == "asc"
    activities = activities.sort_values(sort_col, ascending=ascending, na_position="last")
    total = len(activities)

    start = (page - 1) * per_page
    end = start + per_page
    page_df = activities.iloc[start:end]

    items = [_activity_to_dict(row) for _, row in page_df.iterrows()]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/sport-types")
def get_sport_types(si: StravaIntelligence = Depends(get_si)):
    activities = si.strava_activities_cache.activities_raw
    if activities.empty:
        return []
    return sorted(activities["sport_type"].unique().tolist())


@router.get("/years")
def get_years(si: StravaIntelligence = Depends(get_si)):
    activities = si.strava_activities_cache.get_prepared_view()
    if activities.empty:
        return []
    return sorted(activities["start_date_local"].dt.year.unique().tolist(), reverse=True)


@router.get("/on-dates")
def activities_on_dates(
    dates: str = Query(..., description="Comma-separated YYYY-MM-DD local dates"),
    si: StravaIntelligence = Depends(get_si),
):
    activities = si.strava_activities_cache.get_prepared_view()
    if activities.empty:
        return {"items": []}
    wanted = {d.strip() for d in dates.split(",") if d.strip()}
    day = activities["start_date_local"].dt.strftime("%Y-%m-%d")
    subset = activities[day.isin(wanted)]
    items = [_activity_to_dict(row) for _, row in subset.iterrows()]
    return {"items": items}


@router.get("/polylines")
def get_polylines(
    sport_type: str | None = None,
    year: int | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    """Return lightweight polyline data for all activities (for world map view)."""
    activities = si.strava_analytics._get_prepared_activities()
    if activities.empty:
        return []

    if sport_type:
        activities = activities[activities["sport_type"] == sport_type]
    if year:
        activities = activities[activities["start_date_local"].dt.year == year]

    # Use pre-parsed map dicts — no json.loads needed
    has_map = activities["map"].apply(lambda m: isinstance(m, dict) and bool(m.get("summary_polyline")))
    filtered = activities[has_map]

    return [
        {
            "id": _sanitize(row["id"]),
            "sport_type": row.get("sport_type", ""),
            "polyline": row["map"]["summary_polyline"],
            "name": row.get("name", ""),
        }
        for _, row in filtered.iterrows()
    ]


@router.get("/{activity_id}")
def get_activity(activity_id: int, si: StravaIntelligence = Depends(get_si)):
    row = si.strava_activities_cache.get_activity_by_id(activity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    streams = si.strava_activities_cache.get_streams(activity_id)
    return _activity_to_dict(row, include_streams=True, streams=streams)


@router.get("/{activity_id}/similar")
def get_similar_activities(
    activity_id: int,
    limit: int = Query(5, ge=1, le=20),
    si: StravaIntelligence = Depends(get_si),
):
    target = si.strava_activities_cache.get_activity_by_id(activity_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    activities = si.strava_activities_cache.activities_raw
    if activities.empty:
        return []

    sport = target.get("sport_type")
    distance = target.get("distance")
    elevation = target.get("total_elevation_gain")

    if not sport or distance is None or pd.isna(distance):
        return []

    df = activities.copy()
    df = df[df["sport_type"] == sport]
    df = df[df["id"] != activity_id]

    # Distance within ±10%
    dist_lo = float(distance) * 0.9
    dist_hi = float(distance) * 1.1
    df = df[(df["distance"] >= dist_lo) & (df["distance"] <= dist_hi)]

    # Elevation within ±20% (if target has elevation)
    if elevation is not None and not pd.isna(elevation) and float(elevation) > 0:
        elev_lo = float(elevation) * 0.8
        elev_hi = float(elevation) * 1.2
        df = df[df["total_elevation_gain"].fillna(0).between(elev_lo, elev_hi)]

    df["start_date_local"] = pd.to_datetime(df["start_date_local"])
    df = df.sort_values("start_date_local", ascending=False).head(limit)

    return [_activity_to_dict(row) for _, row in df.iterrows()]
