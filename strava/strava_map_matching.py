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
from shapely.prepared import prep
import numpy as np
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
                print(f"⚠️ Activity {activity_id}: no GPS points within city boundary")
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
                        print(f"  ⚠️ Sub-segment {sub_id} failed: {e}")
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
                print(f"⚠️ No match found for activity {activity_id}")
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

            print(f"✅ Activity {activity_id}: {quality['num_matched_edges']} edges, "
                  f"avg snap {quality['avg_dist_obs_m']}m, "
                  f"{quality['num_sub_segments_matched']}/{quality['num_sub_segments']} sub-segments, "
                  f"coverage {quality['coverage_pct']}%")

        if not matched_rows:
            print("⚠️ No activities were successfully matched")
            return gpd.GeoDataFrame(), match_results

        result_gdf = gpd.GeoDataFrame(matched_rows, geometry='matched_geometry', crs=utm_crs)
        return result_gdf, match_results

    # ------------------------------------------------------------------
    # Coverage analysis
    # ------------------------------------------------------------------

    def coverage_stats(
        self, match_results: dict[int | str, MatchResult]
    ) -> dict:
        """Compute city-wide street coverage statistics.

        Deduplicates edges across all matched activities (an edge traversed
        ten times still counts as one) and computes the fraction of the
        full network covered.

        Returns a dict with:
            total_network_km   – total length of the OSM network in km
            traversed_km       – unique edge length traversed in km
            coverage_pct       – traversed / total * 100
            num_unique_streets – number of unique undirected edges matched
            _traversed_edge_set – set of (min(u,v), max(u,v)) for plot_coverage
        """
        # Collect unique undirected edges across all activities
        traversed: set[tuple[int, int]] = set()
        for result in match_results.values():
            if result.matched_edges_gdf is None or result.matched_edges_gdf.empty:
                continue
            for _, row in result.matched_edges_gdf.iterrows():
                u, v = int(row['edge_u']), int(row['edge_v'])
                traversed.add((min(u, v), max(u, v)))

        # Sum traversed edge lengths
        traversed_length_m = 0.0
        for u, v in traversed:
            edge_row = self._get_edge_row(u, v)
            if edge_row is not None and 'length' in edge_row.index:
                traversed_length_m += float(edge_row['length'])

        # Total network length (undirected)
        total_length_m = 0.0
        seen: set[tuple[int, int]] = set()
        for idx_tuple in self._edges_gdf.index:
            u, v = idx_tuple[0], idx_tuple[1]
            key = (min(u, v), max(u, v))
            if key not in seen:
                seen.add(key)
                total_length_m += float(self._edges_gdf.loc[idx_tuple, 'length'])

        stats = {
            'total_network_km': round(total_length_m / 1000, 2),
            'traversed_km': round(traversed_length_m / 1000, 2),
            'coverage_pct': round(100 * traversed_length_m / total_length_m, 2) if total_length_m > 0 else 0,
            'num_unique_streets': len(traversed),
            '_traversed_edge_set': traversed,
        }

        print(f"📊 Coverage: {stats['traversed_km']} km / {stats['total_network_km']} km "
              f"({stats['coverage_pct']}%) — {stats['num_unique_streets']} unique edges")

        return stats

    def plot_coverage(
        self,
        match_results: dict[int | str, MatchResult],
        save_path: Path | str | None = None,
        neon_color: str = '#fc0101',
        figsize: tuple[float, float] = (20, 20),
    ) -> plt.Figure:
        """Render a neon-glow coverage map of the city.

        Untraversed edges are shown as a dim network base layer.
        Traversed edges glow in neon (3-layer: atmosphere, glow, core).

        Args:
            match_results: dict returned by match().
            save_path: Optional path to save the figure.
            neon_color: Colour for the neon glow.
            figsize: Figure size in inches.

        Returns:
            The matplotlib Figure.
        """
        stats = self.coverage_stats(match_results)
        traversed_set: set[tuple[int, int]] = stats['_traversed_edge_set']

        # Partition edges into traversed / untraversed GeoDataFrames
        trav_rows = []
        untrav_rows = []
        for idx_tuple in self._edges_gdf.index:
            u, v = idx_tuple[0], idx_tuple[1]
            key = (min(u, v), max(u, v))
            geom = self._edges_gdf.loc[idx_tuple, 'geometry']
            if geom is None or geom.is_empty:
                continue
            if key in traversed_set:
                trav_rows.append({'geometry': geom})
            else:
                untrav_rows.append({'geometry': geom})

        crs = self._edges_gdf.crs
        untrav_gdf = gpd.GeoDataFrame(untrav_rows, geometry='geometry', crs=crs) if untrav_rows else gpd.GeoDataFrame()
        trav_gdf = gpd.GeoDataFrame(trav_rows, geometry='geometry', crs=crs) if trav_rows else gpd.GeoDataFrame()

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
            print(f"🗺️ Coverage map saved to {save_path}")

        return fig
