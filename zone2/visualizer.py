from zone2.analytics import StravaAnalytics
from zone2.utils import get_activities_as_gdf, get_region_coordinates, format_pace_or_speed, convert_speed, get_sport_category
from zone2.constants import WEB_MERCATOR_CRS, BASE_CRS
from zone2.analytics import WeeklyReportFeatures

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import geopandas as gpd
import pandas as pd
from pathlib import Path
from shapely.geometry import Point, LineString
import numpy as np
import matplotlib.ticker as ticker
from datetime import datetime
import logging
import threading
from io import BytesIO

logger = logging.getLogger(__name__)



class StravaVisualizer:
    _mpl_lock = threading.Lock()

    def __init__(self, strava_analytics: StravaAnalytics, workdir: Path):
        self.strava_analytics = strava_analytics
        self.workdir = workdir
        self.output_dir = self.workdir / "visualizations"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # (activities version, activities with their summary routes, EPSG:4326)
        self._activities_gdf: tuple[int, gpd.GeoDataFrame] | None = None

    def _activities_with_routes(self) -> gpd.GeoDataFrame:
        """Every activity with a summary route, decoded once per activities
        version (every map export filters these). Callers must not modify it."""
        cache = self.strava_analytics.strava_activities_cache
        if self._activities_gdf is None or self._activities_gdf[0] != cache.cache_version:
            gdf = get_activities_as_gdf(cache.activities)
            if 'start_date_local' in gdf.columns:
                gdf['start_date_local'] = pd.to_datetime(gdf['start_date_local'])
            self._activities_gdf = (cache.cache_version, gdf)
        return self._activities_gdf[1]

    def _finalize_figure(
        self,
        fig,
        save_path: Path | None,
        dpi: int = 300,
        facecolor: str = 'black',
        return_buffer: bool = False,
        **kwargs
    ) -> BytesIO | None:
        try:
            if return_buffer:
                buf = BytesIO()
                fig.savefig(buf, format='png', dpi=dpi, facecolor=facecolor, bbox_inches='tight', **kwargs)
                buf.seek(0)
                return buf
            if save_path:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(save_path, dpi=dpi, facecolor=facecolor, bbox_inches='tight', **kwargs)
            return None
        finally:
            plt.close(fig)

    def _get_centroid_of_map(self, gdf: gpd.GeoDataFrame, center_latlon: tuple[float, float] | None) -> Point:
        """
        Determines the map center.
        """
        if center_latlon is not None:
            return gpd.GeoDataFrame(geometry=[Point(center_latlon[1], center_latlon[0])], 
                                    crs=BASE_CRS).to_crs(WEB_MERCATOR_CRS).iloc[0].geometry

        # Fallback: Calculate median centroid of all activities
        centroids = gdf.geometry.centroid
        return Point(
            np.median(centroids.x),
            np.median(centroids.y)
        )

    def _filter_and_get_gdf(self, sport_types: list[str] | None = None,
                            radius_km: float | None = None,
                            location: str | None = None,
                            filter_by_boundary: bool = False,
                            year: int | None = None) -> tuple[gpd.GeoDataFrame | None, dict | None]:
        """Filters by sport/year, projects to WebMercator, and spatially filters by radius or boundary."""
        gdf = self._activities_with_routes()

        if sport_types:
            gdf = gdf[gdf['sport_type'].isin(sport_types)]

        if year and 'start_date_local' in gdf.columns:
            gdf = gdf[gdf['start_date_local'].dt.year == year]
            
        if gdf.empty:
            logger.info("No activities found for %s", sport_types)
            return None, None
        
        # get region_coordinates if location is provided
        region_coords = get_region_coordinates(location) if location else None
        if region_coords is None:
            return gdf.to_crs(WEB_MERCATOR_CRS), None
        
        if radius_km is not None:
            # Project to WebMercator for distance calculations
            gdf = gdf.to_crs(WEB_MERCATOR_CRS)

            # Determine centroid of the map in WebMercator
            centroid = self._get_centroid_of_map(gdf, (region_coords['lat'], region_coords['lon']))       

            # Filter data on a ~ radius_km as we use WebMercator 
            gdf['dist_to_centroid'] = gdf.geometry.distance(centroid)
            gdf = gdf[gdf['dist_to_centroid'] < radius_km * 1e3]

        elif filter_by_boundary:
            # Use bounding box from OSM to filter activities
            bbox_polygon = region_coords['boundingbox']
            # Ensure we are comparing in Lat/Lon (BASE_CRS) because bbox is Lat/Lon
            gdf_latlon = gdf.to_crs(BASE_CRS)
            
            # Use INTERSECTS instead of WITHIN to keep runs that cross the border
            mask = gdf_latlon.geometry.intersects(bbox_polygon)
            gdf = gdf_latlon[mask]
            
            # Convert result to WebMercator for final plotting
            gdf = gdf.to_crs(WEB_MERCATOR_CRS)
        
        # Fallback: Location provided but no filter method (radius/boundary) selected
        # Usually we just return the full dataset projected
        else:
             gdf = gdf.to_crs(WEB_MERCATOR_CRS)

        return gdf, region_coords

    def thunderstorm_heatmap(
            self,
            location: str | None = None,
            sport_types: list[str] | None = None,
            radius_km: float = 20.0,
            add_basemap: bool = False,
            neon_color: str = "#fc0101", # Cyan default, try '#FF00FF' for Magenta
            show_title: bool = True,
            return_buffer: bool = False,
            year: int | None = None,
            dpi: int | None = None,
            ) -> BytesIO | None:
        """
        Generates a high-contrast 'Neon' visualization of activities.
        """
        gdf, _ = self._filter_and_get_gdf(sport_types, radius_km, location, year=year)
        if gdf is None or gdf.empty:
            logger.info("No data found for the specified parameters.")
            return

        # Setup the 'Dark Mode' canvas
        fig, ax = plt.subplots(figsize=(15, 15), facecolor='black')
        ax.set_facecolor('black')

        # --- THE NEON EFFECT ---
        # Layer 1: The "Atmosphere" (Wide, very faint glow)
        gdf.plot(ax=ax, color=neon_color, linewidth=6, alpha=0.03, zorder=1)
        
        # Layer 2: The "Glow" (Medium, soft light)
        gdf.plot(ax=ax, color=neon_color, linewidth=2, alpha=0.15, zorder=2)
        
        # Layer 3: The "Core" (Thin, bright white center)
        gdf.plot(ax=ax, color='white', linewidth=0.6, alpha=0.9, zorder=3)

        # Optional Basemap
        if add_basemap:
            try:
                # Imported here: contextily (and rasterio under it) is heavy and only maps need it.
                import contextily as ctx
                # DarkMatterOnlyLabels places street names *on top* of the glow, which looks cool
                # DarkMatterNoLabels places just the map background
                ctx.add_basemap(
                    ax, 
                    source=ctx.providers.CartoDB.DarkMatterOnlyLabels, 
                    alpha=0.4,
                    zoom_adjust=1 # Higher res tiles
                )
            except Exception as e:
                logger.warning("Basemap warning: %s", e)

        ax.set_axis_off()
        
        # Summary stats
        total_dist_km = gdf['distance'].sum() / 1000.0
        
        # Formatter: "MADRID | RUNNING | 1,230 KM"
        loc_str = location.upper() if location else None
        sport_str = " / ".join(sport_types).upper() if sport_types else "ALL SPORTS"
        dist_str = f"{total_dist_km:.0f} KM"
        if show_title:
            title_text = f"{loc_str} | {sport_str} | {dist_str}" if loc_str else f"{sport_str} | {dist_str}"

            plt.title(
                title_text, 
                color=neon_color, 
                fontsize=22, 
                fontfamily='monospace',
                fontweight='bold',
                pad=25,
                loc='center'
            )

        # Set limits to the data bounds
        minx, miny, maxx, maxy = gdf.total_bounds
        ax.set_xlim(minx , maxx)
        ax.set_ylim(miny, maxy)
        ax.set_aspect('equal')

        # Save
        filename = f"thunderstorm_{location or 'median'}_{sport_str.replace(' ', '_')}.png"
        save_path = self.output_dir / filename.lower()

        result = self._finalize_figure(fig, save_path, dpi=dpi or 600, return_buffer=return_buffer, pad_inches=0.2)
        if not return_buffer:
            logger.info("Thunderstorm map saved to: %s", save_path)
        return result

    def activity_bubble_map(
            self,
            region: str,  # 'Europe', 'Spain', or None for World
            sport_types: list[str] | None = None,
            min_radius_scale: float = 100.0,
            grid_density: int = 100,  # if too low, bubbles may lose position accuracy
            neon_color: str = "#fc0101",
            show_title: bool = False,
            return_buffer: bool = False,
            dpi: int | None = None,
    ) -> BytesIO | None:
        """
        Generates a 'Bubble Map' where the size of the circle represents 
        the number of activities in that cluster.
        """
        # 1. Get Base Data (Filter by boundary logic is handled inside _filter_and_get_gdf)
        gdf, region_info = self._filter_and_get_gdf(
            sport_types=sport_types, 
            radius_km=None, 
            location=region, 
            filter_by_boundary=True
        )
        
        if gdf is None or gdf.empty:
            logger.info("No activities found.")
            return

        if region_info is None:
            logger.info("Region information not found.")
            return

        # 2. Setup Bounding Box (in Web Mercator)
        # We do this FIRST to determine the grid size
        bbox_latlon = region_info['boundingbox']
        
        # Create a GeoDataFrame just to project the box accurately
        bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_latlon], crs=BASE_CRS).to_crs(WEB_MERCATOR_CRS)
        minx, miny, maxx, maxy = bbox_gdf.total_bounds
        
        box_width = maxx - minx
        box_height = maxy - miny

        # 3. Dynamic Grid Grouping (in Meters)
        # Divide the map width by 'grid_density' to find the cell size
        # e.g. If map is 1000km wide and density is 50, grid cells are 20km wide.
        grid_size = box_width / grid_density
        
        # Convert activities to Web Mercator if they aren't already
        gdf_proj = gdf.to_crs(WEB_MERCATOR_CRS)
        
        # Snap centroids to this dynamic grid
        # Formula: round(coord / size) * size
        gdf_proj['x_group'] = (gdf_proj.geometry.centroid.x // grid_size) * grid_size
        gdf_proj['y_group'] = (gdf_proj.geometry.centroid.y // grid_size) * grid_size
        
        # Group and count
        grouped = gdf_proj.groupby(['x_group', 'y_group']).size().reset_index(name='count')
        
        # Create Bubbles (shift to center of grid cell)
        bubbles_gdf = gpd.GeoDataFrame(
            grouped,
            geometry=gpd.points_from_xy(grouped.x_group + grid_size/2, grouped.y_group + grid_size/2),
            crs=WEB_MERCATOR_CRS
        )

        # 4. Setup Canvas
        fig, ax = plt.subplots(figsize=(20, 12), facecolor='black')
        ax.set_facecolor('black')
        
        # Set Limits explicitly to the Bounding Box
        # Add small padding (1%)
        pad_x = box_width * 0.01
        pad_y = box_height * 0.01
        ax.set_xlim(minx - pad_x, maxx + pad_x)
        ax.set_ylim(miny - pad_y, maxy + pad_y)

        # 5. Calculate Marker Sizes
        # Normalize by max count so the busiest spot is always "1.0" scale
        max_val = bubbles_gdf['count'].max()
        
        # Size formula needs to be responsive to the figure size and grid density
        # If we have many grid cells (high density), bubbles should be smaller to avoid overlap
        # We use a heuristic: base_size relative to grid_density
        relative_scale = (np.sqrt(bubbles_gdf['count']) / np.sqrt(max_val))
        
        # Tuning factor: The visual size of the bubble
        # min_radius_scale passed by user acts as a global multiplier
        sizes = relative_scale * min_radius_scale 

        # 6. Plotting The Neon Bubbles
        
        # Layer 1: Atmosphere
        ax.scatter(
            bubbles_gdf.geometry.x,
            bubbles_gdf.geometry.y,
            s=sizes * 8,
            c=neon_color,
            alpha=0.05,
            linewidth=0,
            zorder=2
        )

        # Layer 2: The Halo
        ax.scatter(
            bubbles_gdf.geometry.x,
            bubbles_gdf.geometry.y,
            s=sizes * 4,
            c=neon_color,
            alpha=0.2,
            linewidth=0,
            zorder=3
        )

        # Layer 3: The Core
        ax.scatter(
            bubbles_gdf.geometry.x,
            bubbles_gdf.geometry.y,
            s=sizes,
            c='white',
            alpha=0.9,
            edgecolors=neon_color,
            linewidth=1,
            zorder=4
        )

        # 7. Basemap
        try:
            import contextily as ctx
            ctx.add_basemap(
                ax,
                source=ctx.providers.CartoDB.DarkMatter,
                alpha=0.6,
                zoom_adjust=0, # Auto-zoom usually works well with set_xlim
                zorder=1
            )
        except Exception as e:
            logger.debug("Basemap tile fetch failed: %s", e)

        ax.set_axis_off()
        ax.axis('equal')

        # 8. Title & Save
        if show_title:
            sport_str = " / ".join(sport_types).upper() if sport_types else "ALL ACTIVITIES"
            
            plt.title(
                f"{region.upper()} | {sport_str} | DENSITY",
                color=neon_color,
                fontsize=24,
                fontfamily='monospace',
                fontweight='bold',
                pad=20
            )

        filename = f"bubble_map_{region.replace(' ', '_')}.png"
        save_path = self.output_dir / filename.lower()

        result = self._finalize_figure(fig, save_path, dpi=dpi or 600, return_buffer=return_buffer)
        if not return_buffer:
            logger.info("Bubble map saved to: %s", save_path)
        return result


    def activity_clock(
        self,
        sport_types: list[str] | None = None,
        neon_color: str = "#fa2100",
        max_dist_km: float | None = None,
        show_title: bool = True,
        return_buffer: bool = False,
        dpi: int | None = None,
    ) -> BytesIO | None:
        """
        Generates a polar scatter plot of activities (Time vs Distance) 
        """
        # 1. Get Data
        activities = self.strava_analytics.strava_activities_cache.activities
        gdf = get_activities_as_gdf(activities)

        # Filter Sports
        if sport_types:
            gdf = gdf[gdf['sport_type'].isin(sport_types)]

        if gdf.empty:
            logger.info("No activities found.")
            return

        # 2. Prepare Coordinates
        # Convert start time to hours (0-24)
        # Ensure it's datetime format just in case
        gdf['start_date_local'] = gpd.pd.to_datetime(gdf['start_date_local'])
        
        hours = gdf['start_date_local'].dt.hour + gdf['start_date_local'].dt.minute / 60.0
        
        # Convert hours to Radians (0 to 2pi)
        theta = (hours / 24.0) * 2 * np.pi
        
        # Radius = Distance in KM
        r = gdf['distance'] / 1e3 

        # 3. Setup Neon Canvas
        fig = plt.figure(figsize=(15, 15), facecolor='black')
        ax = fig.add_subplot(111, projection='polar')
        ax.set_facecolor('black')
        
        # Layer 1: Atmosphere (Large, very faint)
        ax.scatter(theta, r, c=neon_color, s=250, alpha=0.1, edgecolors='none', zorder=1)
        
        # Layer 2: Glow (Medium, soft)
        ax.scatter(theta, r, c=neon_color, s=100, alpha=0.25, edgecolors='none', zorder=2)
        
        # Layer 3: Core (Sharp, white dot)
        ax.scatter(theta, r, c='white', s=15, alpha=0.9, edgecolors='none', zorder=3)

        # 5. Customizing the Polar Grid (make it look "Tech")
        ax.set_theta_zero_location("N")  # Midnight at top
        ax.set_theta_direction(-1)       # Clockwise
        
        # Grid lines styling
        ax.grid(color=neon_color, alpha=0.1, linestyle=':', linewidth=1)
        ax.spines['polar'].set_visible(False) # Hide the outer circle line

        # Custom Hour Labels
        # We only label standard watch positions: 12, 3, 6, 9 (0, 6, 12, 18 in 24h format)
        ax.set_xticks(np.linspace(0, 2*np.pi, 4, endpoint=False))
        ax.set_xticklabels(['12am', '6am', '12pm', '6pm'], 
                           fontfamily='monospace', fontsize=14, color=neon_color, weight='bold')

        # Distance rings (Y-axis) styling
        ax.tick_params(axis='y', colors=neon_color, labelsize=8)
        
        # Optional: Cap the radius view if there are outliers
        if max_dist_km:
             ax.set_ylim(0, max_dist_km)
        
        # Title
        sport_str = ", ".join(sport_types).upper() if sport_types else "ALL ACTIVITIES"
        if show_title:
            plt.title(
                f"{sport_str}", 
                color=neon_color,
                fontsize=20, 
                fontfamily='monospace', 
                fontweight='bold', 
                pad=30
            )

        # 6. Save
        filename = f"activity_clock_{sport_str.replace(' ', '_')}.png"
        save_path = self.output_dir / filename.lower()

        result = self._finalize_figure(fig, save_path, dpi=dpi or 600, return_buffer=return_buffer)
        if not return_buffer:
            logger.info("Activity clock saved to: %s", save_path)
        return result

    def plot_activity(
        self,
        activity_id: int | str,
        strava_endpoint,
        folder: Path | None = None,
        title: str | None = None,
        neon_color: str = "#fc0101",
        filename: str | None = None,
        return_buffer: bool = False,
        dpi: int | None = None,
    ) -> BytesIO | None:
        """
        Plot a single activity with neon style map and elevation profile below.
        Fetches activity streams from Strava API for elevation data.
        Sized for Instagram Stories (9:16 aspect ratio).
        """
        
        # Get activity from cache
        activities = self.strava_analytics.strava_activities_cache.activities
        activity = activities[activities['id'] == int(activity_id)]
        
        if activity.empty:
            logger.info("Activity %s not found in cache.", activity_id)
            return
        
        # TODO: plot zones on that activity if available
        
        activity = activity.iloc[0]
        
        # Fetch streams for elevation data — try the cache first, else hit Strava.
        streams = self.strava_analytics.strava_activities_cache.get_streams(int(activity_id))
        if not streams:
            from zone2.endpoint import StravaStreamFetchError
            try:
                streams = strava_endpoint.get_activity_streams(activity_id)
            except StravaStreamFetchError as e:
                logger.warning("Could not fetch streams for activity %s: %s", activity_id, e)
                return

        if not streams:
            logger.warning("Could not fetch streams for activity %s", activity_id)
            return

        # Extract data from columnar streams (lat/lng list aligned with altitude/distance arrays).
        latlng_col = streams.get('latlng') or []
        altitude_col = streams.get('altitude') or []
        distance_col = streams.get('distance') or []
        latlngs = [(ll[0], ll[1]) for ll in latlng_col
                   if ll is not None and len(ll) == 2 and ll[0] is not None and ll[1] is not None]
        altitudes = [a for a in altitude_col if a is not None] if altitude_col else []
        distances = [d / 1000 for d in distance_col if d is not None] if distance_col else []  # Convert to km
        
        if not latlngs or not altitudes:
            logger.info("No GPS or altitude data for activity %s", activity_id)
            return
        
        # Create LineString geometry
        line = LineString([(lon, lat) for lat, lon in latlngs])
        gdf = gpd.GeoDataFrame(geometry=[line], crs=BASE_CRS).to_crs(WEB_MERCATOR_CRS)
        
        # Instagram Story size: 9:16 aspect ratio (1080x1920 px -> 9x16 inches at 120 dpi for reasonable file)
        fig = plt.figure(figsize=(9, 16), facecolor='black')
        
        # Create gridspec for custom layout (map takes more space)
        gs = fig.add_gridspec(3, 1, height_ratios=[0.8, 3, 1.2], hspace=0.08)
        
        # --- Header Panel (Activity name and title) ---
        ax_header = fig.add_subplot(gs[0])
        ax_header.set_facecolor('black')
        ax_header.set_axis_off()
        
        activity_name = activity.get('name', f'Activity {activity_id}')
        
        # Calculate stats for header
        total_elevation = activity.get('total_elevation_gain', 0)
        distance_km = activity.get('distance', 0) / 1000
        moving_time_secs = activity.get('moving_time', 0)
        avg_speed = activity.get('average_speed', 0)
        
        # Format time
        hours = int(moving_time_secs // 3600)
        mins = int((moving_time_secs % 3600) // 60)
        secs = int(moving_time_secs % 60)
        if hours > 0:
            time_str = f"{hours}h {mins}m"
        else:
            time_str = f"{mins}:{secs:02d}"
        
        # Format pace/speed based on sport type
        sport_type = activity.get('sport_type', '')
        pace_str = format_pace_or_speed(avg_speed, sport_type)
        stats_text = f"{distance_km:.2f} km  •  {time_str}  •  {pace_str}  •  ↑{total_elevation:.0f} m"
        
        # Custom title if provided - at top with reduced opacity
        if title:
            ax_header.text(
                0.5, 0.88, title.upper(),
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=18,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.7
            )
        
        # Activity date - formatted nicely
        activity_date = pd.to_datetime(activity.get('start_date_local', None))
        if activity_date is not None:
            date_str = activity_date.strftime('%d %B %Y')
            ax_header.text(
                0.5, 0.65, date_str,
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=12,
                fontfamily='monospace',
                alpha=0.8
            )
        
        # Activity name (Strava title) - smaller, subtle
        ax_header.text(
            0.5, 0.45, activity_name,
            transform=ax_header.transAxes,
            ha='center', va='center',
            color='white',
            fontsize=14,
            fontfamily='monospace',
            alpha=0.6
        )
        
        # Stats below activity name
        ax_header.text(
            0.5, 0.18, stats_text,
            transform=ax_header.transAxes,
            ha='center', va='center',
            color='white',
            fontsize=12,
            fontfamily='monospace',
            fontweight='bold',
            alpha=0.9
        )
        
        # --- Map Panel (Middle) ---
        ax_map = fig.add_subplot(gs[1])
        ax_map.set_facecolor('black')
        
        # Neon effect for the route
        # Layer 1: The "Atmosphere" (Wide, very faint glow)
        gdf.plot(ax=ax_map, color=neon_color, linewidth=14, alpha=0.03, zorder=1)
        # Layer 2: The "Glow" (Medium, soft light)
        gdf.plot(ax=ax_map, color=neon_color, linewidth=7, alpha=0.15, zorder=2)
        # Layer 3: The "Core" (Thin, bright white center)
        gdf.plot(ax=ax_map, color='white', linewidth=2.5, alpha=0.9, zorder=3)
        
        # Add start/end markers
        coords = list(gdf.iloc[0].geometry.coords)
        start_point = coords[0]
        end_point = coords[-1]
        
        ax_map.scatter(*start_point, color='#00FF00', s=100, zorder=5, marker='o', edgecolors='white', linewidths=1.5)
        ax_map.scatter(*end_point, color=neon_color, s=100, zorder=5, marker='s', edgecolors='white', linewidths=1.5)
        
        ax_map.set_axis_off()
        
        # Set limits to the data bounds with padding
        minx, miny, maxx, maxy = gdf.total_bounds
        pad_x = (maxx - minx) * 0.1
        pad_y = (maxy - miny) * 0.1
        ax_map.set_xlim(minx - pad_x, maxx + pad_x)
        ax_map.set_ylim(miny - pad_y, maxy + pad_y)
        ax_map.set_aspect('equal')
        
        # --- Elevation Panel (Bottom) ---
        ax_elev = fig.add_subplot(gs[2])
        ax_elev.set_facecolor('black')
        
        # Use distance if available, otherwise use index
        if distances and len(distances) == len(altitudes):
            x_data = distances
            x_label = 'Distance (km)'
        else:
            x_data = list(range(len(altitudes)))
            x_label = 'Points'
        
        # Fill elevation profile with gradient effect
        ax_elev.fill_between(x_data, altitudes, alpha=0.3, color=neon_color)
        ax_elev.plot(x_data, altitudes, color=neon_color, linewidth=1.5, alpha=0.8)
        ax_elev.plot(x_data, altitudes, color='white', linewidth=0.5, alpha=0.9)
        
        # Style elevation chart
        ax_elev.set_xlabel(x_label, color='white', fontsize=10, fontfamily='monospace')
        ax_elev.set_ylabel('Elevation (m)', color=neon_color, fontsize=9, fontfamily='monospace')
        ax_elev.tick_params(axis='y', colors=neon_color, labelsize=8)
        ax_elev.tick_params(axis='x', colors='white', labelsize=8)
        ax_elev.spines['bottom'].set_color(neon_color)
        ax_elev.spines['left'].set_color(neon_color)
        ax_elev.spines['top'].set_visible(False)
        ax_elev.spines['right'].set_visible(False)
        ax_elev.grid(color=neon_color, alpha=0.1, linestyle=':')
        
        # Save
        output_folder = folder if folder else self.output_dir
        output_folder.mkdir(parents=True, exist_ok=True)

        safe_title = (title or activity_name).replace(' ', '_').lower()
        filename = f"activity_{activity_id}_{safe_title}.png" if filename is None else filename
        save_path = output_folder / filename

        result = self._finalize_figure(fig, save_path, dpi=dpi or 300, return_buffer=return_buffer, pad_inches=0.3)
        if not return_buffer:
            logger.info("Activity plot saved to: %s", save_path)
        return result

    def plot_year_in_sport_main(
        self,
        year: int,
        year_in_sport: dict,
        main_sport: str,
        folder: Path | None = None,
        neon_color: str = "#fc0101",
        comparison_year: int | None = None,
        comparison_data: dict | None = None,
        comparison_neon_color: str = "#00aaff",
        return_buffer: bool = False,
        dpi: int | None = None,
    ) -> BytesIO | None:
        """
        Plot main sport statistics in neon style for Instagram Stories.
        Shows sport-specific stats, monthly chart, and highlights.
        Optionally shows comparison with previous year.
        """
        from zone2.analytics import YearInSportFeatures
        
        main_sport_data = year_in_sport.get(main_sport, {})
        comparison_sport_data = comparison_data.get(main_sport, {}) if comparison_data else None
        
        # Instagram Story size: 9:16 aspect ratio
        fig = plt.figure(figsize=(9, 16), facecolor='black')
        
        # Create gridspec for layout
        gs = fig.add_gridspec(5, 1, height_ratios=[1.2, 1.2, 2, 1.5, 1.3], hspace=0.10)
        
        # --- Header Panel ---
        ax_header = fig.add_subplot(gs[0])
        ax_header.set_facecolor('black')
        ax_header.set_axis_off()
        
        # Year title - show both years if comparison provided
        if comparison_year is not None:
            # Main year on left
            ax_header.text(
                0.5, 0.75, f"{year}",
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=48,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.9
            )
            # Comparison year on right, different neon color
            ax_header.text(
                0.67, 0.70, f"{comparison_year}",
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=comparison_neon_color,
                fontsize=16,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.5
            )
        else:
            ax_header.text(
                0.5, 0.75, f"{year}",
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=48,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.9
            )
        
        # Sport name as subtitle
        ax_header.text(
            0.5, 0.25, main_sport.upper(),
            transform=ax_header.transAxes,
            ha='center', va='center',
            color='white',
            fontsize=20,
            fontfamily='monospace',
            alpha=0.7
        )
        
        # --- Main Stats Panel ---
        ax_stats = fig.add_subplot(gs[1])
        ax_stats.set_facecolor('black')
        ax_stats.set_axis_off()
        
        sport_activities = main_sport_data.get(YearInSportFeatures.TOTAL_ACTIVITIES, 0)
        sport_km = main_sport_data.get(YearInSportFeatures.TOTAL_DISTANCE_KM, 0)
        sport_elevation = main_sport_data.get(YearInSportFeatures.TOTAL_ELEVATION_M, 0)
        sport_hours = main_sport_data.get(YearInSportFeatures.TOTAL_TIME_HOURS, 0)
        
        # Get comparison values if available
        comp_activities = comparison_sport_data.get(YearInSportFeatures.TOTAL_ACTIVITIES, 0) if comparison_sport_data else None
        comp_km = comparison_sport_data.get(YearInSportFeatures.TOTAL_DISTANCE_KM, 0) if comparison_sport_data else None
        comp_elevation = comparison_sport_data.get(YearInSportFeatures.TOTAL_ELEVATION_M, 0) if comparison_sport_data else None
        comp_hours = comparison_sport_data.get(YearInSportFeatures.TOTAL_TIME_HOURS, 0) if comparison_sport_data else None
        
        # Box-based layout: each stat gets a box, current year takes 2/3, comparison takes 1/3
        stats_big = [
            (f"{sport_activities}", "ACTIVITIES", f"{comp_activities}" if comp_activities is not None else None),
            (f"{sport_km:,.0f}", "KILOMETERS", f"{comp_km:,.0f}" if comp_km is not None else None),
            (f"{sport_hours:,.0f}", "HOURS", f"{comp_hours:,.0f}" if comp_hours is not None else None),
            (f"{sport_elevation:,.0f}", "↑ METERS", f"{comp_elevation:,.0f}" if comp_elevation is not None else None),
        ]
        
        num_boxes = len(stats_big)
        box_width = 1.0 / num_boxes  # Each box takes equal width
        main_y = 0.75

        for i, (value, label, comp_value) in enumerate(stats_big):
            # Box boundaries
            box_left = i * box_width
            box_center = box_left + box_width / 2
            
            if comp_value is not None:
                # With comparison: current year at 1/2 of box, comparison at 3/4 of box
                main_x = box_center
                comp_x = box_center
                main_fontsize = 25
                comp_fontsize = 12
                comp_y = 0.6
            else:
                # Without comparison: center the value
                main_x = box_center
                main_fontsize = 30

            # Main value
            ax_stats.text(
                main_x, main_y, value,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=main_fontsize,
                fontfamily='monospace',
                fontweight='bold'
            )
            
            # Comparison value
            if comp_value is not None:
                ax_stats.text(
                    comp_x, comp_y, comp_value,
                    transform=ax_stats.transAxes,
                    ha='center', va='center',
                    color=comparison_neon_color,
                    fontsize=comp_fontsize,
                    fontfamily='monospace',
                    fontweight='bold',
                    alpha=0.45
                )
            
            # Label centered in box
            ax_stats.text(
                box_center, 0.5, label,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=8,
                fontfamily='monospace',
                alpha=0.6
            )
        
        # --- Monthly Distance Chart ---
        ax_chart = fig.add_subplot(gs[2])
        ax_chart.set_facecolor('black')
        
        distance_per_month = main_sport_data.get(YearInSportFeatures.DISTANCE_PER_MONTH_KM, {})
        comp_distance_per_month = comparison_sport_data.get(YearInSportFeatures.DISTANCE_PER_MONTH_KM, {}) if comparison_sport_data else {}
        
        months = list(range(1, 13))
        month_names = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
        values = [distance_per_month.get(m, 0) for m in months]
        comp_values = [comp_distance_per_month.get(m, 0) for m in months]
        
        # Bar width and positions for grouped bars
        bar_width = 0.35 if comparison_sport_data else 0.6
        x_main = np.array(months) - bar_width/2 if comparison_sport_data else np.array(months)
        x_comp = np.array(months) + bar_width/2
        
        # Main year bars - neon effect
        ax_chart.bar(x_main, values, color=neon_color, alpha=0.15, width=bar_width)
        ax_chart.bar(x_main, values, color=neon_color, alpha=0.4, width=bar_width * 0.6)
        ax_chart.bar(x_main, values, color='white', alpha=0.6, width=bar_width * 0.25)
        
        # Comparison year bars - neon effect with comparison color
        if comparison_sport_data:
            ax_chart.bar(x_comp, comp_values, color=comparison_neon_color, alpha=0.15, width=bar_width)
            ax_chart.bar(x_comp, comp_values, color=comparison_neon_color, alpha=0.35, width=bar_width * 0.6)
            ax_chart.bar(x_comp, comp_values, color='white', alpha=0.4, width=bar_width * 0.25)
        
        ax_chart.set_xticks(months)
        ax_chart.set_xticklabels(month_names, color='white', fontsize=10, fontfamily='monospace')
        ax_chart.set_yticks([])
        ax_chart.tick_params(axis='x', colors='white', length=0)
        ax_chart.spines['bottom'].set_color(neon_color)
        ax_chart.spines['bottom'].set_alpha(0.2)
        ax_chart.spines['left'].set_visible(False)
        ax_chart.spines['top'].set_visible(False)
        ax_chart.spines['right'].set_visible(False)
        ax_chart.set_ylabel('KM PER MONTH', color='white', fontsize=9, fontfamily='monospace', alpha=0.5)
        ax_chart.grid(axis='y', color=neon_color, alpha=0.08, linestyle=':')
        
        # --- Additional Stats ---
        ax_extra = fig.add_subplot(gs[3])
        ax_extra.set_facecolor('black')
        ax_extra.set_axis_off()
        
        active_days = main_sport_data.get(YearInSportFeatures.ACTIVE_DAYS, 0)
        avg_km = main_sport_data.get(YearInSportFeatures.AVERAGE_DISTANCE_KM, 0)
        month_most_km = main_sport_data.get(YearInSportFeatures.MONTH_MOST_KM)
        most_active_weekday = main_sport_data.get(YearInSportFeatures.MOST_ACTIVE_WEEKDAY)
        average_speed = main_sport_data.get(YearInSportFeatures.AVERAGE_SPEED, 0)
        activities_per_week = main_sport_data.get(YearInSportFeatures.ACTIVITIES_PER_WEEK, 0)
        
        # Get comparison values for all features
        comp_active_days = comparison_sport_data.get(YearInSportFeatures.ACTIVE_DAYS, 0) if comparison_sport_data else None
        comp_avg_km = comparison_sport_data.get(YearInSportFeatures.AVERAGE_DISTANCE_KM, 0) if comparison_sport_data else None
        comp_average_speed = comparison_sport_data.get(YearInSportFeatures.AVERAGE_SPEED, 0) if comparison_sport_data else None
        comp_activities_per_week = comparison_sport_data.get(YearInSportFeatures.ACTIVITIES_PER_WEEK, 0) if comparison_sport_data else None
        comp_month_most_km = comparison_sport_data.get(YearInSportFeatures.MONTH_MOST_KM) if comparison_sport_data else None
        comp_most_active_weekday = comparison_sport_data.get(YearInSportFeatures.MOST_ACTIVE_WEEKDAY) if comparison_sport_data else None
        
        weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        month_full_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        weekday_str = weekday_names[most_active_weekday] if most_active_weekday is not None else "N/A"
        month_str = month_full_names[month_most_km] if month_most_km else "N/A"
        comp_weekday_str = weekday_names[comp_most_active_weekday] if comp_most_active_weekday is not None else None
        comp_month_str = month_full_names[comp_month_most_km] if comp_month_most_km else None
        
        # Format average speed using sport-specific formatting
        avg_speed_str = format_pace_or_speed(average_speed, main_sport)
        comp_avg_speed_str = format_pace_or_speed(comp_average_speed, main_sport) if comp_average_speed else None
        
        # Determine label based on sport type
        sport_lower = main_sport.lower()
        cycling_sports = {'ride', 'virtualride', 'ebikeride', 'handcycle', 'velomobile', 
                          'gravel ride', 'gravelride', 'mountain bike ride', 'mountainbikeride'}
        if any(cycle in sport_lower for cycle in cycling_sports):
            avg_speed_label = "avg speed"
        else:
            avg_speed_label = "avg pace"
        
        # Stats with comparison values for all features
        # Box-based layout for additional stats: 3 columns x 2 rows
        stats_extra = [
            (f"{active_days}", "active days", f"{comp_active_days}" if comp_active_days is not None else None),
            (f"{activities_per_week:.1f}", "acts per week", f"{comp_activities_per_week:.1f}" if comp_activities_per_week is not None else None),
            (f"{avg_km:.1f}", "avg distance (km)", f"{comp_avg_km:.1f}" if comp_avg_km is not None else None),
            (avg_speed_str, avg_speed_label, comp_avg_speed_str),
            (weekday_str, "favorite day", comp_weekday_str),
            (month_str, "best month", comp_month_str),
        ]
        
        num_cols = 3
        box_width = 1.0 / num_cols
        
        for i, (value, label, comp_value) in enumerate(stats_extra):
            row = i // num_cols
            col = i % num_cols
            
            # Box boundaries
            box_center = col * box_width + box_width / 2
            y = 0.75 - row * 0.5
            
            # Main value - always centered
            ax_extra.text(
                box_center, y, value,
                transform=ax_extra.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=13,
                fontfamily='monospace',
                fontweight='bold'
            )
            
            # Comparison value - below main value
            if comp_value is not None:
                ax_extra.text(
                    box_center, y - 0.11, comp_value,
                    transform=ax_extra.transAxes,
                    ha='center', va='center',
                    color=comparison_neon_color,
                    fontsize=10,
                    fontfamily='monospace',
                    fontweight='bold',
                    alpha=0.45
                )
            
            # Label centered in box - below comparison (or below main if no comparison)
            label_y = y - 0.19 if comp_value is not None else y - 0.15
            ax_extra.text(
                box_center, label_y, label,
                transform=ax_extra.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=8,
                fontfamily='monospace',
                alpha=0.5
            )
        
        # --- Highlights Panel ---
        ax_highlights = fig.add_subplot(gs[4])
        ax_highlights.set_facecolor('black')
        ax_highlights.set_axis_off()
        
        longest_km = main_sport_data.get(YearInSportFeatures.LONGEST_ACTIVITY_KM, 0)
        longest_mins = main_sport_data.get(YearInSportFeatures.LONGEST_ACTIVITY_MINS, 0)
        fastest_speed = main_sport_data.get(YearInSportFeatures.FASTEST_ACTIVITY_SPEED, 0)
        
        # Get comparison values if available
        comp_longest_km = comparison_sport_data.get(YearInSportFeatures.LONGEST_ACTIVITY_KM, 0) if comparison_sport_data else None
        comp_longest_mins = comparison_sport_data.get(YearInSportFeatures.LONGEST_ACTIVITY_MINS, 0) if comparison_sport_data else None
        comp_fastest_speed = comparison_sport_data.get(YearInSportFeatures.FASTEST_ACTIVITY_SPEED, 0) if comparison_sport_data else None
        
        # Format time helper
        def format_time(mins: float) -> str:
            hours = int(mins // 60)
            m = int(mins % 60)
            return f"{hours}h {m}m" if hours > 0 else f"{m}m"
        
        # Format pace/speed based on sport type using utility function
        pace_str = format_pace_or_speed(fastest_speed, main_sport)
        time_str = format_time(longest_mins)
        
        comp_pace_str = format_pace_or_speed(comp_fastest_speed, main_sport) if comp_fastest_speed else None
        comp_time_str = format_time(comp_longest_mins) if comp_longest_mins else None
        
        ax_highlights.text(
            0.5, 0.9, "PERSONAL BESTS",
            transform=ax_highlights.transAxes,
            ha='center', va='center',
            color=neon_color,
            fontsize=12,
            fontfamily='monospace',
            fontweight='bold',
            alpha=0.7
        )
        
        # Determine label based on sport type (pace vs speed)
        sport_lower = main_sport.lower()
        cycling_sports = {'ride', 'virtualride', 'ebikeride', 'handcycle', 'velomobile', 
                          'gravel ride', 'gravelride', 'mountain bike ride', 'mountainbikeride'}
        if any(cycle in sport_lower for cycle in cycling_sports):
            speed_label = "▸ Top Speed"
        else:
            speed_label = "▸ Fastest Pace"
        
        highlights = [
            ("▸ Longest Distance", f"{longest_km:.1f} km", f"{comp_longest_km:.1f} km" if comp_longest_km else None),
            ("▸ Longest Time", time_str, comp_time_str),
            (speed_label, pace_str, comp_pace_str),
        ]
        
        # Adjust positions based on whether comparison data exists
        has_comparison = comparison_sport_data is not None
        label_x = 0.2 if has_comparison else 0.25
        value_x = 0.62 if has_comparison else 0.75
        comp_x = 0.75
        
        for i, (label, value, comp_value) in enumerate(highlights):
            y = 0.65 - i * 0.22
            ax_highlights.text(
                label_x, y, label,
                transform=ax_highlights.transAxes,
                ha='left', va='center',
                color='white',
                fontsize=10,
                fontfamily='monospace',
                alpha=0.6
            )
            ax_highlights.text(
                value_x, y, value,
                transform=ax_highlights.transAxes,
                ha='right', va='center',
                color='white',
                fontsize=10,
                fontfamily='monospace',
                fontweight='bold'
            )
            # Show comparison value (more transparent)
            if comp_value is not None:
                ax_highlights.text(
                    comp_x, y, comp_value,
                    transform=ax_highlights.transAxes,
                    ha='center', va='center',
                    color=comparison_neon_color,
                    fontsize=10,
                    fontfamily='monospace',
                    fontweight='bold',
                    alpha=0.45
                )
        
        # Save
        output_folder = folder if folder else self.output_dir
        output_folder.mkdir(parents=True, exist_ok=True)

        filename = f"year_in_sport_{year}_{main_sport.lower()}.png"
        save_path = output_folder / filename

        result = self._finalize_figure(fig, save_path, dpi=dpi or 300, return_buffer=return_buffer, pad_inches=0.3)
        if not return_buffer:
            logger.info("Year in sport (%s) saved to: %s", main_sport, save_path)
        return result

    def plot_year_in_sport_totals(
        self,
        year: int,
        year_in_sport: dict,
        folder: Path | None = None,
        neon_color: str = "#fc0101",
        comparison_year: int | None = None,
        comparison_data: dict | None = None,
        comparison_neon_color: str = "#00aaff",
        return_buffer: bool = False,
        dpi: int | None = None,
    ) -> BytesIO | None:
        """
        Plot total year statistics across all sports in neon style for Instagram Stories.
        Shows total stats, sports breakdown, and monthly activity.
        Optionally shows comparison with previous year.
        """
        from zone2.analytics import AllYearInSportFeatures
        
        all_sports_data = year_in_sport.get('all', {})
        comparison_all_data = comparison_data.get('all', {}) if comparison_data else None
        
        # Instagram Story size: 9:16 aspect ratio
        fig = plt.figure(figsize=(9, 16), facecolor='black')
        
        # Create gridspec for layout
        gs = fig.add_gridspec(4, 1, height_ratios=[1.2, 1, 2.5, 2.3], hspace=0.12)
        
        # --- Header Panel ---
        ax_header = fig.add_subplot(gs[0])
        ax_header.set_facecolor('black')
        ax_header.set_axis_off()
        
        # Year title - show both years if comparison provided
        if comparison_year is not None:
            # Main year centered
            ax_header.text(
                0.5, 0.75, f"{year}",
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=48,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.9
            )
            # Comparison year below/right, smaller
            ax_header.text(
                0.67, 0.70, f"{comparison_year}",
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=comparison_neon_color,
                fontsize=16,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.5
            )
        else:
            ax_header.text(
                0.5, 0.75, f"{year}",
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=48,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.9
            )
        
        # Subtitle
        ax_header.text(
            0.5, 0.25, "YEAR IN SPORT",
            transform=ax_header.transAxes,
            ha='center', va='center',
            color='white',
            fontsize=20,
            fontfamily='monospace',
            alpha=0.7
        )
        
        # --- Main Stats Panel ---
        ax_stats = fig.add_subplot(gs[1])
        ax_stats.set_facecolor('black')
        ax_stats.set_axis_off()
        
        total_activities = all_sports_data.get(AllYearInSportFeatures.TOTAL_ACTIVITIES, 0)
        total_km = all_sports_data.get(AllYearInSportFeatures.TOTAL_DISTANCE_KM, 0)
        total_hours = all_sports_data.get(AllYearInSportFeatures.TOTAL_TIME_HOURS, 0)
        
        # Get comparison values if available
        comp_total_activities = comparison_all_data.get(AllYearInSportFeatures.TOTAL_ACTIVITIES, 0) if comparison_all_data else None
        comp_total_km = comparison_all_data.get(AllYearInSportFeatures.TOTAL_DISTANCE_KM, 0) if comparison_all_data else None
        comp_total_hours = comparison_all_data.get(AllYearInSportFeatures.TOTAL_TIME_HOURS, 0) if comparison_all_data else None
        
        # Box-based layout for main stats: 3 columns
        stats_big = [
            (f"{total_activities}", "ACTIVITIES", f"{comp_total_activities}" if comp_total_activities is not None else None),
            (f"{total_km:,.0f}", "KILOMETERS", f"{comp_total_km:,.0f}" if comp_total_km is not None else None),
            (f"{total_hours:,.0f}", "HOURS", f"{comp_total_hours:,.0f}" if comp_total_hours is not None else None),
        ]
        
        num_boxes = len(stats_big)
        box_width = 1.0 / num_boxes
        
        for i, (value, label, comp_value) in enumerate(stats_big):
            box_center = i * box_width + box_width / 2
            
            # Main value - always centered
            ax_stats.text(
                box_center, 0.7, value,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=32,
                fontfamily='monospace',
                fontweight='bold'
            )
            
            # Comparison value - below main value
            if comp_value is not None:
                ax_stats.text(
                    box_center, 0.45, comp_value,
                    transform=ax_stats.transAxes,
                    ha='center', va='center',
                    color=comparison_neon_color,
                    fontsize=18,
                    fontfamily='monospace',
                    fontweight='bold',
                    alpha=0.45
                )
            
            # Label centered in box - below comparison (or below main if no comparison)
            label_y = 0.25 if comp_value is not None else 0.35
            ax_stats.text(
                box_center, label_y, label,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=9,
                fontfamily='monospace',
                alpha=0.6
            )
        
        # --- Sports Breakdown ---
        ax_sports = fig.add_subplot(gs[2])
        ax_sports.set_facecolor('black')
        
        activities_per_sport = all_sports_data.get(AllYearInSportFeatures.ACTIVITIES_PER_SPORT, {})
        comp_activities_per_sport = comparison_all_data.get(AllYearInSportFeatures.ACTIVITIES_PER_SPORT, {}) if comparison_all_data else {}
        
        if activities_per_sport or comp_activities_per_sport:
            # Merge sports from both years - current year sports first (sorted by count), then comp-only sports
            all_sport_names = set(activities_per_sport.keys()) | set(comp_activities_per_sport.keys())
            
            # Sort: current year sports by count desc, then comp-only sports by their count desc
            current_year_sports = sorted(
                [(s, activities_per_sport.get(s, 0)) for s in all_sport_names if s in activities_per_sport],
                key=lambda x: x[1], reverse=True
            )
            comp_only_sports = sorted(
                [(s, comp_activities_per_sport.get(s, 0)) for s in all_sport_names if s not in activities_per_sport],
                key=lambda x: x[1], reverse=True
            )
            
            sorted_sports = current_year_sports + comp_only_sports
            sports = [s[0] for s in sorted_sports]
            counts = [activities_per_sport.get(s, 0) for s in sports]
            comp_counts = [comp_activities_per_sport.get(s, 0) for s in sports]
            
            # Limit to top 10 sports
            if len(sports) > 10:
                sports = sports[:10]
                counts = counts[:10]
                comp_counts = comp_counts[:10]
            
            max_count = max(max(counts) if counts else 0, max(comp_counts) if comp_counts else 0, 1)
            
            # Create left margin for labels by extending xlim
            label_margin = max_count * 0.35
            
            if comparison_all_data:
                # Grouped bar chart - similar to monthly chart style
                bar_height = 0.35
                y_pos = np.arange(len(sports))
                
                # Current year bars - neon style
                ax_sports.barh(y_pos - 0.2, counts, left=label_margin, color=neon_color, alpha=0.15, height=bar_height + 0.1)
                ax_sports.barh(y_pos - 0.2, counts, left=label_margin, color=neon_color, alpha=0.4, height=bar_height)
                ax_sports.barh(y_pos - 0.2, counts, left=label_margin, color='white', alpha=0.6, height=0.08)
                
                # Comparison year bars - neon style  
                ax_sports.barh(y_pos + 0.2, comp_counts, left=label_margin, color=comparison_neon_color, alpha=0.15, height=bar_height + 0.1)
                ax_sports.barh(y_pos + 0.2, comp_counts, left=label_margin, color=comparison_neon_color, alpha=0.4, height=bar_height)
                ax_sports.barh(y_pos + 0.2, comp_counts, left=label_margin, color='white', alpha=0.4, height=0.06)
                
                # Set xlim to include label margin - uses max_count from both years
                ax_sports.set_xlim(0, label_margin + max_count * 1.15)
                
                # Remove axis elements
                ax_sports.set_yticks([])
                ax_sports.set_xticks([])
                ax_sports.invert_yaxis()
                
                ax_sports.spines['bottom'].set_visible(False)
                ax_sports.spines['left'].set_visible(False)
                ax_sports.spines['top'].set_visible(False)
                ax_sports.spines['right'].set_visible(False)
                
                # Add sport names and count labels
                for i, sport in enumerate(sports):
                    count = counts[i]
                    comp_count = comp_counts[i]
                    
                    # Sport name on the left
                    ax_sports.text(
                        label_margin - max_count * 0.03, i, sport,
                        va='center', ha='right',
                        color='white', fontsize=10, fontfamily='monospace', alpha=0.9
                    )
                    # Current year count
                    ax_sports.text(
                        label_margin + count + max_count * 0.02, i - 0.2, str(count),
                        va='center', ha='left',
                        color='white', fontsize=9, fontfamily='monospace', alpha=0.8
                    )
                    # Comparison count
                    ax_sports.text(
                        label_margin + comp_count + max_count * 0.02, i + 0.2, str(comp_count),
                        va='center', ha='left',
                        color=comparison_neon_color, fontsize=8, fontfamily='monospace', alpha=0.5
                    )
            else:
                # Single year - original style
                y_pos = np.arange(len(sports))
                
                ax_sports.barh(y_pos, counts, left=label_margin, color=neon_color, alpha=0.15, height=0.6)
                ax_sports.barh(y_pos, counts, left=label_margin, color=neon_color, alpha=0.4, height=0.35)
                ax_sports.barh(y_pos, counts, left=label_margin, color='white', alpha=0.6, height=0.12)
                
                ax_sports.set_xlim(0, label_margin + max_count * 1.15)
                ax_sports.set_yticks([])
                ax_sports.set_xticks([])
                ax_sports.invert_yaxis()
                
                ax_sports.spines['bottom'].set_visible(False)
                ax_sports.spines['left'].set_visible(False)
                ax_sports.spines['top'].set_visible(False)
                ax_sports.spines['right'].set_visible(False)
                
                for i, (sport, count) in enumerate(zip(sports, counts)):
                    ax_sports.text(
                        label_margin - max_count * 0.03, i, sport,
                        va='center', ha='right',
                        color='white', fontsize=10, fontfamily='monospace', alpha=0.9
                    )
                    ax_sports.text(
                        label_margin + count + max_count * 0.02, i, str(count),
                        va='center', ha='left',
                        color='white', fontsize=9, fontfamily='monospace', alpha=0.7
                    )
        
        # --- Highlights Panel ---
        ax_highlights = fig.add_subplot(gs[3])
        ax_highlights.set_facecolor('black')
        ax_highlights.set_axis_off()
        
        # Convert weekday and month numbers to names
        weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        month_full_names = ['', 'January', 'February', 'March', 'April', 'May', 'June', 
                           'July', 'August', 'September', 'October', 'November', 'December']
        
        most_active_weekday = all_sports_data.get(AllYearInSportFeatures.MOST_ACTIVE_WEEKDAY)
        most_active_month = all_sports_data.get(AllYearInSportFeatures.MOST_ACTIVE_MONTH)
        sport_most_done = all_sports_data.get(AllYearInSportFeatures.SPORT_MOST_DONE, "N/A")
        num_sports = len(activities_per_sport) if activities_per_sport else 0
        active_days = all_sports_data.get(AllYearInSportFeatures.ACTIVE_DAYS, 0)
        activities_per_week = all_sports_data.get(AllYearInSportFeatures.ACTIVITIES_PER_WEEK, 0)
        
        # Get comparison values if available
        comp_active_days = comparison_all_data.get(AllYearInSportFeatures.ACTIVE_DAYS, 0) if comparison_all_data else None
        comp_activities_per_week = comparison_all_data.get(AllYearInSportFeatures.ACTIVITIES_PER_WEEK, 0) if comparison_all_data else None
        comp_activities_per_sport_hl = comparison_all_data.get(AllYearInSportFeatures.ACTIVITIES_PER_SPORT, {}) if comparison_all_data else {}
        comp_num_sports = len(comp_activities_per_sport_hl) if comp_activities_per_sport_hl else None
        comp_most_active_weekday = comparison_all_data.get(AllYearInSportFeatures.MOST_ACTIVE_WEEKDAY) if comparison_all_data else None
        comp_most_active_month = comparison_all_data.get(AllYearInSportFeatures.MOST_ACTIVE_MONTH) if comparison_all_data else None
        comp_sport_most_done = comparison_all_data.get(AllYearInSportFeatures.SPORT_MOST_DONE, None) if comparison_all_data else None
        
        weekday_str = weekday_names[most_active_weekday] if most_active_weekday is not None else "N/A"
        month_str = month_full_names[most_active_month] if most_active_month else "N/A"
        comp_weekday_str = weekday_names[comp_most_active_weekday] if comp_most_active_weekday is not None else None
        comp_month_str = month_full_names[comp_most_active_month] if comp_most_active_month else None
        
        ax_highlights.text(
            0.5, 0.95, "HIGHLIGHTS",
            transform=ax_highlights.transAxes,
            ha='center', va='center',
            color=neon_color,
            fontsize=12,
            fontfamily='monospace',
            fontweight='bold',
            alpha=0.7
        )
        
        highlights = [
            ("▸ Active Days", str(active_days), str(comp_active_days) if comp_active_days is not None else None),
            ("▸ Top Sport", sport_most_done, comp_sport_most_done),
            ("▸ Sports Practiced", str(num_sports), str(comp_num_sports) if comp_num_sports is not None else None),
            ("▸ Most Active Day", weekday_str, comp_weekday_str),
            ("▸ Best Month", month_str, comp_month_str),
        ]
        
        # Adjust positions based on whether comparison data exists
        has_comparison = comparison_all_data is not None
        label_x = 0.08 if has_comparison else 0.15
        value_x = 0.6 if has_comparison else 0.85
        comp_x = 0.82
        
        for i, (label, value, comp_value) in enumerate(highlights):
            y = 0.8 - i * 0.16
            ax_highlights.text(
                label_x, y, label,
                transform=ax_highlights.transAxes,
                ha='left', va='center',
                color='white',
                fontsize=10,
                fontfamily='monospace',
                alpha=0.6
            )
            ax_highlights.text(
                value_x, y, value,
                transform=ax_highlights.transAxes,
                ha='right', va='center',
                color='white',
                fontsize=10,
                fontfamily='monospace',
                fontweight='bold'
            )
            # Show comparison value (more transparent)
            if comp_value is not None:
                ax_highlights.text(
                    comp_x, y, comp_value,
                    transform=ax_highlights.transAxes,
                    ha='right', va='center',
                    color=comparison_neon_color,
                    fontsize=9,
                    fontfamily='monospace',
                    fontweight='bold',
                    alpha=0.45
                )
        
        # Save
        output_folder = folder if folder else self.output_dir
        output_folder.mkdir(parents=True, exist_ok=True)

        filename = f"year_in_sport_{year}_totals.png"
        save_path = output_folder / filename

        result = self._finalize_figure(fig, save_path, dpi=dpi or 300, return_buffer=return_buffer, pad_inches=0.3)
        if not return_buffer:
            logger.info("Year in sport (totals) saved to: %s", save_path)
        return result

    def hud_dashboard(
        self,
        sport_type: str,
        bins: int = 40,
        return_buffer: bool = False,
        dpi: int | None = None,
    ) -> BytesIO | None:
        """
        Generates a 3-row 'Cyberpunk HUD' dashboard showing distributions of
        Distance, Heart Rate, and Speed/Pace.
        Speed/Pace format adapts based on sport type.
        """
        # 1. Get & Filter Data
        activities = self.strava_analytics.strava_activities_cache.activities
        gdf = get_activities_as_gdf(activities)
        
        gdf = gdf[gdf['sport_type'] == sport_type]
        
        if gdf.empty:
            logger.info("No data found.")
            return

        # 2. Determine sport category for speed/pace formatting
        primary_sport = sport_type if sport_type else ""
        category = get_sport_category(primary_sport)

        # 3. Prepare Metrics (Drop NaNs for cleaner plots)
        # Distance: Convert to KM
        dist_data = gdf['distance'].dropna() / 1000.0
        
        # Heart Rate: Use raw BPM
        hr_data = gdf['average_heartrate'].dropna() if 'average_heartrate' in gdf.columns else []
        
        # Speed: Convert based on sport type using utility
        if 'average_speed' in gdf.columns:
            speed_raw = gdf['average_speed'].dropna()
            # Convert each speed value and get the unit label
            speed_data = speed_raw.apply(lambda s: convert_speed(s, primary_sport)[0])
            _, unit_label = convert_speed(1.0, primary_sport)  # Get unit label
            
            if category == 'cycling':
                speed_title = f"SPEED [{unit_label}]"
            else:
                speed_title = f"PACE ['{unit_label.replace('min/', '/')}]"
        else:
            speed_data = []
            speed_title = "SPEED"

        # 4. Setup Canvas (3 Rows, 1 Col)
        fig, axes = plt.subplots(3, 1, figsize=(10, 12), facecolor='black')
        plt.subplots_adjust(hspace=0.4) # Space between panels

        # Helper to draw "Digital Equalizer" style histogram
        def plot_digital_hist(ax, data, color, title):
            if len(data) == 0:
                ax.text(0.5, 0.5, "NO DATA", color='gray', ha='center')
                ax.set_axis_off()
                return

            ax.set_facecolor('black')
            
            # Calculate histogram
            counts, bin_edges = np.histogram(data, bins=bins, density=True)
            centers = (bin_edges[:-1] + bin_edges[1:]) / 2
            
            # --- GLOW EFFECTS ---
            # 1. The "Atmosphere" (Fill)
            ax.fill_between(centers, counts, color=color, alpha=0.1, step='mid', zorder=1)
            
            # 2. The "Glow" (Blurry Line)
            ax.step(centers, counts, color=color, linewidth=6, alpha=0.2, where='mid', zorder=2)
            
            # 3. The "Core" (Sharp Line)
            ax.step(centers, counts, color='white', linewidth=1.0, alpha=0.9, where='mid', zorder=3)

            median_val = np.median(data)
            
            # Median Glow (Wide)
            ax.axvline(median_val, color=color, linewidth=6, alpha=0.2, zorder=4)
            
            # Median Core (Sharp, Dashed)
            ax.axvline(median_val, color='white', linewidth=1.5, linestyle='--', alpha=1.0, zorder=5)

            ax.text(0.8, 0.9, title, transform=ax.transAxes, 
                    color=color, ha='center', fontfamily='monospace', fontsize=14, fontweight='bold', alpha=0.8)

            # # Styling
            ax.tick_params(axis='x', colors='white', labelsize=9)

        # 5. Plot Each Metric
        # Panel 1: Distance (Yellow Neon)
        plot_digital_hist(axes[0], dist_data, color='#faff00', title="DISTANCE [km]")
        
        # Panel 2: Heart Rate (Magenta Neon)
        plot_digital_hist(axes[1], hr_data, color='#ff00ff', title="HR [bpm]")
        
        # Panel 3: Speed/Pace (Cyan Neon) - sport-specific
        plot_digital_hist(axes[2], speed_data, color='#00faed', title=speed_title)

        # 6. Save
        sport_str = sport_type.upper()
        filename = f"hud_{sport_str.replace(' ', '_')}.png"
        save_path = self.output_dir / filename.lower()

        result = self._finalize_figure(fig, save_path, dpi=dpi or 600, return_buffer=return_buffer)
        if not return_buffer:
            logger.info("HUD dashboard saved to: %s", save_path)
        return result

    def plot_efficiency_factor(self, sport_type: str, window=14, return_buffer: bool = False, dpi: int | None = None) -> BytesIO | None:
        """
        Plots Aerobic Efficiency (Speed / HR) with publication-quality styling.
        Includes rolling average, standard deviation bands, and peak annotations.
        """
        # 1. Data Prep
        gdf, _ = self._filter_and_get_gdf([sport_type])
        if gdf is None or gdf.empty:
            logger.info("No data found for the specified parameters.")
            return

        df = gdf.copy()
        
        # Filter invalid HR or very short runs
        df = df[(df['average_heartrate'] > 50) & (df['distance'] > 3_000)]
        
        # Calculate EF: Speed (m/min) / HR (bpm)
        # Speed is in m/s, so * 60 to get m/min
        df['ef_score'] = (df['average_speed'] * 60) / df['average_heartrate']

        # Parse dates
        df['start_date_local'] = pd.to_datetime(df['start_date_local'])
        df = df.sort_values('start_date_local')

        # 2. Statistical Calculations
        # Rolling Mean (Trend)
        df['ef_rolling'] = df['ef_score'].rolling(window=window, center=True).mean()
        # Rolling Std Dev (Consistency) - Valuable for scientific context
        df['ef_std'] = df['ef_score'].rolling(window=window, center=True).std()
        
        # Identify global peak for annotation
        peak_idx = df['ef_rolling'].idxmax()
        if pd.isna(peak_idx): return # Handle edge case of no data
        peak_date = df.loc[peak_idx, 'start_date_local']
        peak_val = df.loc[peak_idx, 'ef_rolling']

        # 3. Professional Plotting Setup
        # Use a white background style typical for journals
        with plt.style.context('seaborn-v0_8-whitegrid'):
            fig, ax = plt.subplots(figsize=(12, 7))

            # A. Raw Data (Background Context)
            # distinct but subtle color
            ax.scatter(df['start_date_local'], df['ef_score'], 
                    alpha=0.15, color='#2c3e50', s=15, 
                    edgecolors='none', label='Daily Session')

            # B. Variance Band (Consistency)
            # Shading +/- 1 Standard Deviation represents stability of the metric
            ax.fill_between(df['start_date_local'], 
                            df['ef_rolling'] - df['ef_std'], 
                            df['ef_rolling'] + df['ef_std'], 
                            color='#3498db', alpha=0.15, 
                            label=fr'{window}-Day Variability (±1$\sigma$)')

            # C. Rolling Trend (Main Focus)
            # Strong, professional line color (e.g., Navy Blue or deep Teal)
            ax.plot(df['start_date_local'], df['ef_rolling'], 
                    color="#005b96", linewidth=2.5, 
                    label=f'{window}-Day Moving Avg')

            # D. Key Event Annotation (Peak)
            ax.plot(peak_date, peak_val, marker='o', color="#d35400", 
                    markersize=4, zorder=5, label='Peak Efficiency')
            
            # Add text annotation with arrow pointing to the peak
            ax.annotate(f'Peak EF: {peak_val:.2f}\n({peak_date.strftime("%b %Y")})',
                        xy=(peak_date, peak_val), 
                        xytext=(15, 15), textcoords='offset points',
                        fontsize=9, color='#d35400', fontweight='bold',
                        arrowprops=dict(arrowstyle='->', color='#d35400', connectionstyle="arc3,rad=.2"))

            # 4. Academic Formatting
            
            # Title and Labels
            # Using TeX notation for units makes it look very scientific
            ax.set_ylabel(r'Efficiency Factor ($\frac{m/min}{bpm}$)', fontsize=11, fontweight='bold')
            ax.set_title('Longitudinal Aerobic Efficiency Trend', fontsize=14, pad=15, fontweight='bold')
            
            # Remove top and right spines (Tufte style minimalism)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_linewidth(0.5)
            ax.spines['bottom'].set_linewidth(0.5)

            # X-Axis Date Formatting
            locator = mdates.AutoDateLocator(minticks=5, maxticks=12)
            formatter = mdates.ConciseDateFormatter(locator)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(formatter)
            plt.setp(ax.get_xticklabels(), fontsize=9)

            # Grid and Legend
            ax.grid(True, which='major', axis='y', linestyle='--', alpha=0.4)
            ax.grid(False, axis='x') # Vertical grids often clutter time series
            
            # Legend placed cleanly
            ax.legend(frameon=True, fancybox=False, edgecolor='black', fontsize=9, loc='upper left')

            # Final layout adjustment
            plt.tight_layout()
            
            # Save
            output_path = self.output_dir / "efficiency_factor.png"

            result = self._finalize_figure(fig, output_path, dpi=dpi or 600, facecolor='white', return_buffer=return_buffer)
            if not return_buffer:
                logger.info("Professional efficiency plot saved to %s", output_path)
            return result

    def plot_performance_frontier(self, sport_types=['Run'], return_buffer: bool = False, dpi: int | None = None) -> BytesIO | None:
        """
        Plots the Distance-Pace Frontier with Riegel's Fatigue Model fitting.
        
        Insights:
        - Empirical Frontier: Actual best performances.
        - Theoretical Frontier: Power-law fit (Riegel's formula).
        - Fatigue Factor: Slope of decay (lower is better endurance).
        """
        
        # --- 1. Data Prep ---
        gdf, _ = self._filter_and_get_gdf(sport_types)
        if gdf is None or gdf.empty:
            logger.info("No data found.")
            return
        
        df = gdf[['distance', 'average_speed', 'start_date_local']].dropna()
        
        # Conversions
        df['dist_km'] = df['distance'] / 1000.0
        df['speed_m_s'] = df['average_speed']
        df['pace_dec'] = 16.66667 / df['average_speed'] # Decimal min/km
        
        # Cleaning: Remove obvious GPS errors or trivial runs
        df = df[(df['pace_dec'] > 2.5) & (df['pace_dec'] < 10.0)] 
        df = df[df['dist_km'] > 1.0]

        # --- 2. Calculate Pareto Frontier (Empirical Boundary) ---
        # Sort by distance to make the loop efficient
        df_sorted = df.sort_values('dist_km', ascending=False)
        
        # A point is on the frontier if it has the highest speed for any distance >= itself.
        # (Simple sweep algorithm)
        frontier_indices = []
        max_speed_so_far = -1
        
        for idx, row in df_sorted.iterrows():
            if row['speed_m_s'] > max_speed_so_far:
                frontier_indices.append(idx)
                max_speed_so_far = row['speed_m_s']
                
        frontier = df.loc[frontier_indices].sort_values('dist_km')

        # --- 3. Scientific Insight: Riegel's Power Law Fit ---
        # Model: Speed = C * Distance^b (where b is fatigue factor, typically negative)
        # We fit this log-log to the frontier points only.
        
        def power_law(x, c, b):
            return c * np.power(x, b)

        # Fit curve to the frontier data (scipy imported here: heavy, and only this plot needs it)
        from scipy.optimize import curve_fit
        popt, _ = curve_fit(power_law, frontier['dist_km'], frontier['speed_m_s'], 
                            p0=[6.0, -0.07], maxfev=5000)
        c_fit, b_fit = popt
        
        # Generate smooth curve for plotting
        x_model = np.linspace(frontier['dist_km'].min(), frontier['dist_km'].max() * 1.1, 100)
        y_model_speed = power_law(x_model, c_fit, b_fit)
        y_model_pace = 16.66667 / y_model_speed

        # --- 4. Professional Plotting ---
        with plt.style.context('seaborn-v0_8-whitegrid'):
            fig, ax = plt.subplots(figsize=(12, 8))

            # A. The "Cloud" (Training Volume)
            ax.scatter(df['dist_km'], df['pace_dec'], 
                    c='#bdc3c7', alpha=0.3, s=10, 
                    label='Training Activities', edgecolors='none')

            # B. The Theoretical Limit (Model)
            # This line represents "Physiological Potential" based on best efforts
            ax.plot(x_model, y_model_pace, 
                    color='#2c3e50', linestyle='--', linewidth=1.5, alpha=0.8,
                    label=f'Riegel Fit (Fatigue Factor: {b_fit:.3f})')

            # C. The Empirical Frontier (Actual Records)
            ax.plot(frontier['dist_km'], frontier['pace_dec'], 
                    color='#e74c3c', linewidth=2.5, marker='o', markersize=6,
                    label='Pareto Frontier (Actual Bests)')

            # D. Smart Annotations for Standard Distances
            # We find the frontier point closest to standard distances to label them
            standard_dists = [5, 10, 21.1, 42.2]
            for d_target in standard_dists:
                # Find nearest point in frontier
                closest_idx = (frontier['dist_km'] - d_target).abs().idxmin()
                row = frontier.loc[closest_idx]
                
                # Only annotate if it's actually close to the standard distance (e.g., within 10%)
                if abs(row['dist_km'] - d_target) / d_target < 0.15:
                    mins = int(row['pace_dec'])
                    secs = int((row['pace_dec'] % 1) * 60)
                    
                    ax.annotate(f"{d_target}k\n{mins}:{secs:02d}", 
                                xy=(row['dist_km'], row['pace_dec']),
                                xytext=(0, 25), textcoords='offset points',
                                ha='center', va='bottom',
                                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#e74c3c", alpha=0.8),
                                fontsize=9, fontweight='bold', color='#c0392b',
                                arrowprops=dict(arrowstyle='->', color='#e74c3c'))

            # --- 5. Formatting ---

            def pace_fmt(x, pos):
                m = int(x)
                s = int((x % 1) * 60)
                return f"{m}:{s:02d}"

            ax.yaxis.set_major_formatter(ticker.FuncFormatter(pace_fmt))
            ax.invert_yaxis() # Traditional running plots have faster (lower) pace at top
            
            ax.set_xlabel('Distance (km)', fontsize=11, fontweight='bold')
            ax.set_ylabel('Pace (min/km)', fontsize=11, fontweight='bold')
            ax.set_title('Performance Frontier & Fatigue Decay', fontsize=14, pad=15, fontweight='bold')
            
            # Legend with insight
            ax.legend(frameon=True, fancybox=False, edgecolor='black', loc='upper right')

            plt.tight_layout()
            out_path = self.output_dir / "performance_frontier.png"

            result = self._finalize_figure(fig, out_path, dpi=dpi or 600, facecolor='white', return_buffer=return_buffer)
            if not return_buffer:
                logger.info("Frontier plot saved to %s", out_path)
            return result


    def plot_weekly_report(
        self,
        weekly_report: dict,
        folder: Path | None = None,
        neon_color: str = "#fc0101",
        return_buffer: bool = False,
        last_week_report: dict | None = None,
        dpi: int | None = None,
    ) -> BytesIO | None:
        """
        Plot weekly report statistics in neon style for Instagram Stories.
        Shows activities per day bar plot, sports breakdown pie charts, and key stats.
        
        Args:
            weekly_report: Dictionary from get_weekly_report()
            folder: Output folder path (default: workdir/weekly_reports)
            neon_color: Primary neon color for the visualization
            last_week_report: Dictionary from get_weekly_report() for the previous week.
                              If provided, deltas (▲/▼) are shown below each main stat.
        """
        
        # Instagram Story size: 9:16 aspect ratio
        fig = plt.figure(figsize=(9, 16), facecolor='black')
        # Adjust margins - increased bottom margin for the accumulated plot
        fig.subplots_adjust(left=0.02, right=0.98, top=0.95, bottom=0.05)

        
        # 1. DEFINE RATIOS
        # We split the bottom space: 1.7 for pies, 2.0 for accumulated plot
        ratios = [0.75, 0.5, 1.0, 1.7, 2.0]
        
        # 2. CREATE GRID (5 rows now)
        gs = fig.add_gridspec(5, 1, height_ratios=ratios, hspace=0.10)
        
        # Extract data
        week_start = weekly_report.get(WeeklyReportFeatures.WEEK_START, "")
        week_end = weekly_report.get(WeeklyReportFeatures.WEEK_END, "")
        total_activities = weekly_report.get(WeeklyReportFeatures.TOTAL_ACTIVITIES, 0)
        total_km = weekly_report.get(WeeklyReportFeatures.TOTAL_DISTANCE_KM, 0)
        total_elevation = weekly_report.get(WeeklyReportFeatures.TOTAL_ELEVATION_M, 0)
        total_hours = weekly_report.get(WeeklyReportFeatures.TOTAL_TIME_HOURS, 0)
        active_days = weekly_report.get(WeeklyReportFeatures.ACTIVE_DAYS, 0)
        activities_per_day = weekly_report.get(WeeklyReportFeatures.ACTIVITIES_PER_DAY, {})
        distance_per_day_km = weekly_report.get(WeeklyReportFeatures.DISTANCE_PER_DAY_KM, {})
        distance_per_sport = weekly_report.get(WeeklyReportFeatures.DISTANCE_PER_SPORT_KM, {})
        activities_per_sport = weekly_report.get(WeeklyReportFeatures.ACTIVITIES_PER_SPORT, {})
        num_sports = len(activities_per_sport)
        longest_km = weekly_report.get(WeeklyReportFeatures.LONGEST_ACTIVITY_KM, 0)
        
        # --- Header Panel ---
        ax_header = fig.add_subplot(gs[0])
        ax_header.set_facecolor('black')
        ax_header.set_axis_off()
        
        # Format week range for display
        try:
            start_dt = datetime.strptime(week_start, '%Y-%m-%d')
            end_dt = datetime.strptime(week_end, '%Y-%m-%d')
            week_range = f"{start_dt.strftime('%b %d')} - {end_dt.strftime('%b %d, %Y')}"
        except ValueError:
            week_range = f"{week_start} - {week_end}"
        
        # Title
        ax_header.text(
            0.5, 0.75, "WEEKLY REPORT",
            transform=ax_header.transAxes,
            ha='center', va='center',
            color=neon_color,
            fontsize=36,
            fontfamily='monospace',
            fontweight='bold',
            alpha=0.9
        )
        
        # Week range subtitle
        ax_header.text(
            0.5, 0.45, week_range.upper(),
            transform=ax_header.transAxes,
            ha='center', va='center',
            color='white',
            fontsize=16,
            fontfamily='monospace',
            alpha=0.7
        )
        
        # --- Main Stats Panel ---
        ax_stats = fig.add_subplot(gs[1])
        ax_stats.set_facecolor('black')
        ax_stats.set_axis_off()
        
        # Compute deltas from last week if available
        if last_week_report is not None:
            prev_activities = last_week_report.get(WeeklyReportFeatures.TOTAL_ACTIVITIES, 0)
            prev_km = last_week_report.get(WeeklyReportFeatures.TOTAL_DISTANCE_KM, 0)
            prev_hours = last_week_report.get(WeeklyReportFeatures.TOTAL_TIME_HOURS, 0)
            prev_active_days = last_week_report.get(WeeklyReportFeatures.ACTIVE_DAYS, 0)
            prev_elevation = last_week_report.get(WeeklyReportFeatures.TOTAL_ELEVATION_M, 0)
            prev_num_sports = len(last_week_report.get(WeeklyReportFeatures.ACTIVITIES_PER_SPORT, {}))
            prev_longest_km = last_week_report.get(WeeklyReportFeatures.LONGEST_ACTIVITY_KM, 0)

            delta_activities = total_activities - prev_activities
            delta_km = total_km - prev_km
            delta_hours = total_hours - prev_hours
            delta_active_days = active_days - prev_active_days
            delta_elevation = total_elevation - prev_elevation
            delta_num_sports = num_sports - prev_num_sports
            delta_longest_km = longest_km - prev_longest_km

            def _fmt_delta(delta: float, fmt: str = ".1f") -> str:
                arrow = "▲" if delta >= 0 else "▼"
                return f"{arrow} {abs(delta):{fmt}}"

            deltas = [
                _fmt_delta(delta_activities, ".0f"),
                _fmt_delta(delta_km, ".1f"),
                _fmt_delta(delta_hours, ".1f"),
                _fmt_delta(delta_active_days, ".0f"),
                _fmt_delta(delta_elevation, ".0f"),
                _fmt_delta(delta_num_sports, ".0f"),
                _fmt_delta(delta_longest_km, ".1f"),
            ]
            def _delta_color(delta: float) -> str:
                if delta == 0:
                    return '#888888'
                return '#00ff88' if delta > 0 else '#ff4444'

            delta_colors = [
                _delta_color(delta_activities),
                _delta_color(delta_km),
                _delta_color(delta_hours),
                _delta_color(delta_active_days),
                _delta_color(delta_elevation),
                _delta_color(delta_num_sports),
                _delta_color(delta_longest_km),
            ]
        else:
            deltas = [None] * 7
            delta_colors = [None] * 7

        stats_data = [
            (f"{total_activities}", "ACTIVITIES"),
            (f"{total_km:,.1f}", "KM"),
            (f"{total_hours:,.1f}", "HOURS"),
            (f"{active_days}", "ACTIVE DAYS"),
            (f"{total_elevation:,.0f}", "↑ METERS"),
            (f"{num_sports}", "SPORTS"),
            (f"{longest_km:,.1f}", "LONGEST KM"),
        ]
        
        num_boxes = len(stats_data)
        box_width = 1.0 / num_boxes
        
        for i, (value, label) in enumerate(stats_data):
            box_center = i * box_width + box_width / 2
            
            # Main value
            ax_stats.text(
                box_center, 0.80, value,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color="#cacaca",
                fontsize=24,
                fontfamily='monospace',
                fontweight='bold'
            )
            
            # Delta from last week (shown below value)
            delta_text = deltas[i]
            if delta_text is not None:
                ax_stats.text(
                    box_center, 0.52, delta_text,
                    transform=ax_stats.transAxes,
                    ha='center', va='center',
                    color=delta_colors[i],
                    fontsize=12,
                    fontfamily='monospace',
                    fontweight='bold',
                    alpha=0.75
                )
            
            # Label
            ax_stats.text(
                box_center, 0.28, label,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=10,
                fontfamily='monospace',
                alpha=0.6
            )
        
        # --- HR Zone Distribution (Horizontal Bar Chart) ---
        ax_chart = fig.add_subplot(gs[2])
        ax_chart.set_facecolor('black')
        
        # Get sports per day data (still needed for sport colors later)
        sports_per_day = weekly_report.get(WeeklyReportFeatures.SPORTS_PER_DAY, {})
        
        # Define sport colors - distinct neon colors for each sport
        sport_color_palette = [
            '#fc0101',  # Red
            '#00ff88',  # Green
            '#00aaff',  # Blue
            '#ff00ff',  # Magenta
            '#faff00',  # Yellow
            '#ff8800',  # Orange
            '#00ffff',  # Cyan
            '#ff0088',  # Pink
            '#88ff00',  # Lime
            '#8800ff',  # Purple
        ]
        
        # Create sport color mapping from distance_per_sport (sorted by distance)
        if distance_per_sport:
            sorted_sports = sorted(distance_per_sport.items(), key=lambda x: x[1], reverse=True)
            all_sports = [s[0] for s in sorted_sports]
        else:
            all_sports = []
        
        sport_colors = {sport: sport_color_palette[i % len(sport_color_palette)] 
                       for i, sport in enumerate(all_sports)}
        
        # HR Zone distribution
        hr_zone_distribution = weekly_report.get(WeeklyReportFeatures.HR_ZONE_DISTRIBUTION, {})
        
        # Get max HR to calculate zone ranges
        hr_max = self.strava_analytics.get_max_heart_rate()
        
        # Zone colors (green to red gradient)
        zone_colors = {
            1: '#00ff88',  # Z1 - Recovery (green)
            2: '#00aaff',  # Z2 - Endurance (blue)
            3: '#faff00',  # Z3 - Tempo (yellow)
            4: '#ff8800',  # Z4 - Threshold (orange)
            5: '#fc0101',  # Z5 - VO2max (red)
        }
        
        # Calculate HR ranges for each zone
        zone_ranges = weekly_report[WeeklyReportFeatures.HR_ZONE_RANGES]
        
        zone_labels = [f'Z{z} ({zone_ranges[z][0]}-{zone_ranges[z][1]})' for z in range(1, 6)]
        zones = [1, 2, 3, 4, 5]
        counts = [hr_zone_distribution.get(z, 0) for z in zones]
        
        # Create horizontal bar chart
        y_positions = range(len(zones))
        bars = ax_chart.barh(y_positions, counts, height=0.6, 
                            color=[zone_colors[z] for z in zones],
                            edgecolor=[zone_colors[z] for z in zones], linewidth=3, alpha=0.6)
        
        # Add count labels at the end of each bar
        max_count = max(counts) if max(counts) > 0 else 1
        for i, (bar, count) in enumerate(zip(bars, counts)):
            if count > 0:
                ax_chart.text(bar.get_width() + max_count * 0.05, bar.get_y() + bar.get_height() / 2,
                             f'{count}%', va='center', ha='left',
                             color=zone_colors[zones[i]], fontsize=12, fontfamily='monospace', fontweight='bold')
        
        # Style the chart - better centered
        ax_chart.set_yticks(y_positions)
        ax_chart.set_yticklabels(zone_labels, color='white', fontsize=10, fontfamily='monospace', fontweight='bold')
        ax_chart.invert_yaxis()  # Z1 at top
        ax_chart.set_xlim(-0.1, max_count * 1.4 if max_count > 0 else 1)
        ax_chart.set_xticks([])
        ax_chart.spines['bottom'].set_visible(False)
        ax_chart.spines['top'].set_visible(False)
        ax_chart.spines['right'].set_visible(False)
        ax_chart.spines['left'].set_visible(False)
        ax_chart.tick_params(axis='y', colors='white', length=0, pad=10)
        
        # Add title
        ax_chart.text(0.5, 1.05, 'HR ZONES', transform=ax_chart.transAxes,
                     ha='center', va='bottom', color='white', fontsize=11,
                     fontfamily='monospace', fontweight='bold', alpha=0.7)
        
        # Center the chart horizontally
        ax_chart.set_position([0.20, ax_chart.get_position().y0, 0.6, ax_chart.get_position().height])

        # --- Sports Breakdown: Two Pie Charts Side by Side ---
        # Create a sub-gridspec for title, legend, and pie charts
        gs_pies = gs[3].subgridspec(2, 2, height_ratios=[0.2, 1], wspace=0.1, hspace=0.0)
        
        # Get time per sport from weekly report (in hours, convert to minutes)
        time_per_sport_hours = weekly_report.get(WeeklyReportFeatures.TIME_PER_SPORT_HOURS, {})
        
        if distance_per_sport:
            # Limit to top 6 sports for pie charts
            sports = all_sports[:6] if len(all_sports) > 6 else all_sports
            # Sort by distance descending
            sport_distances = [distance_per_sport.get(s, 0) for s in sports]
            
            # Use sport_colors from earlier
            colors = [sport_colors.get(s, neon_color) for s in sports]
            
            # --- Add legend row between title and pie charts ---
            ax_legend = fig.add_subplot(gs_pies[0, :])
            ax_legend.set_facecolor('black')
            ax_legend.set_axis_off()
            
            # Create custom legend patches
            from matplotlib.patches import Patch
            legend_patches = [Patch(facecolor=sport_colors.get(s, neon_color), edgecolor='white', label=s.upper()) 
                            for s in sports]
        
            
            # --- Left Pie: Distance per Sport ---
            ax_dist_pie = fig.add_subplot(gs_pies[1, 0])
            ax_dist_pie.set_facecolor('black')

            # A week of only distance-less sessions (gym) has no wedges to draw
            if sum(sport_distances) > 0:
                # Create pie with neon style - show actual km values
                wedges, texts = ax_dist_pie.pie(
                    sport_distances,
                    labels=None,
                    radius=1.2,
                    colors=colors,
                    wedgeprops=dict(width=0.9, edgecolor='black', linewidth=2, alpha=0.6),
                    startangle=90
                )

                # Add actual value labels manually
                for i, (wedge, dist) in enumerate(zip(wedges, sport_distances)):
                    ang = (wedge.theta2 - wedge.theta1) / 2.0 + wedge.theta1
                    x = 0.75 * np.cos(np.radians(ang))
                    y = 0.75 * np.sin(np.radians(ang))
                    if dist > 0:
                        ax_dist_pie.text(x, y, f'{dist:.1f}', ha='center', va='center',
                                        color='white', fontsize=9, fontfamily='monospace', fontweight='bold')

            # Title for distance pie
            ax_dist_pie.text(
                0.5, 1.15, "DISTANCE (KM)",
                transform=ax_dist_pie.transAxes,
                ha='center', va='top',
                color='white',
                fontsize=12,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.8
            )
            
            # --- Right Pie: Time per Sport ---
            ax_time_pie = fig.add_subplot(gs_pies[1, 1])
            ax_time_pie.set_facecolor('black')
            
            # Get time values for the same sports (in order) - convert hours to minutes
            sport_times = [time_per_sport_hours.get(s, 0) * 60 for s in sports]
            
            if sum(sport_times) > 0:
                # Create pie with neon style - show actual minutes values
                wedges2, texts2 = ax_time_pie.pie(
                    sport_times,
                    labels=None,
                    radius=1.2,
                    colors=colors,
                    wedgeprops=dict(width=0.9, edgecolor='black', linewidth=2, alpha=0.6),
                    startangle=90
                )
                
                # Add actual value labels manually
                for i, (wedge, mins) in enumerate(zip(wedges2, sport_times)):
                    ang = (wedge.theta2 - wedge.theta1) / 2.0 + wedge.theta1
                    x = 0.75 * np.cos(np.radians(ang))
                    y = 0.75 * np.sin(np.radians(ang))
                    if mins > 0:
                        ax_time_pie.text(x, y, f'{mins:.0f}', ha='center', va='center',
                                        color='white', fontsize=9, fontfamily='monospace', fontweight='bold')
            
            # Title for time pie
            ax_time_pie.text(
                0.5, 1.15, "MINUTES",
                transform=ax_time_pie.transAxes,
                ha='center', va='top',
                color='white',
                fontsize=12,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.8
            )
        else:
            ax_sports = fig.add_subplot(gs[3])
            ax_sports.set_facecolor('black')
            ax_sports.set_axis_off()
            ax_sports.text(
                0.5, 0.5, "NO ACTIVITIES THIS WEEK",
                transform=ax_sports.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=14,
                fontfamily='monospace',
                alpha=0.5
            )
        
        # --- Accumulated Minutes Line Plot (Bottom Panel) ---
        ax_accum = fig.add_subplot(gs[4])
        ax_accum.set_facecolor('black')
        
        # Add title - using ax_accum.text with transform for 0-1 positioning
        # ax_accum.text(0.5, 0.90, 'ACCUMULATED TRAINING TIME', 
        #              transform=ax_accum.transAxes,
        #              ha='center', va='top',
        #              color='white', fontsize=11,
        #              fontfamily='monospace', fontweight='bold', alpha=0.7)
        
        time_per_sport_per_day = weekly_report.get(WeeklyReportFeatures.TIME_PER_SPORT_PER_DAY_MINS, {})
        activities_titles_per_day_per_sport = weekly_report.get(WeeklyReportFeatures.ACTIVITIES_TITLES_PER_DAY_PER_SPORT, {})
        
        if time_per_sport_per_day and distance_per_sport:
            days = list(range(7))
            day_labels = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
            
            # Calculate total accumulated across all sports first
            total_accumulated = [0] * 7
            total_daily_mins = [0] * 7
            for sport in all_sports:
                if sport not in time_per_sport_per_day:
                    continue
                daily_mins = time_per_sport_per_day[sport]
                for day in days:
                    total_daily_mins[day] += daily_mins.get(day, 0)
            
            # Compute total accumulated
            running_total = 0
            for day in days:
                running_total += total_daily_mins[day]
                total_accumulated[day] = running_total
            
            # Plot total accumulated line (white, continuous, behind sport lines)
            ax_accum.fill_between(days, total_accumulated, alpha=0.05, color='white')
            ax_accum.plot(days, total_accumulated, color='white', linewidth=2, alpha=0.4, zorder=1)
            
            # Points and labels for total - only when change happens
            for d, val in zip(days, total_accumulated):
                if total_daily_mins[d] > 0:
                    # Vertical dashed line from point to bottom
                    ax_accum.vlines(d, 0, val, colors='white', linestyles='dashed', alpha=0.2, linewidth=1, zorder=0)
                    ax_accum.scatter([d], [val], color='white', s=60, zorder=6, edgecolors='white', linewidths=1, alpha=0.8)
                    ax_accum.text(d, val + (max(total_accumulated) * 0.05 if max(total_accumulated) > 0 else 5), 
                                 f'{int(val)}', ha='center', va='bottom',
                                 color='white', fontsize=9, fontfamily='monospace', fontweight='bold', alpha=0.9)
            
            # For each sport, compute accumulated minutes across the week
            for sport in all_sports:
                if sport not in time_per_sport_per_day:
                    continue
                    
                daily_mins = time_per_sport_per_day[sport]
                accumulated = []
                total = 0
                for day in days:
                    total += daily_mins.get(day, 0)
                    accumulated.append(total)
                
                color = sport_colors.get(sport, neon_color)
                
                # Area under the curve with alpha
                ax_accum.fill_between(days, accumulated, alpha=0.15, color=color)
                # Line with linewidth 2
                ax_accum.plot(days, accumulated, color=color, linewidth=2, alpha=0.9, zorder=3)
                
                # Points and labels only when there's activity that day (change happens)
                for d, val in zip(days, accumulated):
                    day_mins = daily_mins.get(d, 0)
                    if day_mins > 0:  # Only show point/label when activity happened that day
                        # Vertical dashed line from point to bottom
                        ax_accum.vlines(d, 0, val, colors=color, linestyles='dashed', alpha=0.2, linewidth=1, zorder=2)
                        ax_accum.scatter([d], [val], color=color, s=50, zorder=5, edgecolors='white', linewidths=1)
                        ax_accum.text(d, val - (max(total_accumulated) * 0.05 if max(total_accumulated) > 0 else 5), 
                                     f'{int(val)}', ha='center', va='top',
                                     color=color, fontsize=8, fontfamily='monospace', fontweight='bold')
                        
                        # Add activity titles if available (small text below the minutes)
                        if sport in activities_titles_per_day_per_sport:
                            titles = activities_titles_per_day_per_sport[sport].get(d, [])
                            if titles:
                                # Truncate long titles and join multiple activities
                                max_size = 18
                                short_titles = [t[:max_size] + '...' if len(t) > max_size else t for t in titles]
                                title_text = ', '.join(short_titles)
                                ax_accum.text(d, val - (max(total_accumulated) * 0.10 if max(total_accumulated) > 0 else 10), 
                                             title_text, ha='center', va='top',
                                             color=color, fontsize=7, fontfamily='monospace', alpha=0.8, fontweight='bold')
            
            # Style the chart - cleaner without y-axis
            ax_accum.set_xticks(days)
            ax_accum.set_xticklabels(day_labels, color='white', fontsize=12, fontfamily='monospace', fontweight='bold')
            ax_accum.tick_params(axis='x', colors='white', length=0, pad=10)
            ax_accum.set_yticks([])  # Remove y-axis ticks
            ax_accum.spines['bottom'].set_visible(False)
            ax_accum.spines['left'].set_visible(False)
            ax_accum.spines['top'].set_visible(False)
            ax_accum.spines['right'].set_visible(False)
            ax_accum.grid(axis='y', color=neon_color, alpha=0.05, linestyle=':')
            ax_accum.set_xlim(-0.5, 6.5)
            
            # Add some padding at the top for labels
            ylim = ax_accum.get_ylim()
            ax_accum.set_ylim(0, ylim[1] * 1.20 if ylim[1] > 0 else 10)
            
            # Add sport legend - centered
            from matplotlib.patches import Patch
            sports_for_legend = all_sports[:6] if len(all_sports) > 6 else all_sports
            legend_patches = [Patch(facecolor=sport_colors.get(s, neon_color), edgecolor='white', label=s.upper()) 
                            for s in sports_for_legend]
            ax_accum.legend(
                handles=legend_patches,
                loc='upper center',
                ncol=min(4, len(sports_for_legend)),
                frameon=False,
                fontsize=11,
                labelcolor='white',
            )
        else:
            ax_accum.set_axis_off()
        
        # --- Save ---
        if folder is None:
            folder = self.workdir / "weekly_reports"
        folder.mkdir(parents=True, exist_ok=True)

        filename = f"weekly_report_{week_start}.png"
        out_path = folder / filename

        result = self._finalize_figure(fig, out_path, dpi=dpi or 300, return_buffer=return_buffer)
        if not return_buffer:
            logger.info("Weekly report saved to %s", out_path)
        return result
