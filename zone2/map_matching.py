import functools
import json
import logging
import os
import threading
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import geopandas as gpd
import matplotlib.lines as mlines
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, Polygon as ShapelyPolygon, mapping as shapely_mapping
from shapely.ops import substring
from shapely.prepared import prep

from zone2.route_matching import MatchedRoute, RouteMatcher
from zone2.utils import summary_polyline_geometry

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


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Union of [lo, hi] intervals, sorted and non-overlapping."""
    merged: list[list[float]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


class WayRole(StrEnum):
    # The street network coverage is counted on.
    STREET = 'street'
    # Walkable but never counted (sidewalks, crossings, steps, service
    # roads...): the matcher routes through them so the network stays
    # connected wherever a runner can actually pass, and the coverage map
    # draws them where they were run.
    CONNECTOR = 'connector'


@dataclass
class MatchResult:
    """Result of map matching a single activity."""
    activity_id: int | str
    original_geometry: LineString       # GPS track (projected CRS)
    # The matched route in travel order, one row per walked piece of a
    # segment (geometry oriented in the direction of travel); `street` is
    # False for connector pieces.
    route: gpd.GeoDataFrame
    # What the activity covered: the metres [lo, hi] it walked along each
    # way's geometry (`way` is a row of the walkable network), merged per way.
    walked: pd.DataFrame
    outliers: np.ndarray                # GPS observations left out by the matcher (x, y)
    quality: dict

    def plot(self, figsize: tuple[float, float] = (14, 10),
             save_path: Path | str | None = None) -> plt.Figure:
        """Plot the GPS track, the matched route with direction arrows and
        the observations left out as outliers."""
        BG, TEXT, DIM = '#0d1117', '#c9d1d9', '#8b949e'
        CLR = {'gps': '#39d0ff', 'street': '#ff7b3d', 'connector': '#a5d6ff', 'arrow': '#ffd33d',
               'outlier': '#ff4d4d'}

        fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
        ax.set_facecolor(BG)
        if self.original_geometry is not None and not self.original_geometry.is_empty:
            ax.plot(*self.original_geometry.xy, color=CLR['gps'], linewidth=0.8, alpha=0.6, zorder=3)
        bounds = self.route.total_bounds if not self.route.empty else self.original_geometry.bounds
        arrow_every = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 25
        since = arrow_every
        for geom, street in zip(self.route.geometry, self.route['street']):
            ax.plot(*geom.xy, color=CLR['street' if street else 'connector'], linewidth=2.4,
                    solid_capstyle='round', zorder=4)
            since += geom.length
            if since >= arrow_every and geom.length > 5:
                p0, p1 = geom.interpolate(0.4, normalized=True), geom.interpolate(0.6, normalized=True)
                ax.annotate('', xy=(p1.x, p1.y), xytext=(p0.x, p0.y), zorder=5,
                            arrowprops=dict(arrowstyle='-|>', color=CLR['arrow'], lw=1.4, mutation_scale=14))
                since = 0.0
        if len(self.outliers):
            ax.scatter(*self.outliers.T, s=40, marker='x', color=CLR['outlier'], linewidths=1.5, zorder=6)

        handles = [
            mlines.Line2D([], [], color=CLR['gps'], linewidth=1, label='GPS track'),
            mlines.Line2D([], [], color=CLR['street'], linewidth=2.4, label='Matched route (street)'),
            mlines.Line2D([], [], color=CLR['connector'], linewidth=2.4, label='Matched route (connector)'),
            mlines.Line2D([], [], marker='x', color='none', markeredgecolor=CLR['outlier'], markersize=6,
                          label='Left out as outlier'),
        ]
        legend = ax.legend(handles=handles, loc='upper left', fontsize=8, facecolor='#161b22',
                           edgecolor='#30363d', labelcolor=TEXT, framealpha=0.92)
        legend.get_frame().set_linewidth(0.5)
        q = self.quality
        ax.set_title(f"Activity {self.activity_id} — route {q.get('route_km', '?')} km vs GPS {q.get('gps_km', '?')} km, "
                     f"{q.get('street_km', '?')} km on streets", color=TEXT, fontsize=10,
                     fontweight='bold', pad=14)
        ax.text(0.5, 1.01, f"Points: {q.get('num_points', '?')}  |  Outliers: {q.get('num_outliers', '?')}  |  "
                f"Breaks: {q.get('num_breaks', '?')}  |  On connectors: {q.get('pct_on_connectors', '?')}%",
                transform=ax.transAxes, ha='center', fontsize=8, color=DIM)
        ax.set_aspect('equal')
        ax.axis('off')
        plt.tight_layout()
        if save_path is not None:
            fig.savefig(save_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
            logger.info("Saved plot to %s", save_path)
        return fig


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
    # Fraction of the city area the mapped district polygons must cover to be
    # treated as a real subdivision. Below this the city isn't administratively
    # mapped in OSM (e.g. Palma) and we fall back to a single whole-city district.
    MIN_DISTRICT_COVERAGE = 0.4
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
    # A street's unwalked remainder shorter than this isn't drawn as missing.
    MIN_MISSING_M = 5.0

    def __init__(self, city_name: str, workdir: Path, force_reload: bool = False,
                 on_progress: Callable[[str], None] | None = None):
        """
        Initialize the StravaMapMatcher with a specified city name.

        :param city_name: Name of the city to load the street network for.
        :param on_progress: Called with a human-readable stage description at
            each phase of a first-time city download.
        """
        self.city_name = city_name
        self.workdir = workdir / "osm_maps"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._on_progress = on_progress or (lambda stage: None)

        self._edges_gdf: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._city_boundary: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._und_gdf: gpd.GeoDataFrame | None = None
        # Built on first match and released after a sync: the walkable network
        # (streets then connectors) and its matcher are only needed to match.
        self._walkable: gpd.GeoDataFrame | None = None
        self._matcher: RouteMatcher | None = None
        # Coverage derived from the persisted state, reused until a sync rewrites it
        self._flagged_cache: dict[bool, tuple[tuple, gpd.GeoDataFrame]] = {}
        self._layer_cache: dict[bool, tuple[tuple, gpd.GeoDataFrame]] = {}
        # Serializes state-file reads/writes so a background sync rewriting the
        # coverage parquet can't be observed mid-write by request threads.
        self._state_lock = threading.RLock()

        self._load_map(force_reload=force_reload)
        logger.info("Map for %s loaded with %d street segments", self.city_name, len(self._edges_gdf))

    def _slug(self) -> str:
        return self.city_name.replace(', ', '_').lower()

    @staticmethod
    def artifact_path(osm_dir: Path, slug: str, name: str) -> Path:
        """Where a city's artifact `name` (e.g. 'edges.parquet') lives."""
        return osm_dir / f"{slug}_{name}"

    def _artifact(self, name: str) -> Path:
        return self.artifact_path(self.workdir, self._slug(), name)

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
        edges_fp, connectors_fp = self._artifact('edges.parquet'), self._artifact('connectors.parquet')
        boundary_fp, meta_fp = self._artifact('boundary.parquet'), self._artifact('meta.json')

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
        self._und_gdf = self._walkable = self._matcher = None

    def _overpass_filters(self) -> list[str]:
        """Overpass way filter for every class that can be a street or a
        connector; access, foot and tunnel rules are applied in _way_roles."""
        classes = '|'.join(sorted(self.RUNNABLE_HIGHWAYS | self.CONNECTOR_HIGHWAYS))
        return [f'["highway"~"^({classes})$"]["area"!~"yes"]']

    def _segments_from_overpass(self, responses, polygon) -> gpd.GeoDataFrame:
        """Street and connector segments (EPSG:4326) from raw Overpass responses.

        Built directly rather than through an osmnx graph, whose per-node
        Python objects need ~3 GB for a city like Madrid. Ways are cut at
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
            connectors_fp = self._artifact('connectors.parquet')
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

    def match(self, activities: gpd.GeoDataFrame) -> dict[int | str, MatchResult]:
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
        results: dict[int | str, MatchResult] = {}
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

    def _walked_result(self, activity_id, geom: LineString, routes: list[tuple[np.ndarray, MatchedRoute]],
                       walk: gpd.GeoDataFrame, rm: RouteMatcher) -> MatchResult:
        street = walk['street'].to_numpy()
        by_way: dict[int, list[tuple[float, float]]] = defaultdict(list)
        pieces = []
        for _, route in routes:
            for e, a, b in route.pieces:
                if abs(b - a) < self.MIN_WALKED_M:
                    continue
                by_way[e].append((min(a, b), max(a, b)))
                pieces.append((substring(rm.geoms[e], a, b), bool(street[e])))
        walked = pd.DataFrame(
            [(e, lo, hi) for e, ivs in by_way.items() for lo, hi in _merge_intervals(ivs)],
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
        quality = {
            'num_points': n_points,
            'num_outliers': len(outliers),
            'num_breaks': sum(len(r.breaks) for _, r in routes),
            'route_km': round(route_m / 1000, 2),
            'gps_km': round(gps_m / 1000, 2),
            'pct_on_connectors': round(100 * on_connectors / route_m, 1) if route_m else 0.0,
            # Distinct street metres walked (laps count once)
            'street_km': round(on_streets / 1000, 2),
            # Share of the (thinned) in-city points the route explains
            'coverage_pct': round(100 * (1 - len(outliers) / n_points), 1) if n_points else 0.0,
        }
        return MatchResult(activity_id=activity_id, original_geometry=geom, route=route_gdf,
                           walked=walked, outliers=outliers, quality=quality)

    # ------------------------------------------------------------------
    # Coverage analysis & incremental state
    # ------------------------------------------------------------------

    @classmethod
    def _state_paths_of(cls, osm_dir: Path, slug: str) -> tuple[Path, Path]:
        """The walked stretches of every matched activity, and the activities
        matched (or attempted)."""
        return (cls.artifact_path(osm_dir, slug, 'walked.parquet'),
                cls.artifact_path(osm_dir, slug, 'matched_activities.parquet'))

    def _state_paths(self) -> tuple[Path, Path]:
        return self._state_paths_of(self.workdir, self._slug())

    def _atomic_write_parquet(self, df: pd.DataFrame, path: Path) -> None:
        """Write a parquet via a temp file + atomic rename, so a crash mid-write
        (e.g. OOM kill) can never leave a truncated file that readers choke on."""
        tmp = path.parent / f"{path.name}.tmp{os.getpid()}"
        df.to_parquet(tmp)
        os.replace(tmp, path)

    @classmethod
    def _network_stamp(cls, osm_dir: Path, slug: str) -> bytes:
        """Identifies the street map a walked `way` indexes into (a row of the
        walkable network built from the streets and connectors files)."""
        fps = (cls.artifact_path(osm_dir, slug, 'edges.parquet'), cls.artifact_path(osm_dir, slug, 'connectors.parquet'))
        return ','.join(str(fp.stat().st_mtime_ns) if fp.exists() else '0' for fp in fps).encode()

    @classmethod
    def _state_is_current(cls, osm_dir: Path, slug: str) -> bool:
        """Whether the walked stretches exist and index into the current street
        map. When not (a state from before walked stretches, or a re-downloaded
        map), every activity counts as unmatched and the next sync re-matches all."""
        walked_fp, _ = cls._state_paths_of(osm_dir, slug)
        if not walked_fp.exists():
            return False
        return (pq.read_metadata(walked_fp).metadata or {}).get(b'network') == cls._network_stamp(osm_dir, slug)

    @classmethod
    def state_version_of(cls, osm_dir: Path, slug: str) -> tuple[int, int]:
        """Changes whenever a sync rewrites the city's persisted coverage state."""
        return tuple(fp.stat().st_mtime_ns if fp.exists() else 0 for fp in cls._state_paths_of(osm_dir, slug))

    def state_version(self) -> tuple[int, int]:
        return self.state_version_of(self.workdir, self._slug())

    @classmethod
    def _matched_ids_of(cls, osm_dir: Path, slug: str) -> set:
        """Ids of activities already matched (or attempted) against city `slug`."""
        _, meta_fp = cls._state_paths_of(osm_dir, slug)
        if not meta_fp.exists() or not cls._state_is_current(osm_dir, slug):
            return set()
        return set(pd.read_parquet(meta_fp, columns=['activity_id'])['activity_id'])

    @classmethod
    def pending_activities(cls, osm_dir: Path, slug: str, activities: pd.DataFrame) -> pd.DataFrame:
        """Activities still to match against city `slug`: not in its state yet
        and with a summary route near the city. Reads only the small state and
        boundary files, so a sync with nothing new never loads the network or
        any GPS stream."""
        todo = activities[~activities['id'].isin(cls._matched_ids_of(osm_dir, slug))]
        if todo.empty:
            return todo
        boundary = gpd.read_parquet(cls.artifact_path(osm_dir, slug, 'boundary.parquet'))
        # ~200 m of slack: summary polylines are simplified versions of the GPS track
        near = boundary.to_crs('EPSG:4326').union_all().buffer(0.002)
        routes = todo['map'].map(summary_polyline_geometry)
        return todo[[g is not None and g.intersects(near) for g in routes]]

    def matched_activity_ids(self) -> set:
        """Ids of activities already matched (or attempted) against this city."""
        with self._state_lock:
            return self._matched_ids_of(self.workdir, self._slug())

    # (osm_dir, slug) -> (state version, (stretches, covered metres of each way))
    _walked_by_city: dict[tuple[Path, str], tuple[tuple, tuple[pd.DataFrame, np.ndarray]]] = {}

    @classmethod
    def walked_state_of(cls, osm_dir: Path, slug: str) -> tuple[pd.DataFrame, np.ndarray]:
        """Coverage of city `slug` from its state file alone, reused until a
        sync rewrites it:
          - stretches: every walked stretch (columns way, lo, hi, times), split
            where the number of distinct activities that walked it changes;
          - covered: metres walked of each way (indexed by way, 0 when unwalked),
            each metre counted once however many runs covered it."""
        version = cls.state_version_of(osm_dir, slug)
        cached = cls._walked_by_city.get((osm_dir, slug))
        if cached is None or cached[0] != version:
            walked_fp, _ = cls._state_paths_of(osm_dir, slug)
            walked = (pd.read_parquet(walked_fp, columns=['way', 'lo', 'hi'])
                      if cls._state_is_current(osm_dir, slug) else pd.DataFrame(columns=['way', 'lo', 'hi']))
            stretches = cls._stretches(walked)
            covered = np.bincount(stretches['way'].to_numpy(dtype=np.int64),
                                  weights=(stretches['hi'] - stretches['lo']).to_numpy(dtype=np.float64))
            cached = cls._walked_by_city[(osm_dir, slug)] = (version, (stretches, covered))
        return cached[1]

    @staticmethod
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

    def save_match_state(
        self,
        match_results: dict[int | str, MatchResult],
        attempted_ids: list | None = None,
    ) -> None:
        """Append per-activity walked stretches and matched routes to the
        persisted state. A state that isn't current (see _state_is_current) is
        replaced rather than appended to.

        Activities attempted but not matched are recorded with nothing walked
        so incremental runs don't retry them forever.
        """
        walked_fp, meta_fp = self._state_paths()
        routes_fp = self._artifact('routes.parquet')
        current = self._state_is_current(self.workdir, self._slug())

        walked_rows = [r.walked.assign(activity_id=aid) for aid, r in match_results.items() if len(r.walked)]
        meta_rows = []
        route_ids, route_geoms = [], []
        for aid, result in match_results.items():
            if not result.route.empty:
                route_ids.append(aid)
                route_geoms.append(self._route_lines(result.route))
            meta_rows.append({
                'activity_id': aid,
                'matched_at': pd.Timestamp.utcnow().isoformat(),
                'street_km': result.quality.get('street_km'),
                'coverage_pct': result.quality.get('coverage_pct'),
            })
        matched_ids = set(match_results.keys())
        for aid in (attempted_ids or []):
            if aid not in matched_ids:
                meta_rows.append({
                    'activity_id': aid,
                    'matched_at': pd.Timestamp.utcnow().isoformat(),
                    'street_km': 0.0,
                    'coverage_pct': 0.0,
                })

        with self._state_lock:
            if walked_rows or not current:
                new_walked = pd.concat(walked_rows, ignore_index=True) if walked_rows else pd.DataFrame(
                    {'way': pd.Series(dtype=np.int64), 'lo': pd.Series(dtype=np.float64),
                     'hi': pd.Series(dtype=np.float64), 'activity_id': pd.Series(dtype=np.int64)})
                if current:
                    old = pd.read_parquet(walked_fp)
                    # A re-matched activity replaces its stretches
                    new_walked = pd.concat([old[~old['activity_id'].isin(matched_ids)], new_walked], ignore_index=True)
                table = pa.Table.from_pandas(new_walked[['activity_id', 'way', 'lo', 'hi']], preserve_index=False)
                table = table.replace_schema_metadata({'network': self._network_stamp(self.workdir, self._slug())})
                tmp = walked_fp.parent / f"{walked_fp.name}.tmp{os.getpid()}"
                pq.write_table(table, tmp)
                os.replace(tmp, walked_fp)
            if meta_rows:
                new_meta = pd.DataFrame(meta_rows)
                if current and meta_fp.exists():
                    new_meta = pd.concat([pd.read_parquet(meta_fp), new_meta], ignore_index=True)
                self._atomic_write_parquet(
                    new_meta.drop_duplicates('activity_id', keep='last'), meta_fp)
            if route_ids:
                new_routes = gpd.GeoDataFrame({'activity_id': route_ids}, geometry=route_geoms,
                                              crs=self._edges_gdf.crs).to_crs('EPSG:4326')
                if routes_fp.exists():
                    new_routes = pd.concat([gpd.read_parquet(routes_fp), new_routes], ignore_index=True)
                self._atomic_write_parquet(new_routes.drop_duplicates('activity_id', keep='last'), routes_fp)

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

    @classmethod
    def read_route(cls, osm_dir: Path, slug: str, activity_id: int) -> dict | None:
        """The matched route of an activity in city `slug` as a GeoJSON
        MultiLineString (EPSG:4326, lines oriented in travel order), or None
        when the city hasn't matched it. Reads only the routes file, so it
        never builds a matcher."""
        routes_fp = cls.artifact_path(osm_dir, slug, 'routes.parquet')
        if activity_id not in cls._route_ids(routes_fp):
            return None
        hit = gpd.read_parquet(routes_fp, filters=[('activity_id', '==', activity_id)])
        if hit.empty:
            return None
        geom = hit.geometry.iloc[0]
        lines = [geom] if isinstance(geom, LineString) else list(geom.geoms)
        return {'type': 'MultiLineString', 'coordinates': [cls._round_coords(shapely_mapping(ln)['coordinates'])
                                                           for ln in lines]}

    # routes file -> (mtime, activity ids in it)
    _route_ids_cache: dict[Path, tuple[int, frozenset[int]]] = {}

    @classmethod
    def _route_ids(cls, routes_fp: Path) -> frozenset[int]:
        """Activities with a route in `routes_fp`, so a route lookup opens only
        the city that has it (the activity page asks every city)."""
        try:
            mtime = routes_fp.stat().st_mtime_ns
        except FileNotFoundError:
            return frozenset()
        cached = cls._route_ids_cache.get(routes_fp)
        if cached is None or cached[0] != mtime:
            ids = pq.read_table(routes_fp, columns=['activity_id']).column('activity_id').to_pylist()
            cached = cls._route_ids_cache[routes_fp] = (mtime, frozenset(ids))
        return cached[1]

    def match_incremental(self, activities: gpd.GeoDataFrame) -> dict:
        """Match only activities not yet in the persisted state, then return
        the updated coverage stats. This is the entry point for sync flows:
        the backfill cost is paid once, each new activity costs one match.
        """
        done = self.matched_activity_ids()
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
        # Release what only matching needs (the walkable network and its
        # routing graph, a few hundred MB for a large city)
        self._walkable = self._matcher = None
        stats = self.coverage_stats_from_state()
        self.write_stats_cache()
        return stats

    def _stats_cache_path(self) -> Path:
        return self.workdir / f"{self._slug()}_stats.json"

    def write_stats_cache(self) -> None:
        """Persist summary coverage stats to JSON so list endpoints can report
        numbers without constructing a matcher (which would hold ~140 MB per
        city). Written after every sync and on city add."""
        payload = {
            'city_name': self.city_name,
            'num_matched_activities': len(self.matched_activity_ids()),
            'bbox': self.city_bbox(),
            'all': {k: v for k, v in self.coverage_stats_from_state(streets_only=False).items()
                    if not k.startswith('_')},
            'streets': {k: v for k, v in self.coverage_stats_from_state(streets_only=True).items()
                        if not k.startswith('_')},
        }
        path = self._stats_cache_path()
        tmp = path.parent / f"{path.name}.tmp{os.getpid()}"
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, path)

    def coverage_stats_from_state(self, streets_only: bool = False) -> dict:
        """Coverage from the persisted state: the metres of the street network
        (streets_only: without paths) the matched routes walked, each counted
        once however many runs covered it."""
        und = self.undirected_with_covered(streets_only=streets_only)
        total_m = float(und['length'].sum())
        walked_m = float(und['covered_m'].sum())
        stats = {
            'total_network_km': round(total_m / 1000, 2),
            'traversed_km': round(walked_m / 1000, 2),
            'coverage_pct': round(100 * walked_m / total_m, 2) if total_m > 0 else 0,
            'num_unique_streets': int(und['covered'].sum()),
        }
        logger.info("Coverage: %s km / %s km (%s%%) — %d segments",
                    stats['traversed_km'], stats['total_network_km'], stats['coverage_pct'],
                    stats['num_unique_streets'])
        return stats

    @staticmethod
    def _covered_at(covered: np.ndarray, ways: np.ndarray) -> np.ndarray:
        """covered[ways], 0 past the last walked way."""
        out = np.zeros(len(ways))
        inside = ways < len(covered)
        out[inside] = covered[ways[inside]]
        return out

    def walked_layer(self, streets_only: bool = False) -> gpd.GeoDataFrame:
        """The walked stretches as drawn on the coverage map, in EPSG:4326:
        exactly the ways the routes used (connectors included unless
        streets_only, which keeps streets without paths), with `times`, the
        number of distinct activities that walked each stretch. Reused until
        the state changes; callers must not modify it."""
        version = self.state_version()
        cached = self._layer_cache.get(streets_only)
        if cached is not None and cached[0] == version:
            return cached[1]
        stretches, _ = self.walked_state_of(self.workdir, self._slug())
        # Least run first, so where lines touch the busiest stretch is drawn on top
        stretches = stretches.sort_values('times', kind='stable')
        walk = self._walkable_network()
        ways = stretches['way'].to_numpy()
        if streets_only:
            keep = (walk['street'].to_numpy() & self._street_flags(walk['highway']))[ways]
            stretches, ways = stretches[keep], ways[keep]
        geoms = [substring(g, lo, hi) for g, lo, hi in
                 zip(walk.geometry.to_numpy()[ways], stretches['lo'].tolist(), stretches['hi'].tolist())]
        layer = gpd.GeoDataFrame({'name': walk['name'].to_numpy()[ways], 'times': stretches['times'].to_numpy()},
                                 geometry=geoms, crs=walk.crs).to_crs('EPSG:4326')
        self._layer_cache[streets_only] = (version, layer)
        return layer

    # ------------------------------------------------------------------
    # Scoped coverage: districts & arbitrary areas
    # ------------------------------------------------------------------

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
        """Unique undirected edges with geometry — the serving/aggregation view."""
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
            self._und_gdf = gdf.drop_duplicates(['u', 'v']).reset_index(drop=True)
        return self._und_gdf

    def undirected_with_covered(self, streets_only: bool = False) -> gpd.GeoDataFrame:
        """Undirected edges with `covered_m`, the metres of each the matched
        routes walked, and `covered`, whether at least SEGMENT_COUNT_FRACTION
        of it was. Callers must not modify the result, which is reused until
        the state changes."""
        version = self.state_version()
        cached = self._flagged_cache.get(streets_only)
        if cached is not None and cached[0] == version:
            return cached[1]
        und = self._undirected_gdf()
        if streets_only:
            und = und[und['street']]
        _, covered = self.walked_state_of(self.workdir, self._slug())
        out = und.copy()
        out['covered_m'] = np.minimum(self._covered_at(covered, und['way'].to_numpy()), und['length'].to_numpy())
        out['covered'] = out['covered_m'] >= self.SEGMENT_COUNT_FRACTION * out['length']
        self._flagged_cache[streets_only] = (version, out)
        return out

    @staticmethod
    def edge_feature(coords: list, name, times: int | None = None) -> dict:
        """GeoJSON feature of an edge served to the coverage map."""
        props = {"name": None if name is None or str(name) == "nan" else str(name)}
        if times is not None:
            props["times"] = int(times)
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": props}

    # Viewport index: the undirected edges in EPSG:4326, ordered along a
    # Z-order curve of ~200 m cells and stored in small row groups, so the
    # row-group bounds statistics let a viewport query skip most of the city.
    # Each edge's feature is stored rendered up to its closing braces, so an
    # unwalked edge costs joined bytes, no per-coordinate work; partly walked
    # ones are cut from their projected geometry, stored alongside.
    VIEWPORT_CELL_DEG = 0.002
    VIEWPORT_ROW_GROUP = 1024
    VIEWPORT_INDEX_VERSION = b'4'   # bump when the index layout or rendering changes

    @classmethod
    def _viewport_index_path(cls, osm_dir: Path, slug: str) -> Path:
        return cls.artifact_path(osm_dir, slug, 'viewport.parquet')

    # index path -> ((index mtime, map mtime), (footer, bounds of each row group) or None if not current)
    _viewport_meta_cache: dict[Path, tuple[tuple[int, int], tuple[pq.FileMetaData, np.ndarray] | None]] = {}

    @classmethod
    def _viewport_meta(cls, osm_dir: Path, slug: str) -> tuple[pq.FileMetaData, np.ndarray] | None:
        """The current viewport index's footer and per-row-group [minx, miny,
        maxx, maxy], read once per index file; None when it is missing, older
        than the street map or of another layout."""
        fp = cls._viewport_index_path(osm_dir, slug)
        edges_fp = cls.artifact_path(osm_dir, slug, 'edges.parquet')
        if not fp.exists() or not edges_fp.exists():
            return None
        mtimes = (fp.stat().st_mtime_ns, edges_fp.stat().st_mtime_ns)
        cached = cls._viewport_meta_cache.get(fp)
        if cached is None or cached[0] != mtimes:
            meta = None
            footer = pq.read_metadata(fp)
            current = (footer.metadata or {}).get(b'viewport_index_version') == cls.VIEWPORT_INDEX_VERSION
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
                meta = (footer, bounds)
            cached = cls._viewport_meta_cache[fp] = (mtimes, meta)
        return cached[1]

    @classmethod
    def has_viewport_index(cls, osm_dir: Path, slug: str) -> bool:
        """Whether the viewport index is current: this layout, newer than the street map."""
        return cls._viewport_meta(osm_dir, slug) is not None

    def write_viewport_index(self) -> None:
        """Write the city's viewport index (see viewport_missing_geojson). It
        depends on the street map only, not on coverage, so it is built once per map."""
        und = self._undirected_gdf()
        projected = und.geometry.values
        geoms = und.geometry.to_crs('EPSG:4326').values
        bounds = shapely.bounds(geoms)
        cells = ((bounds[:, :2] + bounds[:, 2:]) / 2 - bounds[:, :2].min(axis=0)) // self.VIEWPORT_CELL_DEG
        order = np.argsort(self._z_order(cells[:, 0].astype(np.uint32), cells[:, 1].astype(np.uint32)), kind='stable')
        geoms, names = geoms[order], und['name'].to_numpy()[order]
        xy, owner = shapely.get_coordinates(geoms, return_index=True)
        ends = np.cumsum(np.bincount(owner, minlength=len(geoms))).tolist()
        rounded = [[round(x, 6), round(y, 6)] for x, y in xy.tolist()]
        # Rendered as the viewport response renders it (FastAPI's compact JSON),
        # minus the closing '}}' so `times` can still be appended.
        features = [
            self._compact_json(self.edge_feature(rounded[a:b], name))[:-2] if b > a else None
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
        fp = self._viewport_index_path(self.workdir, self._slug())
        tmp = fp.parent / f"{fp.name}.tmp{os.getpid()}"
        pq.write_table(table, tmp, row_group_size=self.VIEWPORT_ROW_GROUP)
        os.replace(tmp, fp)

    @staticmethod
    def _compact_json(obj) -> bytes:
        return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _z_order(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Morton code of 16-bit cell coordinates: nearby cells get nearby codes."""
        def spread(n: np.ndarray) -> np.ndarray:
            n = n & 0xFFFF
            n = (n | (n << 8)) & 0x00FF00FF
            n = (n | (n << 4)) & 0x0F0F0F0F
            n = (n | (n << 2)) & 0x33333333
            return (n | (n << 1)) & 0x55555555
        return spread(x) | (spread(y) << 1)

    # (osm_dir, slug) -> (state version, walked [lo, hi] of each walked way, merged)
    _walked_union_cache: dict[tuple[Path, str], tuple[tuple, dict[int, list[tuple[float, float]]]]] = {}

    @classmethod
    def _walked_union_of(cls, osm_dir: Path, slug: str) -> dict[int, list[tuple[float, float]]]:
        version = cls.state_version_of(osm_dir, slug)
        cached = cls._walked_union_cache.get((osm_dir, slug))
        if cached is None or cached[0] != version:
            stretches, _ = cls.walked_state_of(osm_dir, slug)
            union: dict[int, list[tuple[float, float]]] = defaultdict(list)
            for way, lo, hi in zip(stretches['way'].tolist(), stretches['lo'].tolist(), stretches['hi'].tolist()):
                ivs = union[way]
                if ivs and lo <= ivs[-1][1]:
                    ivs[-1] = (ivs[-1][0], max(ivs[-1][1], hi))
                else:
                    ivs.append((lo, hi))
            cached = cls._walked_union_cache[(osm_dir, slug)] = (version, dict(union))
        return cached[1]

    @staticmethod
    @functools.lru_cache(maxsize=8)
    def _to_wgs84(crs: str) -> Transformer:
        return Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)

    @classmethod
    def viewport_missing_geojson(cls, osm_dir: Path, slug: str, bbox: tuple[float, float, float, float],
                                 streets_only: bool = False, with_counts: bool = False) -> bytes | None:
        """GeoJSON (compact bytes, EPSG:4326) of what is left to run around
        `bbox` (south, west, north, east): the street-network edges intersecting
        it, minus the stretches the matched routes walked (remainders under
        MIN_MISSING_M aren't drawn). Read from the viewport index without
        loading the city; None when the index isn't current (build it with
        write_viewport_index)."""
        meta = cls._viewport_meta(osm_dir, slug)
        if meta is None:
            return None
        footer, group_bounds = meta
        south, west, north, east = bbox
        groups = np.flatnonzero((group_bounds[:, 0] <= east) & (group_bounds[:, 2] >= west)
                                & (group_bounds[:, 1] <= north) & (group_bounds[:, 3] >= south))
        near = pq.ParquetFile(cls._viewport_index_path(osm_dir, slug), metadata=footer).read_row_groups(
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

        _, covered = cls.walked_state_of(osm_dir, slug)
        way = near.column('way').to_numpy()
        length = near.column('length_m').to_numpy()
        walked_m = cls._covered_at(covered, way)
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
        partial = np.flatnonzero(hit & (walked_m > 0) & (length - walked_m >= cls.MIN_MISSING_M))
        partial = partial[np.argsort(order[partial], kind='stable')]
        if len(partial):
            union = cls._walked_union_of(osm_dir, slug)
            to_wgs84 = cls._to_wgs84(footer.metadata[b'crs'].decode())
            lines = shapely.from_wkb(near.column('geometry_m').take(partial).to_numpy(zero_copy_only=False))
            names = near.column('name').take(partial).to_pylist()
            for line, w, name in zip(lines, way[partial].tolist(), names):
                start = 0.0
                for lo, hi in [*union.get(w, []), (line.length, line.length)]:
                    if lo - start >= cls.MIN_MISSING_M:
                        xs, ys = to_wgs84.transform(*shapely.get_coordinates(substring(line, start, lo)).T)
                        coords = [[round(x, 6), round(y, 6)] for x, y in zip(xs.tolist(), ys.tolist())]
                        parts.append(cls._compact_json(cls.edge_feature(coords, name, 0 if with_counts else None)))
                    start = max(start, hi)
        return b'{"type":"FeatureCollection","features":[' + b','.join(parts) + b']}'

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
        fp = self.workdir / f"{self._slug()}_districts_{admin_level}.parquet"
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
    def _scoped_stats(total_m: float, covered_m: float, num_streets: float, num_covered: float) -> dict:
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

    @staticmethod
    def _round_coords(obj: list | float) -> list | float:
        if isinstance(obj, (list, tuple)):
            return [StravaMapMatcher._round_coords(x) for x in obj]
        return round(obj, 5)

    def coverage_by_district(self, admin_level: int = 9, include_geometry: bool = False,
                             streets_only: bool = False) -> list[dict]:
        """Coverage stats per administrative district, best-covered first.

        Segments count for their district, border streets split between the
        districts they border (see _district_shares). With include_geometry,
        each district carries its simplified boundary as a GeoJSON geometry.
        """
        districts = self.load_districts(admin_level)
        und = self.undirected_with_covered(streets_only=streets_only)
        shares = self._district_shares(und, districts)
        seg, share = shares['seg'].to_numpy(), shares['share'].to_numpy()
        per_district = pd.DataFrame({
            'district': shares['district'].to_numpy(),
            'total_m': und['length'].to_numpy()[seg] * share,
            'covered_m': und['covered_m'].to_numpy()[seg] * share,
            'num_streets': share,
            'num_covered': und['covered'].to_numpy()[seg] * share,
        }).groupby('district').sum()

        geoms_4326 = None
        if include_geometry:
            geoms_4326 = districts.set_index('name').geometry.simplify(20).to_crs('EPSG:4326')

        results = []
        for name, row in per_district.iterrows():
            stats = self._scoped_stats(row['total_m'], row['covered_m'], row['num_streets'], row['num_covered'])
            geom = districts.loc[districts['name'] == name, 'geometry']
            bounds = gpd.GeoSeries(geom, crs=districts.crs).to_crs('EPSG:4326').total_bounds
            entry = {
                'name': name,
                **stats,
                # [south, west, north, east] for map fitBounds
                'bbox': [round(bounds[1], 5), round(bounds[0], 5),
                         round(bounds[3], 5), round(bounds[2], 5)],
            }
            if geoms_4326 is not None and name in geoms_4326.index:
                gj = shapely_mapping(geoms_4326[name])
                entry['geometry'] = {
                    'type': gj['type'],
                    'coordinates': self._round_coords(gj['coordinates']),
                }
            results.append(entry)
        return sorted(results, key=lambda r: r['coverage_pct'], reverse=True)

    def coverage_in_polygon(self, latlon_coords: list[tuple[float, float]],
                            streets_only: bool = False) -> dict:
        """Coverage stats within an arbitrary polygon of (lat, lon) vertices."""
        poly = ShapelyPolygon([(lon, lat) for lat, lon in latlon_coords])
        poly_proj = gpd.GeoSeries([poly], crs='EPSG:4326').to_crs(self._edges_gdf.crs).iloc[0]
        und = self.undirected_with_covered(streets_only=streets_only)
        inside = und[und.representative_point().within(poly_proj)]
        return self._scoped_stats(inside['length'].sum(), inside['covered_m'].sum(), len(inside), inside['covered'].sum())

    def plot_coverage(
        self,
        save_path: Path | str | None = None,
        neon_color: str = '#fc0101',
        figsize: tuple[float, float] = (20, 20),
    ) -> plt.Figure:
        """Render a neon-glow coverage map of the city from the persisted state:
        the street network as a dim base layer, the walked stretches glowing
        in neon (3-layer: atmosphere, glow, core)."""
        stats = self.coverage_stats_from_state()
        crs = self._edges_gdf.crs
        geoms = self._edges_gdf.geometry
        base = gpd.GeoDataFrame(geometry=geoms[geoms.notna() & ~geoms.is_empty].values, crs=crs)
        walked = self.walked_layer().to_crs(crs)

        fig, ax = plt.subplots(figsize=figsize, facecolor='black')
        ax.set_facecolor('black')
        ax.set_axis_off()
        if not base.empty:
            base.plot(ax=ax, color='#1c2333', linewidth=0.3, alpha=0.85, zorder=0)
        if self._city_boundary is not None and not self._city_boundary.empty:
            self._city_boundary.boundary.plot(ax=ax, color='#30363d', linewidth=0.5, alpha=0.4, zorder=0)
        if not walked.empty:
            walked.plot(ax=ax, color=neon_color, linewidth=6, alpha=0.03, zorder=1)
            walked.plot(ax=ax, color=neon_color, linewidth=2.5, alpha=0.15, zorder=2)
            walked.plot(ax=ax, color='white', linewidth=0.5, alpha=0.9, zorder=3)

        subtitle = (
            f"{stats['traversed_km']} km / {stats['total_network_km']} km  "
            f"({stats['coverage_pct']}%)"
        )
        ax.text(
            0.5, 0.1, subtitle.upper(),
            transform=ax.transAxes, ha='center', va='top',
            color='#8b949e', fontsize=14, fontfamily='monospace',
        )
        ax.text(
            0.5, 0.07, f"{self.city_name} — Coverage".upper(),
            transform=ax.transAxes, ha='center', va='top',
            color=neon_color, fontsize=26, fontfamily='monospace',
            fontweight='bold', alpha=0.9,
        )

        plt.tight_layout()

        if save_path is not None:
            fig.savefig(save_path, dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
            logger.info("Coverage map saved to %s", save_path)

        return fig
