"""One coverage city's persisted state under `{osm_dir}/{slug}_*`: the walked
stretches of every matched activity, their routes, the new streets, the
matched courses, the summary stats and the viewport index, with what is
derived from them. Nothing here loads the street network (writers that need
it are handed what they write), so status, route and viewport requests are
served without loading the city."""
from __future__ import annotations

import functools
import json
import os
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, mapping as shapely_mapping

from zone2.utils import summary_polyline_geometry

# Every file a city keeps under `{slug}_` besides its districts_{level}.parquet
ARTIFACTS = (
    'edges.parquet', 'connectors.parquet', 'boundary.parquet', 'meta.json', 'viewport.parquet',
    'walked.parquet', 'matched_activities.parquet', 'routes.parquet', 'new_streets.parquet',
    'stats.json', 'way_classes.parquet', 'far_activities.parquet', 'courses.parquet', 'covered_edges.parquet',
)

ActivityId = int | str
# mtimes of the walked stretches and matched activities files
StateVersion = tuple[int, int]
LatLon = tuple[float, float]
# south, west, north, east
BBox = tuple[float, float, float, float]
# A planned loop's new street: (row of the walkable network, metres)
NewWay = tuple[int, float]


class LineStringGeometry(TypedDict):
    type: Literal['LineString']
    coordinates: list[list[float]]


class MultiLineStringGeometry(TypedDict):
    type: Literal['MultiLineString']
    coordinates: list[list[list[float]]]


class EdgeProperties(TypedDict):
    name: str | None
    times: NotRequired[int]


class EdgeFeature(TypedDict):
    type: Literal['Feature']
    geometry: LineStringGeometry
    properties: EdgeProperties


class MatchRecord(TypedDict):
    """A row of the matched activities file: one per activity matched or attempted."""
    activity_id: ActivityId
    matched_at: str
    street_km: float
    coverage_pct: float


class CoverageStats(TypedDict):
    total_network_km: float
    traversed_km: float
    coverage_pct: float
    num_unique_streets: int


class CityStats(TypedDict):
    city_name: str
    num_matched_activities: int
    bbox: list[float]
    all: CoverageStats
    streets: CoverageStats


@dataclass(frozen=True, eq=False)
class WalkedState:
    # Every walked stretch (columns way, lo, hi, times), split where the
    # number of distinct activities that walked it changes
    stretches: pd.DataFrame
    # Metres walked of each way (indexed by way, 0 when unwalked), each metre
    # counted once however many runs covered it
    covered: np.ndarray


@dataclass(frozen=True, eq=False)
class _ViewportIndex:
    footer: pq.FileMetaData
    # [minx, miny, maxx, maxy] of each row group
    group_bounds: np.ndarray


@dataclass(eq=False)
class _CityCache:
    """What a city's files derive to, shared by every CityCoverage of the city
    until it is removed. Each entry carries the file version it was read at."""
    # Serializes state-file reads/writes so a background sync rewriting the
    # coverage parquet can't be observed mid-write by request threads.
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    walked: tuple[StateVersion, WalkedState] | None = None
    # Walked [lo, hi] of each walked way, merged
    walked_union: tuple[StateVersion, dict[int, list[tuple[float, float]]]] | None = None
    # Activities with a route, by routes file mtime
    route_ids: tuple[int, frozenset[int]] | None = None
    # By (index mtime, street map mtime); None when the index isn't current
    viewport: tuple[tuple[int, int], _ViewportIndex | None] | None = None


_caches: dict[tuple[Path, str], _CityCache] = {}
_caches_lock = threading.Lock()


def atomic_write(path: Path, data: pa.Table | pd.DataFrame | str | bytes, **parquet_kwargs) -> None:
    """Write `path` through a temp file and an atomic rename, so a crash
    mid-write (e.g. an OOM kill) never leaves a truncated file for readers.
    Tables and frames are written as parquet. The temp file is hidden, so a
    sweep of files by name prefix never sees one."""
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        if isinstance(data, pa.Table):
            pq.write_table(data, tmp, **parquet_kwargs)
        elif isinstance(data, pd.DataFrame):
            data.to_parquet(tmp, **parquet_kwargs)
        elif isinstance(data, str):
            tmp.write_text(data)
        else:
            tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Union of [lo, hi] intervals, sorted and non-overlapping."""
    merged: list[list[float]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def substrings(lines: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """shapely.ops.substring of many LineStrings at once, for distances within
    each line and start != end: the points at both distances with the vertices
    strictly between them, reversed when start > end."""
    start, end = np.asarray(start, dtype=np.float64), np.asarray(end, dtype=np.float64)
    xy, owner = shapely.get_coordinates(lines, return_index=True)
    count = np.bincount(owner, minlength=len(lines))
    first = np.r_[0, np.cumsum(count)[:-1]]
    last = first + count - 1
    # Each vertex's distance along its line, summed per line in substring's
    # order and arithmetic, so a cut on a vertex includes it exactly as it would
    d = np.diff(xy, axis=0)
    seg = np.r_[0.0, np.power(d[:, 0] ** 2 + d[:, 1] ** 2, 0.5)]   # seg[i]: vertex i-1 to i
    dist = np.zeros(len(xy))
    for n in np.unique(count[count > 1]).tolist():
        rows = first[count == n][:, None] + np.arange(1, n)
        dist[rows] = np.cumsum(seg[rows], axis=1)
    lo = np.clip(np.minimum(start, end), 0.0, dist[last])
    hi = np.clip(np.maximum(start, end), 0.0, dist[last])

    def vertex_at_or_before(t: np.ndarray) -> np.ndarray:
        """Per line, the last vertex at distance <= t (binary search within the line)."""
        left, right = first.copy(), last.copy()
        while (active := left < right).any():
            mid = (left + right + 1) // 2
            ok = dist[mid] <= t
            left = np.where(active & ok, mid, left)
            right = np.where(active & ~ok, mid - 1, right)
        return left

    i_lo, i_hi = vertex_at_or_before(lo), vertex_at_or_before(hi)
    # Interior vertices: distance strictly between lo and hi
    begin = i_lo + 1
    stop = np.where(dist[i_hi] == hi, i_hi, i_hi + 1)
    n_inner = np.maximum(stop - begin, 0)
    sizes = n_inner + 2
    out_first = np.r_[0, np.cumsum(sizes)[:-1]]
    coords = np.empty((int(sizes.sum()), 2))
    # GEOS interpolation, as substring's own
    coords[out_first] = shapely.get_coordinates(shapely.line_interpolate_point(lines, lo))
    coords[out_first + sizes - 1] = shapely.get_coordinates(shapely.line_interpolate_point(lines, hi))
    k = np.arange(int(n_inner.sum())) - np.repeat(np.r_[0, np.cumsum(n_inner)[:-1]], n_inner)
    coords[np.repeat(out_first + 1, n_inner) + k] = xy[np.repeat(begin, n_inner) + k]
    pieces = shapely.linestrings(coords, indices=np.repeat(np.arange(len(lines)), sizes))
    reverse = start > end
    pieces[reverse] = shapely.reverse(pieces[reverse])
    return pieces


def covered_at(covered: np.ndarray, ways: np.ndarray) -> np.ndarray:
    """covered[ways], 0 past the last walked way."""
    out = np.zeros(len(ways))
    inside = ways < len(covered)
    out[inside] = covered[ways[inside]]
    return out


def edge_feature(coords: list[list[float]], name: str | float | None, times: int | None = None) -> EdgeFeature:
    """GeoJSON feature of an edge served to the coverage map."""
    props: EdgeProperties = {"name": None if name is None or str(name) == "nan" else str(name)}
    if times is not None:
        props["times"] = int(times)
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": props}


def round_coords(obj: list | float) -> list | float:
    if isinstance(obj, (list, tuple)):
        return [round_coords(x) for x in obj]
    return round(obj, 5)


@functools.lru_cache(maxsize=8)
def to_wgs84(crs: str) -> Transformer:
    return Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)


@functools.lru_cache(maxsize=8)
def from_wgs84(crs: str) -> Transformer:
    return Transformer.from_crs('EPSG:4326', crs, always_xy=True)


def _compact_json(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _z_order(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Morton code of 16-bit cell coordinates: nearby cells get nearby codes."""
    def spread(n: np.ndarray) -> np.ndarray:
        n = n & 0xFFFF
        n = (n | (n << 8)) & 0x00FF00FF
        n = (n | (n << 4)) & 0x0F0F0F0F
        n = (n | (n << 2)) & 0x33333333
        return (n | (n << 1)) & 0x55555555
    return spread(x) | (spread(y) << 1)


def _stretches(walked: pd.DataFrame) -> pd.DataFrame:
    """Overlay the activities' walked intervals: each activity's intervals
    are merged per way, so the overlap depth is the number of activities."""
    n = len(walked)
    way = np.concatenate([walked['way'].to_numpy(dtype=np.int64)] * 2)
    pos = np.concatenate([walked['lo'].to_numpy(dtype=np.float64), walked['hi'].to_numpy(dtype=np.float64)])
    delta = np.r_[np.ones(n, np.int64), -np.ones(n, np.int64)]
    order = np.lexsort((delta, pos, way))   # by way, then position, ends before starts
    way, pos, delta = way[order], pos[order], delta[order]
    depth = np.cumsum(delta)                 # each way's deltas sum to 0
    keep = (way[:-1] == way[1:]) & (depth[:-1] > 0) & (pos[1:] > pos[:-1])
    way, lo, hi, times = way[:-1][keep], pos[:-1][keep], pos[1:][keep], depth[:-1][keep]
    if not len(way):
        return pd.DataFrame({'way': pd.Series(dtype=np.int64), 'lo': pd.Series(dtype=np.float64),
                             'hi': pd.Series(dtype=np.float64), 'times': pd.Series(dtype=np.int64)})
    # Join touching stretches walked by as many activities
    new = np.r_[True, (way[1:] != way[:-1]) | (times[1:] != times[:-1]) | (lo[1:] != hi[:-1])]
    starts = np.flatnonzero(new)
    ends = np.r_[starts[1:], len(way)] - 1
    return pd.DataFrame({'way': way[starts], 'lo': lo[starts], 'hi': hi[ends], 'times': times[starts]})


def _parquet_stamp(fp: Path, key: bytes) -> bytes | None:
    """The value of `key` in a parquet file's metadata; None when the file is missing."""
    if not fp.exists():
        return None
    return (pq.read_metadata(fp).metadata or {}).get(key)


class CityCoverage:
    """The coverage files of city `slug` in `osm_dir`. Cheap to construct: the
    caches derived from the files are shared per city, and `remove` drops
    them with the files."""
    # Viewport index: the undirected edges in EPSG:4326, ordered along a
    # Z-order curve of ~200 m cells and stored in small row groups, so the
    # row-group bounds statistics let a viewport query skip most of the city.
    # Each edge's feature is stored rendered up to its closing braces, so an
    # unwalked edge costs joined bytes, no per-coordinate work; partly walked
    # ones are cut from their projected geometry, stored alongside.
    VIEWPORT_CELL_DEG = 0.002
    VIEWPORT_ROW_GROUP = 1024
    VIEWPORT_INDEX_VERSION = b'5'   # bump when the index layout or rendering changes
    ROUTES_ROW_GROUP = 32
    # A street's unwalked remainder shorter than this isn't drawn as missing.
    MIN_MISSING_M = 5.0

    def __init__(self, osm_dir: Path, slug: str):
        self.osm_dir = osm_dir
        self.slug = slug

    @property
    def _cache(self) -> _CityCache:
        key = (self.osm_dir, self.slug)
        with _caches_lock:
            cache = _caches.get(key)
            if cache is None:
                cache = _caches[key] = _CityCache()
            return cache

    def path(self, name: str) -> Path:
        """Where the city's artifact `name` (e.g. 'edges.parquet') lives."""
        return self.osm_dir / f"{self.slug}_{name}"

    def districts_path(self, admin_level: int) -> Path:
        return self.path(f"districts_{admin_level}.parquet")

    def remove(self) -> int:
        """Delete every file of the city and forget what was derived from
        them. Returns the number of files removed."""
        with _caches_lock:
            _caches.pop((self.osm_dir, self.slug), None)
        # Explicit artifact names: a bare glob on the slug prefix could match
        # another city whose slug extends this one.
        paths = [self.path(name) for name in ARTIFACTS]
        paths += self.osm_dir.glob(f"{self.slug}_districts_*.parquet")
        removed = 0
        for fp in paths:
            if fp.exists():
                fp.unlink()
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # State stamps
    # ------------------------------------------------------------------

    def network_stamp(self) -> str:
        """Identifies the street map a walked `way` indexes into (a row of the
        walkable network built from the streets and connectors files)."""
        fps = (self.path('edges.parquet'), self.path('connectors.parquet'))
        return ','.join(str(fp.stat().st_mtime_ns) if fp.exists() else '0' for fp in fps)

    def state_is_current(self) -> bool:
        """Whether the walked stretches exist and index into the current street
        map. When not (a state from before walked stretches, or a re-downloaded
        map), every activity counts as unmatched and the next sync re-matches all."""
        return _parquet_stamp(self.path('walked.parquet'), b'network') == self.network_stamp().encode()

    def state_version(self) -> StateVersion:
        """Changes whenever a sync rewrites the city's persisted coverage state."""
        walked_fp, meta_fp = self.path('walked.parquet'), self.path('matched_activities.parquet')
        return (walked_fp.stat().st_mtime_ns if walked_fp.exists() else 0,
                meta_fp.stat().st_mtime_ns if meta_fp.exists() else 0)

    # ------------------------------------------------------------------
    # Matched activities
    # ------------------------------------------------------------------

    def matched_ids(self) -> set[ActivityId]:
        """Ids of activities already matched (or attempted) against the city."""
        meta_fp = self.path('matched_activities.parquet')
        with self._cache.state_lock:
            if not meta_fp.exists() or not self.state_is_current():
                return set()
            return set(pd.read_parquet(meta_fp, columns=['activity_id'])['activity_id'])

    def pending_activities(self, activities: pd.DataFrame) -> pd.DataFrame:
        """Activities still to match against the city: not in its state yet
        and with a summary route near the city. Reads only the small state and
        boundary files, so a sync with nothing new never loads the network or
        any GPS stream. The ones found away from the city are remembered (for
        that boundary), so each summary route is decoded once, not every sync."""
        todo = activities[~activities['id'].isin(self.matched_ids())]
        if todo.empty:
            return todo
        boundary_fp, far_fp = self.path('boundary.parquet'), self.path('far_activities.parquet')
        stamp = str(boundary_fp.stat().st_mtime_ns).encode()
        far: set[int] = set()
        if _parquet_stamp(far_fp, b'boundary') == stamp:
            far = set(pq.read_table(far_fp).column('activity_id').to_pylist())
        todo = todo[~todo['id'].isin(far)]
        if todo.empty:
            return todo
        boundary = gpd.read_parquet(boundary_fp)
        # ~200 m of slack: summary polylines are simplified versions of the GPS track
        near = boundary.to_crs('EPSG:4326').union_all().buffer(0.002)
        routes = todo['map'].map(summary_polyline_geometry)
        is_near = np.array([g is not None and g.intersects(near) for g in routes], dtype=bool)
        if (~is_near).any():
            ids = sorted(far | set(todo['id'][~is_near].astype('int64').tolist()))
            atomic_write(far_fp, pa.table({'activity_id': pa.array(ids, pa.int64())})
                         .replace_schema_metadata({'boundary': stamp}))
        return todo[is_near]

    def save_matches(self, walked: dict[ActivityId, pd.DataFrame], records: list[MatchRecord],
                     routes: gpd.GeoDataFrame) -> None:
        """Append matched activities to the persisted state: `walked`, the
        stretches (way, lo, hi) each matched activity walked, which replace a
        re-matched activity's; `records`, a row per activity matched or
        attempted; `routes`, the matched routes (activity_id, geometry) of the
        ones that have one. A state that isn't current (see state_is_current)
        is replaced rather than appended to."""
        walked_fp, meta_fp, routes_fp = (self.path('walked.parquet'), self.path('matched_activities.parquet'),
                                         self.path('routes.parquet'))
        current = self.state_is_current()
        walked_rows = [w.assign(activity_id=aid) for aid, w in walked.items() if len(w)]
        with self._cache.state_lock:
            if walked_rows or not current:
                new_walked = pd.concat(walked_rows, ignore_index=True) if walked_rows else pd.DataFrame(
                    {'way': pd.Series(dtype=np.int64), 'lo': pd.Series(dtype=np.float64),
                     'hi': pd.Series(dtype=np.float64), 'activity_id': pd.Series(dtype=np.int64)})
                if current:
                    old = pd.read_parquet(walked_fp)
                    new_walked = pd.concat([old[~old['activity_id'].isin(set(walked))], new_walked], ignore_index=True)
                table = pa.Table.from_pandas(new_walked[['activity_id', 'way', 'lo', 'hi']], preserve_index=False)
                atomic_write(walked_fp, table.replace_schema_metadata({'network': self.network_stamp().encode()}))
            if records:
                new_meta = pd.DataFrame(records)
                if current and meta_fp.exists():
                    new_meta = pd.concat([pd.read_parquet(meta_fp), new_meta], ignore_index=True)
                atomic_write(meta_fp, new_meta.drop_duplicates('activity_id', keep='last'))
            if len(routes):
                new_routes = routes.to_crs('EPSG:4326')
                if routes_fp.exists():
                    new_routes = pd.concat([gpd.read_parquet(routes_fp), new_routes], ignore_index=True)
                # Sorted in small row groups: an activity page's lookup (read_route) reads one
                atomic_write(routes_fp, new_routes.drop_duplicates('activity_id', keep='last').sort_values('activity_id'),
                             row_group_size=self.ROUTES_ROW_GROUP)

    def walked_state(self) -> WalkedState:
        """The city's coverage from its state file alone, reused until a sync rewrites it."""
        version = self.state_version()
        cache = self._cache
        cached = cache.walked
        if cached is None or cached[0] != version:
            walked = (pd.read_parquet(self.path('walked.parquet'), columns=['way', 'lo', 'hi'])
                      if self.state_is_current() else pd.DataFrame(columns=['way', 'lo', 'hi']))
            stretches = _stretches(walked)
            covered = np.bincount(stretches['way'].to_numpy(dtype=np.int64),
                                  weights=(stretches['hi'] - stretches['lo']).to_numpy(dtype=np.float64))
            cached = cache.walked = (version, WalkedState(stretches, covered))
        return cached[1]

    def _walked_union(self) -> dict[int, list[tuple[float, float]]]:
        version = self.state_version()
        cache = self._cache
        cached = cache.walked_union
        if cached is None or cached[0] != version:
            stretches = self.walked_state().stretches
            union: dict[int, list[tuple[float, float]]] = defaultdict(list)
            for way, lo, hi in zip(stretches['way'].tolist(), stretches['lo'].tolist(), stretches['hi'].tolist()):
                ivs = union[way]
                if ivs and lo <= ivs[-1][1]:
                    ivs[-1] = (ivs[-1][0], max(ivs[-1][1], hi))
                else:
                    ivs.append((lo, hi))
            cached = cache.walked_union = (version, dict(union))
        return cached[1]

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def read_route(self, activity_id: int) -> MultiLineStringGeometry | None:
        """The matched route of an activity as a GeoJSON MultiLineString
        (EPSG:4326, lines oriented in travel order), or None when the city
        hasn't matched it. Reads only the routes file."""
        routes_fp = self.path('routes.parquet')
        if activity_id not in self._route_ids():
            return None
        # The stored WKB straight from pyarrow: geopandas would also build the
        # file's CRS, most of a lookup's time, and routes are already EPSG:4326
        hit = pq.read_table(routes_fp, columns=['geometry'], filters=[('activity_id', '==', activity_id)])
        if hit.num_rows == 0:
            return None
        geom = shapely.from_wkb(hit.column('geometry')[0].as_py())
        lines = [geom] if isinstance(geom, LineString) else list(geom.geoms)
        return {'type': 'MultiLineString',
                'coordinates': [round_coords(shapely_mapping(ln)['coordinates']) for ln in lines]}

    def _route_ids(self) -> frozenset[int]:
        """Activities with a route, so a route lookup opens only the city that
        has it (the activity page asks every city)."""
        routes_fp = self.path('routes.parquet')
        try:
            mtime = routes_fp.stat().st_mtime_ns
        except FileNotFoundError:
            return frozenset()
        cache = self._cache
        cached = cache.route_ids
        if cached is None or cached[0] != mtime:
            ids = pq.read_table(routes_fp, columns=['activity_id']).column('activity_id').to_pylist()
            cached = cache.route_ids = (mtime, frozenset(ids))
        return cached[1]

    def usual_start(self) -> LatLon | None:
        """(lat, lon) where the city's matched runs most often start: the mean
        start in the ~300 m cell with the most. None before any match."""
        routes_fp = self.path('routes.parquet')
        if not routes_fp.exists():
            return None
        routes = gpd.read_parquet(routes_fp, columns=['geometry'])
        if routes.empty:
            return None
        # The first line's first point; a LineString is its own first part
        starts = shapely.get_coordinates(shapely.get_point(shapely.get_geometry(routes.geometry.values, 0), 0))
        cells = np.round(starts / [0.004, 0.0027])   # ~300 m at mid latitudes
        _, cell_of, counts = np.unique(cells, axis=0, return_inverse=True, return_counts=True)
        lon, lat = starts[cell_of.ravel() == counts.argmax()].mean(axis=0)
        return round(float(lat), 6), round(float(lon), 6)

    # ------------------------------------------------------------------
    # New streets, planned loops and courses
    # ------------------------------------------------------------------

    def write_new_streets(self, street_length: pd.Series, started: pd.Series) -> pd.DataFrame:
        """Per matched activity, the metres of street network it walked that no
        activity started earlier had: its new streets (`street_length`: metres
        of each street by way; `started`: activity id -> start time). They add
        up to the city's covered total. Persisted for the current coverage
        state, see new_streets."""
        walked = (pd.read_parquet(self.path('walked.parquet')) if self.state_is_current()
                  else pd.DataFrame(columns=['activity_id', 'way', 'lo', 'hi']))
        walked = walked[walked['way'].isin(street_length.index)]   # the street network, as the totals count it
        start = pd.to_datetime(walked['activity_id'].map(started), utc=True)
        # Unknown start times go last; ties by id
        start_ns = start.astype('int64').where(start.notna(), np.iinfo(np.int64).max).to_numpy()
        order = np.lexsort((walked['activity_id'].to_numpy(), start_ns, walked['way'].to_numpy()))
        new_m: dict[int, float] = defaultdict(float)
        union: list[tuple[float, float]] = []
        last_way = None
        for aid, way, lo, hi in zip(walked['activity_id'].to_numpy()[order].tolist(), walked['way'].to_numpy()[order].tolist(),
                                    walked['lo'].to_numpy()[order].tolist(), walked['hi'].to_numpy()[order].tolist()):
            if way != last_way:
                union, last_way = [], way
            hi = min(hi, float(street_length[way]))
            if hi <= lo:
                continue
            seen = sum(max(0.0, min(hi, b) - max(lo, a)) for a, b in union)
            new_m[int(aid)] += (hi - lo) - seen
            union = merge_intervals([*union, (lo, hi)])
        out = pd.DataFrame({'activity_id': sorted(self.matched_ids())})
        out['new_m'] = out['activity_id'].map(new_m).fillna(0.0)
        table = pa.Table.from_pandas(out, preserve_index=False).replace_schema_metadata(
            {'state': repr(self.state_version()).encode()})
        atomic_write(self.path('new_streets.parquet'), table)
        return out

    def new_streets(self) -> pd.DataFrame | None:
        """write_new_streets' result for the current coverage state, or None
        when it hasn't been written since the state last changed."""
        fp = self.path('new_streets.parquet')
        if _parquet_stamp(fp, b'state') != repr(self.state_version()).encode():
            return None
        return pd.read_parquet(fp)

    def new_km_now(self, new_ways: list[NewWay], network: str) -> float | None:
        """Km of a planned loop's new streets (StravaMapMatcher.plan_loop's
        (row, metres)) still not run; None when the city's street map changed
        since it was planned. Reads only the coverage state."""
        if network != self.network_stamp():
            return None
        if not new_ways:
            return 0.0
        rows, metres = (np.asarray(x) for x in zip(*new_ways))
        covered = self.walked_state().covered
        return round(float(np.maximum(0.0, metres - covered_at(covered, rows.astype(np.int64))).sum()) / 1000, 2)

    def street_km(self, streets: pd.DataFrame | None) -> tuple[float, float] | None:
        """(km not run yet, km) of street stretches (way, lo, hi) of the city,
        from its coverage state alone; None for None."""
        if streets is None:
            return None
        stretches = self.walked_state().stretches
        run = {way: list(zip(g['lo'], g['hi'])) for way, g in stretches[stretches['way'].isin(streets['way'])].groupby('way')}
        new_m = sum((hi - lo) - sum(max(0.0, min(hi, b) - max(lo, a)) for a, b in run.get(way, ()))
                    for way, lo, hi in streets[['way', 'lo', 'hi']].itertuples(index=False))
        return round(max(new_m, 0.0) / 1000, 2), round(float((streets['hi'] - streets['lo']).sum()) / 1000, 2)

    def course_streets(self) -> dict[str, pd.DataFrame | None]:
        """The street stretches of each course matched in the city (see
        StravaMapMatcher.match_courses), by course key, for its current street map."""
        fp = self.path('courses.parquet')
        if _parquet_stamp(fp, b'network') != self.network_stamp().encode():
            return {}
        rows = pd.read_parquet(fp)
        return {key: (None if (g['way'] < 0).all() else g[['way', 'lo', 'hi']].reset_index(drop=True))
                for key, g in rows.groupby('key', sort=False)}

    def write_courses(self, courses: dict[str, pd.DataFrame | None]) -> None:
        """Keep the street stretches of every course matched here (None: it
        doesn't match), for the current street map."""
        rows = pd.concat(
            [(g if g is not None else pd.DataFrame({'way': [-1], 'lo': [0.0], 'hi': [0.0]})).assign(key=key)
             for key, g in courses.items()], ignore_index=True)
        table = pa.Table.from_pandas(rows.astype({'way': np.int64, 'lo': np.float64, 'hi': np.float64})[['key', 'way', 'lo', 'hi']],
                                     preserve_index=False)
        atomic_write(self.path('courses.parquet'),
                     table.replace_schema_metadata({'network': self.network_stamp().encode()}))

    def way_classes(self, build: Callable[[], np.ndarray]) -> np.ndarray:
        """WayClass codes of the walkable network's rows, kept on disk per
        street map; `build` computes them when it changed."""
        fp = self.path('way_classes.parquet')
        stamp = self.network_stamp().encode()
        if _parquet_stamp(fp, b'network') == stamp:
            return pq.read_table(fp).column('code').to_numpy()
        codes = build()
        atomic_write(fp, pa.table({'code': pa.array(codes, pa.int8())}).replace_schema_metadata({'network': stamp}))
        return codes

    # ------------------------------------------------------------------
    # Summary stats
    # ------------------------------------------------------------------

    def write_stats(self, stats: CityStats) -> None:
        """Summary coverage stats, so list endpoints can report numbers without
        loading the city."""
        atomic_write(self.path('stats.json'), json.dumps(stats))

    def read_stats(self) -> CityStats | None:
        fp = self.path('stats.json')
        if not fp.exists():
            return None
        try:
            return json.loads(fp.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Viewport index
    # ------------------------------------------------------------------

    def _viewport_index(self) -> _ViewportIndex | None:
        """The current viewport index's footer and row-group bounds, read once
        per index file; None when it is missing, older than the street map or
        of another layout."""
        fp, edges_fp = self.path('viewport.parquet'), self.path('edges.parquet')
        if not fp.exists() or not edges_fp.exists():
            return None
        mtimes = (fp.stat().st_mtime_ns, edges_fp.stat().st_mtime_ns)
        cache = self._cache
        cached = cache.viewport
        if cached is None or cached[0] != mtimes:
            index = None
            footer = pq.read_metadata(fp)
            current = (footer.metadata or {}).get(b'viewport_index_version') == self.VIEWPORT_INDEX_VERSION
            if current and mtimes[0] >= mtimes[1]:
                names = footer.schema.to_arrow_schema().names
                bounds = np.empty((footer.num_row_groups, 4))
                for g in range(footer.num_row_groups):
                    group = footer.row_group(g)
                    for i, (col, use_min) in enumerate((('minx', True), ('miny', True), ('maxx', False), ('maxy', False))):
                        stats = group.column(names.index(col)).statistics
                        bound = (stats.min if use_min else stats.max) if stats is not None and stats.has_min_max else np.nan
                        # A group without usable statistics is always read
                        bounds[g, i] = bound if np.isfinite(bound) else (-np.inf if use_min else np.inf)
                index = _ViewportIndex(footer, bounds)
            cached = cache.viewport = (mtimes, index)
        return cached[1]

    def has_viewport_index(self) -> bool:
        """Whether the viewport index is current: this layout, newer than the street map."""
        return self._viewport_index() is not None

    def write_viewport_index(self, und: gpd.GeoDataFrame) -> None:
        """Write the viewport index (see viewport_missing_geojson) of the street
        segments `und` (columns way, name, street; projected geometry). It
        depends on the street map only, not on coverage, so it is built once per map."""
        projected = und.geometry.values
        geoms = und.geometry.to_crs('EPSG:4326').values
        bounds = shapely.bounds(geoms)
        cells = ((bounds[:, :2] + bounds[:, 2:]) / 2 - bounds[:, :2].min(axis=0)) // self.VIEWPORT_CELL_DEG
        order = np.argsort(_z_order(cells[:, 0].astype(np.uint32), cells[:, 1].astype(np.uint32)), kind='stable')
        geoms, names = geoms[order], und['name'].to_numpy()[order]
        xy, owner = shapely.get_coordinates(geoms, return_index=True)
        ends = np.cumsum(np.bincount(owner, minlength=len(geoms))).tolist()
        rounded = [[round(x, 6), round(y, 6)] for x, y in xy.tolist()]
        # Rendered as the viewport response renders it (FastAPI's compact JSON),
        # minus the closing '}}' so `times` can still be appended.
        features = [
            _compact_json(edge_feature(rounded[a:b], name))[:-2] if b > a else None
            for a, b, name in zip([0, *ends[:-1]], ends, names)
        ]
        table = pa.table({
            'order': pa.array(order, pa.int32()),
            'way': und['way'].to_numpy()[order],
            'street': und['street'].to_numpy(dtype=bool)[order],
            'minx': bounds[order, 0], 'miny': bounds[order, 1],
            'maxx': bounds[order, 2], 'maxy': bounds[order, 3],
            'geometry': pa.array(shapely.to_wkb(geoms), pa.binary()),
            'feature': pa.array([f.decode() if f is not None else None for f in features], pa.string()),
            # Walked offsets are metres along the projected geometry
            'geometry_m': pa.array(shapely.to_wkb(projected[order]), pa.binary()),
            'length_m': shapely.length(projected[order]),
            'name': pa.array(names, pa.string(), from_pandas=True),
        }).replace_schema_metadata({'viewport_index_version': self.VIEWPORT_INDEX_VERSION,
                                    'crs': und.crs.to_string()})
        atomic_write(self.path('viewport.parquet'), table, row_group_size=self.VIEWPORT_ROW_GROUP)

    def viewport_missing_geojson(self, bbox: BBox, streets_only: bool = False, with_counts: bool = False) -> bytes | None:
        """GeoJSON (compact bytes, EPSG:4326) of what is left to run around
        `bbox`: the street-network edges intersecting it, minus the stretches
        the matched routes walked (remainders under MIN_MISSING_M aren't
        drawn). Read from the viewport index without loading the city; None
        when the index isn't current (build it with write_viewport_index)."""
        index = self._viewport_index()
        if index is None:
            return None
        south, west, north, east = bbox
        group_bounds = index.group_bounds
        groups = np.flatnonzero((group_bounds[:, 0] <= east) & (group_bounds[:, 2] >= west)
                                & (group_bounds[:, 1] <= north) & (group_bounds[:, 3] >= south))
        near = pq.ParquetFile(self.path('viewport.parquet'), metadata=index.footer).read_row_groups(
            groups.tolist(), columns=['order', 'way', 'street', 'minx', 'miny', 'maxx', 'maxy', 'geometry',
                                      'feature', 'geometry_m', 'length_m', 'name'])
        minx, miny, maxx, maxy = (near.column(c).to_numpy() for c in ('minx', 'miny', 'maxx', 'maxy'))
        overlaps = (minx <= east) & (maxx >= west) & (miny <= north) & (maxy >= south)
        # An edge whose bounds lie inside the bbox intersects it; only the ones
        # crossing its border need their geometry decoded.
        hit = overlaps & (minx >= west) & (maxx <= east) & (miny >= south) & (maxy <= north)
        crossing = np.flatnonzero(overlaps & ~hit)
        geoms = shapely.from_wkb(near.column('geometry').take(crossing).to_numpy(zero_copy_only=False))
        hit[crossing] = shapely.intersects(geoms, shapely.box(west, south, east, north))
        hit &= near.column('feature').is_valid().to_numpy(zero_copy_only=False)
        if streets_only:
            hit &= near.column('street').to_numpy()

        covered = self.walked_state().covered
        way = near.column('way').to_numpy()
        length = near.column('length_m').to_numpy()
        walked_m = covered_at(covered, way)
        order = near.column('order').to_numpy()

        # Unwalked edges: their stored features, joined in edge order
        rows = np.flatnonzero(hit & (walked_m == 0))
        rows = rows[np.argsort(order[rows], kind='stable')]
        whole = near.column('feature').take(rows).combine_chunks()
        suffix = ',"times":0}}' if with_counts else '}}'
        whole = pc.binary_join_element_wise(whole, suffix, '')
        parts = [pc.binary_join(pa.ListArray.from_arrays(pa.array([0, len(rows)], pa.int32()), whole), ',')[0]
                 .as_buffer().to_pybytes()] if len(rows) else []

        # Partly walked edges: the remainders, cut from the projected geometry
        partial = np.flatnonzero(hit & (walked_m > 0) & (length - walked_m >= self.MIN_MISSING_M))
        partial = partial[np.argsort(order[partial], kind='stable')]
        if len(partial):
            union = self._walked_union()
            transform = to_wgs84(index.footer.metadata[b'crs'].decode())
            lines = shapely.from_wkb(near.column('geometry_m').take(partial).to_numpy(zero_copy_only=False))
            names = near.column('name').take(partial).to_pylist()
            # Every remainder of every edge first, then cut and reprojected in one go
            cut_line, cut_start, cut_end = [], [], []
            for k, (line, w) in enumerate(zip(lines, way[partial].tolist())):
                start = 0.0
                for lo, hi in [*union.get(w, []), (line.length, line.length)]:
                    if lo - start >= self.MIN_MISSING_M:
                        cut_line.append(k); cut_start.append(start); cut_end.append(lo)
                    start = max(start, hi)
            if cut_line:
                pieces = substrings(lines[cut_line], np.asarray(cut_start), np.asarray(cut_end))
                xy, owner = shapely.get_coordinates(pieces, return_index=True)
                xs, ys = transform.transform(xy[:, 0], xy[:, 1])
                rounded = [[round(x, 6), round(y, 6)] for x, y in zip(xs.tolist(), ys.tolist())]
                ends = np.cumsum(np.bincount(owner, minlength=len(pieces))).tolist()
                for k, a, b in zip(cut_line, [0, *ends[:-1]], ends):
                    parts.append(_compact_json(edge_feature(rounded[a:b], names[k], 0 if with_counts else None)))
        return b'{"type":"FeatureCollection","features":[' + b','.join(parts) + b']}'
