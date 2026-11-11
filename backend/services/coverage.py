"""Coverage cities, shared by the coverage and planner routers, the coach's tools and the Strava
sync: the cities and their download, the street networks loaded in memory (a few at most,
released when idle), the map-layer responses cached per city, the coverage sync that matches
new activities in each city, the loops planned and not saved yet, and the Garmin courses
starting in a city."""

import ctypes
import gc
import hashlib
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any, NotRequired, TypedDict

from fastapi import Response
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import shapely

from backend._serialize import PackedJSON, PackedJSONResponse
from backend.config import settings
from backend.errors import Conflict, NotFound
from backend.services.garmin_courses import course_line, course_list
from zone2.city_coverage import CityCoverage, LatLon, NewWay, atomic_write, edge_feature
from zone2.core import Zone2
from zone2.map_matching import LoopFeature, PolygonCoverage, StravaMapMatcher, city_slug
from zone2.utils import get_activities_as_gdf_from_streams

logger = logging.getLogger(__name__)

# Each loaded city holds its street network in memory (~140 MB for a large city);
# only the most recently used ones stay loaded.
_MAX_LOADED_CITIES = 3
_matchers: "OrderedDict[str, StravaMapMatcher]" = OrderedDict()
_matchers_lock = Lock()
# ...and are unloaded once unused this long: the map layers are served from
# disk, so a city is only needed for area queries, syncs and index builds.
_CITY_IDLE_S = 600
_matcher_used: dict[str, float] = {}   # slug -> time.monotonic() of last use

# Serialized map-layer responses, reused until a sync rewrites the city's
# coverage state (the key's version is its state files' mtimes). They are
# also persisted under osm_maps/responses, so a restart doesn't load a city
# just to redraw the same layers.
_MAX_CACHED_RESPONSES = 32
_responses: "OrderedDict[tuple, tuple[tuple, PackedJSON]]" = OrderedDict()
_responses_lock = Lock()

# Per-city sync status; matching runs in a BackgroundTasks thread.
_sync_status: dict[str, dict] = {}
_sync_lock = Lock()


class HeldPlan(TypedDict):
    """A loop planned and not saved yet (services/planned_routes.plan)."""
    slug: str
    feature: LoopFeature
    new_ways: list[NewWay]
    network: str
    # The PlanRequest as JSON, with the start it was planned from
    request: dict[str, Any]


# Loops planned but not saved yet, by plan_id, so saving one stores exactly the loop on screen
_MAX_HELD_PLANS = 32
_held_plans: "OrderedDict[str, HeldPlan]" = OrderedDict()
_held_plans_lock = Lock()

# Part of the map layers' cache version: bump when their content changes for
# the same coverage state, so responses persisted by older code aren't served.
LAYERS_FORMAT = 3

# Part of the Garmin courses' cache version: bump when their fields change
_COURSES_FORMAT = 2


def osm_dir() -> Path:
    return Path(settings.workdir) / "osm_maps"


def city_coverage(slug: str) -> CityCoverage:
    """The city's persisted coverage, read without loading the city."""
    return CityCoverage(osm_dir(), slug)


def known_cities() -> dict[str, str]:
    """slug -> city_name for every city with a slim map on disk."""
    cities = {}
    for edges_fp in sorted(osm_dir().glob("*_edges.parquet")):
        if edges_fp.name.endswith("_covered_edges.parquet"):
            continue
        slug = edges_fp.name.removesuffix("_edges.parquet")
        meta_fp = osm_dir() / f"{slug}_meta.json"
        city_name = slug
        if meta_fp.exists():
            try:
                city_name = json.loads(meta_fp.read_text()).get("city_name", slug)
            except json.JSONDecodeError:
                pass
        cities[slug] = city_name
    return cities


def require_city(slug: str) -> str:
    """The city's name; NotFound when there is no coverage map for `slug`."""
    name = known_cities().get(slug)
    if name is None:
        raise NotFound(f"No coverage map for '{slug}'")
    return name


class CitySummary(TypedDict):
    slug: str
    city_name: str
    num_matched_activities: int
    bbox: list[float] | None
    total_network_km: float
    traversed_km: float
    coverage_pct: float
    num_unique_streets: int


def city_list(streets_only: bool = False) -> list[CitySummary]:
    """Every city with its coverage, from its stats file, so listing never loads a city; one
    added before stats were cached is loaded once to write them. A city still downloading is
    left out."""
    variant = "streets" if streets_only else "all"
    download = add_status()
    downloading = download["slug"] if download["running"] else None
    out: list[CitySummary] = []
    for slug, city_name in known_cities().items():
        if slug == downloading:
            continue
        cached = city_coverage(slug).read_stats()
        if cached and variant in cached:
            out.append({"slug": slug, "city_name": cached.get("city_name", city_name),
                        "num_matched_activities": cached.get("num_matched_activities", 0),
                        "bbox": cached.get("bbox"), **cached[variant]})
            continue
        matcher = get_matcher(slug)
        stats = matcher.coverage_stats_from_state(streets_only=streets_only)
        matcher.write_stats_cache()
        out.append({"slug": slug, "city_name": city_name, "num_matched_activities": len(matcher.coverage.matched_ids()),
                    "bbox": matcher.city_bbox(), **stats})
    return out


def get_matcher(slug: str) -> StravaMapMatcher:
    city_name = require_city(slug)
    # Built under the lock so concurrent requests never load the same city twice
    with _matchers_lock:
        if slug in _matchers:
            _matchers.move_to_end(slug)
            _matcher_used[slug] = time.monotonic()
            return _matchers[slug]
        matcher = StravaMapMatcher(city_name=city_name, workdir=Path(settings.workdir))
        _remember_matcher_locked(slug, matcher)
        return matcher


def _remember_matcher_locked(slug: str, matcher: StravaMapMatcher) -> None:
    _matchers[slug] = matcher
    _matchers.move_to_end(slug)
    _matcher_used[slug] = time.monotonic()
    while len(_matchers) > _MAX_LOADED_CITIES:
        _matchers.popitem(last=False)


def remember_matcher(slug: str, matcher: StravaMapMatcher) -> None:
    """Keep a city loaded elsewhere (a new download) as the most recently used."""
    with _matchers_lock:
        _remember_matcher_locked(slug, matcher)


def unload_idle_cities() -> list[str]:
    """Drop the cities unused for _CITY_IDLE_S (a request or sync already
    holding one keeps it until done) and hand the memory back to the OS.
    Returns the slugs unloaded."""
    now = time.monotonic()
    with _matchers_lock:
        idle = [slug for slug in _matchers if now - _matcher_used.get(slug, 0.0) >= _CITY_IDLE_S]
        for slug in idle:
            del _matchers[slug]
    if idle:
        gc.collect()
        _return_freed_memory()
        logger.info("Unloaded idle coverage cities: %s", ", ".join(idle))
    return idle


class CityDownload(TypedDict):
    running: bool
    city_name: str | None
    slug: str | None
    error: str | None
    progress: str | None
    # time.time() when it started
    started_at: float | None


# A new city's download, one at a time: it holds the city's network while it builds
_download: CityDownload = {"running": False, "city_name": None, "slug": None, "error": None, "progress": None,
                           "started_at": None}
_download_lock = Lock()


def add_status() -> CityDownload:
    with _download_lock:
        return CityDownload(**_download)


def claim_city_download(city_name: str) -> str:
    """Take the download slot for `city_name` and return its slug; Conflict when the city is
    added already or another download runs. The caller then runs download_city."""
    slug = city_slug(city_name)
    if slug in known_cities():
        raise Conflict(f"'{city_name}' is already added")
    with _download_lock:
        if _download["running"]:
            raise Conflict(f"A city download is already running ({_download['city_name']})")
        _download.update(running=True, city_name=city_name, slug=slug, error=None, progress="starting",
                         started_at=time.time())
    return slug


def download_city(city_name: str) -> None:
    """Download and store the runnable street network of the city claimed, in the slot taken."""
    def report(stage: str) -> None:
        with _download_lock:
            _download["progress"] = stage

    err, slug = None, None
    try:
        matcher = StravaMapMatcher(city_name=city_name, workdir=Path(settings.workdir), on_progress=report)
        slug = matcher.slug
        remember_matcher(slug, matcher)
        # So listing the cities and the first map pans needn't load it
        matcher.write_stats_cache()
        matcher.write_viewport_index()
        logger.info("City map for %s ready (%s)", city_name, slug)
    except Exception as e:
        logger.exception("Adding city %s failed", city_name)
        err = f"{type(e).__name__}: {e}"
    finally:
        with _download_lock:
            _download.update(running=False, slug=slug, error=err, progress=None)


class GeocodeSuggestion(TypedDict):
    query: str
    display_name: str
    area_km2: float


class GeocodeBox(TypedDict):
    south: float
    west: float
    north: float
    east: float


class GeocodeResult(TypedDict):
    query: str
    display_name: str
    lat: float
    lon: float
    bbox: GeocodeBox
    area_km2: NotRequired[float]
    # Only a point in OSM, with no boundary to cover; `suggestion` is the area around it, if any
    point_only: NotRequired[bool]
    suggestion: NotRequired[GeocodeSuggestion | None]


def _geocode_to_gdf(query: str) -> gpd.GeoDataFrame:
    import osmnx as ox

    return ox.geocode_to_gdf(query)


def _nominatim(endpoint: str, **params: Any) -> Any:
    import osmnx as ox
    import requests

    return requests.get(f"{ox.settings.nominatim_url.rstrip('/')}/{endpoint}", params={"format": "json", **params},
                        headers={"User-Agent": ox.settings.http_user_agent}, timeout=30).json()


def _area_km2(gdf: gpd.GeoDataFrame) -> float:
    return round(float(gdf.to_crs(gdf.estimate_utm_crs()).area.iloc[0]) / 1e6, 1)


def _containing_area(point: dict[str, Any]) -> GeocodeSuggestion | None:
    """For a place Nominatim has only as a point (e.g. a village), the
    smallest boundary around it that can be added instead: town, then city,
    then county level. Only a name that geocodes back to that same boundary
    is suggested, since cities are added (and later re-geocoded) by name."""
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
            gdf = _geocode_to_gdf(name)
        except Exception:
            continue
        if int(gdf.iloc[0].get("osm_id", -1)) != int(area["osm_id"]):
            continue
        return {"query": name, "display_name": str(gdf.iloc[0].get("display_name", name)), "area_km2": _area_km2(gdf)}
    return None


def geocode_city(query: str) -> GeocodeResult:
    """What a city name resolves to on OSM, to confirm before downloading it.
    Guards against Nominatim surprises (bare 'Amsterdam' → New York City,
    whose historical name is New Amsterdam). A place mapped only as a point
    has no boundary to cover, so it then carries `point_only` and suggests the
    area around it (`suggestion`, None when there is none)."""
    try:
        gdf = _geocode_to_gdf(query)
    except TypeError:
        # osmnx raises TypeError when the place's geometry isn't a (Multi)Polygon
        hits = _nominatim("search", q=query, limit=1)
        if not hits:
            raise NotFound(f"'{query}' not found")
        south, north, west, east = (float(v) for v in hits[0]["boundingbox"])
        return {
            "query": query,
            "display_name": hits[0]["display_name"],
            "lat": float(hits[0]["lat"]),
            "lon": float(hits[0]["lon"]),
            "bbox": {"south": south, "west": west, "north": north, "east": east},
            "point_only": True,
            "suggestion": _containing_area(hits[0]),
        }
    except Exception as e:
        raise NotFound(f"{type(e).__name__}: {e}") from e
    west, south, east, north = (float(v) for v in gdf.total_bounds)
    centroid = gdf.iloc[0].geometry.centroid
    return {
        "query": query,
        "display_name": str(gdf.iloc[0].get("display_name", query)),
        "lat": float(centroid.y),
        "lon": float(centroid.x),
        "bbox": {"south": south, "west": west, "north": north, "east": east},
        "area_km2": _area_km2(gdf),
    }


def _responses_dir() -> Path:
    return osm_dir() / "responses"


def _response_file(key: tuple, version: tuple) -> Path:
    """`{slug}__{key digest}__{version digest}.json.gz`; key[1] is the slug."""
    def digest(obj: tuple) -> str:
        return hashlib.sha1(repr(obj).encode()).hexdigest()[:16]
    return _responses_dir() / f"{key[1]}__{digest(key)}__{digest(version)}.json.gz"


def _persist_response(fp: Path, body: bytes) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(fp, body)
    # Older versions of the same layer
    key_prefix = fp.name.rsplit("__", 1)[0] + "__"
    for old in fp.parent.iterdir():
        if old.name.startswith(key_prefix) and old != fp:
            old.unlink(missing_ok=True)


def cached_json(key: tuple, version: tuple, build: Callable[[], dict | list]) -> Response:
    """The JSON response for `key` (`(layer, slug, *params)`) at `version`, built only when
    neither memory nor disk holds it."""
    return PackedJSONResponse(cached_layer(key, version, build))


def cached_layer(key: tuple, version: tuple, build: Callable[[], dict | list]) -> PackedJSON:
    """cached_json's serialized body."""
    with _responses_lock:
        hit = _responses.get(key)
        if hit is not None and hit[0] == version:
            _responses.move_to_end(key)
            return hit[1]
    fp = _response_file(key, version)
    if fp.exists():
        packed = PackedJSON.from_gzipped(fp.read_bytes())
    else:
        packed = PackedJSON(json.dumps(build()).encode())
        _persist_response(fp, packed.to_gzipped())
    with _responses_lock:
        _responses[key] = (version, packed)
        _responses.move_to_end(key)
        while len(_responses) > _MAX_CACHED_RESPONSES:
            _responses.popitem(last=False)
    return packed


def state_version(slug: str, *extra: Path) -> tuple:
    return city_coverage(slug).state_version() + tuple(
        fp.stat().st_mtime_ns if fp.exists() else 0 for fp in extra)


def hold_plan(plan_id: str, plan: HeldPlan) -> None:
    """Keep a planned loop until it is saved, the most recent ones only."""
    with _held_plans_lock:
        _held_plans[plan_id] = plan
        _held_plans.move_to_end(plan_id)
        while len(_held_plans) > _MAX_HELD_PLANS:
            _held_plans.popitem(last=False)


def held_plan(slug: str, plan_id: str) -> HeldPlan | None:
    """The city's loop planned under `plan_id`, if still held."""
    with _held_plans_lock:
        plan = _held_plans.get(plan_id)
    return plan if plan is not None and plan["slug"] == slug else None


def delete_city(slug: str) -> int:
    """Unload the city, forget everything held for it and remove its map, its matched state and
    its cached layers from disk. Returns the number of files removed."""
    with _matchers_lock:
        _matchers.pop(slug, None)
        _matcher_used.pop(slug, None)
    with _held_plans_lock:
        for plan_id in [k for k, plan in _held_plans.items() if plan["slug"] == slug]:
            del _held_plans[plan_id]
    with _responses_lock:
        for key in [k for k in _responses if k[1] == slug]:
            del _responses[key]
    if _responses_dir().exists():
        for fp in _responses_dir().iterdir():
            if fp.name.startswith(f"{slug}__"):
                fp.unlink(missing_ok=True)
    with _sync_lock:
        _sync_status.pop(slug, None)
    removed = city_coverage(slug).remove()
    logger.info("Deleted city %s (%d files)", slug, removed)
    return removed


def start_times(z2: Zone2) -> pd.Series:
    """Activity id -> start time, the order first-walked streets are credited in."""
    acts = z2.strava_activities_cache.activities_raw
    return pd.Series(pd.to_datetime(acts['start_date'], utc=True).to_numpy(), index=acts['id'].to_numpy())


def edges_to_geojson(subset, include_times: bool = False) -> dict:
    features = []
    names = subset["name"].tolist()
    times = (subset["times"].tolist() if include_times and "times" in subset.columns
             else [None] * len(subset))
    # Every vertex in one array: far cheaper than walking each geometry's coords
    geoms = subset.geometry.values
    xy, owner = shapely.get_coordinates(geoms, return_index=True)
    ends = np.cumsum(np.bincount(owner, minlength=len(geoms))).tolist()
    rounded = [[round(x, 6), round(y, 6)] for x, y in xy.tolist()]
    starts = [0, *ends[:-1]]
    for start, end, name, t in zip(starts, ends, names, times):
        if start < end:
            features.append(edge_feature(rounded[start:end], name, t))
    return {"type": "FeatureCollection", "features": features}


def walked_edges(slug: str, streets_only: bool, counts: bool) -> Response:
    """The stretches the city's matched routes walked, as GeoJSON."""
    def build():
        return edges_to_geojson(get_matcher(slug).walked_layer(streets_only=streets_only), include_times=counts)
    return cached_json(("edges", slug, True, streets_only, counts),
                       state_version(slug) + (LAYERS_FORMAT,), build)


def districts(slug: str, admin_level: int, geometry: bool, streets_only: bool) -> PackedJSON:
    """Coverage per district of the city at `admin_level`."""
    def build():
        return get_matcher(slug).coverage_by_district(
            admin_level=admin_level, include_geometry=geometry, streets_only=streets_only
        )
    districts_fp = city_coverage(slug).districts_path(admin_level)
    return cached_layer(("districts", slug, admin_level, geometry, streets_only),
                        state_version(slug, districts_fp) + (LAYERS_FORMAT,), build)


def hexes(slug: str, resolution: int, geometry: bool, streets_only: bool) -> PackedJSON:
    """Coverage per H3 cell of the city at `resolution`."""
    def build():
        return get_matcher(slug).coverage_by_hex(
            resolution=resolution, include_geometry=geometry, streets_only=streets_only
        )
    return cached_layer(("hexes", slug, resolution, geometry, streets_only),
                        state_version(slug) + (LAYERS_FORMAT,), build)


class AreaKind(StrEnum):
    DISTRICT = "district"
    NEIGHBOURHOOD = "neighbourhood"
    HEX = "hex"


_ADMIN_LEVEL = {AreaKind.DISTRICT: 9, AreaKind.NEIGHBOURHOOD: 10}


class AreaCoverage(TypedDict):
    # The district's name, or the H3 cell's id
    name: str
    total_km: float
    covered_km: float
    coverage_pct: float
    # An H3 cell's centre, and the district it lies in when the city's districts are downloaded
    centre: NotRequired[LatLon]
    district: NotRequired[str]


def area_coverage(slug: str, kind: AreaKind) -> list[AreaCoverage]:
    """Coverage per district, neighbourhood or H3 cell of the city, best covered first, without
    shapes: the layer the Coverage page draws, read from its cache, and built and kept the way
    the page builds it when not stored yet."""
    require_city(slug)
    # The page's own variant (with shapes), so either one finds the layer the other built
    if kind is AreaKind.HEX:
        packed = hexes(slug, StravaMapMatcher.HEX_RESOLUTION, geometry=True, streets_only=False)
    else:
        packed = districts(slug, _ADMIN_LEVEL[kind], geometry=True, streets_only=False)
    rows: list[PolygonCoverage] = json.loads(packed.raw)
    areas: list[AreaCoverage] = [{"name": r["name"], "total_km": r["total_km"], "covered_km": r["covered_km"],
                                  "coverage_pct": r["coverage_pct"]} for r in rows]
    if kind is not AreaKind.HEX or not areas:
        return areas
    centres: list[LatLon] = [h3.cell_to_latlng(a["name"]) for a in areas]
    for area, centre, district in zip(areas, centres, district_of(slug, centres)):
        area["centre"] = centre
        if district is not None:
            area["district"] = district
    return areas


def district_of(slug: str, points: list[LatLon]) -> list[str | None]:
    """The district (admin level 9) each (lat, lon) lies in, or the nearest one for a point
    outside them all (an H3 cell's centre beyond the city's edge), from the city's downloaded
    districts; None for each when the city has none downloaded or isn't divided."""
    fp = city_coverage(slug).districts_path(9)
    if not fp.exists():
        return [None] * len(points)
    polys = gpd.read_parquet(fp, columns=["name", "geometry"])
    if len(polys) < 2:
        return [None] * len(points)
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy([lon for _, lon in points], [lat for lat, _ in points]),
                           crs="EPSG:4326").to_crs(polys.crs)
    nearest = gpd.sjoin_nearest(pts, polys, how="left")
    return [str(n) for n in nearest[~nearest.index.duplicated()]["name"]]


def city_garmin_courses(slug: str, z2: Zone2) -> PackedJSON:
    """The Garmin courses starting in the city, each with `city_km`, the km of
    streets of its part in the city, and `new_km`, those not run yet (both
    null when it doesn't match here). Kept until the coverage or the courses
    change; warmed after syncs."""
    city = city_coverage(slug)
    south, west, north, east = (city.read_stats() or {}).get("bbox") or get_matcher(slug).city_bbox()
    courses = [c for c in course_list(z2)
               if c["start"][0] is not None and south <= c["start"][0] <= north and west <= c["start"][1] <= east]

    def build():
        # A course's id and distance identify its line; a changed course is matched again
        keys = {f"{c['course_id']}:{c['distance_km']}": c for c in courses}
        streets = city.course_streets()
        if any(key not in streets for key in keys):
            streets = get_matcher(slug).match_courses({
                key: (lambda c=c: [(lat, lon) for lon, lat in course_line(z2, c["course_id"])["coordinates"]])
                for key, c in keys.items()
            })
        out = []
        for key, c in keys.items():
            new_km, city_km = city.street_km(streets.get(key)) or (None, None)
            out.append({**c, "new_km": new_km, "city_km": city_km})
        return out
    version = state_version(slug) + (LAYERS_FORMAT, _COURSES_FORMAT,
                                     tuple((c["course_id"], c["name"], c["distance_km"]) for c in courses))
    return cached_layer(("garmin-courses", slug), version, build)


class CityCourse(TypedDict):
    course_id: int
    name: str
    distance_km: float
    # [lat, lon]
    start: list[float | None]
    sport: str | None
    created_at: str | None
    new_km: float | None
    city_km: float | None


def garmin_courses_in(slug: str, z2: Zone2) -> list[CityCourse]:
    """city_garmin_courses, read."""
    return json.loads(city_garmin_courses(slug, z2).raw)


def sync_status(slug: str) -> dict:
    with _sync_lock:
        return dict(_sync_status.get(slug, {"running": False, "last_error": None}))


def try_claim_sync(slug: str) -> bool:
    """Atomic check-and-set: whether the caller now owns the city's sync slot."""
    with _sync_lock:
        if _sync_status.get(slug, {}).get("running"):
            return False
        _sync_status[slug] = {"running": True, "last_error": None}
        return True


def run_city_sync(slug: str, z2: Zone2, sport_types: list[str], keep_loaded: bool = True) -> None:
    """Match the city's new activities and bring the page's layers up to date,
    in the slot the caller claimed. Without keep_loaded (background syncs) a
    city this loaded is released afterwards: the page's layers are cached by then."""
    err = None
    with _matchers_lock:
        was_loaded = slug in _matchers
    try:
        cache = z2.strava_activities_cache
        activities = cache.activities_raw[cache.activities_raw["sport_type"].isin(sport_types)]
        todo = city_coverage(slug).pending_activities(activities)
        # High-resolution GPS streams, which the matcher thins to ~20 m. No
        # summary-polyline fallback: a match is persisted once and never
        # redone, so an activity whose streams aren't cached yet waits for a
        # later sync instead of being frozen at polyline resolution.
        gdf = get_activities_as_gdf_from_streams(todo, cache.streams, polyline_fallback=False)
        if gdf.empty:
            logger.info("Coverage sync for %s: nothing new to match", slug)
        else:
            stats = get_matcher(slug).match_incremental(gdf)
            logger.info("Coverage sync for %s done: %s%%", slug, stats.get("coverage_pct"))
        # Also with nothing new: after a deploy that changed a layer's format,
        # this rebuilds it before anyone opens the city. On the network the
        # matching just built, released only afterwards.
        _warm_map_layers(slug, z2)
        # A city someone is viewing keeps its network unless this sync matched in it
        if not gdf.empty or not was_loaded:
            with _matchers_lock:
                matcher = _matchers.get(slug)
            if matcher is not None:
                matcher.release_matching()
                if not keep_loaded:
                    with _matchers_lock:
                        _matchers.pop(slug, None)
    except Exception as e:
        logger.exception("Coverage sync for %s failed", slug)
        err = f"{type(e).__name__}: {e}"
    finally:
        with _sync_lock:
            _sync_status[slug] = {"running": False, "last_error": err}


def _warm_map_layers(slug: str, z2: Zone2) -> None:
    """Build the layers the coverage page opens with, so the first visit after
    new runs doesn't wait for them. A current layer is only a cache read; the
    city is loaded just to rebuild a stale one."""
    walked_edges(slug, streets_only=False, counts=True)
    city = city_coverage(slug)
    if city.new_streets() is None:
        get_matcher(slug).write_new_streets(start_times(z2))
    if not city.has_viewport_index():
        get_matcher(slug).write_viewport_index()
    # Districts only when already downloaded: fetching them is the page's call.
    if city.districts_path(9).exists():
        districts(slug, admin_level=9, geometry=True, streets_only=False)
    if z2.garmin_client.enabled:
        try:
            city_garmin_courses(slug, z2)
        except Exception as e:
            logger.warning("Garmin courses of %s not warmed: %s", slug, e)


def _return_freed_memory() -> None:
    """Hand freed heap back to the OS, which glibc otherwise keeps: releasing
    a city after matching frees its network, ~140 MB for a large city."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # not glibc (e.g. macOS)


def sync_all_cities(z2: Zone2, sport_types: tuple[str, ...] = ("Run",)) -> None:
    """Match new activities in every coverage city, one city at a time,
    skipping cities already syncing. Next to free when nothing is new."""
    for slug in known_cities():
        if not try_claim_sync(slug):
            continue
        run_city_sync(slug, z2, list(sport_types), keep_loaded=False)
    _return_freed_memory()
