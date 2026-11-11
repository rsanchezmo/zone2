from datetime import date
import json
from fastapi import APIRouter, Depends, HTTPException, Query
import pandas as pd

from backend._serialize import sanitize as _sanitize
from backend._ttl_cache import TTLCache
from backend.dependencies import get_z2
from backend.services import activities
from backend.services.activities import activity_dict
from zone2.activities_cache import _has_full_photo_list
from zone2.core import Zone2
from zone2.utils import df_rows

router = APIRouter()

# Columns to exclude from list view (heavy data)
_EXCLUDE_FROM_LIST = {"map"}

_SORT_FIELDS = {"date", "distance", "moving_time", "total_elevation_gain", "average_speed"}


@router.get("")
def list_activities(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sport_type: str | None = None,
    year: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    gear_id: str | None = None,
    search: str | None = Query(None),
    sort_by: str = Query("date"),
    sort_dir: str = Query("desc"),
    z2: Zone2 = Depends(get_z2),
):
    activities = z2.strava_activities_cache.get_prepared_view()
    if activities.empty:
        return {"items": [], "total": 0, "page": page, "per_page": per_page}

    # Build the filter mask without materializing intermediates. This keeps
    # the prepared view immutable (it's the live cache) and avoids a df.copy()
    # per request.
    sdl = activities["start_date_local"]
    mask = pd.Series(True, index=activities.index)
    if search:
        mask &= activities["name"].str.contains(search, case=False, na=False, regex=False)
    if sport_type:
        mask &= activities["sport_type"] == sport_type
    if gear_id and "gear_id" in activities.columns:
        mask &= activities["gear_id"] == gear_id
    if year:
        mask &= sdl.dt.year == year
    if date_from or date_to:
        mask &= z2.strava_activities_cache.days_mask(
            date_from.isoformat() if date_from else None, date_to.isoformat() if date_to else None,
        )
    activities = activities[mask]

    # Sort
    sort_col = "start_date_local" if sort_by not in _SORT_FIELDS or sort_by == "date" else sort_by
    ascending = sort_dir == "asc"
    activities = activities.sort_values(sort_col, ascending=ascending, na_position="last")
    total = len(activities)

    start = (page - 1) * per_page
    end = start + per_page
    page_df = activities.iloc[start:end]

    items = [activity_dict(row) for _, row in page_df.iterrows()]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/sport-types")
def get_sport_types(z2: Zone2 = Depends(get_z2)):
    activities = z2.strava_activities_cache.activities_raw
    if activities.empty:
        return []
    return sorted(activities["sport_type"].unique().tolist())


@router.get("/years")
def get_years(z2: Zone2 = Depends(get_z2)):
    activities = z2.strava_activities_cache.get_prepared_view()
    if activities.empty:
        return []
    return sorted(activities["start_date_local"].dt.year.unique().tolist(), reverse=True)


@router.get("/on-dates")
def activities_on_dates(
    dates: str = Query(..., description="Comma-separated YYYY-MM-DD local dates"),
    z2: Zone2 = Depends(get_z2),
):
    wanted = {d.strip() for d in dates.split(",") if d.strip()}
    return {"items": activities.on_dates(z2, wanted)}


# Keyed by the filters and the activities version: the full history is a large
# payload the maps request on every visit.
_polylines_cache = TTLCache(maxsize=32, ttl_seconds=24 * 3600)


@router.get("/polylines")
def get_polylines(
    sport_type: str | None = None,
    year: int | None = None,
    gear_id: str | None = None,
    z2: Zone2 = Depends(get_z2),
):
    """Return lightweight polyline data for all activities (for world map view)."""
    key = (sport_type, year, gear_id, z2.strava_activities_cache.cache_version)
    return _polylines_cache.json_response(key, lambda: _polylines(z2, sport_type, year, gear_id))


def _polylines(z2: Zone2, sport_type: str | None, year: int | None, gear_id: str | None) -> list[dict]:
    activities = z2.strava_activities_cache.get_prepared_view()
    if activities.empty or "summary_polyline" not in activities.columns:
        return []

    mask = activities["summary_polyline"].notna()
    if sport_type:
        mask &= activities["sport_type"] == sport_type
    if year:
        mask &= activities["start_date_local"].dt.year == year
    if gear_id and "gear_id" in activities.columns:
        mask &= activities["gear_id"] == gear_id

    return [
        {
            "id": _sanitize(row["id"]),
            "sport_type": row.get("sport_type", ""),
            "year": row["start_date_local"].year,
            "polyline": row["summary_polyline"],
            "name": row.get("name", ""),
        }
        for row in df_rows(activities[mask], "id", "sport_type", "start_date_local", "summary_polyline", "name")
    ]


@router.get("/photos/recent")
def recent_photos(
    limit: int = Query(6, ge=1, le=30),
    z2: Zone2 = Depends(get_z2),
):
    """Newest activity photos first, each tagged with its activity — for the
    profile collage. Walks activities newest-first and stops once `limit`
    photos are collected, so it rarely scans the whole cache."""
    activities = z2.strava_activities_cache.get_prepared_view()
    if activities.empty or "photos" not in activities.columns:
        return []

    ordered = activities.sort_values("start_date_local", ascending=False, na_position="last")
    out: list[dict] = []
    for _, row in ordered.iterrows():
        raw = row["photos"]
        if not _has_full_photo_list(raw):
            continue
        photos = [p for p in json.loads(raw) if isinstance(p.get("urls"), dict) and p["urls"]]
        if not photos:
            continue
        # One photo per activity so the collage spans recent activities rather
        # than clustering on one; Strava marks its cover shot as default_photo.
        photo = next((p for p in photos if p.get("default_photo")), photos[0])
        out.append({
            "unique_id": photo.get("unique_id"),
            "urls": photo["urls"],
            "caption": photo.get("caption"),
            "activity_id": _sanitize(row["id"]),
            "activity_name": row.get("name"),
            "sport_type": row.get("sport_type"),
            "start_date_local": _sanitize(row["start_date_local"]),
        })
        if len(out) >= limit:
            break
    return out


@router.get("/{activity_id}")
def get_activity(activity_id: int, z2: Zone2 = Depends(get_z2)):
    row = z2.strava_activities_cache.get_activity_by_id(activity_id, include_detail=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    streams = z2.strava_activities_cache.get_streams(activity_id)
    return activity_dict(row, include_streams=True, streams=streams)


@router.get("/{activity_id}/similar")
def get_similar_activities(
    activity_id: int,
    limit: int = Query(5, ge=1, le=20),
    z2: Zone2 = Depends(get_z2),
):
    df = activities.similar(z2, activity_id, limit)
    if df is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return [activity_dict(row) for _, row in df.iterrows()]
