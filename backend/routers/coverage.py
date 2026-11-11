import logging
import time
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
import pandas as pd

from backend.config import settings
from backend.dependencies import get_z2
from backend.services import coverage
from zone2.core import Zone2
from zone2.map_matching import StravaMapMatcher, city_slug

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/cities")
def list_cities(streets_only: bool = Query(False)):
    """City list with coverage stats. Reads the per-city stats JSON so it never
    has to build a matcher (each instance holds ~300 MB); falls back to building
    one — and backfilling the cache — for cities added before stats caching."""
    variant = "streets" if streets_only else "all"
    out = []
    for slug, city_name in coverage.known_cities().items():
        cached = coverage.city_coverage(slug).read_stats()
        if cached and variant in cached:
            out.append({
                "slug": slug,
                "city_name": cached.get("city_name", city_name),
                "num_matched_activities": cached.get("num_matched_activities", 0),
                "bbox": cached.get("bbox"),
                **cached[variant],
            })
            continue
        matcher = coverage.get_matcher(slug)
        stats = matcher.coverage_stats_from_state(streets_only=streets_only)
        matcher.write_stats_cache()
        out.append({
            "slug": slug,
            "city_name": city_name,
            "num_matched_activities": len(matcher.coverage.matched_ids()),
            "bbox": matcher.city_bbox(),
            **stats,
        })
    return out


# City download runs in a BackgroundTasks thread; single global slot.
_add_status: dict = {
    "running": False, "city_name": None, "slug": None, "error": None,
    "progress": None, "started_at": None,
}
_add_lock = Lock()


def _run_add_city(city_name: str):
    def report(stage: str):
        with _add_lock:
            _add_status["progress"] = stage

    err, slug = None, None
    try:
        matcher = StravaMapMatcher(
            city_name=city_name, workdir=Path(settings.workdir), on_progress=report
        )
        slug = matcher.slug
        coverage.remember_matcher(slug, matcher)
        # Seed the stats cache and viewport index so the first /cities call
        # and map pans needn't build a matcher.
        matcher.write_stats_cache()
        matcher.write_viewport_index()
        logger.info("City map for %s ready (%s)", city_name, slug)
    except Exception as e:
        logger.exception("Adding city %s failed", city_name)
        err = f"{type(e).__name__}: {e}"
    finally:
        with _add_lock:
            _add_status.update({"running": False, "slug": slug, "error": err, "progress": None})


@router.post("/add")
def add_city(background_tasks: BackgroundTasks, city_name: str = Query(min_length=3)):
    """Download and store the runnable street network for a new city."""
    slug = city_slug(city_name)
    if slug in coverage.known_cities():
        raise HTTPException(status_code=409, detail=f"'{city_name}' is already added")
    with _add_lock:
        if _add_status["running"]:
            raise HTTPException(status_code=409, detail="A city download is already running")
        _add_status.update({
            "running": True, "city_name": city_name, "slug": None, "error": None,
            "progress": "starting", "started_at": time.time(),
        })
    background_tasks.add_task(_run_add_city, city_name)
    return {"status": "started"}


@router.get("/add/status")
def add_city_status():
    with _add_lock:
        return dict(_add_status)


def _nominatim(endpoint: str, **params) -> list | dict:
    import requests
    import osmnx as ox

    return requests.get(f"{ox.settings.nominatim_url.rstrip('/')}/{endpoint}", params={"format": "json", **params},
                        headers={"User-Agent": ox.settings.http_user_agent}, timeout=30).json()


def _containing_area(point: dict) -> dict | None:
    """For a place Nominatim has only as a point (e.g. a village), the
    smallest boundary around it that can be added instead: town, then city,
    then county level. Only a name that geocodes back to that same boundary
    is suggested, since cities are added (and later re-geocoded) by name."""
    import osmnx as ox

    seen: set[int] = set()
    for zoom in (12, 10, 8):  # Nominatim reverse zoom levels for town, city, county
        time.sleep(1)  # Nominatim usage policy: at most one request per second
        area = _nominatim("reverse", lat=point["lat"], lon=point["lon"], zoom=zoom, addressdetails=1)
        if area.get("osm_type") != "relation" or area.get("osm_id") in seen:
            continue
        seen.add(area["osm_id"])
        address = area.get("address", {})
        name = ", ".join(p for p in (area.get("name"), address.get("state"), address.get("country")) if p)
        try:
            gdf = ox.geocode_to_gdf(name)
        except Exception:
            continue
        if int(gdf.iloc[0].get("osm_id", -1)) != int(area["osm_id"]):
            continue
        km2 = float(gdf.to_crs(gdf.estimate_utm_crs()).area.iloc[0]) / 1e6
        return {"query": name, "display_name": str(gdf.iloc[0].get("display_name", name)), "area_km2": round(km2, 1)}
    return None


@router.get("/geocode")
def geocode_city(q: str = Query(min_length=3)):
    """Preview what a city query resolves to before downloading it.
    Guards against Nominatim surprises (bare 'Amsterdam' → New York City,
    whose historical name is New Amsterdam). A place mapped only as a point
    has no boundary to cover, so the preview then carries `point_only` and
    suggests the area around it (`suggestion`, None when there is none)."""
    import osmnx as ox

    try:
        gdf = ox.geocode_to_gdf(q)
    except TypeError:
        # osmnx raises TypeError when the place's geometry isn't a (Multi)Polygon
        hits = _nominatim("search", q=q, limit=1)
        if not hits:
            raise HTTPException(status_code=404, detail=f"'{q}' not found")
        south, north, west, east = (float(v) for v in hits[0]["boundingbox"])
        return {
            "query": q,
            "display_name": hits[0]["display_name"],
            "lat": float(hits[0]["lat"]),
            "lon": float(hits[0]["lon"]),
            "bbox": {"south": south, "west": west, "north": north, "east": east},
            "point_only": True,
            "suggestion": _containing_area(hits[0]),
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"{type(e).__name__}: {e}")
    west, south, east, north = (float(v) for v in gdf.total_bounds)
    centroid = gdf.iloc[0].geometry.centroid
    return {
        "query": q,
        "display_name": str(gdf.iloc[0].get("display_name", q)),
        "lat": float(centroid.y),
        "lon": float(centroid.x),
        "bbox": {"south": south, "west": west, "north": north, "east": east},
    }


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
):
    return coverage.districts(slug, admin_level, geometry, streets_only)


@router.get("/{slug}/hexes")
def coverage_hexes(
    slug: str,
    resolution: int = Query(StravaMapMatcher.HEX_RESOLUTION, ge=7, le=9),
    geometry: bool = Query(False),
    streets_only: bool = Query(False),
):
    def build():
        return coverage.get_matcher(slug).coverage_by_hex(
            resolution=resolution, include_geometry=geometry, streets_only=streets_only
        )
    return coverage.cached_json(("hexes", slug, resolution, geometry, streets_only),
                                coverage.state_version(slug) + (coverage.LAYERS_FORMAT,), build)


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
