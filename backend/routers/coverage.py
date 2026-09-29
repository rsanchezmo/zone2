import json
import logging
import time
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import settings
from backend.dependencies import get_z2
from zone2.core import Zone2
from zone2.map_matching import StravaMapMatcher
from zone2.utils import get_activities_as_gdf_from_streams

router = APIRouter()
logger = logging.getLogger(__name__)

_matchers: dict[str, StravaMapMatcher] = {}
_matchers_lock = Lock()

# Per-city sync status; matching runs in a BackgroundTasks thread.
_sync_status: dict[str, dict] = {}
_sync_lock = Lock()


def _osm_dir() -> Path:
    return Path(settings.workdir) / "osm_maps"


def _known_cities() -> dict[str, str]:
    """slug -> city_name for every city with a slim map on disk."""
    cities = {}
    for edges_fp in sorted(_osm_dir().glob("*_edges.parquet")):
        if edges_fp.name.endswith("_covered_edges.parquet"):
            continue
        slug = edges_fp.name.removesuffix("_edges.parquet")
        meta_fp = _osm_dir() / f"{slug}_meta.json"
        city_name = slug
        if meta_fp.exists():
            try:
                city_name = json.loads(meta_fp.read_text()).get("city_name", slug)
            except json.JSONDecodeError:
                pass
        cities[slug] = city_name
    return cities


def _get_matcher(slug: str) -> StravaMapMatcher:
    cities = _known_cities()
    if slug not in cities:
        raise HTTPException(status_code=404, detail=f"No coverage map for '{slug}'")
    with _matchers_lock:
        if slug not in _matchers:
            _matchers[slug] = StravaMapMatcher(
                city_name=cities[slug], workdir=Path(settings.workdir)
            )
        return _matchers[slug]


def _read_stats_cache(slug: str) -> dict | None:
    fp = _osm_dir() / f"{slug}_stats.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


@router.get("/cities")
def list_cities(streets_only: bool = Query(False)):
    """City list with coverage stats. Reads the per-city stats JSON so it never
    has to build a matcher (each instance holds ~300 MB); falls back to building
    one — and backfilling the cache — for cities added before stats caching."""
    variant = "streets" if streets_only else "all"
    out = []
    for slug, city_name in _known_cities().items():
        cached = _read_stats_cache(slug)
        if cached and variant in cached:
            out.append({
                "slug": slug,
                "city_name": cached.get("city_name", city_name),
                "num_matched_activities": cached.get("num_matched_activities", 0),
                "bbox": cached.get("bbox"),
                **cached[variant],
            })
            continue
        matcher = _get_matcher(slug)
        stats = matcher.coverage_stats_from_state(streets_only=streets_only)
        matcher.write_stats_cache()
        out.append({
            "slug": slug,
            "city_name": city_name,
            "num_matched_activities": len(matcher.matched_activity_ids()),
            "bbox": matcher.city_bbox(),
            **{k: v for k, v in stats.items() if not k.startswith("_")},
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
        slug = matcher._slug()
        with _matchers_lock:
            _matchers[slug] = matcher
        # Seed the stats cache so the first /cities call needn't build a matcher.
        matcher.write_stats_cache()
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
    slug = city_name.replace(", ", "_").lower()
    if slug in _known_cities():
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
    if slug not in _known_cities():
        raise HTTPException(status_code=404, detail=f"No coverage map for '{slug}'")
    with _sync_lock:
        if _sync_status.get(slug, {}).get("running"):
            raise HTTPException(status_code=409, detail="A sync is running for this city")
    with _matchers_lock:
        _matchers.pop(slug, None)
    # Explicit artifact names — a bare glob on the slug prefix could match
    # another city whose slug extends this one.
    suffixes = [
        "edges.parquet", "connectors.parquet", "boundary.parquet", "meta.json",
        "covered_edges.parquet", "matched_activities.parquet", "routes.parquet", "stats.json",
    ]
    paths = [_osm_dir() / f"{slug}_{s}" for s in suffixes]
    paths += _osm_dir().glob(f"{slug}_districts_*.parquet")
    removed = 0
    for fp in paths:
        if fp.exists():
            fp.unlink()
            removed += 1
    logger.info("Deleted city %s (%d files)", slug, removed)
    return {"status": "deleted", "files_removed": removed}


@router.get("/routes/{activity_id}")
def activity_route(activity_id: int):
    """The activity's matched route in every coverage city that matched it,
    as GeoJSON features (lines oriented in travel order); no features when
    none has."""
    features = []
    for slug, city_name in _known_cities().items():
        geometry = StravaMapMatcher.read_route(_osm_dir(), slug, activity_id)
        if geometry is not None:
            features.append({"type": "Feature", "geometry": geometry,
                             "properties": {"slug": slug, "city_name": city_name}})
    return {"type": "FeatureCollection", "features": features}


@router.get("/{slug}/summary")
def coverage_summary(slug: str, streets_only: bool = Query(False)):
    matcher = _get_matcher(slug)
    stats = matcher.coverage_stats_from_state(streets_only=streets_only)
    return {
        "slug": slug,
        "city_name": matcher.city_name,
        "num_matched_activities": len(matcher.matched_activity_ids()),
        "bbox": matcher.city_bbox(),
        **{k: v for k, v in stats.items() if not k.startswith("_")},
    }


def _clip_to_bbox(gdf, bbox: str):
    try:
        south, west, north, east = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox must be south,west,north,east")
    return gdf.cx[west:east, south:north]


def _edges_to_geojson(subset, include_times: bool = False) -> dict:
    features = []
    names = subset["name"].tolist()
    times = (subset["times"].tolist() if include_times and "times" in subset.columns
             else [None] * len(subset))
    for geom, name, t in zip(subset.geometry, names, times):
        if geom is None or geom.is_empty:
            continue
        coords = [[round(x, 6), round(y, 6)] for x, y in geom.coords]
        props = {"name": None if name is None or str(name) == "nan" else str(name)}
        if t is not None:
            props["times"] = int(t)
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


@router.get("/{slug}/edges")
def coverage_edges(
    slug: str,
    covered: bool = Query(True),
    bbox: str | None = Query(None, description="south,west,north,east — required for covered=false"),
    streets_only: bool = Query(False),
    counts: bool = Query(False, description="Include per-edge traversal count as `times`"),
):
    """Runnable edges as GeoJSON. Covered edges are few; uncovered edges are
    the whole city, so they must be bounded by a bbox."""
    if not covered and not bbox:
        raise HTTPException(status_code=400, detail="bbox is required for covered=false")

    matcher = _get_matcher(slug)
    und = matcher.undirected_with_covered(streets_only=streets_only, with_counts=counts)
    subset = und[und["covered"] == covered].to_crs("EPSG:4326")
    if bbox:
        subset = _clip_to_bbox(subset, bbox)
    return _edges_to_geojson(subset, include_times=counts)


@router.get("/{slug}/districts")
def coverage_districts(
    slug: str,
    admin_level: int = Query(9, ge=4, le=11),
    geometry: bool = Query(False),
    streets_only: bool = Query(False),
):
    matcher = _get_matcher(slug)
    return matcher.coverage_by_district(
        admin_level=admin_level, include_geometry=geometry, streets_only=streets_only
    )


class AreaRequest(BaseModel):
    # Polygon vertices as [lat, lon]
    points: list[tuple[float, float]] = Field(min_length=3)
    streets_only: bool = False


@router.post("/{slug}/area")
def coverage_area(slug: str, payload: AreaRequest):
    matcher = _get_matcher(slug)
    return matcher.coverage_in_polygon(payload.points, streets_only=payload.streets_only)


def _run_coverage_sync(slug: str, z2: Zone2, sport_types: list[str]):
    err = None
    try:
        matcher = _get_matcher(slug)
        # High-resolution GPS streams, which the matcher thins to ~20 m. No
        # summary-polyline fallback: a match is persisted once and never
        # redone, so an activity whose streams aren't cached yet waits for a
        # later sync instead of being frozen at polyline resolution.
        cache = z2.strava_activities_cache
        activities = cache.activities[cache.activities["sport_type"].isin(sport_types)]
        gdf = get_activities_as_gdf_from_streams(activities, cache.streams, polyline_fallback=False)
        stats = matcher.match_incremental(gdf)
        logger.info("Coverage sync for %s done: %s%%", slug, stats.get("coverage_pct"))
    except Exception as e:
        logger.exception("Coverage sync for %s failed", slug)
        err = f"{type(e).__name__}: {e}"
    finally:
        with _sync_lock:
            _sync_status[slug] = {"running": False, "last_error": err}


@router.post("/{slug}/sync")
def trigger_coverage_sync(
    slug: str,
    background_tasks: BackgroundTasks,
    sport_types: str = Query("Run", description="Comma-separated sport types"),
    z2: Zone2 = Depends(get_z2),
):
    _get_matcher(slug)  # 404 before claiming the slot
    with _sync_lock:
        if _sync_status.get(slug, {}).get("running"):
            raise HTTPException(status_code=409, detail="Coverage sync already running")
        _sync_status[slug] = {"running": True, "last_error": None}
    sports = [s.strip() for s in sport_types.split(",") if s.strip()]
    background_tasks.add_task(_run_coverage_sync, slug, z2, sports)
    return {"status": "started"}


@router.get("/{slug}/sync/status")
def coverage_sync_status(slug: str):
    with _sync_lock:
        return _sync_status.get(slug, {"running": False, "last_error": None})
