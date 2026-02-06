import osmnx as ox
from leuvenmapmatching.matcher.distance import DistanceMatcher
from leuvenmapmatching.map.inmem import InMemMap
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
from pathlib import Path
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge
from dataclasses import dataclass, field


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
            print(f"\U0001f4ca Saved plot to {save_path}")

        return fig


class StravaMapMatcher:
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

        self._load_map(force_reload=force_reload)

        # Build a lookup for edges by (u, v) ignoring key — for fast edge geometry retrieval
        self._edge_lookup: dict[tuple[int, int], tuple] = {}
        for idx_tuple in self._edges_gdf.index:
            u, v = idx_tuple[0], idx_tuple[1]
            if (u, v) not in self._edge_lookup:
                self._edge_lookup[(u, v)] = idx_tuple

        print(f"🏙️ Map for {self.city_name} loaded with {len(self._edges_gdf)} edges "
              f"and {len(self._nodes_gdf)} nodes")

    def _build_matcher_map(self):
        """
        Build the InMemMap required for the DistanceMatcher from the loaded OSMnx graph.
        Explicitly adds bidirectional edges to allow matching against traffic.
        """
        map_con = InMemMap("osm_map", use_latlon=False, index_edges=True, use_rtree=True)

        for nid, row in self._nodes_gdf[['x', 'y']].iterrows():
            map_con.add_node(nid, (row['x'], row['y']))

        for eid, row in self._edges_gdf.iterrows():
            u, v = eid[0], eid[1]
            map_con.add_edge(u, v)
            map_con.add_edge(v, u)  # Bidirectional for running/walking/cycling

        self._map_con = map_con

    def _load_map(self, force_reload: bool = False):
        """
        Load the street network for the specified city using OSMnx.
        """
        filename = f"{self.city_name.replace(', ', '_').lower()}.gpkg"
        filepath = self.workdir / filename

        if filepath.exists() and not force_reload:
            self._edges_gdf = gpd.read_file(filepath, layer='edges')
            self._nodes_gdf = gpd.read_file(filepath, layer='nodes')
            self._city_boundary = gpd.read_file(filepath, layer='city_boundary')

            if 'u' in self._edges_gdf.columns and 'v' in self._edges_gdf.columns:
                if 'key' in self._edges_gdf.columns:
                    self._edges_gdf = self._edges_gdf.set_index(['u', 'v', 'key'])
                else:
                    self._edges_gdf = self._edges_gdf.set_index(['u', 'v'])

            if 'osmid' in self._nodes_gdf.columns:
                self._nodes_gdf = self._nodes_gdf.set_index('osmid')
        else:
            print(f"🌐 Downloading map for {self.city_name} from OSM...")
            graph = ox.graph_from_place(self.city_name, network_type='all')
            city_boundary = ox.geocode_to_gdf(self.city_name)
            graph_proj = ox.project_graph(graph)
            nodes_gdf, edges_gdf = ox.graph_to_gdfs(graph_proj, edges=True, nodes=True)
            city_boundary_gdf = city_boundary.to_crs(edges_gdf.crs)
            edges_gdf.to_file(filepath, layer='edges', driver='GPKG')
            nodes_gdf.to_file(filepath, layer='nodes', driver='GPKG')
            city_boundary_gdf.to_file(filepath, layer='city_boundary', driver='GPKG')
            print(f"✅ Map for {self.city_name} saved to {filepath}")
            self._edges_gdf = edges_gdf
            self._nodes_gdf = nodes_gdf
            self._city_boundary = city_boundary_gdf

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

    def _create_matcher(self) -> DistanceMatcher:
        """Create a fresh DistanceMatcher instance."""
        if self._map_con is None:
            self._build_matcher_map()

        return DistanceMatcher(
            self._map_con,
            max_dist=200,
            max_dist_init=100,
            min_prob_norm=0.0001,
            non_emitting_length_factor=0.9,
            obs_noise=50,
            dist_noise=50,
            max_lattice_width=20,
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
            path = list(geom.coords)

            # Fresh matcher per activity to avoid stale state
            matcher = self._create_matcher()

            try:
                states, last_idx = matcher.match(path)

                if not states or len(states) == 0:
                    print(f"⚠️ No match found for activity {activity_id}")
                    continue

                # 1. Build matched edges with real OSM geometries
                matched_edges_gdf, matched_geometry = self._build_matched_edges(matcher, utm_crs)

                # 2. Build per-observation matching details
                matching_details = self._build_matching_details(matcher, path, utm_crs)

                # 3. Quality metrics
                avg_dist = matching_details['dist_obs'].mean() if not matching_details.empty else None
                max_dist = matching_details['dist_obs'].max() if not matching_details.empty else None
                n_emitting = matching_details['is_emitting'].sum() if not matching_details.empty else 0

                quality = {
                    'num_observations': len(path),
                    'num_matched': last_idx + 1,
                    'num_emitting_states': int(n_emitting),
                    'num_matched_edges': len(matched_edges_gdf),
                    'avg_dist_obs_m': round(float(avg_dist), 2) if avg_dist is not None else None,
                    'max_dist_obs_m': round(float(max_dist), 2) if max_dist is not None else None,
                    'matched_path_distance_m': matcher.path_pred_distance(),
                    'observation_distance_m': matcher.path_distance(),
                    'early_stop_idx': matcher.early_stop_idx,
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
                result['matched_distance_m'] = quality['matched_path_distance_m']
                result['early_stop_idx'] = quality['early_stop_idx']
                matched_rows.append(result)

                print(f"✅ Activity {activity_id}: {quality['num_matched_edges']} edges, "
                      f"avg snap dist {quality['avg_dist_obs_m']}m, "
                      f"early_stop={quality['early_stop_idx']}")

            except Exception as e:
                print(f"❌ Error matching activity {activity_id}: {e}")
                continue

        if not matched_rows:
            print("⚠️ No activities were successfully matched")
            return gpd.GeoDataFrame(), match_results

        result_gdf = gpd.GeoDataFrame(matched_rows, geometry='matched_geometry', crs=utm_crs)
        return result_gdf, match_results
