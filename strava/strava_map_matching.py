import json
import logging
import osmnx as ox
from leuvenmapmatching.matcher.distance import DistanceMatcher
from leuvenmapmatching.map.inmem import InMemMap
from leuvenmapmatching.util import dist_euclidean as _dist_euclidean
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
from pathlib import Path
from shapely.geometry import LineString, MultiLineString, Point, Polygon as ShapelyPolygon
from shapely.ops import linemerge
from shapely.prepared import prep
import numpy as np
from collections import defaultdict
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


@dataclass
class MatchResult:
    """Result of map matching a single activity."""
    activity_id: int | str
    original_geometry: LineString  # Original GPS track (projected CRS)
    matched_geometry: LineString | MultiLineString | None  # Real OSM edge geometries merged
    matched_edges_gdf: gpd.GeoDataFrame  # Individual matched OSM edges with attributes
    matching_details: gpd.GeoDataFrame   # Per-observation: obs point, snapped point, edge, distance
    quality: dict = field(default_factory=dict)

    def plot(self, figsize: tuple[float, float] = (14, 10),
            save_path: Path | str | None = None) -> plt.Figure:
        """Plot the match result: GPS track, matched OSM edges, and snapped points.

        Three layers are drawn:
        1. Matched OSM edges (solid, single colour)
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
        CLR_GPS_LINE = '#ff6b6b'
        CLR_GPS_PT = '#ff6b6b'
        CLR_SNAP_PT = '#7ee787'
        CLR_CONN = '#ffffff'
        CLR_TEXT = '#c9d1d9'
        CLR_TEXT_DIM = '#8b949e'

        fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
        ax.set_facecolor(BG)

        # --- 1. Matched OSM edges ---
        if not self.matched_edges_gdf.empty:
            for _, edge_row in self.matched_edges_gdf.iterrows():
                geom = edge_row.geometry
                if isinstance(geom, LineString):
                    xs, ys = geom.xy
                    ax.plot(xs, ys, color=CLR_EDGES, linewidth=2.5, alpha=0.8,
                            solid_capstyle='round', zorder=2)
                elif isinstance(geom, MultiLineString):
                    for part in geom.geoms:
                        xs, ys = part.xy
                        ax.plot(xs, ys, color=CLR_EDGES, linewidth=2.5, alpha=0.8,
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
            f"{q.get('num_matched_edges', '?')} edges, "
            f"avg snap {q.get('avg_dist_obs_m', '?')} m, "
            f"max snap {q.get('max_dist_obs_m', '?')} m"
        )
        subtitle = (
            f"Obs: {q.get('num_observations', '?')}  |  "
            f"Matched: {q.get('num_matched', '?')}  |  "
            f"Early stop: {q.get('early_stop_idx', None)}"
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

    def __init__(self, city_name: str, workdir: Path, force_reload: bool = False):
        """
        Initialize the StravaMapMatcher with a specified city name.

        :param city_name: Name of the city to load the street network for.
        """
        self.city_name = city_name
        self.workdir = workdir / "osm_maps"
        self.workdir.mkdir(parents=True, exist_ok=True)

        self._nodes_gdf: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._edges_gdf: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._map_con: InMemMap | None = None
        self._city_boundary: gpd.GeoDataFrame = None  # type: ignore[assignment]
        self._und_gdf: gpd.GeoDataFrame | None = None

        self._load_map(force_reload=force_reload)

        # Build a lookup for edges by (u, v) ignoring key — for fast edge geometry retrieval
        self._edge_lookup: dict[tuple[int, int], tuple] = {}
        for idx_tuple in self._edges_gdf.index:
            u, v = idx_tuple[0], idx_tuple[1]
            if (u, v) not in self._edge_lookup:
                self._edge_lookup[(u, v)] = idx_tuple

        logger.info(
            "Map for %s loaded with %d edges and %d nodes",
            self.city_name, len(self._edges_gdf), len(self._nodes_gdf),
        )

    def _matcher_map_name(self) -> str:
        return f"{self._slug()}_inmem"

    def _build_matcher_map(self):
        """
        Build the InMemMap required for the DistanceMatcher, cached on disk.

        The graph dict is built vectorized and handed to InMemMap whole so the
        rtree is bulk-loaded from a generator instead of one insert per edge,
        then persisted (pickle + file-based rtree) for fast reloads. Edges are
        bidirectional to allow matching against traffic.
        """
        map_name = self._matcher_map_name()
        pkl_path = self.workdir / f"{map_name}.pkl"
        # setup_index() only reuses the on-disk rtree if this marker exists
        # (the rtree itself lives in <map_name>.idx/.dat).
        rtree_marker = self.workdir / map_name

        if pkl_path.exists() and rtree_marker.exists():
            self._map_con = InMemMap.from_pickle(pkl_path)
            logger.info("Loaded matcher map from %s", pkl_path)
            return

        neighbors: dict[int, set[int]] = defaultdict(set)
        us = self._edges_gdf.index.get_level_values(0).to_numpy().tolist()
        vs = self._edges_gdf.index.get_level_values(1).to_numpy().tolist()
        for u, v in zip(us, vs):
            neighbors[u].add(v)
            neighbors[v].add(u)

        node_ids = self._nodes_gdf.index.to_numpy().tolist()
        xs = self._nodes_gdf['x'].to_numpy().tolist()
        ys = self._nodes_gdf['y'].to_numpy().tolist()
        graph = {
            nid: ((x, y), sorted(neighbors[nid]))
            for nid, x, y in zip(node_ids, xs, ys)
        }

        # Stale rtree files would otherwise be reopened by the bulk loader
        for suffix in ('.dat', '.idx'):
            (self.workdir / (map_name + suffix)).unlink(missing_ok=True)

        map_con = InMemMap(map_name, use_latlon=False, index_edges=True,
                           use_rtree=True, dir=self.workdir, graph=graph)
        map_con.dump()
        rtree_marker.touch()
        self._map_con = map_con
        logger.info("Built matcher map and cached to %s", pkl_path)

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

    def _filter_runnable(self, edges_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Reduce the raw OSM network to runnable streets.

        This subset is both the matching target and the coverage denominator:
        matching directly against it makes a sidewalk run snap to (and credit)
        the street itself. Excluded: sidewalks and crossings mapped as
        separate ways, motorways, service roads (parking aisles, driveways),
        steps, and private-access ways.
        """
        def keep(highway, footway, access) -> bool:
            if self._as_tags(access) & self.EXCLUDED_ACCESS:
                return False
            hw = self._as_tags(highway)
            if hw & self.RUNNABLE_HIGHWAYS:
                return True
            if 'footway' in hw:
                return not (self._as_tags(footway) & self.EXCLUDED_FOOTWAY_TYPES)
            return False

        footway_col = edges_gdf['footway'] if 'footway' in edges_gdf.columns else pd.Series(None, index=edges_gdf.index)
        access_col = edges_gdf['access'] if 'access' in edges_gdf.columns else pd.Series(None, index=edges_gdf.index)
        mask = [
            keep(h, f, a)
            for h, f, a in zip(edges_gdf['highway'], footway_col, access_col)
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
        if not meta_fp.exists():
            meta_fp.write_text(json.dumps({'city_name': self.city_name}))

        if not force_reload and nodes_fp.exists() and edges_fp.exists() and boundary_fp.exists():
            self._edges_gdf = gpd.read_parquet(edges_fp).set_index(['u', 'v', 'key'])
            nodes = pd.read_parquet(nodes_fp).set_index('osmid')
            self._nodes_gdf = nodes  # type: ignore[assignment]
            self._city_boundary = gpd.read_parquet(boundary_fp)
            return

        logger.info("Downloading map for %s from OSM...", self.city_name)
        # The footway subtag distinguishes sidewalks/crossings (excluded)
        # from real park paths (kept); it is not in osmnx defaults.
        if 'footway' not in ox.settings.useful_tags_way:
            ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ['footway']
        graph = ox.graph_from_place(self.city_name, network_type='all')
        city_boundary = ox.geocode_to_gdf(self.city_name)
        graph_proj = ox.project_graph(graph)
        nodes_gdf, edges_gdf = ox.graph_to_gdfs(graph_proj, edges=True, nodes=True)
        city_boundary_gdf = city_boundary.to_crs(edges_gdf.crs)

        edges_gdf = self._filter_runnable(edges_gdf)
        used_nodes = set(edges_gdf.index.get_level_values(0)) | set(edges_gdf.index.get_level_values(1))
        nodes_gdf = nodes_gdf[nodes_gdf.index.isin(used_nodes)]

        # Slim to what matching/coverage needs; 2m geometry tolerance is well
        # below GPS accuracy.
        slim_edges = edges_gdf.reset_index()[
            [c for c in ('u', 'v', 'key', 'highway', 'name', 'footway', 'length', 'geometry')
             if c in edges_gdf.reset_index().columns]
        ].copy()
        slim_edges['geometry'] = slim_edges['geometry'].simplify(2.0)
        for col in ('highway', 'name', 'footway'):
            if col in slim_edges.columns:
                slim_edges[col] = slim_edges[col].apply(
                    lambda v: str(v) if isinstance(v, (list, tuple)) else v)
        slim_nodes = nodes_gdf.reset_index()[['osmid', 'x', 'y']]

        slim_edges.to_parquet(edges_fp)
        slim_nodes.to_parquet(nodes_fp)
        city_boundary_gdf.to_parquet(boundary_fp)
        logger.info("Runnable map for %s saved to %s (%d edges, %d nodes)",
                    self.city_name, self.workdir, len(slim_edges), len(slim_nodes))

        self._edges_gdf = slim_edges.set_index(['u', 'v', 'key'])
        self._nodes_gdf = slim_nodes.set_index('osmid')  # type: ignore[assignment]
        self._city_boundary = city_boundary_gdf

        # Invalidate the cached matcher map — it derives from this graph
        map_name = self._matcher_map_name()
        for suffix in ('.pkl', '.dat', '.idx', ''):
            (self.workdir / (map_name + suffix)).unlink(missing_ok=True)

    def _get_edge_geometry(self, u: int, v: int) -> LineString | None:
        """Look up the real OSM edge geometry for (u, v), trying reverse direction too."""
        for key in [(u, v), (v, u)]:
            if key in self._edge_lookup:
                full_key = self._edge_lookup[key]
                return self._edges_gdf.loc[full_key, 'geometry']
        return None

    def _get_edge_row(self, u: int, v: int) -> pd.Series | None:
        """Look up full edge data for (u, v), trying reverse direction too."""
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

    @staticmethod
    def _split_by_distance(coords: list[tuple], max_gap_m: float = 100.0) -> list[list[tuple]]:
        """Split a coordinate list at consecutive points further than max_gap_m apart."""
        n = len(coords)
        if n < 2:
            return []

        a = np.asarray(coords)           # shape (n, 2)
        d = np.diff(a, axis=0)                             # shape (n-1, 2)
        dist2 = (d * d).sum(axis=1)
        cuts = np.nonzero(dist2 > (max_gap_m * max_gap_m))[0] + 1

        parts = np.split(a, cuts)                          # [web:25]
        # Keep only segments with >= 2 points; convert back to list[tuple]
        return [list(map(tuple, p)) for p in parts if len(p) >= 2]

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

        Each row maps a lattice state to its matched OSM edge and snapped point.
        """
        records = []

        for m in matcher.lattice_best:
            obs_idx = m.obs
            obs_ne = m.obs_ne
            is_emitting = obs_ne == 0

            obs_coord = path[obs_idx] if obs_idx < len(path) else None
            edge_u = m.edge_m.l1
            edge_v = m.edge_m.l2
            matcher_snapped = m.edge_m.pi if m.edge_m.pi is not None else m.edge_m.p1

            # Re-project onto real curved OSM edge geometry
            snapped_point = None
            if edge_v is not None:
                real_geom = self._get_edge_geometry(edge_u, edge_v)
                if real_geom is not None and obs_coord is not None:
                    obs_point_geom = Point(obs_coord)
                    frac = real_geom.project(obs_point_geom, normalized=True)
                    snapped_point = real_geom.interpolate(frac, normalized=True)
                else:
                    snapped_point = Point(matcher_snapped) if matcher_snapped is not None else None
            else:
                node_coords = self._nodes_gdf.loc[edge_u, ['x', 'y']].values
                snapped_point = Point(node_coords)

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
            u, v = m.edge_m.l1, m.edge_m.l2
            if v is None:
                continue
            edge_key = (u, v)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                ordered_edges.append(edge_key)

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

            record = {'edge_u': u, 'edge_v': v, 'geometry': geom}
            for col in ['highway', 'name', 'length', 'oneway', 'maxspeed', 'osmid']:
                if col in edge_row.index:
                    record[col] = edge_row[col]

            edge_records.append(record)
            edge_geoms.append(geom)

        if not edge_records:
            return gpd.GeoDataFrame(), None

        edges_gdf = gpd.GeoDataFrame(edge_records, geometry='geometry', crs=utm_crs)
        merged = linemerge(MultiLineString(edge_geoms))

        return edges_gdf, merged

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

            if not all_edges_gdfs or all(df.empty for df in all_edges_gdfs):
                logger.warning("No match found for activity %s", activity_id)
                continue

            # Merge all segments
            matched_edges_gdf = pd.concat(all_edges_gdfs, ignore_index=True)  # type: ignore[assignment]
            matching_details = pd.concat(all_details_dfs, ignore_index=True)  # type: ignore[assignment]

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
                'num_matched_edges': len(matched_edges_gdf),
                'avg_dist_obs_m': round(float(avg_dist), 2) if avg_dist is not None else None,
                'max_dist_obs_m': round(float(max_dist), 2) if max_dist is not None else None,
                'coverage_pct': round(100 * total_matched / len(full_path), 1) if full_path else 0,
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
                "Activity %s: %d edges, avg snap %sm, %d/%d sub-segments, coverage %s%%",
                activity_id,
                quality['num_matched_edges'],
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

    def matched_activity_ids(self) -> set:
        """Ids of activities already matched (or attempted) against this city."""
        _, meta_fp = self._state_paths()
        if not meta_fp.exists():
            return set()
        return set(pd.read_parquet(meta_fp)['activity_id'])

    def covered_edge_set(self) -> set[tuple[int, int]]:
        """Unique undirected edges covered so far, from the persisted state."""
        edges_fp, _ = self._state_paths()
        if not edges_fp.exists():
            return set()
        df = pd.read_parquet(edges_fp)
        return set(zip(df['u'].tolist(), df['v'].tolist()))

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

        if edge_rows:
            new_edges = pd.DataFrame(edge_rows)
            if edges_fp.exists():
                new_edges = pd.concat([pd.read_parquet(edges_fp), new_edges], ignore_index=True)
            new_edges.drop_duplicates(['activity_id', 'u', 'v']).to_parquet(edges_fp)
        if meta_rows:
            new_meta = pd.DataFrame(meta_rows)
            if meta_fp.exists():
                new_meta = pd.concat([pd.read_parquet(meta_fp), new_meta], ignore_index=True)
            new_meta.drop_duplicates('activity_id', keep='last').to_parquet(meta_fp)

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
        return self.coverage_stats_from_state()

    def _undirected_edges(self) -> pd.DataFrame:
        idx = self._edges_gdf.index
        u = idx.get_level_values(0).to_numpy()
        v = idx.get_level_values(1).to_numpy()
        df = pd.DataFrame({
            'u': np.minimum(u, v),
            'v': np.maximum(u, v),
            'length': self._edges_gdf['length'].to_numpy(),
        })
        return df.drop_duplicates(['u', 'v'])

    def _coverage_from_edges(self, traversed: set[tuple[int, int]]) -> dict:
        und = self._undirected_edges()
        total_length_m = float(und['length'].sum())
        covered_mask = [
            (u, v) in traversed for u, v in zip(und['u'].tolist(), und['v'].tolist())
        ]
        traversed_length_m = float(und.loc[covered_mask, 'length'].sum())

        stats = {
            'total_network_km': round(total_length_m / 1000, 2),
            'traversed_km': round(traversed_length_m / 1000, 2),
            'coverage_pct': round(100 * traversed_length_m / total_length_m, 2) if total_length_m > 0 else 0,
            'num_unique_streets': len(traversed),
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

    def coverage_stats_from_state(self) -> dict:
        """Coverage stats from the persisted per-activity state (no matching)."""
        return self._coverage_from_edges(self.covered_edge_set())

    # ------------------------------------------------------------------
    # Scoped coverage: districts & arbitrary areas
    # ------------------------------------------------------------------

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
                },
                geometry=self._edges_gdf.geometry.values,
                crs=self._edges_gdf.crs,
            )
            self._und_gdf = gdf.drop_duplicates(['u', 'v']).reset_index(drop=True)
        return self._und_gdf

    def undirected_with_covered(self) -> gpd.GeoDataFrame:
        """Undirected edges flagged with whether the persisted state covers them."""
        und = self._undirected_gdf()
        covered = self.covered_edge_set()
        out = und.copy()
        out['covered'] = [
            (u, v) in covered for u, v in zip(und['u'].tolist(), und['v'].tolist())
        ]
        return out

    def load_districts(self, admin_level: int = 9, force_reload: bool = False) -> gpd.GeoDataFrame:
        """Administrative districts of the city (cached parquet).

        admin_level 9 = districts, 10 = neighborhoods (OSM convention for ES;
        varies by country).
        """
        fp = self.workdir / f"{self._slug()}_districts_{admin_level}.parquet"
        if fp.exists() and not force_reload:
            return gpd.read_parquet(fp)

        logger.info("Downloading admin_level=%d boundaries for %s...", admin_level, self.city_name)
        # osmnx ORs the tags dict, so admin_level must be filtered afterwards
        feats = ox.features_from_place(
            self.city_name,
            tags={'boundary': 'administrative', 'admin_level': str(admin_level)},
        )
        if 'admin_level' in feats.columns:
            feats = feats[feats['admin_level'] == str(admin_level)]
        polys = feats[feats.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])]
        polys = polys.dropna(subset=['name'])[['name', 'geometry']].reset_index(drop=True)
        polys = polys.to_crs(self._edges_gdf.crs)
        # features_from_place can return boundaries that merely touch the city
        polys = polys[polys.representative_point().within(self._city_boundary.union_all())]
        polys = polys.drop_duplicates('name').reset_index(drop=True)
        polys.to_parquet(fp)
        logger.info("Saved %d districts to %s", len(polys), fp)
        return polys

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

    def coverage_by_district(self, admin_level: int = 9) -> list[dict]:
        """Coverage stats per administrative district, best-covered first.

        Edges are assigned to the district containing their representative
        point, so border streets count exactly once.
        """
        districts = self.load_districts(admin_level)
        und = self.undirected_with_covered()
        pts = und.copy()
        pts['geometry'] = und.representative_point()
        joined = gpd.sjoin(pts, districts[['name', 'geometry']],
                           predicate='within', how='inner')

        results = []
        for name, group in joined.groupby('name_right' if 'name_right' in joined.columns else 'name'):
            stats = self._scoped_stats(group)
            geom = districts.loc[districts['name'] == name, 'geometry']
            bounds = gpd.GeoSeries(geom, crs=districts.crs).to_crs('EPSG:4326').total_bounds
            results.append({
                'name': name,
                **stats,
                # [south, west, north, east] for map fitBounds
                'bbox': [round(bounds[1], 5), round(bounds[0], 5),
                         round(bounds[3], 5), round(bounds[2], 5)],
            })
        return sorted(results, key=lambda r: r['coverage_pct'], reverse=True)

    def coverage_in_polygon(self, latlon_coords: list[tuple[float, float]]) -> dict:
        """Coverage stats within an arbitrary polygon of (lat, lon) vertices."""
        poly = ShapelyPolygon([(lon, lat) for lat, lon in latlon_coords])
        poly_proj = gpd.GeoSeries([poly], crs='EPSG:4326').to_crs(self._edges_gdf.crs).iloc[0]
        und = self.undirected_with_covered()
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
