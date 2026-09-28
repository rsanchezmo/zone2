import json
import logging
import os
import pickle
import threading
from leuvenmapmatching.matcher.distance import DistanceMatcher
from leuvenmapmatching.map.inmem import InMemMap
from leuvenmapmatching.util import dist_euclidean as _dist_euclidean
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import shapely
from pathlib import Path
from shapely.geometry import LineString, MultiLineString, Point, Polygon as ShapelyPolygon, mapping as shapely_mapping
from shapely.ops import linemerge
from shapely.prepared import prep
import numpy as np
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _project(s1, s2, p, delta=0.0):
    if abs(s1[0] - s2[0]) <= 1e-08 and abs(s1[1] - s2[1]) <= 1e-08:
        return s1, 0.0
    l2 = (s1[0] - s2[0]) ** 2 + (s1[1] - s2[1]) ** 2
    t = max(delta, min(1 - delta,
                       ((p[0] - s1[0]) * (s2[0] - s1[0]) + (p[1] - s1[1]) * (s2[1] - s1[1])) / l2))
    return (s1[0] + t * (s2[0] - s1[0]), s1[1] + t * (s2[1] - s1[1])), t


def _distance_segment_to_segment(f1, f2, t1, t2):
    x1, y1 = f1
    x2, y2 = f2
    x3, y3 = t1
    x4, y4 = t2
    n = ((y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1))
    if abs(n) <= 1e-08:
        n = 0.0001  # parallel — simulates a point far away
    u_f = ((x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)) / n
    u_t = ((x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)) / n
    xi = x1 + u_f * (x2 - x1)
    yi = y1 + u_f * (y2 - y1)
    changed_f = False
    changed_t = False
    if u_t > 1:
        u_t = 1
        changed_t = True
    elif u_t < 0:
        u_t = 0
        changed_t = True
    if u_f > 1:
        u_f = 1
        changed_f = True
    elif u_f < 0:
        u_f = 0
        changed_f = True
    if not changed_t and not changed_f:
        return 0, (xi, yi), (xi, yi), u_f, u_t
    xf = x1 + u_f * (x2 - x1)
    yf = y1 + u_f * (y2 - y1)
    xt = x3 + u_t * (x4 - x3)
    yt = y3 + u_t * (y4 - y3)
    if changed_t and changed_f:
        df = (xf - xi) ** 2 + (yf - yi) ** 2
        dt = (xt - xi) ** 2 + (yt - yi) ** 2
        if df > dt:
            changed_t = False
        else:
            changed_f = False
    if changed_t:
        pt = (xt, yt)
        pf, u_f = _project(f1, f2, pt)
    else:
        pf = (xf, yf)
        pt, u_t = _project(t1, t2, pf)
    d = _dist_euclidean.distance(pf, pt)
    return d, pf, pt, u_f, u_t


# leuvenmapmatching spends most of its matching time in np.isclose/np.allclose
# called on scalars inside these two functions (~15µs of numpy dispatch per
# call, >100k calls per activity). These drop-ins keep identical semantics
# (atol=1e-8, rtol=0) with plain math. Must be installed before any map object
# is built — the library binds them onto map instances at construction.
_dist_euclidean.project = _project
_dist_euclidean.distance_segment_to_segment = _distance_segment_to_segment


def _import_osmnx():
    """osmnx set up for one-off city downloads. Imported lazily because it
    pulls in a heavy dependency stack (~140 MB RSS), never needed to serve a
    city that is already on disk."""
    import osmnx as ox
    # Each city is downloaded once; the on-disk response cache would only
    # keep tens of MB of Overpass JSON around.
    ox.settings.use_cache = False
    return ox


@dataclass
class MatchResult:
    """Result of map matching a single activity."""
    activity_id: int | str
    original_geometry: LineString  # Original GPS track (projected CRS)
    matched_geometry: LineString | MultiLineString | None  # HMM-matched OSM edge geometries merged
    # Credited OSM edges; `source` is 'matched' (HMM path) or 'corridor'
    # (a parallel way the track ran along, see StravaMapMatcher.CORRIDOR_BUFFER_M).
    matched_edges_gdf: gpd.GeoDataFrame
    matching_details: gpd.GeoDataFrame   # Per-observation: obs point, snapped point, edge, distance
    quality: dict = field(default_factory=dict)

    def plot(self, figsize: tuple[float, float] = (14, 10),
            save_path: Path | str | None = None) -> plt.Figure:
        """Plot the match result: GPS track, matched OSM edges, and snapped points.

        Three layers are drawn:
        1. Credited OSM edges (solid; HMM-matched and corridor in distinct colours)
        2. Original GPS track (dashed)
        3. Observation → snapped-point connections with points

        Args:
            figsize: Figure size in inches.
            save_path: If provided, saves the figure to this path.

        Returns:
            The matplotlib Figure.
        """
        BG = '#0d1117'
        CLR_EDGES = '#58a6ff'
        CLR_CORRIDOR = '#f0883e'
        CLR_GPS_LINE = '#ff6b6b'
        CLR_GPS_PT = '#ff6b6b'
        CLR_SNAP_PT = '#7ee787'
        CLR_CONN = '#ffffff'
        CLR_TEXT = '#c9d1d9'
        CLR_TEXT_DIM = '#8b949e'

        fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
        ax.set_facecolor(BG)

        # --- 1. Credited OSM edges ---
        if not self.matched_edges_gdf.empty:
            for _, edge_row in self.matched_edges_gdf.iterrows():
                geom = edge_row.geometry
                color = CLR_CORRIDOR if edge_row.get('source') == 'corridor' else CLR_EDGES
                if isinstance(geom, LineString):
                    xs, ys = geom.xy
                    ax.plot(xs, ys, color=color, linewidth=2.5, alpha=0.8,
                            solid_capstyle='round', zorder=2)
                elif isinstance(geom, MultiLineString):
                    for part in geom.geoms:
                        xs, ys = part.xy
                        ax.plot(xs, ys, color=color, linewidth=2.5, alpha=0.8,
                                solid_capstyle='round', zorder=2)

        # --- 2. Original GPS track ---
        if self.original_geometry is not None and not self.original_geometry.is_empty:
            gps_x, gps_y = self.original_geometry.xy
            ax.plot(gps_x, gps_y, color=CLR_GPS_LINE, linewidth=1.2, linestyle='--',
                    alpha=0.7, zorder=4)

        # --- 3. Snapped points + connection lines ---
        if not self.matching_details.empty:
            details = self.matching_details
            emitting = details[details['is_emitting']]

            # Connection lines: obs → snapped
            for _, row in emitting.iterrows():
                obs_pt = row['obs_point']
                snap_pt = row['snapped_point']
                if obs_pt is not None and snap_pt is not None:
                    ax.plot([obs_pt.x, snap_pt.x], [obs_pt.y, snap_pt.y],
                            color=CLR_CONN, linewidth=0.6, alpha=0.45, zorder=3)

            # GPS observation points
            obs_points = emitting['obs_point'].dropna()
            if not obs_points.empty:
                obs_x = [p.x for p in obs_points]
                obs_y = [p.y for p in obs_points]
                ax.scatter(obs_x, obs_y, c=CLR_GPS_PT, s=10, zorder=6,
                           edgecolors='none', alpha=0.8)

            # Snapped points (single colour)
            snap_points = emitting.dropna(subset=['snapped_point'])
            if not snap_points.empty:
                snap_x = [p.x for p in snap_points['snapped_point']]
                snap_y = [p.y for p in snap_points['snapped_point']]
                ax.scatter(snap_x, snap_y, c=CLR_SNAP_PT, s=10, zorder=7,
                           edgecolors='none', alpha=0.8)

        # --- Legend ---
        legend_handles = [
            mlines.Line2D([], [], color=CLR_GPS_LINE, linestyle='--', linewidth=1.2,
                          alpha=0.7, label='GPS track'),
            mlines.Line2D([], [], color=CLR_EDGES, linewidth=2.5, label='Matched OSM edges'),
            mlines.Line2D([], [], color=CLR_CORRIDOR, linewidth=2.5, label='Corridor-credited edges'),
            mlines.Line2D([], [], marker='o', color='none', markerfacecolor=CLR_GPS_PT,
                          markersize=5, label='GPS points'),
            mlines.Line2D([], [], marker='o', color='none', markerfacecolor=CLR_SNAP_PT,
                          markersize=5, label='Snapped points'),
            mlines.Line2D([], [], color=CLR_CONN, linewidth=0.6, alpha=0.45,
                          label='Obs \u2192 Snap'),
        ]
        legend = ax.legend(handles=legend_handles, loc='upper left', fontsize=8,
                           facecolor='#161b22', edgecolor='#30363d', labelcolor=CLR_TEXT,
                           framealpha=0.92)
        legend.get_frame().set_linewidth(0.5)

        # --- Title ---
        q = self.quality
        title = (
            f"Activity {self.activity_id}  \u2014  "
            f"{q.get('num_matched_edges', '?')} edges "
            f"(+{q.get('num_corridor_edges', 0)} corridor), "
            f"avg snap {q.get('avg_dist_obs_m', '?')} m, "
            f"max snap {q.get('max_dist_obs_m', '?')} m"
        )
        subtitle = (
            f"Obs: {q.get('num_observations_in_coverage', '?')}  |  "
            f"Matched: {q.get('num_matched', '?')}  |  "
            f"Sub-segments: {q.get('num_sub_segments_matched', '?')}/{q.get('num_sub_segments', '?')}"
        )
        ax.set_title(title, color=CLR_TEXT, fontsize=10, fontweight='bold', pad=14)
        ax.text(0.5, 1.01, subtitle, transform=ax.transAxes, ha='center',
                fontsize=8, color=CLR_TEXT_DIM)

        # --- Clean axes ---
        ax.set_aspect('equal')
        ax.axis('off')

        plt.tight_layout()

        if save_path is not None:
            fig.savefig(save_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
            logger.info("Saved plot to %s", save_path)

        return fig


class StravaMapMatcher:
    # Street classes that count as runnable — the matching target and the
    # coverage denominator.
    RUNNABLE_HIGHWAYS = {
        'residential', 'living_street', 'pedestrian',
        'primary', 'secondary', 'tertiary',
        'primary_link', 'secondary_link', 'tertiary_link',
        'unclassified', 'path', 'track', 'cycleway',
    }
    # Footway subtypes mapped as separate ways alongside a street; running
    # the street covers them implicitly.
    EXCLUDED_FOOTWAY_TYPES = {'sidewalk', 'crossing', 'traffic_island', 'access_aisle'}
    EXCLUDED_ACCESS = {'private', 'no'}
    # Pedestrian streets are commonly `access=no` + `foot=yes`, so an explicit
    # foot permission overrides EXCLUDED_ACCESS.
    FOOT_ALLOWED = {'yes', 'designated', 'permissive'}
    # `foot=no` on a surface road usually means its sidewalk is mapped as a
    # separate way, and running that sidewalk credits the road. Only in a
    # tunnel does it mean there is nowhere to run.
    TUNNEL_TAGS = {'yes', 'building_passage'}
    # Runnable classes that are paths/trails rather than streets. Still part
    # of the matching target (running them is recorded), but excluded from
    # the denominator in the streets-only coverage view.
    PATH_HIGHWAYS = {'footway', 'path', 'track', 'steps', 'cycleway', 'bridleway'}
    # Fraction of the city area the mapped district polygons must cover to be
    # treated as a real subdivision. Below this the city isn't administratively
    # mapped in OSM (e.g. Palma) and we fall back to a single whole-city district.
    MIN_DISTRICT_COVERAGE = 0.4
    # Per-segment attributes persisted per city; everything else OSM carries
    # (footway, access, foot, ...) only feeds _filter_runnable at download.
    EDGE_COLUMNS = ('u', 'v', 'key', 'highway', 'name', 'length', 'geometry')
    # Way tags read from Overpass: EDGE_COLUMNS' attributes plus what
    # _filter_runnable decides on.
    WAY_TAGS = ('highway', 'name', 'footway', 'access', 'foot', 'tunnel')
    # The matcher only sees straight segments between graph nodes, so each
    # edge's shape points (simplified to this tolerance) become synthetic
    # nodes; otherwise GPS on a curved path can lie beyond max_dist of its
    # u-v chord.
    MATCH_GRAPH_SIMPLIFY_M: float = 5.0
    # OSM maps a road, its cycle path and its footway as separate ways metres
    # apart, and the HMM credits only the one it snapped to. An edge lying
    # almost entirely within this buffer of the GPS track was run along too.
    # The minimum length keeps junction stubs, which a passing track swallows
    # whole, from being credited.
    CORRIDOR_BUFFER_M: float = 12.0
    CORRIDOR_MIN_FRACTION: float = 0.9
    CORRIDOR_MIN_EDGE_M: float = 20.0

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

        self._nodes_gdf: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._edges_gdf: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._map_con: InMemMap | None = None
        # Row i is the OSM edge (u, v) that synthetic matcher node -(i + 1) lies on
        self._synthetic_parents: np.ndarray | None = None
        self._city_boundary: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._und_gdf: gpd.GeoDataFrame | None = None
        # Serializes state-file reads/writes so a background sync rewriting the
        # coverage parquet can't be observed mid-write by request threads.
        self._state_lock = threading.RLock()

        self._load_map(force_reload=force_reload)
        # (u, v) -> full (u, v, key) index; only matching needs it, so it is
        # built on first use and released with the matcher map after a sync.
        self._edge_lookup: dict[tuple[int, int], tuple] | None = None

        logger.info(
            "Map for %s loaded with %d edges and %d nodes",
            self.city_name, len(self._edges_gdf), len(self._nodes_gdf),
        )

    def _matcher_map_name(self) -> str:
        return f"{self._slug()}_matchgraph"

    # Files making up the cached matcher map, as suffixes of _matcher_map_name()
    MATCHER_MAP_SUFFIXES = ('', '.pkl', '.dat', '.idx', '_parents.npy')

    def _build_matcher_map(self):
        """
        Build the InMemMap required for the DistanceMatcher, cached on disk.

        Nodes are the OSM intersections plus synthetic nodes (negative ids)
        tracing each edge's shape; _synthetic_parents maps them back to their
        edge. The graph dict is handed to InMemMap whole so the rtree is
        bulk-loaded from a generator instead of one insert per edge, then
        persisted (pickle + file-based rtree) for fast reloads. Edges are
        bidirectional to allow matching against traffic.
        """
        map_name = self._matcher_map_name()
        pkl_path = self.workdir / f"{map_name}.pkl"
        parents_path = self.workdir / f"{map_name}_parents.npy"
        # setup_index() only reuses the on-disk rtree if this marker exists
        # (the rtree itself lives in <map_name>.idx/.dat).
        rtree_marker = self.workdir / map_name

        if pkl_path.exists() and parents_path.exists() and rtree_marker.exists():
            with pkl_path.open('rb') as f:
                data = pickle.load(f)
            # The pickle records the directory it was built from, which may be
            # relative to another cwd or a since-moved workdir.
            data['dir'] = self.workdir
            self._map_con = InMemMap.deserialize(data)
            self._synthetic_parents = np.load(parents_path)
            logger.info("Loaded matcher map from %s", pkl_path)
            return

        edges = self._edges_gdf.reset_index()
        shapes = shapely.simplify(edges.geometry.to_numpy(), self.MATCH_GRAPH_SIMPLIFY_M)

        locs: dict[int, tuple[float, float]] = dict(zip(
            self._nodes_gdf.index.tolist(),
            zip(self._nodes_gdf['x'].tolist(), self._nodes_gdf['y'].tolist()),
        ))
        neighbors: dict[int, set[int]] = defaultdict(set)
        parents: list[tuple[int, int]] = []
        for u, v, shape in zip(edges['u'].tolist(), edges['v'].tolist(), shapes):
            chain = [u]
            for x, y in shapely.get_coordinates(shape)[1:-1].tolist():
                node_id = -(len(parents) + 1)
                parents.append((u, v))
                locs[node_id] = (x, y)
                chain.append(node_id)
            chain.append(v)
            for a, b in zip(chain, chain[1:]):
                if a != b:
                    neighbors[a].add(b)
                    neighbors[b].add(a)
        graph = {nid: (locs[nid], sorted(nbrs)) for nid, nbrs in neighbors.items()}

        # Stale rtree files would otherwise be reopened by the bulk loader
        for suffix in ('.dat', '.idx'):
            (self.workdir / (map_name + suffix)).unlink(missing_ok=True)

        map_con = InMemMap(map_name, use_latlon=False, index_edges=True,
                           use_rtree=True, dir=self.workdir, graph=graph)
        map_con.dump()
        self._synthetic_parents = np.asarray(parents, dtype=np.int64).reshape(-1, 2)
        np.save(parents_path, self._synthetic_parents)
        rtree_marker.touch()
        self._map_con = map_con
        logger.info("Built matcher map (%d nodes, %d synthetic) and cached to %s",
                    len(graph), len(parents), pkl_path)

    def _parent_edge(self, a: int, b: int) -> tuple[int, int]:
        """The OSM edge (u, v) that matcher-graph segment (a, b) lies on."""
        synthetic = a if a < 0 else b if b < 0 else None
        if synthetic is None:
            return a, b
        u, v = self._synthetic_parents[-synthetic - 1]
        return int(u), int(v)

    def _slug(self) -> str:
        return self.city_name.replace(', ', '_').lower()

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

    def _filter_runnable(self, edges_gdf: pd.DataFrame) -> pd.DataFrame:
        """Reduce OSM ways (one row of tags each) to runnable streets.

        This subset is both the matching target and the coverage denominator:
        matching directly against it makes a sidewalk run snap to (and credit)
        the street itself. Excluded: sidewalks and crossings mapped as
        separate ways, motorways, service roads (parking aisles, driveways),
        steps, restricted-access ways without a foot permission, and road
        tunnels closed to pedestrians.
        """
        def keep(highway, footway, access, foot, tunnel) -> bool:
            foot_tags = self._as_tags(foot)
            if self._as_tags(access) & self.EXCLUDED_ACCESS and not foot_tags & self.FOOT_ALLOWED:
                return False
            if 'no' in foot_tags and self._as_tags(tunnel) & self.TUNNEL_TAGS:
                return False
            hw = self._as_tags(highway)
            if hw & self.RUNNABLE_HIGHWAYS:
                return True
            if 'footway' in hw:
                return not (self._as_tags(footway) & self.EXCLUDED_FOOTWAY_TYPES)
            return False

        def col(name: str) -> pd.Series:
            return edges_gdf[name] if name in edges_gdf.columns else pd.Series(None, index=edges_gdf.index)

        mask = [
            keep(h, f, a, ft, t)
            for h, f, a, ft, t in zip(edges_gdf['highway'], col('footway'), col('access'),
                                      col('foot'), col('tunnel'))
        ]
        return edges_gdf[mask]

    def _load_map(self, force_reload: bool = False):
        """Load the runnable street network, downloading and slimming on first use.

        The durable per-city artifacts are three small parquets (nodes with
        coordinates, runnable edges with simplified geometry, city boundary)
        instead of the full raw OSM dump — ~15 MB per city.
        """
        slug = self._slug()
        nodes_fp = self.workdir / f"{slug}_nodes.parquet"
        edges_fp = self.workdir / f"{slug}_edges.parquet"
        boundary_fp = self.workdir / f"{slug}_boundary.parquet"

        meta_fp = self.workdir / f"{slug}_meta.json"

        if not force_reload and nodes_fp.exists() and edges_fp.exists() and boundary_fp.exists():
            edges = gpd.read_parquet(edges_fp, columns=list(self.EDGE_COLUMNS))
            self._edges_gdf = self._one_row_per_segment(edges).set_index(['u', 'v', 'key'])
            nodes = pd.read_parquet(nodes_fp).set_index('osmid')
            self._nodes_gdf = nodes  # type: ignore[assignment]
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
        edges_4326, nodes_4326 = self._segments_from_overpass(responses, polygon)

        slim_edges = edges_4326.to_crs(utm_crs)
        # Length of the full shape; the 2 m simplification below is well
        # under GPS accuracy but still shortens curves slightly.
        slim_edges['length'] = slim_edges.length
        lo = np.minimum(slim_edges['u'], slim_edges['v'])
        hi = np.maximum(slim_edges['u'], slim_edges['v'])
        slim_edges['key'] = slim_edges.groupby([lo, hi]).cumcount()
        slim_edges = slim_edges[list(self.EDGE_COLUMNS)].copy()
        slim_edges['geometry'] = slim_edges['geometry'].simplify(2.0)
        points = gpd.GeoSeries(gpd.points_from_xy(nodes_4326['lon'], nodes_4326['lat']),
                               crs='EPSG:4326').to_crs(utm_crs)
        slim_nodes = pd.DataFrame({'osmid': nodes_4326['osmid'].to_numpy(),
                                   'x': points.x.to_numpy(), 'y': points.y.to_numpy()})

        self._on_progress('saving the city map')
        slim_edges.to_parquet(edges_fp)
        slim_nodes.to_parquet(nodes_fp)
        city_boundary_gdf.to_parquet(boundary_fp)
        # Only after a successful download — a failed add must leave no trace
        # that _known_cities could mistake for a real city.
        if not meta_fp.exists():
            meta_fp.write_text(json.dumps({'city_name': self.city_name}))
        logger.info("Runnable map for %s saved to %s (%d edges, %d nodes)",
                    self.city_name, self.workdir, len(slim_edges), len(slim_nodes))

        self._edges_gdf = slim_edges.set_index(['u', 'v', 'key'])
        self._nodes_gdf = slim_nodes.set_index('osmid')  # type: ignore[assignment]
        self._city_boundary = city_boundary_gdf

        # Invalidate the cached matcher map — it derives from this graph
        map_name = self._matcher_map_name()
        for suffix in self.MATCHER_MAP_SUFFIXES:
            (self.workdir / (map_name + suffix)).unlink(missing_ok=True)

    def _overpass_filters(self) -> list[str]:
        """Overpass way filters for the runnable classes, one query each.

        Sidewalks, crossings and service roads are most of a city's raw ways
        and are dropped anyway, so they are excluded server-side; the access,
        foot and tunnel rules stay in _filter_runnable.
        """
        classes = '|'.join(sorted(self.RUNNABLE_HIGHWAYS))
        footway_types = '|'.join(sorted(self.EXCLUDED_FOOTWAY_TYPES))
        return [
            f'["highway"~"^({classes})$"]["area"!~"yes"]',
            f'["highway"="footway"]["footway"!~"^({footway_types})$"]["area"!~"yes"]',
        ]

    def _segments_from_overpass(self, responses, polygon) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
        """Runnable street segments (EPSG:4326) and their end nodes from raw
        Overpass responses.

        Built directly rather than through an osmnx graph, whose per-node
        Python objects need ~3 GB for a city like Madrid. Ways are cut at
        every node another runnable way also uses (and at their ends), and
        segments with an end outside the city are dropped.
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
        keep = self._filter_runnable(pd.DataFrame(tags)).index
        ways = [ways[i] for i in keep]
        tags = [tags[i] for i in keep]

        uses: Counter[int] = Counter()
        for nodes in ways:
            uses.update(nodes)
            uses.update((nodes[0], nodes[-1]))
        node_ids = np.fromiter(uses, dtype=np.int64, count=len(uses))
        lon, lat = np.array([coords[n] for n in node_ids.tolist()]).T
        inside = dict(zip(node_ids.tolist(), shapely.contains_xy(polygon, lon, lat).tolist()))

        us: list[int] = []
        vs: list[int] = []
        seg_tags: list[dict] = []
        shapes: list[LineString] = []
        for nodes, way_tags in zip(ways, tags):
            start = 0
            for i in range(1, len(nodes)):
                if uses[nodes[i]] < 2 and i < len(nodes) - 1:
                    continue
                u, v = nodes[start], nodes[i]
                if inside[u] and inside[v]:
                    us.append(u)
                    vs.append(v)
                    seg_tags.append(way_tags)
                    shapes.append(LineString([coords[n] for n in nodes[start:i + 1]]))
                start = i
        edges = gpd.GeoDataFrame(
            {
                'u': np.asarray(us, dtype=np.int64),
                'v': np.asarray(vs, dtype=np.int64),
                'highway': [t['highway'] for t in seg_tags],
                'name': [t['name'] for t in seg_tags],
            },
            geometry=shapes, crs='EPSG:4326',
        )
        end_nodes = sorted(set(us) | set(vs))
        nodes_lonlat = np.array([coords[n] for n in end_nodes]).reshape(-1, 2)
        nodes = pd.DataFrame({'osmid': np.asarray(end_nodes, dtype=np.int64),
                              'lon': nodes_lonlat[:, 0], 'lat': nodes_lonlat[:, 1]})
        return edges, nodes

    @staticmethod
    def _one_row_per_segment(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """OSM gives two-way streets as (u, v, k) and (v, u, k) with the same
        geometry reversed; keep one row per undirected segment. Length is
        part of the identity because two distinct one-way ways between the
        same nodes can share (u, v, k) in opposite directions."""
        lo = np.minimum(edges['u'], edges['v'])
        hi = np.maximum(edges['u'], edges['v'])
        ident = pd.DataFrame({'lo': lo, 'hi': hi, 'key': edges['key'], 'len': edges['length'].round(1)})
        return edges[~ident.duplicated().to_numpy()]

    def _get_edge_row(self, u: int, v: int) -> pd.Series | None:
        """Look up full edge data for (u, v), trying reverse direction too."""
        if self._edge_lookup is None:
            self._edge_lookup = {}
            for idx_tuple in self._edges_gdf.index:
                self._edge_lookup.setdefault((idx_tuple[0], idx_tuple[1]), idx_tuple)
        for key in [(u, v), (v, u)]:
            if key in self._edge_lookup:
                full_key = self._edge_lookup[key]
                return self._edges_gdf.loc[full_key]
        return None

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
    # (~3 m at 1 Hz) are thinned to this so the Viterbi lattice stays cheap;
    # sparse summary polylines (~24 m) pass through essentially untouched.
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
        """Split a coordinate list at large gaps, then thin each part to
        ~THIN_SPACING_M spacing.

        The gap threshold is tuned for the input's density: Strava summary
        polylines are Douglas-Peucker simplified and routinely leave >100 m gaps
        between vertices on straight streets, so a tighter cut severs (and loses)
        those streets. 250 m still breaks at genuine GPS dropouts while letting
        the matcher's non-emitting states bridge simplification gaps.

        Thinning keeps the matcher cheap on high-resolution GPS streams without
        discarding accuracy — the kept vertices are real observations, just
        fewer of them.
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

    def _create_matcher(self) -> DistanceMatcher:
        """Create a fresh DistanceMatcher instance."""
        if self._map_con is None:
            self._build_matcher_map()

        return DistanceMatcher(
            self._map_con,
            max_dist=35,
            max_dist_init=35,
            min_prob_norm=1e-3,
            non_emitting_length_factor=0.75,
            obs_noise=18,
            obs_noise_ne=35,
            dist_noise=25,
            max_lattice_width=12,
            non_emitting_states=True,
        )

    def _build_matching_details(self, matcher: DistanceMatcher, path: list[tuple],
                                utm_crs) -> gpd.GeoDataFrame:
        """Build per-observation matching table from lattice_best.

        Each row maps a lattice state to its matched OSM edge and snapped
        point. The snapped point is the matcher's own projection, which lies on
        the edge's shape to within MATCH_GRAPH_SIMPLIFY_M.
        """
        records = []

        for m in matcher.lattice_best:
            obs_idx = m.obs
            obs_ne = m.obs_ne
            is_emitting = obs_ne == 0

            obs_coord = path[obs_idx] if obs_idx < len(path) else None
            if m.edge_m.l2 is not None:
                edge_u, edge_v = self._parent_edge(m.edge_m.l1, m.edge_m.l2)
            else:
                edge_u, edge_v = m.edge_m.l1, None
            matcher_snapped = m.edge_m.pi if m.edge_m.pi is not None else m.edge_m.p1
            snapped_point = Point(matcher_snapped) if matcher_snapped is not None else None

            obs_point_geom = Point(obs_coord) if obs_coord is not None else None
            dist_to_snapped = (obs_point_geom.distance(snapped_point)
                               if obs_point_geom and snapped_point else m.dist_obs)

            records.append({
                'obs_idx': obs_idx,
                'is_emitting': is_emitting,
                'obs_ne': obs_ne,
                'edge_u': edge_u,
                'edge_v': edge_v,
                'obs_point': obs_point_geom,
                'snapped_point': snapped_point,
                'dist_obs': dist_to_snapped,
                'logprob': m.logprob,
                'logprob_norm': m.logprob / m.length if m.length > 0 else 0,
            })

        if not records:
            return gpd.GeoDataFrame()

        return gpd.GeoDataFrame(records, geometry='snapped_point', crs=utm_crs)

    def _build_matched_edges(self, matcher: DistanceMatcher,
                             utm_crs) -> tuple[gpd.GeoDataFrame, LineString | MultiLineString | None]:
        """Extract unique matched OSM edges with their real geometries.

        Returns:
            - GeoDataFrame of individual matched edges with OSM attributes
            - Merged geometry of the full matched route
        """
        seen_edges = set()
        ordered_edges = []

        for m in matcher.lattice_best:
            if m.edge_m.l2 is None:
                continue
            u, v = self._parent_edge(m.edge_m.l1, m.edge_m.l2)
            edge_key = (min(u, v), max(u, v))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                ordered_edges.append((u, v))

        if not ordered_edges:
            return gpd.GeoDataFrame(), None

        edge_records = []
        edge_geoms = []

        for u, v in ordered_edges:
            edge_row = self._get_edge_row(u, v)
            if edge_row is None:
                continue

            geom = edge_row.get('geometry')
            if geom is None or geom.is_empty:
                continue

            record = {'edge_u': u, 'edge_v': v, 'geometry': geom, 'source': 'matched'}
            for col in ['highway', 'name', 'length']:
                if col in edge_row.index:
                    record[col] = edge_row[col]

            edge_records.append(record)
            edge_geoms.append(geom)

        if not edge_records:
            return gpd.GeoDataFrame(), None

        edges_gdf = gpd.GeoDataFrame(edge_records, geometry='geometry', crs=utm_crs)
        merged = linemerge(MultiLineString(edge_geoms))

        return edges_gdf, merged

    def _corridor_edges(self, track: LineString, credited: set[tuple[int, int]]) -> gpd.GeoDataFrame:
        """Runnable edges the track ran along that aren't already credited,
        i.e. parallel siblings of the HMM path (see CORRIDOR_BUFFER_M)."""
        und = self._undirected_gdf()
        zone = track.simplify(2.0).buffer(self.CORRIDOR_BUFFER_M)
        cand = und.iloc[und.sindex.query(zone, predicate='intersects')]
        geoms = cand.geometry.to_numpy()
        lengths = shapely.length(geoms)
        inside = shapely.length(shapely.intersection(geoms, zone))
        along = (lengths >= self.CORRIDOR_MIN_EDGE_M) & (inside >= self.CORRIDOR_MIN_FRACTION * lengths)
        new = np.array([(u, v) not in credited for u, v in zip(cand['u'].tolist(), cand['v'].tolist())],
                       dtype=bool)
        picked = cand[along & new]
        return gpd.GeoDataFrame(
            {
                'edge_u': picked['u'].to_numpy(),
                'edge_v': picked['v'].to_numpy(),
                'source': 'corridor',
                'name': picked['name'].to_numpy(),
                'length': picked['length'].to_numpy(),
            },
            geometry=picked.geometry.to_numpy(),
            crs=und.crs,
        )

    def match(self, activities: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict[int | str, MatchResult]]:
        """Map match activities to the OSM street network.

        Args:
            activities: GeoDataFrame with LineString geometries.

        Returns:
            Tuple of:
            - GeoDataFrame with matched geometries and quality metrics
            - Dict mapping activity ID -> MatchResult with per-edge and per-point details
        """
        if self._map_con is None:
            self._build_matcher_map()

        utm_crs = self._edges_gdf.crs
        activities_in_city = activities.to_crs(utm_crs)

        # Filter activities that intersect the city boundary (not 'within' — allows boundary-crossing)
        activities_in_city = gpd.sjoin(
            activities_in_city, self._city_boundary, predicate='intersects', how='inner'
        )

        matched_rows = []
        match_results: dict[int | str, MatchResult] = {}

        for idx, row in activities_in_city.iterrows():
            geom = row.geometry
            if not isinstance(geom, LineString) or geom.is_empty:
                continue

            activity_id = row.get('id', idx)
            full_path = list(geom.coords)

            # Split path into contiguous in-coverage segments
            segments = self._split_path_by_coverage(geom)
            if not segments:
                logger.warning("Activity %s: no GPS points within city boundary", activity_id)
                continue

            # Match each segment independently and collect results.
            # When the matcher dies early (lattice collapse), skip a few
            # points past the failure and retry with the remaining tail.
            SKIP_ON_FAILURE = 5   # points to skip past the failure point
            MIN_SUBSEG_LEN = 10   # minimum points to attempt a match

            all_edges_gdfs: list[gpd.GeoDataFrame] = []
            all_details_dfs: list[gpd.GeoDataFrame] = []
            all_edge_geoms: list[LineString | MultiLineString] = []
            total_matched = 0
            total_observations = sum(len(s) for s in segments)  # total in-coverage points
            sub_id = 0           # monotonic sub-segment counter

            for segment_path in segments:
                remaining = segment_path

                while len(remaining) >= MIN_SUBSEG_LEN:
                    matcher = self._create_matcher()

                    try:
                        states, last_idx = matcher.match(remaining)
                    except Exception as e:
                        logger.warning("Sub-segment %s failed: %s", sub_id, e)
                        break  # give up on this segment entirely

                    if not states or len(states) == 0:
                        # No match at all — skip ahead and retry
                        remaining = remaining[SKIP_ON_FAILURE:]
                        sub_id += 1
                        continue

                    seg_edges_gdf, seg_geometry = self._build_matched_edges(matcher, utm_crs)
                    seg_details = self._build_matching_details(matcher, remaining, utm_crs)

                    if not seg_details.empty:
                        seg_details['segment_id'] = sub_id
                    if not seg_edges_gdf.empty:
                        seg_edges_gdf['segment_id'] = sub_id

                    all_edges_gdfs.append(seg_edges_gdf)
                    all_details_dfs.append(seg_details)
                    if seg_geometry is not None:
                        all_edge_geoms.append(seg_geometry)

                    matched_count = last_idx + 1
                    total_matched += matched_count
                    sub_id += 1

                    # If the matcher consumed all points, we're done
                    if matched_count >= len(remaining):
                        break

                    # Otherwise skip past the failure point and retry the tail
                    resume_at = matched_count + SKIP_ON_FAILURE
                    remaining = remaining[resume_at:]

            hmm_edges = [df for df in all_edges_gdfs if not df.empty]
            credited = {
                (min(u, v), max(u, v))
                for df in hmm_edges for u, v in zip(df['edge_u'].tolist(), df['edge_v'].tolist())
            }
            corridor_gdf = self._corridor_edges(geom, credited)
            if not hmm_edges and corridor_gdf.empty:
                logger.warning("No match found for activity %s", activity_id)
                continue

            # Merge all segments
            matched_edges_gdf = gpd.GeoDataFrame(
                pd.concat([df for df in hmm_edges + [corridor_gdf] if not df.empty], ignore_index=True),
                geometry='geometry', crs=utm_crs,
            )
            details = [df for df in all_details_dfs if not df.empty]
            matching_details = (pd.concat(details, ignore_index=True) if details
                                else gpd.GeoDataFrame({'is_emitting': [], 'dist_obs': []}))

            # Flatten any MultiLineStrings before merging
            flat_lines: list[LineString] = []
            for g in all_edge_geoms:
                if isinstance(g, MultiLineString):
                    flat_lines.extend(g.geoms)
                elif isinstance(g, LineString):
                    flat_lines.append(g)
            matched_geometry = linemerge(MultiLineString(flat_lines)) if flat_lines else None

            # Quality metrics (emitting states only for distance stats)
            emitting = matching_details[matching_details['is_emitting']] if not matching_details.empty else matching_details
            avg_dist = emitting['dist_obs'].mean() if not emitting.empty else None
            max_dist = emitting['dist_obs'].max() if not emitting.empty else None
            n_emitting = int(emitting.shape[0]) if not emitting.empty else 0

            quality = {
                'num_observations_total': len(full_path),
                'num_observations_in_coverage': total_observations,
                'num_matched': total_matched,
                'num_coverage_segments': len(segments),
                'num_sub_segments': sub_id,
                'num_sub_segments_matched': sum(1 for df in all_edges_gdfs if not df.empty),
                'num_emitting_states': n_emitting,
                'num_matched_edges': len(credited),
                'num_corridor_edges': len(corridor_gdf),
                'avg_dist_obs_m': round(float(avg_dist), 2) if avg_dist is not None else None,
                'max_dist_obs_m': round(float(max_dist), 2) if max_dist is not None else None,
                # Share of the (thinned) in-city observations the HMM consumed
                'coverage_pct': (round(100 * total_matched / total_observations, 1)
                                 if total_observations else 0),
            }

            match_results[activity_id] = MatchResult(
                activity_id=activity_id,
                original_geometry=geom,
                matched_geometry=matched_geometry,
                matched_edges_gdf=matched_edges_gdf,
                matching_details=matching_details,
                quality=quality,
            )

            result = row.to_dict()
            result['matched_geometry'] = matched_geometry
            result['num_matched_edges'] = quality['num_matched_edges']
            result['avg_dist_obs_m'] = quality['avg_dist_obs_m']
            result['max_dist_obs_m'] = quality['max_dist_obs_m']
            result['num_sub_segments'] = quality['num_sub_segments']
            result['coverage_pct'] = quality['coverage_pct']
            matched_rows.append(result)

            logger.info(
                "Activity %s: %d edges (+%d corridor), avg snap %sm, %d/%d sub-segments, coverage %s%%",
                activity_id,
                quality['num_matched_edges'],
                quality['num_corridor_edges'],
                quality['avg_dist_obs_m'],
                quality['num_sub_segments_matched'],
                quality['num_sub_segments'],
                quality['coverage_pct'],
            )

        if not matched_rows:
            logger.warning("No activities were successfully matched")
            return gpd.GeoDataFrame(), match_results

        result_gdf = gpd.GeoDataFrame(matched_rows, geometry='matched_geometry', crs=utm_crs)
        return result_gdf, match_results

    # ------------------------------------------------------------------
    # Coverage analysis & incremental state
    # ------------------------------------------------------------------

    def _state_paths(self) -> tuple[Path, Path]:
        slug = self._slug()
        return (self.workdir / f"{slug}_covered_edges.parquet",
                self.workdir / f"{slug}_matched_activities.parquet")

    def _atomic_write_parquet(self, df: pd.DataFrame, path: Path) -> None:
        """Write a parquet via a temp file + atomic rename, so a crash mid-write
        (e.g. OOM kill) can never leave a truncated file that readers choke on."""
        tmp = path.parent / f"{path.name}.tmp{os.getpid()}"
        df.to_parquet(tmp)
        os.replace(tmp, path)

    def matched_activity_ids(self) -> set:
        """Ids of activities already matched (or attempted) against this city."""
        _, meta_fp = self._state_paths()
        with self._state_lock:
            if not meta_fp.exists():
                return set()
            return set(pd.read_parquet(meta_fp)['activity_id'])

    def covered_edge_set(self) -> set[tuple[int, int]]:
        """Unique undirected edges covered so far, from the persisted state."""
        edges_fp, _ = self._state_paths()
        with self._state_lock:
            if not edges_fp.exists():
                return set()
            df = pd.read_parquet(edges_fp)
        return set(zip(df['u'].tolist(), df['v'].tolist()))

    def covered_edge_counts(self) -> dict[tuple[int, int], int]:
        """Per undirected edge, how many distinct activities traversed it —
        the traversal-frequency signal behind the coverage heatmap."""
        edges_fp, _ = self._state_paths()
        with self._state_lock:
            if not edges_fp.exists():
                return {}
            df = pd.read_parquet(edges_fp)
        counts = df.groupby(['u', 'v'])['activity_id'].nunique()
        return {(int(u), int(v)): int(c) for (u, v), c in counts.items()}

    def save_match_state(
        self,
        match_results: dict[int | str, MatchResult],
        attempted_ids: list | None = None,
    ) -> None:
        """Append per-activity covered edges to the persisted state.

        Activities attempted but not matched are recorded with zero edges so
        incremental runs don't retry them forever.
        """
        edges_fp, meta_fp = self._state_paths()

        edge_rows = []
        meta_rows = []
        for aid, result in match_results.items():
            keys: set[tuple[int, int]] = set()
            if result.matched_edges_gdf is not None and not result.matched_edges_gdf.empty:
                us = result.matched_edges_gdf['edge_u'].astype('int64')
                vs = result.matched_edges_gdf['edge_v'].astype('int64')
                keys = {(min(u, v), max(u, v)) for u, v in zip(us.tolist(), vs.tolist())}
            edge_rows.extend({'activity_id': aid, 'u': u, 'v': v} for u, v in keys)
            meta_rows.append({
                'activity_id': aid,
                'matched_at': pd.Timestamp.utcnow().isoformat(),
                'num_edges': len(keys),
                'coverage_pct': result.quality.get('coverage_pct'),
            })
        matched_ids = set(match_results.keys())
        for aid in (attempted_ids or []):
            if aid not in matched_ids:
                meta_rows.append({
                    'activity_id': aid,
                    'matched_at': pd.Timestamp.utcnow().isoformat(),
                    'num_edges': 0,
                    'coverage_pct': 0.0,
                })

        with self._state_lock:
            if edge_rows:
                new_edges = pd.DataFrame(edge_rows)
                if edges_fp.exists():
                    new_edges = pd.concat([pd.read_parquet(edges_fp), new_edges], ignore_index=True)
                self._atomic_write_parquet(
                    new_edges.drop_duplicates(['activity_id', 'u', 'v']), edges_fp)
            if meta_rows:
                new_meta = pd.DataFrame(meta_rows)
                if meta_fp.exists():
                    new_meta = pd.concat([pd.read_parquet(meta_fp), new_meta], ignore_index=True)
                self._atomic_write_parquet(
                    new_meta.drop_duplicates('activity_id', keep='last'), meta_fp)

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
            _, results = self.match(todo)
            self.save_match_state(results, attempted_ids=list(todo['id']))
        # Release what only matching needs (the InMemMap + rtree and the edge
        # lookup, tens of MB each); the map reloads from its on-disk pickle in
        # ~0.1 s when the next sync needs it.
        self._map_con = None
        self._edge_lookup = None
        stats = self.coverage_stats_from_state()
        self.write_stats_cache()
        return stats

    def _stats_cache_path(self) -> Path:
        return self.workdir / f"{self._slug()}_stats.json"

    def write_stats_cache(self) -> None:
        """Persist summary coverage stats to JSON so list endpoints can report
        numbers without constructing a matcher (which would hold ~300 MB per
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

    def _coverage_from_edges(self, traversed: set[tuple[int, int]],
                             streets_only: bool = False) -> dict:
        und = self._undirected_gdf()
        if streets_only:
            und = und[und['street']]
        total_length_m = float(und['length'].sum())
        covered_mask = [
            (u, v) in traversed for u, v in zip(und['u'].tolist(), und['v'].tolist())
        ]
        traversed_length_m = float(und.loc[covered_mask, 'length'].sum())

        stats = {
            'total_network_km': round(total_length_m / 1000, 2),
            'traversed_km': round(traversed_length_m / 1000, 2),
            'coverage_pct': round(100 * traversed_length_m / total_length_m, 2) if total_length_m > 0 else 0,
            'num_unique_streets': int(np.count_nonzero(covered_mask)),
            '_traversed_edge_set': traversed,
        }
        logger.info(
            "Coverage: %s km / %s km (%s%%) — %d unique edges",
            stats['traversed_km'], stats['total_network_km'], stats['coverage_pct'],
            stats['num_unique_streets'],
        )
        return stats

    def coverage_stats(self, match_results: dict[int | str, MatchResult]) -> dict:
        """Compute city-wide street coverage statistics from match results.

        Deduplicates edges across all matched activities (an edge traversed
        ten times still counts as one) and computes the fraction of the
        runnable network covered.
        """
        traversed: set[tuple[int, int]] = set()
        for result in match_results.values():
            if result.matched_edges_gdf is None or result.matched_edges_gdf.empty:
                continue
            us = result.matched_edges_gdf['edge_u'].astype('int64')
            vs = result.matched_edges_gdf['edge_v'].astype('int64')
            traversed.update((min(u, v), max(u, v)) for u, v in zip(us.tolist(), vs.tolist()))
        return self._coverage_from_edges(traversed)

    def coverage_stats_from_state(self, streets_only: bool = False) -> dict:
        """Coverage stats from the persisted per-activity state (no matching)."""
        return self._coverage_from_edges(self.covered_edge_set(), streets_only=streets_only)

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
                    'length': self._edges_gdf['length'].to_numpy(),
                    'name': (self._edges_gdf['name'].to_numpy()
                             if 'name' in self._edges_gdf.columns else None),
                    'street': ([self._is_street(h) for h in self._edges_gdf['highway']]
                               if 'highway' in self._edges_gdf.columns else True),
                },
                geometry=self._edges_gdf.geometry.values,
                crs=self._edges_gdf.crs,
            )
            self._und_gdf = gdf.drop_duplicates(['u', 'v']).reset_index(drop=True)
        return self._und_gdf

    def undirected_with_covered(self, streets_only: bool = False,
                                with_counts: bool = False) -> gpd.GeoDataFrame:
        """Undirected edges flagged with whether the persisted state covers them.

        With with_counts, also carries a `times` column — the number of distinct
        activities that traversed each edge (0 when uncovered)."""
        und = self._undirected_gdf()
        if streets_only:
            und = und[und['street']]
        out = und.copy()
        us, vs = und['u'].tolist(), und['v'].tolist()
        if with_counts:
            counts = self.covered_edge_counts()
            times = [counts.get((u, v), 0) for u, v in zip(us, vs)]
            out['times'] = times
            out['covered'] = [t > 0 for t in times]
        else:
            covered = self.covered_edge_set()
            out['covered'] = [(u, v) in covered for u, v in zip(us, vs)]
        return out

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
        try:
            # osmnx ORs the tags dict, so admin_level must be filtered afterwards
            feats = ox.features_from_polygon(
                boundary_4326,
                tags={'boundary': 'administrative', 'admin_level': str(admin_level)},
            )
            if 'admin_level' in feats.columns:
                feats = feats[feats['admin_level'] == str(admin_level)]
            polys = self._named_polygons(feats)
        except ox._errors.InsufficientResponseError:
            polys = None

        if polys is None or len(polys) < 2:
            place_values = (['borough', 'suburb', 'city_district'] if admin_level <= 9
                            else ['quarter', 'neighbourhood'])
            logger.info("No admin boundaries at level %d for %s; falling back to place=%s",
                        admin_level, self.city_name, place_values)
            try:
                feats = ox.features_from_polygon(boundary_4326, tags={'place': place_values})
                polys = self._named_polygons(feats)
            except ox._errors.InsufficientResponseError:
                polys = gpd.GeoDataFrame({'name': []}, geometry=[], crs='EPSG:4326')

        polys = polys[['name', 'geometry']].reset_index(drop=True)
        polys = polys.to_crs(self._edges_gdf.crs)
        # The query polygon is a bbox-ish hull; drop polygons merely touching it
        polys = polys[polys.representative_point().within(self._city_boundary.union_all())]
        polys = polys.drop_duplicates('name').reset_index(drop=True)
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

    def _with_city_fallback(self, polys: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Collapse to a whole-city district when the mapped polygons cover too
        little of the city to be a real subdivision. Applied to both freshly
        fetched and cached polygons, so cities OSM doesn't subdivide (and any
        stale sparse cache) stay usable without re-querying OSM."""
        if len(polys):
            city_area = self._city_boundary.union_all().area
            if city_area > 0 and polys.union_all().area / city_area >= self.MIN_DISTRICT_COVERAGE:
                return polys
        return self._city_polygon_fallback()

    @staticmethod
    def _scoped_stats(scoped: gpd.GeoDataFrame) -> dict:
        total_m = float(scoped['length'].sum())
        covered_m = float(scoped.loc[scoped['covered'], 'length'].sum())
        return {
            'total_km': round(total_m / 1000, 2),
            'covered_km': round(covered_m / 1000, 2),
            'coverage_pct': round(100 * covered_m / total_m, 2) if total_m > 0 else 0.0,
            'num_streets': int(len(scoped)),
            'num_covered_streets': int(scoped['covered'].sum()),
        }

    @staticmethod
    def _round_coords(obj: list | float) -> list | float:
        if isinstance(obj, (list, tuple)):
            return [StravaMapMatcher._round_coords(x) for x in obj]
        return round(obj, 5)

    def coverage_by_district(self, admin_level: int = 9, include_geometry: bool = False,
                             streets_only: bool = False) -> list[dict]:
        """Coverage stats per administrative district, best-covered first.

        Edges are assigned to the district containing their representative
        point, so border streets count exactly once. With include_geometry,
        each district carries its simplified boundary as a GeoJSON geometry.
        """
        districts = self.load_districts(admin_level)
        und = self.undirected_with_covered(streets_only=streets_only)
        pts = und.copy()
        pts['geometry'] = und.representative_point()
        joined = gpd.sjoin(pts, districts[['name', 'geometry']],
                           predicate='within', how='inner')

        geoms_4326 = None
        if include_geometry:
            geoms_4326 = districts.set_index('name').geometry.simplify(20).to_crs('EPSG:4326')

        results = []
        for name, group in joined.groupby('name_right' if 'name_right' in joined.columns else 'name'):
            stats = self._scoped_stats(group)
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
        return self._scoped_stats(inside)

    def plot_coverage(
        self,
        match_results: dict[int | str, MatchResult] | None = None,
        save_path: Path | str | None = None,
        neon_color: str = '#fc0101',
        figsize: tuple[float, float] = (20, 20),
    ) -> plt.Figure:
        """Render a neon-glow coverage map of the city.

        Untraversed edges are shown as a dim network base layer.
        Traversed edges glow in neon (3-layer: atmosphere, glow, core).

        Args:
            match_results: dict returned by match(). When None, the persisted
                incremental state is used instead.
            save_path: Optional path to save the figure.
            neon_color: Colour for the neon glow.
            figsize: Figure size in inches.

        Returns:
            The matplotlib Figure.
        """
        stats = (self.coverage_stats(match_results) if match_results is not None
                 else self.coverage_stats_from_state())
        traversed_set: set[tuple[int, int]] = stats['_traversed_edge_set']

        # Partition edges into traversed / untraversed GeoDataFrames
        idx = self._edges_gdf.index
        us = idx.get_level_values(0).to_numpy()
        vs = idx.get_level_values(1).to_numpy()
        mask = np.fromiter(
            ((u, v) in traversed_set for u, v in zip(np.minimum(us, vs).tolist(), np.maximum(us, vs).tolist())),
            dtype=bool, count=len(us),
        )
        geoms = self._edges_gdf.geometry
        valid = geoms.notna().to_numpy() & ~geoms.is_empty.to_numpy()
        crs = self._edges_gdf.crs
        trav_gdf = gpd.GeoDataFrame(geometry=geoms[mask & valid].values, crs=crs)
        untrav_gdf = gpd.GeoDataFrame(geometry=geoms[~mask & valid].values, crs=crs)

        # --- Plot ---
        fig, ax = plt.subplots(figsize=figsize, facecolor='black')
        ax.set_facecolor('black')
        ax.set_axis_off()

        # Layer 0: Dim untraversed network
        if not untrav_gdf.empty:
            untrav_gdf.plot(ax=ax, color='#1c2333', linewidth=0.3, alpha=0.85, zorder=0)

        # Layer 1: City boundary outline
        if self._city_boundary is not None and not self._city_boundary.empty:
            self._city_boundary.boundary.plot(ax=ax, color='#30363d', linewidth=0.5, alpha=0.4, zorder=0)

        if not trav_gdf.empty:
            # Layer 2: Atmosphere (wide, very faint)
            trav_gdf.plot(ax=ax, color=neon_color, linewidth=6, alpha=0.03, zorder=1)
            # Layer 3: Glow (medium, soft)
            trav_gdf.plot(ax=ax, color=neon_color, linewidth=2.5, alpha=0.15, zorder=2)
            # Layer 4: Core (thin, bright white)
            trav_gdf.plot(ax=ax, color='white', linewidth=0.5, alpha=0.9, zorder=3)

        # Stats and title at bottom
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
