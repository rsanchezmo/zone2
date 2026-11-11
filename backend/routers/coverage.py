from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
import pandas as pd

from backend._serialize import PackedJSONResponse
from backend.dependencies import get_z2
from backend.services import coverage
from zone2.core import Zone2
from zone2.map_matching import StravaMapMatcher

router = APIRouter()


@router.get("/cities")
def list_cities(streets_only: bool = Query(False)) -> list[coverage.CitySummary]:
    """City list with coverage stats, read from each city's stats file (see coverage.city_list)."""
    return coverage.city_list(streets_only)


@router.post("/add")
def add_city(background_tasks: BackgroundTasks, city_name: str = Query(min_length=3)):
    """Download and store the runnable street network for a new city, one at a time."""
    coverage.claim_city_download(city_name)
    background_tasks.add_task(coverage.download_city, city_name)
    return {"status": "started"}


@router.get("/add/status")
def add_city_status() -> coverage.CityDownload:
    return coverage.add_status()


@router.get("/geocode")
def geocode_city(q: str = Query(min_length=3)) -> coverage.GeocodeResult:
    """Preview what a city query resolves to before downloading it (see coverage.geocode_city)."""
    return coverage.geocode_city(q)


@router.delete("/{slug}")
def delete_city(slug: str):
    """Remove a city's map and all its matched state from disk."""
    if slug not in coverage.known_cities():
        raise HTTPException(status_code=404, detail=f"No coverage map for '{slug}'")
    if coverage.sync_status(slug)["running"]:
        raise HTTPException(status_code=409, detail="A sync is running for this city")
    removed = coverage.delete_city(slug)
    return {"status": "deleted", "files_removed": removed}


_new_streets_lock = Lock()


def _new_streets(slug: str, z2: Zone2) -> pd.DataFrame:
    """Each matched activity's new streets (see CityCoverage.write_new_streets),
    written after every sync that adds runs; built here only when missing."""
    city = coverage.city_coverage(slug)
    new = city.new_streets()
    if new is None:
        with _new_streets_lock:
            new = city.new_streets()
            if new is None:
                new = coverage.get_matcher(slug).write_new_streets(coverage.start_times(z2))
    return new


@router.get("/routes/{activity_id}")
def activity_route(activity_id: int, z2: Zone2 = Depends(get_z2)):
    """The activity's matched route in every coverage city that matched it,
    as GeoJSON features (lines oriented in travel order) with the km of
    streets it walked first (`new_km`); no features when none has."""
    features = []
    for slug, city_name in coverage.known_cities().items():
        geometry = coverage.city_coverage(slug).read_route(activity_id)
        if geometry is not None:
            new = _new_streets(slug, z2)
            new_m = new.loc[new['activity_id'] == activity_id, 'new_m'].sum()
            features.append({"type": "Feature", "geometry": geometry,
                             "properties": {"slug": slug, "city_name": city_name,
                                            "new_km": round(float(new_m) / 1000, 2)}})
    return {"type": "FeatureCollection", "features": features}


@router.get("/{slug}/timeline")
def coverage_timeline(slug: str, z2: Zone2 = Depends(get_z2)):
    """Streets walked for the first time per month (`new_km`, adding up to
    the city's covered km as `cumulative_km`), from the first matched run to
    the athlete's current month, with the runs matched in the city that month."""
    this_month = z2.clock.today().strftime('%Y-%m')

    def build():
        new = _new_streets(slug, z2)
        started = coverage.start_times(z2)
        runs = new.assign(start=new['activity_id'].map(started)).dropna(subset=['start'])
        if runs.empty:
            return {"months": []}
        month = pd.to_datetime(runs['start'], utc=True).dt.strftime('%Y-%m')
        per_month = runs.groupby(month).agg(new_m=('new_m', 'sum'), runs=('activity_id', 'size'))
        months = pd.period_range(per_month.index.min(), this_month, freq='M').strftime('%Y-%m')
        per_month = per_month.reindex(months, fill_value=0)
        cumulative = per_month['new_m'].cumsum()
        return {"months": [
            {"month": m, "new_km": round(float(row.new_m) / 1000, 2), "runs": int(row.runs),
             "cumulative_km": round(float(total) / 1000, 2)}
            for m, row, total in zip(per_month.index, per_month.itertuples(), cumulative)
        ]}
    # The months run up to this one
    version = coverage.state_version(slug) + (coverage.LAYERS_FORMAT, this_month)
    return coverage.cached_json(("timeline", slug), version, build)


_viewport_index_lock = Lock()


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        south, west, north, east = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox must be south,west,north,east")
    return south, west, north, east


def _missing_geojson(slug: str, bbox: str, streets_only: bool, counts: bool) -> bytes:
    """GeoJSON of what is left to run in the lat/lon bbox, from the city's
    viewport index: a pan reads only the index rows around it and never loads
    the city, except to build the index on the first pan of a city (or of a
    new street map)."""
    box = _parse_bbox(bbox)
    city = coverage.city_coverage(slug)

    def query():
        return city.viewport_missing_geojson(box, streets_only=streets_only, with_counts=counts)
    body = query()
    if body is None:
        with _viewport_index_lock:
            body = query()
            if body is None:
                coverage.get_matcher(slug).write_viewport_index()
                body = query()
    return body


@router.get("/{slug}/edges")
def coverage_edges(
    slug: str,
    covered: bool = Query(True),
    bbox: str | None = Query(None, description="south,west,north,east — required for covered=false"),
    streets_only: bool = Query(False),
    counts: bool = Query(False, description="Include per-stretch run count as `times`"),
):
    """covered: the stretches the matched routes walked, exactly as run
    (sidewalks and crossings included), with how many runs walked each.
    Otherwise what is left to run: street-network edges minus their walked
    stretches, which is most of the city, so it must be bounded by a bbox."""
    if not covered and not bbox:
        raise HTTPException(status_code=400, detail="bbox is required for covered=false")
    if not covered:
        # A new bbox on every pan: not cached, served from the viewport index
        return Response(_missing_geojson(slug, bbox, streets_only, counts), media_type="application/json")

    if bbox:
        south, west, north, east = _parse_bbox(bbox)
        layer = coverage.get_matcher(slug).walked_layer(streets_only=streets_only).cx[west:east, south:north]
        return coverage.edges_to_geojson(layer, include_times=counts)
    return coverage.walked_edges(slug, streets_only, counts)


@router.get("/{slug}/districts")
def coverage_districts(
    slug: str,
    admin_level: int = Query(9, ge=4, le=11),
    geometry: bool = Query(False),
    streets_only: bool = Query(False),
) -> Response:
    return PackedJSONResponse(coverage.districts(slug, admin_level, geometry, streets_only))


@router.get("/{slug}/hexes")
def coverage_hexes(
    slug: str,
    resolution: int = Query(StravaMapMatcher.HEX_RESOLUTION, ge=7, le=9),
    geometry: bool = Query(False),
    streets_only: bool = Query(False),
) -> Response:
    return PackedJSONResponse(coverage.hexes(slug, resolution, geometry, streets_only))


class AreaRequest(BaseModel):
    # Polygon vertices as [lat, lon]
    points: list[tuple[float, float]] = Field(min_length=3)
    streets_only: bool = False


@router.post("/{slug}/area")
def coverage_area(slug: str, payload: AreaRequest):
    matcher = coverage.get_matcher(slug)
    return matcher.coverage_in_polygon(payload.points, streets_only=payload.streets_only)


@router.post("/{slug}/sync")
def trigger_coverage_sync(
    slug: str,
    background_tasks: BackgroundTasks,
    sport_types: str = Query("Run", description="Comma-separated sport types"),
    z2: Zone2 = Depends(get_z2),
):
    if slug not in coverage.known_cities():
        raise HTTPException(status_code=404, detail=f"No coverage map for '{slug}'")
    if not coverage.try_claim_sync(slug):
        raise HTTPException(status_code=409, detail="Coverage sync already running")
    sports = [s.strip() for s in sport_types.split(",") if s.strip()]
    background_tasks.add_task(coverage.run_city_sync, slug, z2, sports)
    return {"status": "started"}


@router.get("/{slug}/sync/status")
def coverage_sync_status(slug: str):
    return coverage.sync_status(slug)
