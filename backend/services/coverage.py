"""Coverage cities, shared by the coverage and planner routers and the Strava sync: the street
networks loaded in memory (a few at most, released when idle), the map-layer responses cached
per city, the coverage sync that matches new activities in each city, and the Garmin courses
starting in a city."""

import ctypes
import gc
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from fastapi import HTTPException, Response
import numpy as np
import pandas as pd
import shapely

from backend._serialize import PackedJSON, PackedJSONResponse
from backend.config import settings
from backend.services.garmin_courses import course_line, course_list
from zone2.core import Zone2
from zone2.map_matching import StravaMapMatcher
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

# Part of the map layers' cache version: bump when their content changes for
# the same coverage state, so responses persisted by older code aren't served.
LAYERS_FORMAT = 3

# Part of the Garmin courses' cache version: bump when their fields change
_COURSES_FORMAT = 2


def osm_dir() -> Path:
    return Path(settings.workdir) / "osm_maps"


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


def get_matcher(slug: str) -> StravaMapMatcher:
    cities = known_cities()
    if slug not in cities:
        raise HTTPException(status_code=404, detail=f"No coverage map for '{slug}'")
    # Built under the lock so concurrent requests never load the same city twice
    with _matchers_lock:
        if slug in _matchers:
            _matchers.move_to_end(slug)
            _matcher_used[slug] = time.monotonic()
            return _matchers[slug]
        matcher = StravaMapMatcher(city_name=cities[slug], workdir=Path(settings.workdir))
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


def _responses_dir() -> Path:
    return osm_dir() / "responses"


def _response_file(key: tuple, version: tuple) -> Path:
    """`{slug}__{key digest}__{version digest}.json.gz`; key[1] is the slug."""
    def digest(obj: tuple) -> str:
        return hashlib.sha1(repr(obj).encode()).hexdigest()[:16]
    return _responses_dir() / f"{key[1]}__{digest(key)}__{digest(version)}.json.gz"


def _persist_response(fp: Path, body: bytes) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_name(f".{fp.name}.tmp{os.getpid()}")
    tmp.write_bytes(body)
    os.replace(tmp, fp)
    # Older versions of the same layer
    key_prefix = fp.name.rsplit("__", 1)[0] + "__"
    for old in fp.parent.iterdir():
        if old.name.startswith(key_prefix) and old != fp:
            old.unlink(missing_ok=True)


def cached_json(key: tuple, version: tuple, build: Callable[[], dict | list]) -> Response:
    """The JSON response for `key` (`(layer, slug, *params)`) at `version`, built only when
    neither memory nor disk holds it."""
    with _responses_lock:
        hit = _responses.get(key)
        if hit is not None and hit[0] == version:
            _responses.move_to_end(key)
            return PackedJSONResponse(hit[1])
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
    return PackedJSONResponse(packed)


def state_version(slug: str, *extra: Path) -> tuple:
    return StravaMapMatcher.state_version_of(osm_dir(), slug) + tuple(
        fp.stat().st_mtime_ns if fp.exists() else 0 for fp in extra)


def read_stats_cache(slug: str) -> dict | None:
    fp = osm_dir() / f"{slug}_stats.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def delete_city(slug: str) -> int:
    """Unload the city and remove its map, its matched state and its cached layers from disk.
    Returns the number of files removed."""
    with _matchers_lock:
        _matchers.pop(slug, None)
    with _responses_lock:
        for key in [k for k in _responses if k[1] == slug]:
            del _responses[key]
    if _responses_dir().exists():
        for fp in _responses_dir().iterdir():
            if fp.name.startswith(f"{slug}__"):
                fp.unlink(missing_ok=True)
    # Explicit artifact names — a bare glob on the slug prefix could match
    # another city whose slug extends this one.
    paths = [StravaMapMatcher.artifact_path(osm_dir(), slug, name) for name in StravaMapMatcher.ARTIFACTS]
    paths += osm_dir().glob(f"{slug}_districts_*.parquet")
    removed = 0
    for fp in paths:
        if fp.exists():
            fp.unlink()
            removed += 1
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
            features.append(StravaMapMatcher.edge_feature(rounded[start:end], name, t))
    return {"type": "FeatureCollection", "features": features}


def walked_edges(slug: str, streets_only: bool, counts: bool) -> Response:
    """The stretches the city's matched routes walked, as GeoJSON."""
    def build():
        return edges_to_geojson(get_matcher(slug).walked_layer(streets_only=streets_only), include_times=counts)
    return cached_json(("edges", slug, True, streets_only, counts),
                       state_version(slug) + (LAYERS_FORMAT,), build)


def districts(slug: str, admin_level: int, geometry: bool, streets_only: bool) -> Response:
    """Coverage per district of the city at `admin_level`."""
    def build():
        return get_matcher(slug).coverage_by_district(
            admin_level=admin_level, include_geometry=geometry, streets_only=streets_only
        )
    districts_fp = StravaMapMatcher.artifact_path(osm_dir(), slug, f"districts_{admin_level}.parquet")
    return cached_json(("districts", slug, admin_level, geometry, streets_only),
                       state_version(slug, districts_fp) + (LAYERS_FORMAT,), build)


def city_garmin_courses(slug: str, z2: Zone2) -> Response:
    """The Garmin courses starting in the city, each with `city_km`, the km of
    streets of its part in the city, and `new_km`, those not run yet (both
    null when it doesn't match here). Kept until the coverage or the courses
    change; warmed after syncs."""
    south, west, north, east = (read_stats_cache(slug) or {}).get("bbox") or get_matcher(slug).city_bbox()
    courses = [c for c in course_list(z2)
               if c["start"][0] is not None and south <= c["start"][0] <= north and west <= c["start"][1] <= east]

    def build():
        # A course's id and distance identify its line; a changed course is matched again
        keys = {f"{c['course_id']}:{c['distance_km']}": c for c in courses}
        streets = StravaMapMatcher.course_streets_of(osm_dir(), slug)
        if any(key not in streets for key in keys):
            streets = get_matcher(slug).match_courses({
                key: (lambda c=c: [(lat, lon) for lon, lat in course_line(z2, c["course_id"])["coordinates"]])
                for key, c in keys.items()
            })
        out = []
        for key, c in keys.items():
            new_km, city_km = StravaMapMatcher.street_km_of(osm_dir(), slug, streets.get(key)) or (None, None)
            out.append({**c, "new_km": new_km, "city_km": city_km})
        return out
    version = state_version(slug) + (LAYERS_FORMAT, _COURSES_FORMAT,
                                     tuple((c["course_id"], c["name"], c["distance_km"]) for c in courses))
    return cached_json(("garmin-courses", slug), version, build)


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
        todo = StravaMapMatcher.pending_activities(osm_dir(), slug, activities)
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
    if StravaMapMatcher.new_streets_of(osm_dir(), slug) is None:
        get_matcher(slug).write_new_streets(start_times(z2))
    if not StravaMapMatcher.has_viewport_index(osm_dir(), slug):
        get_matcher(slug).write_viewport_index()
    # Districts only when already downloaded: fetching them is the page's call.
    if StravaMapMatcher.artifact_path(osm_dir(), slug, "districts_9.parquet").exists():
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
