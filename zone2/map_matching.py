"""Map matching: each activity matched to one continuous route on its city's
walkable network, and the coverage views that need that network loaded
(walked layers, totals, districts, hexes, areas, planned loops). The city's
persisted coverage state is CityCoverage's (zone2/city_coverage.py)."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon as ShapelyPolygon, mapping as shapely_mapping
from shapely.prepared import prep

from zone2.city_coverage import (
    ActivityId, CityCoverage, CityStats, CoverageStats, LatLon, LineStringGeometry, MatchRecord, NewWay, StateVersion,
    covered_at, from_wgs84, merge_intervals, round_coords, substrings, to_wgs84,
)
from zone2.route_matching import MatchedRoute, RouteMatcher
from zone2.route_planner import WAY_CLASSES, ExplorationPlanner, WayClass

logger = logging.getLogger(__name__)


def _import_osmnx():
    """osmnx set up for one-off city downloads. Imported lazily because it
    pulls in a heavy dependency stack (~140 MB RSS), never needed to serve a
    city that is already on disk."""
    import osmnx as ox
    # Each city is downloaded once; the on-disk response cache would only
    # keep tens of MB of Overpass JSON around.
    ox.settings.use_cache = False
    return ox


def city_slug(city_name: str) -> str:
    """The name a city's files are kept under."""
    return city_name.replace(', ', '_').lower()


class WayRole(StrEnum):
    # The street network coverage is counted on.
    STREET = 'street'
    # Walkable but never counted (sidewalks, crossings, steps, service
    # roads...): the matcher routes through them so the network stays
    # connected wherever a runner can actually pass, and the coverage map
    # draws them where they were run.
    CONNECTOR = 'connector'


class MatchQuality(TypedDict):
    num_points: int
    num_outliers: int
    num_breaks: int
    route_km: float
    gps_km: float
    pct_on_connectors: float
    # Distinct street metres walked (laps count once)
    street_km: float
    # Share of the (thinned) in-city points the route explains
    coverage_pct: float


@dataclass
class MatchResult:
    """Result of map matching a single activity."""
    activity_id: ActivityId
    original_geometry: LineString       # GPS track (projected CRS)
    # The matched route in travel order, one row per walked piece of a
    # segment (geometry oriented in the direction of travel); `street` is
    # False for connector pieces.
    route: gpd.GeoDataFrame
    # What the activity covered: the metres [lo, hi] it walked along each
    # way's geometry (`way` is a row of the walkable network), merged per way.
    walked: pd.DataFrame
    outliers: np.ndarray                # GPS observations left out by the matcher (x, y)
    quality: MatchQuality


class ScopedStats(TypedDict):
    total_km: float
    covered_km: float
    coverage_pct: float
    num_streets: int
    num_covered_streets: int


class PolygonGeometry(TypedDict):
    type: str
    coordinates: list


class PolygonCoverage(ScopedStats):
    name: str
    # [south, west, north, east] for map fitBounds
    bbox: list[float]
    geometry: NotRequired[PolygonGeometry]


class LoopProperties(TypedDict):
    length_km: float
    new_km: float
    start: NotRequired[list[float]]
    plan_id: NotRequired[str]


class LoopFeature(TypedDict):
    type: Literal['Feature']
    geometry: LineStringGeometry
    properties: LoopProperties


class StravaMapMatcher:
    # Street classes that count as runnable: the street network coverage is
    # counted on.
    RUNNABLE_HIGHWAYS = {
        'residential', 'living_street', 'pedestrian',
        'primary', 'secondary', 'tertiary',
        'primary_link', 'secondary_link', 'tertiary_link',
        'unclassified', 'path', 'track', 'cycleway',
    }
    # Footway subtypes mapped as separate ways alongside a street. They are
    # connectors, so a street with two mapped sidewalks counts once.
    EXCLUDED_FOOTWAY_TYPES = {'sidewalk', 'crossing', 'traffic_island', 'access_aisle'}
    # Classes that never count for coverage but that runners pass through;
    # together with excluded footways they are the connectors.
    CONNECTOR_HIGHWAYS = {'footway', 'steps', 'service', 'trunk', 'trunk_link', 'bridleway', 'road'}
    EXCLUDED_ACCESS = {'private', 'no'}
    # Pedestrian streets are commonly `access=no` + `foot=yes`, so an explicit
    # foot permission overrides EXCLUDED_ACCESS.
    FOOT_ALLOWED = {'yes', 'designated', 'permissive'}
    # `foot=no` on a surface road usually means its sidewalk is mapped as a
    # separate way, so the road stays a street. Only in a tunnel does it mean
    # there is nowhere to run.
    TUNNEL_TAGS = {'yes', 'building_passage'}
    # Runnable classes that are paths/trails rather than streets. Still part
    # of the matching target (running them is recorded), but excluded from
    # the denominator in the streets-only coverage view.
    PATH_HIGHWAYS = {'footway', 'path', 'track', 'steps', 'cycleway', 'bridleway'}
    # Road classes a planned run can avoid (see way_classes)
    MAIN_ROAD_HIGHWAYS = {'primary', 'secondary', 'tertiary', 'primary_link', 'secondary_link', 'tertiary_link',
                          'trunk', 'trunk_link'}
    # A sidewalk takes the class of the street within this distance
    SIDEWALK_STREET_M = 30.0
    # Fraction of the city area the mapped district polygons must cover to be
    # treated as a real subdivision. Below this the city isn't administratively
    # mapped in OSM (e.g. a small city) and we fall back to a single whole-city district.
    MIN_DISTRICT_COVERAGE = 0.4
    # ~0.74 km² cells: finer than most neighbourhoods, coarse enough to read at city zoom
    HEX_RESOLUTION = 8
    # Per-segment attributes persisted per city (streets / connectors); the
    # rest of the OSM tags only decide the way's role at download.
    EDGE_COLUMNS = ('u', 'v', 'key', 'highway', 'name', 'length', 'geometry')
    CONNECTOR_COLUMNS = ('u', 'v', 'highway', 'footway', 'length', 'geometry')
    WAY_TAGS = ('highway', 'name', 'footway', 'access', 'foot', 'tunnel')

    # Matching. A connector costs this much extra per observation
    # (log units), so the matcher takes the street when it is about as close
    # and the connector when the runner clearly used it.
    CONNECTOR_COST = 0.7
    # An activity with more than OFF_NETWORK_SHARE of its points farther than
    # OFF_NETWORK_M from any walkable way isn't a street run (e.g. intervals
    # on an athletics track) and would only count the streets around it.
    OFF_NETWORK_M = 25.0
    OFF_NETWORK_SHARE = 0.5
    # Coverage is what the matched routes walked: the metres of each street
    # covered, each counted once however many runs covered it. Pieces shorter
    # than this are junction rounding, not running.
    MIN_WALKED_M = 0.5
    # The segment tally counts a segment once at least this share of it was walked.
    SEGMENT_COUNT_FRACTION = 0.5

    def __init__(self, city_name: str, workdir: Path, force_reload: bool = False,
                 on_progress: Callable[[str], None] | None = None):
        """
        Initialize the StravaMapMatcher with a specified city name.

        :param city_name: Name of the city to load the street network for.
        :param on_progress: Called with a human-readable stage description at
            each phase of a first-time city download.
        """
        self.city_name = city_name
        self.slug = city_slug(city_name)
        self.workdir = workdir / "osm_maps"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.coverage = CityCoverage(self.workdir, self.slug)
        self._on_progress = on_progress or (lambda stage: None)

        self._edges_gdf: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._city_boundary: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._und_gdf: gpd.GeoDataFrame | None = None
        # Built on first match and released after a sync: the walkable network
        # (streets then connectors) and its matcher are only needed to match.
        self._walkable: gpd.GeoDataFrame | None = None
        self._matcher: RouteMatcher | None = None
        self._planner: ExplorationPlanner | None = None
        # Coverage derived from the persisted state, reused until a sync rewrites it
        self._flagged_cache: dict[bool, tuple[StateVersion, gpd.GeoDataFrame]] = {}
        self._layer_cache: dict[bool, tuple[StateVersion, gpd.GeoDataFrame]] = {}

        self._load_map(force_reload=force_reload)
        logger.info("Map for %s loaded with %d street segments", self.city_name, len(self._edges_gdf))

    @staticmethod
    def _as_tags(val) -> set[str]:
        """Normalize an OSM tag value (str, list, or gpkg-roundtripped
        '[a, b]' string, or NaN) to a set of strings."""
        if isinstance(val, (list, tuple)):
            return {str(v) for v in val}
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return set()
        s = str(val)
        if s.startswith('['):
            return {c.strip(" '\"") for c in s.strip('[]').split(',')}
        return {s}

    def _way_roles(self, ways: pd.DataFrame) -> list[WayRole | None]:
        """Role of each OSM way (one row of tags each), None for ways runners
        can't use.

        Streets are the network coverage is counted on.
        Excluded from streets: sidewalks and crossings mapped as separate ways,
        service roads, steps and trunk roads, which become connectors when
        passable; motorways, restricted-access ways without a foot permission
        and road tunnels closed to pedestrians are dropped.
        """
        def role(highway, footway, access, foot, tunnel) -> WayRole | None:
            foot_tags = self._as_tags(foot)
            if self._as_tags(access) & self.EXCLUDED_ACCESS and not foot_tags & self.FOOT_ALLOWED:
                return None
            if 'no' in foot_tags and self._as_tags(tunnel) & self.TUNNEL_TAGS:
                return None
            hw = self._as_tags(highway)
            if hw & self.RUNNABLE_HIGHWAYS:
                return WayRole.STREET
            if 'footway' in hw and not self._as_tags(footway) & self.EXCLUDED_FOOTWAY_TYPES:
                return WayRole.STREET
            if hw & self.CONNECTOR_HIGHWAYS and 'no' not in foot_tags:
                return WayRole.CONNECTOR
            return None

        def col(name: str) -> pd.Series:
            return ways[name] if name in ways.columns else pd.Series(None, index=ways.index)

        return [role(h, f, a, ft, t) for h, f, a, ft, t in
                zip(ways['highway'], col('footway'), col('access'), col('foot'), col('tunnel'))]

    def _load_map(self, force_reload: bool = False):
        """Load the city's street network, downloading it on first use.

        The durable per-city artifacts are small parquets: street segments
        (the coverage network), connector segments (walkable but never
        counted, read for matching and drawing) and the city boundary.
        """
        edges_fp, connectors_fp = self.coverage.path('edges.parquet'), self.coverage.path('connectors.parquet')
        boundary_fp, meta_fp = self.coverage.path('boundary.parquet'), self.coverage.path('meta.json')

        if not force_reload and edges_fp.exists() and boundary_fp.exists():
            edges = gpd.read_parquet(edges_fp, columns=list(self.EDGE_COLUMNS))
            self._edges_gdf = self._one_row_per_segment(edges).set_index(['u', 'v', 'key'])
            self._city_boundary = gpd.read_parquet(boundary_fp)
            if not meta_fp.exists():
                meta_fp.write_text(json.dumps({'city_name': self.city_name}))
            return

        logger.info("Downloading map for %s from OSM...", self.city_name)
        ox = _import_osmnx()
        from osmnx import _overpass
        # Geocode once and download within that polygon, so the network and the
        # boundary can never come from different geocoder results.
        self._on_progress('resolving the city with OSM')
        city_boundary = ox.geocode_to_gdf(self.city_name)
        display_name = str(city_boundary.iloc[0].get('display_name', self.city_name))
        logger.info("Geocoded %s to %s", self.city_name, display_name)
        polygon = city_boundary.union_all()
        utm_crs = ox.projection.project_gdf(city_boundary).crs
        city_boundary_gdf = city_boundary.to_crs(utm_crs)

        self._on_progress(f'downloading the street network of {display_name}')
        # osmnx's own Overpass client (query subdivision, rate-limit pauses,
        # retries on busy servers); private, so it is pinned by poetry.lock.
        responses = _overpass._download_overpass_network(polygon, 'all', self._overpass_filters())
        self._on_progress('building street segments')
        segments = self._segments_from_overpass(responses, polygon).to_crs(utm_crs)
        # Length of the full shape; the 2 m simplification below is well
        # under GPS accuracy but still shortens curves slightly.
        segments['length'] = segments.length
        segments['geometry'] = segments.geometry.simplify(2.0)
        is_street = (segments['role'] == WayRole.STREET).to_numpy()
        streets = segments[is_street].copy()
        lo, hi = np.minimum(streets['u'], streets['v']), np.maximum(streets['u'], streets['v'])
        streets['key'] = streets.groupby([lo, hi]).cumcount()
        streets = streets[list(self.EDGE_COLUMNS)]
        connectors = segments[~is_street][list(self.CONNECTOR_COLUMNS)]

        self._on_progress('saving the city map')
        streets.to_parquet(edges_fp)
        connectors.to_parquet(connectors_fp)
        city_boundary_gdf.to_parquet(boundary_fp)
        # Only after a successful download — a failed add must leave no trace
        # that _known_cities could mistake for a real city.
        if not meta_fp.exists():
            meta_fp.write_text(json.dumps({'city_name': self.city_name}))
        logger.info("Map for %s saved to %s (%d street and %d connector segments)",
                    self.city_name, self.workdir, len(streets), len(connectors))

        self._edges_gdf = streets.set_index(['u', 'v', 'key'])
        self._city_boundary = city_boundary_gdf
        self._und_gdf = self._walkable = self._matcher = self._planner = None

    def _overpass_filters(self) -> list[str]:
        """Overpass way filter for every class that can be a street or a
        connector; access, foot and tunnel rules are applied in _way_roles."""
        classes = '|'.join(sorted(self.RUNNABLE_HIGHWAYS | self.CONNECTOR_HIGHWAYS))
        return [f'["highway"~"^({classes})$"]["area"!~"yes"]']

    def _segments_from_overpass(self, responses, polygon) -> gpd.GeoDataFrame:
        """Street and connector segments (EPSG:4326) from raw Overpass responses.

        Built directly rather than through an osmnx graph, whose per-node
        Python objects need ~3 GB for a large city. Ways are cut at
        every node another kept way also uses (and at their ends), so streets
        and connectors join wherever they meet; segments with an end outside
        the city are dropped.
        """
        coords: dict[int, tuple[float, float]] = {}
        ways: list[list[int]] = []
        tags: list[dict] = []
        for response in responses:
            for element in response['elements']:
                if element['type'] == 'node':
                    coords[element['id']] = (element['lon'], element['lat'])
                elif element['type'] == 'way' and len(element['nodes']) >= 2:
                    ways.append(element['nodes'])
                    way_tags = element.get('tags', {})
                    tags.append({t: way_tags.get(t) for t in self.WAY_TAGS})
        if not ways:
            raise ValueError(f"No streets found in OSM for {self.city_name}")
        roles = self._way_roles(pd.DataFrame(tags))
        kept = [(nodes, t, r) for nodes, t, r in zip(ways, tags, roles) if r is not None]

        uses: Counter[int] = Counter()
        for nodes, _, _ in kept:
            uses.update(nodes)
            uses.update((nodes[0], nodes[-1]))
        node_ids = np.fromiter(uses, dtype=np.int64, count=len(uses))
        lon, lat = np.array([coords[n] for n in node_ids.tolist()]).T
        inside = dict(zip(node_ids.tolist(), shapely.contains_xy(polygon, lon, lat).tolist()))

        rows = []
        for nodes, way_tags, role in kept:
            start = 0
            for i in range(1, len(nodes)):
                if uses[nodes[i]] < 2 and i < len(nodes) - 1:
                    continue
                u, v = nodes[start], nodes[i]
                if inside[u] and inside[v]:
                    rows.append((u, v, str(role), way_tags['highway'], way_tags['name'], way_tags['footway'],
                                 LineString([coords[n] for n in nodes[start:i + 1]])))
                start = i
        df = pd.DataFrame(rows, columns=['u', 'v', 'role', 'highway', 'name', 'footway', 'geometry'])
        return gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')

    @staticmethod
    def _one_row_per_segment(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Keep one row per undirected segment: networks downloaded through an
        osmnx graph hold two-way streets as (u, v, k) and (v, u, k) with the
        same geometry reversed. Length is part of the identity because two
        distinct one-way ways between the same nodes can share (u, v, k) in
        opposite directions."""
        lo = np.minimum(edges['u'], edges['v'])
        hi = np.maximum(edges['u'], edges['v'])
        ident = pd.DataFrame({'lo': lo, 'hi': hi, 'key': edges['key'], 'len': edges['length'].round(1)})
        return edges[~ident.duplicated().to_numpy()]

    def _split_path_by_coverage(self, geom: LineString) -> list[list[tuple]]:
        """Clip a LineString to the city boundary and return in-coverage segments.

        Walks the linestring vertex-by-vertex to avoid planar noding issues
        that `split()` / `intersection()` cause with self-intersecting loops.

        1. If the geom is fully contained → return it directly (fast path).
        2. Otherwise, classify each vertex as inside/outside the boundary,
           group contiguous inside-runs into segments.
        3. Further split each segment at large inter-point gaps.

        Returns a list of sub-paths (each a list of coordinate tuples).
        Only segments with >= 2 points are returned.
        """
        boundary_geom = self._city_boundary.union_all()

        # Fast path: fully inside → skip point-by-point test
        if boundary_geom.contains(geom):
            return self._split_by_distance(list(geom.coords))

        # Walk vertices and split into contiguous inside-runs
        prepared_boundary = prep(boundary_geom)
        coords = list(geom.coords)

        segments: list[list[tuple]] = []
        current: list[tuple] = []

        for coord in coords:
            if prepared_boundary.contains(Point(coord)):
                current.append(coord)
            else:
                if len(current) >= 2:
                    segments.append(current)
                current = []

        if len(current) >= 2:
            segments.append(current)

        # Further split each segment at large inter-point gaps
        result: list[list[tuple]] = []
        for seg in segments:
            result.extend(self._split_by_distance(seg))

        return result

    # Target spacing (m) for GPS points fed to the matcher. Dense streams
    # (~3 m at 1 Hz) are thinned to this so the Viterbi stays cheap.
    THIN_SPACING_M: float = 20.0

    @staticmethod
    def _thin(pts: np.ndarray, min_m: float) -> np.ndarray:
        """Decimate an (n, 2) projected-metre array to ~1 point per min_m,
        measured from the last kept point. First and last are always kept."""
        if len(pts) <= 2:
            return pts
        min2 = min_m * min_m
        keep = [0]
        lx, ly = pts[0]
        for i in range(1, len(pts) - 1):
            dx, dy = pts[i][0] - lx, pts[i][1] - ly
            if dx * dx + dy * dy >= min2:
                keep.append(i)
                lx, ly = pts[i]
        keep.append(len(pts) - 1)
        return pts[keep]

    @staticmethod
    def _split_by_distance(coords: list[tuple], max_gap_m: float = 250.0) -> list[list[tuple]]:
        """Split a coordinate list where the recording has no points for
        more than max_gap_m, then thin each part to ~THIN_SPACING_M spacing.

        Across a gap that long there is no evidence of which streets were
        run, so the parts are matched separately rather than bridged.
        """
        n = len(coords)
        if n < 2:
            return []

        a = np.asarray(coords)           # shape (n, 2), projected metres
        d = np.diff(a, axis=0)                             # shape (n-1, 2)
        dist2 = (d * d).sum(axis=1)
        cuts = np.nonzero(dist2 > (max_gap_m * max_gap_m))[0] + 1

        parts = np.split(a, cuts)
        out: list[list[tuple]] = []
        for p in parts:
            if len(p) < 2:
                continue
            thinned = StravaMapMatcher._thin(p, StravaMapMatcher.THIN_SPACING_M)
            if len(thinned) >= 2:
                out.append([tuple(x) for x in thinned])
        return out

    def _walkable_network(self) -> gpd.GeoDataFrame:
        """Streets followed by connectors, the network the matcher routes on.
        `street` flags the rows coverage counts."""
        if self._walkable is None:
            streets = self._edges_gdf.reset_index()
            connectors_fp = self.coverage.path('connectors.parquet')
            if connectors_fp.exists():
                connectors = gpd.read_parquet(connectors_fp)
            else:
                logger.warning("No connectors for %s; matching on streets only (re-download the city)",
                               self.city_name)
                connectors = gpd.GeoDataFrame(columns=list(self.CONNECTOR_COLUMNS), geometry='geometry',
                                              crs=streets.crs)
            self._walkable = gpd.GeoDataFrame(
                {
                    'u': np.concatenate([streets['u'].to_numpy(), connectors['u'].to_numpy()]).astype(np.int64),
                    'v': np.concatenate([streets['v'].to_numpy(), connectors['v'].to_numpy()]).astype(np.int64),
                    'street': np.r_[np.ones(len(streets), bool), np.zeros(len(connectors), bool)],
                    'sidewalk': np.r_[np.zeros(len(streets), bool),
                                      connectors['footway'].astype(str).eq('sidewalk').to_numpy()],
                    'name': np.concatenate([streets['name'].to_numpy(), np.full(len(connectors), None)]),
                    'highway': np.concatenate([streets['highway'].to_numpy(), connectors['highway'].to_numpy()]),
                },
                geometry=np.concatenate([streets.geometry.to_numpy(), connectors.geometry.to_numpy()]),
                crs=streets.crs,
            )
        return self._walkable

    def _route_matcher(self) -> RouteMatcher:
        if self._matcher is None:
            w = self._walkable_network()
            self._matcher = RouteMatcher(w['u'].to_numpy(), w['v'].to_numpy(), w.geometry.to_numpy(),
                                         penalty=np.where(w['street'].to_numpy(), 0.0, self.CONNECTOR_COST))
        return self._matcher

    def match(self, activities: gpd.GeoDataFrame) -> dict[ActivityId, MatchResult]:
        """Match each activity to one continuous route on the walkable
        network and record the stretches of each way it walked.

        Activities outside the city, or whose points mostly lie off any
        walkable way, are left out of the result.
        """
        rm = self._route_matcher()
        walk = self._walkable_network()
        utm_crs = self._edges_gdf.crs
        acts = activities.to_crs(utm_crs)
        acts = acts[acts.intersects(self._city_boundary.union_all())]
        results: dict[ActivityId, MatchResult] = {}
        for idx, row in acts.iterrows():
            geom = row.geometry
            if not isinstance(geom, LineString) or geom.is_empty:
                continue
            activity_id = row.get('id', idx)
            parts = [np.asarray(p) for p in self._split_path_by_coverage(geom)]
            if not parts:
                continue
            points = np.vstack(parts)
            if rm.far_share(points, self.OFF_NETWORK_M) > self.OFF_NETWORK_SHARE:
                logger.info("Activity %s: mostly off the street network, not matched", activity_id)
                continue
            routes = [(p, rm.match(p)) for p in parts]
            results[activity_id] = self._walked_result(activity_id, geom, routes, walk, rm)
            q = results[activity_id].quality
            logger.info("Activity %s: route %s km vs GPS %s km, %s km on streets, %d outliers, %d breaks",
                        activity_id, q['route_km'], q['gps_km'], q['street_km'],
                        q['num_outliers'], q['num_breaks'])
        return results

    def _walked_result(self, activity_id: ActivityId, geom: LineString, routes: list[tuple[np.ndarray, MatchedRoute]],
                       walk: gpd.GeoDataFrame, rm: RouteMatcher) -> MatchResult:
        street = walk['street'].to_numpy()
        by_way: dict[int, list[tuple[float, float]]] = defaultdict(list)
        piece_rows: list[tuple[int, float, float]] = []
        for _, route in routes:
            for e, a, b in route.pieces:
                if abs(b - a) < self.MIN_WALKED_M:
                    continue
                by_way[e].append((min(a, b), max(a, b)))
                piece_rows.append((e, a, b))
        ways, starts, ends = (np.asarray(c) for c in zip(*piece_rows)) if piece_rows else (np.zeros(0, np.int64),) * 3
        pieces = list(zip(substrings(rm.geoms[ways], starts, ends) if piece_rows else [], street[ways].tolist()))
        walked = pd.DataFrame(
            [(e, lo, hi) for e, ivs in by_way.items() for lo, hi in merge_intervals(ivs)],
            columns=['way', 'lo', 'hi'],
        ).astype({'way': np.int64, 'lo': np.float64, 'hi': np.float64})

        route_gdf = gpd.GeoDataFrame({'street': [s for _, s in pieces]},
                                     geometry=[ln for ln, _ in pieces], crs=walk.crs)
        route_m = sum(r.length for _, r in routes)
        gps_m = sum(float(np.hypot(*np.diff(p, axis=0).T).sum()) for p, _ in routes)
        on_connectors = sum(ln.length for ln, s in pieces if not s)
        on_streets = float((walked['hi'] - walked['lo'])[street[walked['way'].to_numpy()]].sum()) if len(walked) else 0.0
        n_points = sum(len(p) for p, _ in routes)
        outliers = np.array([p[t] for p, r in routes for t in r.outliers]).reshape(-1, 2)
        quality: MatchQuality = {
            'num_points': n_points,
            'num_outliers': len(outliers),
            'num_breaks': sum(len(r.breaks) for _, r in routes),
            'route_km': round(route_m / 1000, 2),
            'gps_km': round(gps_m / 1000, 2),
            'pct_on_connectors': round(100 * on_connectors / route_m, 1) if route_m else 0.0,
            'street_km': round(on_streets / 1000, 2),
            'coverage_pct': round(100 * (1 - len(outliers) / n_points), 1) if n_points else 0.0,
        }
        return MatchResult(activity_id=activity_id, original_geometry=geom, route=route_gdf,
                           walked=walked, outliers=outliers, quality=quality)

    # ------------------------------------------------------------------
    # Persisting matches
    # ------------------------------------------------------------------

    def save_match_state(
        self,
        match_results: dict[ActivityId, MatchResult],
        attempted_ids: list[ActivityId] | None = None,
    ) -> None:
        """Persist the walked stretches and routes of matched activities (see
        CityCoverage.save_matches). Activities attempted but not matched are
        recorded with nothing walked so incremental runs don't retry them forever.
        """
        records: list[MatchRecord] = [
            {'activity_id': aid, 'matched_at': pd.Timestamp.utcnow().isoformat(),
             'street_km': result.quality['street_km'], 'coverage_pct': result.quality['coverage_pct']}
            for aid, result in match_results.items()
        ]
        records += [
            {'activity_id': aid, 'matched_at': pd.Timestamp.utcnow().isoformat(), 'street_km': 0.0, 'coverage_pct': 0.0}
            for aid in (attempted_ids or []) if aid not in match_results
        ]
        routed = [(aid, result.route) for aid, result in match_results.items() if not result.route.empty]
        routes = gpd.GeoDataFrame({'activity_id': [aid for aid, _ in routed]},
                                  geometry=[self._route_lines(route) for _, route in routed], crs=self._edges_gdf.crs)
        self.coverage.save_matches({aid: result.walked for aid, result in match_results.items()}, records, routes)

    @staticmethod
    def _route_lines(route: gpd.GeoDataFrame) -> MultiLineString:
        """The route's pieces joined into continuous lines in travel order (a
        new line only where a gap or break separates them), each oriented in
        the direction of travel."""
        lines: list[list[tuple[float, float]]] = []
        for geom in route.geometry:
            coords = list(geom.coords)
            if lines and Point(lines[-1][-1]).distance(Point(coords[0])) < 1.0:
                lines[-1].extend(coords[1:])
            else:
                lines.append(coords)
        return MultiLineString([ln for ln in lines if len(ln) >= 2]).simplify(1.0)

    def match_incremental(self, activities: gpd.GeoDataFrame) -> CoverageStats:
        """Match only activities not yet in the persisted state, then return
        the updated coverage stats. This is the entry point for sync flows:
        the backfill cost is paid once, each new activity costs one match.
        """
        done = self.coverage.matched_ids()
        todo = activities[~activities['id'].isin(done)] if 'id' in activities.columns else activities
        if not todo.empty:
            # Only attempt activities that touch this city at all
            in_city = gpd.sjoin(
                todo.to_crs(self._city_boundary.crs), self._city_boundary,
                predicate='intersects', how='inner',
            )
            todo = todo[todo['id'].isin(set(in_city['id']))]
        if not todo.empty:
            logger.info("Matching %d new activities for %s", len(todo), self.city_name)
            results = self.match(todo)
            self.save_match_state(results, attempted_ids=list(todo['id']))
        stats = self.coverage_stats_from_state()
        self.write_stats_cache()
        return stats

    def release_matching(self) -> None:
        """Drop what only matching and planning need (the walkable network and
        its routing graphs, a few hundred MB for a large city); rebuilt on use."""
        self._walkable = self._matcher = self._planner = None

    def write_stats_cache(self) -> None:
        """Persist summary coverage stats so list endpoints can report numbers
        without constructing a matcher (which would hold ~140 MB per city).
        Written after every sync and on city add."""
        stats: CityStats = {
            'city_name': self.city_name,
            'num_matched_activities': len(self.coverage.matched_ids()),
            'bbox': self.city_bbox(),
            'all': self.coverage_stats_from_state(streets_only=False),
            'streets': self.coverage_stats_from_state(streets_only=True),
        }
        self.coverage.write_stats(stats)

    def write_new_streets(self, started: pd.Series) -> pd.DataFrame:
        """Each matched activity's new streets (see CityCoverage.write_new_streets)."""
        und = self._undirected_gdf()
        return self.coverage.write_new_streets(pd.Series(und['length'].to_numpy(), index=und['way'].to_numpy()), started)

    def write_viewport_index(self) -> None:
        """Write the city's viewport index (see CityCoverage.viewport_missing_geojson)."""
        self.coverage.write_viewport_index(self._undirected_gdf())

    # ------------------------------------------------------------------
    # Coverage on the street network
    # ------------------------------------------------------------------

    def coverage_stats_from_state(self, streets_only: bool = False) -> CoverageStats:
        """Coverage from the persisted state: the metres of the street network
        (streets_only: without paths) the matched routes walked, each counted
        once however many runs covered it."""
        und = self.undirected_with_covered(streets_only=streets_only)
        total_m = float(und['length'].sum())
        walked_m = float(und['covered_m'].sum())
        stats: CoverageStats = {
            'total_network_km': round(total_m / 1000, 2),
            'traversed_km': round(walked_m / 1000, 2),
            'coverage_pct': round(100 * walked_m / total_m, 2) if total_m > 0 else 0,
            'num_unique_streets': int(und['covered'].sum()),
        }
        logger.info("Coverage: %s km / %s km (%s%%) — %d segments",
                    stats['traversed_km'], stats['total_network_km'], stats['coverage_pct'],
                    stats['num_unique_streets'])
        return stats

    def walked_layer(self, streets_only: bool = False) -> gpd.GeoDataFrame:
        """The walked stretches as drawn on the coverage map, in EPSG:4326:
        exactly the ways the routes used (connectors included unless
        streets_only, which keeps streets without paths), with `times`, the
        number of distinct activities that walked each stretch. Reused until
        the state changes; callers must not modify it."""
        version = self.coverage.state_version()
        cached = self._layer_cache.get(streets_only)
        if cached is not None and cached[0] == version:
            return cached[1]
        stretches = self.coverage.walked_state().stretches
        # Least run first, so where lines touch the busiest stretch is drawn on top
        stretches = stretches.sort_values('times', kind='stable')
        walk = self._walkable_network()
        ways = stretches['way'].to_numpy()
        if streets_only:
            keep = (walk['street'].to_numpy() & self._street_flags(walk['highway']))[ways]
            stretches, ways = stretches[keep], ways[keep]
        geoms = substrings(walk.geometry.to_numpy()[ways], stretches['lo'].to_numpy(), stretches['hi'].to_numpy())
        layer = gpd.GeoDataFrame({'name': walk['name'].to_numpy()[ways], 'times': stretches['times'].to_numpy()},
                                 geometry=geoms, crs=walk.crs).to_crs('EPSG:4326')
        self._layer_cache[streets_only] = (version, layer)
        return layer

    def city_bbox(self) -> list[float]:
        """City bounds as [south, west, north, east] in EPSG:4326."""
        b = self._city_boundary.to_crs('EPSG:4326').total_bounds
        return [round(b[1], 5), round(b[0], 5), round(b[3], 5), round(b[2], 5)]

    def _is_street(self, highway) -> bool:
        """Whether an edge is a street (has a runnable class beyond paths/trails)."""
        return bool(self._as_tags(highway) - self.PATH_HIGHWAYS)

    def _street_flags(self, highway: pd.Series) -> np.ndarray:
        """_is_street per edge, evaluated once per distinct highway value."""
        return highway.map({h: self._is_street(h) for h in highway.unique()}).to_numpy(dtype=bool)

    def _undirected_gdf(self) -> gpd.GeoDataFrame:
        """Street segments with geometry — the serving/aggregation view. One row
        per segment already (see _one_row_per_segment): distinct ways between
        the same two nodes are separate streets, so (u, v) is not unique."""
        if self._und_gdf is None:
            idx = self._edges_gdf.index
            u = idx.get_level_values(0).to_numpy()
            v = idx.get_level_values(1).to_numpy()
            gdf = gpd.GeoDataFrame(
                {
                    'u': np.minimum(u, v),
                    'v': np.maximum(u, v),
                    # Row of the walkable network (streets come first, in this order)
                    'way': np.arange(len(self._edges_gdf)),
                    'length': self._edges_gdf['length'].to_numpy(),
                    'name': (self._edges_gdf['name'].to_numpy()
                             if 'name' in self._edges_gdf.columns else None),
                    'street': (self._street_flags(self._edges_gdf['highway'])
                               if 'highway' in self._edges_gdf.columns else True),
                },
                geometry=self._edges_gdf.geometry.values,
                crs=self._edges_gdf.crs,
            )
            self._und_gdf = gdf
        return self._und_gdf

    def undirected_with_covered(self, streets_only: bool = False) -> gpd.GeoDataFrame:
        """Undirected edges with `covered_m`, the metres of each the matched
        routes walked, and `covered`, whether at least SEGMENT_COUNT_FRACTION
        of it was. Callers must not modify the result, which is reused until
        the state changes."""
        version = self.coverage.state_version()
        cached = self._flagged_cache.get(streets_only)
        if cached is not None and cached[0] == version:
            return cached[1]
        und = self._undirected_gdf()
        if streets_only:
            und = und[und['street']]
        covered = self.coverage.walked_state().covered
        out = und.copy()
        out['covered_m'] = np.minimum(covered_at(covered, und['way'].to_numpy()), und['length'].to_numpy())
        out['covered'] = out['covered_m'] >= self.SEGMENT_COUNT_FRACTION * out['length']
        self._flagged_cache[streets_only] = (version, out)
        return out

    # ------------------------------------------------------------------
    # Planned loops and courses
    # ------------------------------------------------------------------

    @classmethod
    def _way_class(cls, highway) -> WayClass:
        hw = cls._as_tags(highway)
        if hw & cls.MAIN_ROAD_HIGHWAYS:
            return WayClass.MAIN_ROAD
        for tag, way_class in (('cycleway', WayClass.CYCLEWAY), ('track', WayClass.TRACK), ('steps', WayClass.STEPS)):
            if tag in hw:
                return way_class
        if hw & {'footway', 'path', 'bridleway'}:
            return WayClass.PATH
        return WayClass.STREET

    def way_classes(self) -> np.ndarray:
        """WayClass code (index into WAY_CLASSES) of each walkable-network row.
        Sidewalks take the class of the nearest street, so avoiding main roads
        avoids their sidewalks too; crossings stay streets. That nearest-street
        search is computed once per street map and kept on disk."""
        return self.coverage.way_classes(self._compute_way_classes)

    def _compute_way_classes(self) -> np.ndarray:
        w = self._walkable_network()
        highway = w['highway'].astype(str)
        codes = highway.map({h: WAY_CLASSES.index(self._way_class(h)) for h in highway.unique()}).to_numpy(np.int8)
        sidewalk = np.flatnonzero(w['sidewalk'].to_numpy())
        streets = np.flatnonzero(w['street'].to_numpy())
        if len(sidewalk) and len(streets):
            geoms = w.geometry.to_numpy()
            at, nearest = shapely.STRtree(geoms[streets]).query_nearest(
                geoms[sidewalk], max_distance=self.SIDEWALK_STREET_M, all_matches=False)
            codes[sidewalk] = WAY_CLASSES.index(WayClass.STREET)
            codes[sidewalk[at]] = codes[streets[nearest]]
        return codes

    def plan_loop(self, start_latlon: LatLon, distance_m: float,
                  via_latlon: list[LatLon] = (), new_share: float = 1.0,
                  avoid: frozenset[WayClass] = frozenset(), seed: int = 0) -> tuple[LoopFeature, list[NewWay]] | None:
        """A loop of about distance_m from the start through the via points
        (lat, lon) over streets not run yet, new_share of it where it can (see
        ExplorationPlanner), as a GeoJSON Feature in EPSG:4326, with the rows
        of its new streets and their lengths, (row, metres), for
        CityCoverage.new_km_now. None when no loop of that length is found."""
        # Held locally: a sync may release the network meanwhile
        planner = self._planner
        if planner is None:
            w = self._walkable_network()
            planner = self._planner = ExplorationPlanner(w['u'].to_numpy(), w['v'].to_numpy(), w.geometry.to_numpy(),
                                                         self.way_classes())
        und = self.undirected_with_covered()
        ways = und['way'].to_numpy()
        covered = np.zeros(len(planner.u))
        covered[ways] = und['covered_m'].to_numpy()
        missing = np.zeros(len(planner.u))
        missing[ways] = np.maximum(0.0, planner.length[ways] - covered[ways])

        to_crs = from_wgs84(str(self._edges_gdf.crs))
        start_xy = to_crs.transform(start_latlon[1], start_latlon[0])
        via_xy = [to_crs.transform(lon, lat) for lat, lon in via_latlon]
        loop = planner.plan(start_xy, distance_m, missing, covered, via_xy=via_xy, new_share=new_share,
                            avoid=avoid, seed=seed)
        if loop is None:
            return None
        xs, ys = to_wgs84(str(self._edges_gdf.crs)).transform(*shapely.get_coordinates(loop.line).T)
        feature: LoopFeature = {
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[round(x, 6), round(y, 6)] for x, y in zip(xs.tolist(), ys.tolist())]},
            "properties": {"length_km": round(loop.length_m / 1000, 2), "new_km": round(loop.new_m / 1000, 2)},
        }
        rows = np.unique(loop.rows)
        rows = rows[missing[rows] > 0]
        return feature, [(int(r), round(float(planner.length[r]), 2)) for r in rows]

    def new_km_along(self, latlon: list[LatLon]) -> tuple[float, float] | None:
        """(km of streets not run yet, km of streets) along a route drawn
        elsewhere (points as (lat, lon)): its part in this city, matched like a
        run and counted like the coverage totals. None when it doesn't match here."""
        return self.coverage.street_km(self._streets_along(latlon))

    def _streets_along(self, latlon: list[LatLon]) -> pd.DataFrame | None:
        """The street stretches (way, lo, hi) a route drawn elsewhere walks
        here, matched like a run; None when it doesn't match."""
        line = LineString([(lon, lat) for lat, lon in latlon])
        result = self.match(gpd.GeoDataFrame({'id': [0]}, geometry=[line], crs='EPSG:4326')).get(0)
        if result is None:
            return None
        return result.walked[result.walked['way'].isin(self._undirected_gdf()['way'])].reset_index(drop=True)

    def match_courses(self, points: dict[str, Callable[[], list[LatLon]]]) -> dict[str, pd.DataFrame | None]:
        """Match routes drawn elsewhere (Garmin courses) once per street map:
        `points[key]()` gives a course's (lat, lon) points and is called only
        for keys not matched yet. Kept in `{slug}_courses.parquet`, since what
        a course walks doesn't change with the coverage. Returns every course
        matched here, by key."""
        known = self.coverage.course_streets()
        new = {key: self._streets_along(get()) for key, get in points.items() if key not in known}
        if not new:
            return known
        known.update(new)
        self.coverage.write_courses(known)
        return known

    # ------------------------------------------------------------------
    # Scoped coverage: districts & arbitrary areas
    # ------------------------------------------------------------------

    @staticmethod
    def _named_polygons(feats: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        polys = feats[feats.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])]
        if 'name' not in polys.columns:
            return polys.iloc[0:0]
        return polys.dropna(subset=['name'])

    def load_districts(self, admin_level: int = 9, force_reload: bool = False) -> gpd.GeoDataFrame:
        """District polygons of the city (cached parquet).

        Tries administrative boundaries at admin_level (9 = districts,
        10 = neighborhoods — the convention in ES). Cities that don't map
        districts administratively (e.g. NL, where Amsterdam's stadsdelen are
        place=suburb) fall back to place polygons.
        """
        fp = self.coverage.districts_path(admin_level)
        if fp.exists() and not force_reload:
            cached = gpd.read_parquet(fp)
            if len(cached):
                return self._with_city_fallback(cached)

        logger.info("Downloading admin_level=%d boundaries for %s...", admin_level, self.city_name)
        ox = _import_osmnx()
        boundary_4326 = self._city_boundary.to_crs('EPSG:4326').union_all()
        city = self._city_boundary.union_all()

        def fetch(tags: dict, admin_level_tag: str | None = None) -> gpd.GeoDataFrame:
            """Named polygons within the city (the query polygon is a bbox-ish
            hull, so polygons merely touching it are dropped), same-named parts merged."""
            try:
                feats = ox.features_from_polygon(boundary_4326, tags=tags)
            except ox._errors.InsufficientResponseError:
                return gpd.GeoDataFrame({'name': []}, geometry=[], crs=self._edges_gdf.crs)
            if admin_level_tag is not None and 'admin_level' in feats.columns:
                # osmnx ORs the tags dict, so admin_level must be filtered afterwards
                feats = feats[feats['admin_level'] == admin_level_tag]
            polys = self._named_polygons(feats)
            polys = gpd.GeoDataFrame({'name': polys['name'].to_numpy() if 'name' in polys else []},
                                     geometry=polys.geometry.values, crs=polys.crs).to_crs(self._edges_gdf.crs)
            polys = polys[polys.representative_point().within(city)]
            return polys.dissolve(by='name', as_index=False)[['name', 'geometry']]

        polys = fetch({'boundary': 'administrative', 'admin_level': str(admin_level)}, str(admin_level))
        if len(polys) < 2 or not self._subdivides_city(polys):
            place_values = (['borough', 'suburb', 'city_district'] if admin_level <= 9
                            else ['quarter', 'neighbourhood'])
            logger.info("No admin boundaries subdividing %s at level %d; falling back to place=%s",
                        self.city_name, admin_level, place_values)
            polys = fetch({'place': place_values})
        # Persist the whole-city fallback when OSM has nothing, so we don't
        # re-hit Overpass on every request; a real but sparse set is kept as-is
        # and collapsed at read time by _with_city_fallback.
        if len(polys) == 0:
            polys = self._city_polygon_fallback()
        polys.to_parquet(fp)
        logger.info("Saved %d districts to %s", len(polys), fp)
        return self._with_city_fallback(polys)

    def _city_polygon_fallback(self) -> gpd.GeoDataFrame:
        """A single district spanning the whole city, named after it."""
        name = self.city_name.split(',')[0].strip()
        geom = self._city_boundary.union_all()
        return gpd.GeoDataFrame({'name': [name]}, geometry=[geom], crs=self._city_boundary.crs)

    def _subdivides_city(self, polys: gpd.GeoDataFrame) -> bool:
        """Whether the polygons (in the city's CRS) cover enough of it to be a real subdivision."""
        city = self._city_boundary.union_all()
        return (len(polys) > 0 and city.area > 0
                and polys.union_all().intersection(city).area / city.area >= self.MIN_DISTRICT_COVERAGE)

    def _with_city_fallback(self, polys: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Collapse to a whole-city district when the mapped polygons cover too
        little of the city to be a real subdivision. Applied to both freshly
        fetched and cached polygons, so cities OSM doesn't subdivide (and any
        stale sparse cache) stay usable without re-querying OSM."""
        return polys if self._subdivides_city(polys) else self._city_polygon_fallback()

    @staticmethod
    def _scoped_stats(total_m: float, covered_m: float, num_streets: float, num_covered: float) -> ScopedStats:
        total_m, covered_m = float(total_m), float(covered_m)
        return {
            'total_km': round(total_m / 1000, 2),
            'covered_km': round(covered_m / 1000, 2),
            'coverage_pct': round(100 * covered_m / total_m, 2) if total_m > 0 else 0.0,
            'num_streets': int(round(num_streets)),
            'num_covered_streets': int(round(num_covered)),
        }

    # A segment whose midpoint lies within this distance of a district border
    # is on it (district borders mostly run along streets).
    DISTRICT_BORDER_M = 1.0

    def _district_shares(self, und: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> pd.DataFrame:
        """Each segment's share of each district (columns seg: row of und,
        district, share): all of it for the district containing its midpoint
        (the smallest, where place polygons nest); a street on a border is
        split evenly between the districts it borders; the few outside every
        polygon go to the nearest. A segment's shares sum to 1, so the
        districts add up to the city."""
        pts = gpd.GeoDataFrame({'seg': np.arange(len(und))}, geometry=und.representative_point().values, crs=und.crs)
        polys = gpd.GeoDataFrame({'district': districts['name'].to_numpy(), 'area': districts.area.to_numpy()},
                                 geometry=districts.geometry.values, crs=districts.crs)
        inside = (gpd.sjoin(pts, polys, predicate='within', how='inner')
                  .sort_values('area').drop_duplicates('seg')[['seg', 'district']])
        rest = pts[~pts['seg'].isin(inside['seg'])]
        border = gpd.sjoin(rest, polys.assign(geometry=polys.buffer(self.DISTRICT_BORDER_M)),
                           predicate='within', how='inner')[['seg', 'district']]
        rest = rest[~rest['seg'].isin(border['seg'])]
        nearest = gpd.sjoin_nearest(rest, polys, how='inner').drop_duplicates('seg')[['seg', 'district']]
        shares = pd.concat([inside, border, nearest], ignore_index=True)
        shares['share'] = 1.0 / shares.groupby('seg')['seg'].transform('size')
        return shares

    def load_hexes(self, resolution: int = HEX_RESOLUTION) -> gpd.GeoDataFrame:
        """The H3 cells overlapping the city, named by cell id."""
        city = self._city_boundary.union_all()
        # A cell overlapping the city has its centre within one edge length of
        # it; twice the average edge allows for the cells larger than average.
        reach_m = 2 * h3.average_hexagon_edge_length(resolution, unit='m')
        search = gpd.GeoSeries([city.buffer(reach_m)], crs=self._city_boundary.crs).to_crs('EPSG:4326').iloc[0]
        cells = h3.geo_to_cells(search, resolution)
        hexes = gpd.GeoDataFrame(
            {'name': cells},
            geometry=[ShapelyPolygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in cells],
            crs='EPSG:4326',
        ).to_crs(self._city_boundary.crs)
        return hexes[hexes.intersects(city)].reset_index(drop=True)

    def coverage_by_district(self, admin_level: int = 9, include_geometry: bool = False,
                             streets_only: bool = False) -> list[PolygonCoverage]:
        """Coverage stats per administrative district, best-covered first."""
        return self._coverage_by_polygon(self.load_districts(admin_level), include_geometry, streets_only)

    def coverage_by_hex(self, resolution: int = HEX_RESOLUTION, include_geometry: bool = False,
                        streets_only: bool = False) -> list[PolygonCoverage]:
        """Coverage stats per H3 cell with streets, best-covered first."""
        return self._coverage_by_polygon(self.load_hexes(resolution), include_geometry, streets_only)

    def _coverage_by_polygon(self, polys: gpd.GeoDataFrame, include_geometry: bool,
                             streets_only: bool) -> list[PolygonCoverage]:
        """Coverage stats per named polygon with streets, best-covered first.

        Segments count for their polygon, border streets split between the
        polygons they border (see _district_shares). With include_geometry,
        each polygon carries its simplified boundary as a GeoJSON geometry.
        """
        und = self.undirected_with_covered(streets_only=streets_only)
        shares = self._district_shares(und, polys)
        seg, share = shares['seg'].to_numpy(), shares['share'].to_numpy()
        per_polygon = pd.DataFrame({
            'district': shares['district'].to_numpy(),
            'total_m': und['length'].to_numpy()[seg] * share,
            'covered_m': und['covered_m'].to_numpy()[seg] * share,
            'num_streets': share,
            'num_covered': und['covered'].to_numpy()[seg] * share,
        }).groupby('district').sum()

        by_name = polys.set_index('name').geometry
        bounds = by_name.to_crs('EPSG:4326').bounds
        geoms_4326 = by_name.simplify(20).to_crs('EPSG:4326') if include_geometry else None

        results: list[PolygonCoverage] = []
        for name, row in per_polygon.iterrows():
            stats = self._scoped_stats(row['total_m'], row['covered_m'], row['num_streets'], row['num_covered'])
            b = bounds.loc[name]
            entry: PolygonCoverage = {
                'name': name,
                **stats,
                'bbox': [round(b['miny'], 5), round(b['minx'], 5), round(b['maxy'], 5), round(b['maxx'], 5)],
            }
            if geoms_4326 is not None:
                gj = shapely_mapping(geoms_4326[name])
                entry['geometry'] = {
                    'type': gj['type'],
                    'coordinates': round_coords(gj['coordinates']),
                }
            results.append(entry)
        return sorted(results, key=lambda r: r['coverage_pct'], reverse=True)

    def coverage_in_polygon(self, latlon_coords: list[LatLon], streets_only: bool = False) -> ScopedStats:
        """Coverage stats within an arbitrary polygon of (lat, lon) vertices."""
        poly = ShapelyPolygon([(lon, lat) for lat, lon in latlon_coords])
        poly_proj = gpd.GeoSeries([poly], crs='EPSG:4326').to_crs(self._edges_gdf.crs).iloc[0]
        und = self.undirected_with_covered(streets_only=streets_only)
        inside = und[und.representative_point().within(poly_proj)]
        return self._scoped_stats(inside['length'].sum(), inside['covered_m'].sum(), len(inside), inside['covered'].sum())
