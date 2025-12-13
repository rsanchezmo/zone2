from strava.strava_analytics import StravaAnalytics
from strava.strava_utils import get_activities_as_gdf, get_region_coordinates
from strava.constants import WEB_MERCATOR_CRS, BASE_CRS

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import geopandas as gpd
import contextily as ctx
import pandas as pd
from pathlib import Path
from shapely.geometry import Point
import numpy as np
from scipy.optimize import curve_fit
import matplotlib.ticker as ticker


class StravaVisualizer:
    def __init__(self, strava_analytics: StravaAnalytics, workdir: Path):
        self.strava_analytics = strava_analytics
        self.workdir = workdir
        self.output_dir = self.workdir / "visualizations"
        self.output_dir.mkdir(parents=True, exist_ok=True)

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
                            filter_by_boundary: bool = False) -> tuple[gpd.GeoDataFrame | None, dict | None]:
        """Filters by sport, projects to WebMercator, and spatially filters by radius or boundary."""
        activities = self.strava_analytics.strava_activities_cache.activities
        gdf = get_activities_as_gdf(activities)

        if sport_types:
            gdf = gdf[gdf['sport_type'].isin(sport_types)]
            
        if gdf.empty:
            print(f"No activities found for {sport_types}")
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
            show_title: bool = True
            ) -> None:
        """
        Generates a high-contrast 'Neon' visualization of activities.
        """
        gdf, _ = self._filter_and_get_gdf(sport_types, radius_km, location)
        if gdf is None or gdf.empty:
            print(f"No data found for the specified parameters.")
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
                # DarkMatterOnlyLabels places street names *on top* of the glow, which looks cool
                # DarkMatterNoLabels places just the map background
                ctx.add_basemap(
                    ax, 
                    source=ctx.providers.CartoDB.DarkMatterOnlyLabels, 
                    alpha=0.4,
                    zoom_adjust=1 # Higher res tiles
                )
            except Exception as e:
                print(f"Basemap warning: {e}")

        ax.set_axis_off()
        
        # Summary stats
        total_dist_km = gdf['distance'].sum() / 1000.0
        
        # Formatter: "PARIS | RUNNING | 1,000 KM"
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
        
        plt.savefig(
            save_path, 
            dpi=600, 
            facecolor='black', 
            bbox_inches='tight',
            pad_inches=0.2
        )
        print(f"⚡ Thunderstorm map saved to: {save_path}")
        plt.close()

    def activity_bubble_map(
            self,
            region: str,  # 'Europe', 'Spain', or None for World
            sport_types: list[str] | None = None,
            min_radius_scale: float = 100.0,
            grid_density: int = 100,  # if too low, bubbles may lose position accuracy
            neon_color: str = "#fc0101",
            show_title: bool = False
    ) -> None:
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
            print("No activities found.")
            return
        
        if region_info is None:
            print("Region information not found.")
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
            ctx.add_basemap(
                ax,
                source=ctx.providers.CartoDB.DarkMatter, 
                alpha=0.6,
                zoom_adjust=0, # Auto-zoom usually works well with set_xlim
                zorder=1
            )
        except Exception:
            pass

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
        
        plt.savefig(save_path, dpi=600, facecolor='black', bbox_inches='tight')
        print(f"⚪ Bubble map saved to: {save_path}")
        plt.close()


    def activity_clock(
        self, 
        sport_types: list[str] | None = None,
        neon_color: str = "#fa2100",
        max_dist_km: float | None = None,
        show_title: bool = True
    ) -> None:
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
            print(f"No activities found.")
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
        
        plt.savefig(
            save_path, 
            dpi=600, 
            facecolor='black', 
            bbox_inches='tight'
        )
        print(f"🕑 Activity clock saved to: {save_path}")
        plt.close()

    def plot_activity(
        self,
        activity_id: int | str,
        strava_endpoint,
        folder: Path | None = None,
        title: str | None = None,
        neon_color: str = "#fc0101"
    ) -> None:
        """
        Plot a single activity with neon style map and elevation profile below.
        Fetches activity streams from Strava API for elevation data.
        Sized for Instagram Stories (9:16 aspect ratio).
        """
        from shapely.geometry import LineString
        
        # Get activity from cache
        activities = self.strava_analytics.strava_activities_cache.activities
        activity = activities[activities['id'] == int(activity_id)]
        
        if activity.empty:
            print(f"Activity {activity_id} not found in cache.")
            return
        
        activity = activity.iloc[0]
        
        # Fetch streams for elevation data
        streams = strava_endpoint.get_activity_streams(activity_id)
        
        if not streams:
            print(f"Could not fetch streams for activity {activity_id}")
            return
        
        # Extract data from streams
        latlngs = [(p['lat'], p['lng']) for p in streams if 'lat' in p and 'lng' in p]
        altitudes = [p.get('altitude', 0) for p in streams if 'altitude' in p]
        distances = [p.get('distance', 0) / 1000 for p in streams if 'distance' in p]  # Convert to km
        
        if not latlngs or not altitudes:
            print(f"No GPS or altitude data for activity {activity_id}")
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
        
        # Format pace
        if avg_speed > 0:
            pace_min_per_km = 1000 / (60 * avg_speed)
            pace_mins = int(pace_min_per_km)
            pace_secs = round((pace_min_per_km % 1) * 60)
            if pace_secs == 60:
                pace_mins += 1
                pace_secs = 0
            pace_str = f"{pace_mins}:{pace_secs:02d} /km"
        else:
            pace_str = "N/A"
        stats_text = f"{distance_km:.2f} km  •  {time_str}  •  {pace_str}  •  ↑{total_elevation:.0f} m"
        
        # Custom title if provided - at top with reduced opacity
        if title:
            ax_header.text(
                0.5, 0.82, title.upper(),
                transform=ax_header.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=18,
                fontfamily='monospace',
                fontweight='bold',
                alpha=0.7
            )
        
        # Activity name (Strava title) - smaller, subtle
        ax_header.text(
            0.5, 0.5, activity_name,
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
        filename = f"activity_{activity_id}_{safe_title}.png"
        save_path = output_folder / filename
        
        plt.savefig(
            save_path,
            dpi=120,  # 9*120=1080, 16*120=1920 -> Instagram Story resolution
            facecolor='black',
            bbox_inches='tight',
            pad_inches=0.3
        )
        print(f"🗺️ Activity plot saved to: {save_path}")
        plt.close()

    def plot_year_in_sport_main(
        self,
        year: int,
        year_in_sport: dict,
        main_sport: str,
        folder: Path | None = None,
        neon_color: str = "#fc0101"
    ) -> None:
        """
        Plot main sport statistics in neon style for Instagram Stories.
        Shows sport-specific stats, monthly chart, and highlights.
        """
        from strava.strava_analytics import YearInSportFeatures
        
        main_sport_data = year_in_sport.get(main_sport, {})
        
        # Instagram Story size: 9:16 aspect ratio
        fig = plt.figure(figsize=(9, 16), facecolor='black')
        
        # Create gridspec for layout
        gs = fig.add_gridspec(5, 1, height_ratios=[1.2, 1, 2, 1.5, 1.3], hspace=0.12)
        
        # --- Header Panel ---
        ax_header = fig.add_subplot(gs[0])
        ax_header.set_facecolor('black')
        ax_header.set_axis_off()
        
        # Year title
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
        
        # Big numbers row - 3 stats
        stats_big = [
            (f"{sport_activities}", "ACTIVITIES"),
            (f"{sport_km:,.0f}", "KILOMETERS"),
            (f"↑{sport_elevation:,.0f}", "METERS"),
        ]
        
        for i, (value, label) in enumerate(stats_big):
            x = 0.17 + i * 0.33
            ax_stats.text(
                x, 0.65, value,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color=neon_color,
                fontsize=28,
                fontfamily='monospace',
                fontweight='bold'
            )
            ax_stats.text(
                x, 0.25, label,
                transform=ax_stats.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=9,
                fontfamily='monospace',
                alpha=0.6
            )
        
        # --- Monthly Distance Chart ---
        ax_chart = fig.add_subplot(gs[2])
        ax_chart.set_facecolor('black')
        
        distance_per_month = main_sport_data.get(YearInSportFeatures.DISTANCE_PER_MONTH_KM, {})
        months = list(range(1, 13))
        month_names = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
        values = [distance_per_month.get(m, 0) for m in months]
        
        # Softer neon bar chart
        ax_chart.bar(months, values, color=neon_color, alpha=0.15, width=0.6)
        ax_chart.bar(months, values, color=neon_color, alpha=0.4, width=0.35)
        ax_chart.bar(months, values, color='white', alpha=0.6, width=0.15)
        
        ax_chart.set_xticks(months)
        ax_chart.set_xticklabels(month_names, color='white', fontsize=10, fontfamily='monospace')
        ax_chart.set_yticks([])  # Remove y-axis ticks to prevent width expansion
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
        
        weekday_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        month_full_names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        weekday_str = weekday_names[most_active_weekday] if most_active_weekday is not None else "N/A"
        month_str = month_full_names[month_most_km] if month_most_km else "N/A"
        
        stats_extra = [
            (f"{active_days}", "active days"),
            (f"{avg_km:.1f} km", "avg distance"),
            (weekday_str, "favorite day"),
            (month_str, "best month"),
        ]
        
        for i, (value, label) in enumerate(stats_extra):
            row = i // 2
            col = i % 2
            x = 0.25 + col * 0.5
            y = 0.7 - row * 0.45
            
            ax_extra.text(
                x, y, value,
                transform=ax_extra.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=16,
                fontfamily='monospace',
                fontweight='bold'
            )
            ax_extra.text(
                x, y - 0.15, label,
                transform=ax_extra.transAxes,
                ha='center', va='center',
                color='white',
                fontsize=9,
                fontfamily='monospace',
                alpha=0.5
            )
        
        # --- Highlights Panel ---
        ax_highlights = fig.add_subplot(gs[4])
        ax_highlights.set_facecolor('black')
        ax_highlights.set_axis_off()
        
        longest_km = main_sport_data.get(YearInSportFeatures.LONGEST_ACTIVITY_KM, 0)
        longest_mins = main_sport_data.get(YearInSportFeatures.LONGEST_ACTIVITY_MINS, 0)
        fastest_pace = main_sport_data.get(YearInSportFeatures.FASTEST_ACTIVITY_PACE, 0)
        
        # Format pace (use round for seconds to avoid truncation errors)
        if fastest_pace > 0:
            pace_mins = int(fastest_pace)
            pace_secs = round((fastest_pace % 1) * 60)
            if pace_secs == 60:  # Handle rounding up to 60 seconds
                pace_mins += 1
                pace_secs = 0
            pace_str = f"{pace_mins}:{pace_secs:02d} /km"
        else:
            pace_str = "N/A"
        
        # Format time
        hours = int(longest_mins // 60)
        mins = int(longest_mins % 60)
        time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
        
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
        
        highlights = [
            ("> Longest Distance", f"{longest_km:.2f} km"),
            ("> Longest Time", time_str),
            ("> Fastest Pace", pace_str),
        ]
        
        for i, (label, value) in enumerate(highlights):
            y = 0.65 - i * 0.22
            ax_highlights.text(
                0.1, y, label,
                transform=ax_highlights.transAxes,
                ha='left', va='center',
                color='white',
                fontsize=11,
                fontfamily='monospace',
                alpha=0.6
            )
            ax_highlights.text(
                0.9, y, value,
                transform=ax_highlights.transAxes,
                ha='right', va='center',
                color='white',
                fontsize=11,
                fontfamily='monospace',
                fontweight='bold'
            )
        
        # Save
        output_folder = folder if folder else self.output_dir
        output_folder.mkdir(parents=True, exist_ok=True)
        
        filename = f"year_in_sport_{year}_{main_sport.lower()}.png"
        save_path = output_folder / filename
        
        plt.savefig(
            save_path,
            dpi=120,
            facecolor='black',
            bbox_inches='tight',
            pad_inches=0.3
        )
        print(f"📊 Year in sport ({main_sport}) saved to: {save_path}")
        plt.close()

    def plot_year_in_sport_totals(
        self,
        year: int,
        year_in_sport: dict,
        folder: Path | None = None,
        neon_color: str = "#fc0101"
    ) -> None:
        """
        Plot total year statistics across all sports in neon style for Instagram Stories.
        Shows total stats, sports breakdown, and monthly activity.
        """
        from strava.strava_analytics import AllYearInSportFeatures
        
        all_sports_data = year_in_sport.get('all', {})
        
        # Instagram Story size: 9:16 aspect ratio
        fig = plt.figure(figsize=(9, 16), facecolor='black')
        
        # Create gridspec for layout
        gs = fig.add_gridspec(4, 1, height_ratios=[1.2, 1, 2.5, 2.3], hspace=0.12)
        
        # --- Header Panel ---
        ax_header = fig.add_subplot(gs[0])
        ax_header.set_facecolor('black')
        ax_header.set_axis_off()
        
        # Year title
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
        
        # Big numbers row - 3 columns
        ax_stats.text(
            0.17, 0.6, f"{total_activities}",
            transform=ax_stats.transAxes,
            ha='center', va='center',
            color=neon_color,
            fontsize=36,
            fontfamily='monospace',
            fontweight='bold'
        )
        ax_stats.text(
            0.17, 0.2, "ACTIVITIES",
            transform=ax_stats.transAxes,
            ha='center', va='center',
            color='white',
            fontsize=9,
            fontfamily='monospace',
            alpha=0.6
        )
        
        ax_stats.text(
            0.5, 0.6, f"{total_km:,.0f}",
            transform=ax_stats.transAxes,
            ha='center', va='center',
            color=neon_color,
            fontsize=36,
            fontfamily='monospace',
            fontweight='bold'
        )
        ax_stats.text(
            0.5, 0.2, "KILOMETERS",
            transform=ax_stats.transAxes,
            ha='center', va='center',
            color='white',
            fontsize=9,
            fontfamily='monospace',
            alpha=0.6
        )
        
        ax_stats.text(
            0.83, 0.6, f"{total_hours:,.0f}",
            transform=ax_stats.transAxes,
            ha='center', va='center',
            color=neon_color,
            fontsize=36,
            fontfamily='monospace',
            fontweight='bold'
        )
        ax_stats.text(
            0.83, 0.2, "HOURS",
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
        
        if activities_per_sport:
            # Sort by count descending
            sorted_sports = sorted(activities_per_sport.items(), key=lambda x: x[1], reverse=True)
            sports = [s[0] for s in sorted_sports]
            counts = [s[1] for s in sorted_sports]
            
            # Limit to top 10 sports
            if len(sports) > 10:
                sports = sports[:10]
                counts = counts[:10]
            
            y_pos = np.arange(len(sports))
            max_count = max(counts)
            
            # Create left margin for labels by extending xlim
            label_margin = max_count * 0.35
            
            # Horizontal bar chart with soft neon
            ax_sports.barh(y_pos, counts, left=label_margin, color=neon_color, alpha=0.15, height=0.6)
            ax_sports.barh(y_pos, counts, left=label_margin, color=neon_color, alpha=0.4, height=0.35)
            ax_sports.barh(y_pos, counts, left=label_margin, color='white', alpha=0.6, height=0.12)
            
            # Set xlim to include label margin
            ax_sports.set_xlim(0, label_margin + max_count * 1.15)
            
            # Remove y-axis labels
            ax_sports.set_yticks([])
            ax_sports.set_xticks([])  # Also hide x ticks for cleaner look
            ax_sports.invert_yaxis()
            
            ax_sports.spines['bottom'].set_visible(False)
            ax_sports.spines['left'].set_visible(False)
            ax_sports.spines['top'].set_visible(False)
            ax_sports.spines['right'].set_visible(False)
            
            # Add sport names and count labels
            for i, (sport, count) in enumerate(zip(sports, counts)):
                # Sport name on the left of the bar
                ax_sports.text(
                    label_margin - max_count * 0.03, i, sport,
                    va='center', ha='right',
                    color='white', fontsize=10, fontfamily='monospace', alpha=0.9
                )
                # Count at the end of bar
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
        
        weekday_str = weekday_names[most_active_weekday] if most_active_weekday is not None else "N/A"
        month_str = month_full_names[most_active_month] if most_active_month else "N/A"
        
        ax_highlights.text(
            0.5, 0.92, "HIGHLIGHTS",
            transform=ax_highlights.transAxes,
            ha='center', va='center',
            color=neon_color,
            fontsize=12,
            fontfamily='monospace',
            fontweight='bold',
            alpha=0.7
        )
        
        highlights = [
            ("> Top Sport", sport_most_done),
            ("> Sports Practiced", str(num_sports)),
            ("> Most Active Day", weekday_str),
            ("> Best Month", month_str),
        ]
        
        for i, (label, value) in enumerate(highlights):
            y = 0.75 - i * 0.18
            ax_highlights.text(
                0.1, y, label,
                transform=ax_highlights.transAxes,
                ha='left', va='center',
                color='white',
                fontsize=11,
                fontfamily='monospace',
                alpha=0.6
            )
            ax_highlights.text(
                0.9, y, value,
                transform=ax_highlights.transAxes,
                ha='right', va='center',
                color='white',
                fontsize=11,
                fontfamily='monospace',
                fontweight='bold'
            )
        
        # Save
        output_folder = folder if folder else self.output_dir
        output_folder.mkdir(parents=True, exist_ok=True)
        
        filename = f"year_in_sport_{year}_totals.png"
        save_path = output_folder / filename
        
        plt.savefig(
            save_path,
            dpi=120,
            facecolor='black',
            bbox_inches='tight',
            pad_inches=0.3
        )
        print(f"📊 Year in sport (totals) saved to: {save_path}")
        plt.close()

    def hud_dashboard(
        self, 
        sport_types: list[str] | None = None,
        bins: int = 40
    ) -> None:
        """
        Generates a 3-row 'Cyberpunk HUD' dashboard showing distributions of 
        Distance, Heart Rate, and Speed.
        """
        # 1. Get & Filter Data
        activities = self.strava_analytics.strava_activities_cache.activities
        gdf = get_activities_as_gdf(activities)
        
        if sport_types:
            gdf = gdf[gdf['sport_type'].isin(sport_types)]
        
        if gdf.empty:
            print("No data found.")
            return

        # 2. Prepare Metrics (Drop NaNs for cleaner plots)
        # Distance: Convert to KM
        dist_data = gdf['distance'].dropna() / 1000.0
        
        # Heart Rate: Use raw BPM
        hr_data = gdf['average_heartrate'].dropna() if 'average_heartrate' in gdf.columns else []
        
        # Speed: Convert m/s to  min/km
        speed_data = (16.66667 / gdf['average_speed'].dropna()) if 'average_speed' in gdf.columns else []

        # 3. Setup Canvas (3 Rows, 1 Col)
        fig, axes = plt.subplots(3, 1, figsize=(10, 12), facecolor='black')
        plt.subplots_adjust(hspace=0.4) # Space between panels

        # Helper to draw "Digital Equalizer" style histogram
        def plot_digital_hist(ax, data, color, title, is_pace: bool = False):
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

        # 4. Plot Each Metric
        # Panel 1: Distance (Yellow Neon)
        plot_digital_hist(axes[0], dist_data, color='#faff00', title="DISTANCE [km]")
        
        # Panel 2: Heart Rate (Magenta Neon)
        # Typical neon magenta: #ff00ff
        plot_digital_hist(axes[1], hr_data, color='#ff00ff', title="HR [bpm]")
        
        # Panel 3: Speed (Cyan Neon)
        plot_digital_hist(axes[2], speed_data, color='#00faed', title="PACE ['/km]", is_pace=True)

        # 5. Save
        sport_str = " / ".join(sport_types).upper() if sport_types else "ALL_ACTIVITIES"
        filename = f"hud_{sport_str.replace(' ', '_')}.png"
        save_path = self.output_dir / filename.lower()
        
        plt.savefig(save_path, dpi=600, facecolor='black', bbox_inches='tight')
        print(f"🎛️ HUD dashboard saved to: {save_path}")
        plt.close()

    def plot_efficiency_factor(self, sport_types=['Run'], window=14):
        """
        Plots Aerobic Efficiency (Speed / HR) with publication-quality styling.
        Includes rolling average, standard deviation bands, and peak annotations.
        """
        # 1. Data Prep
        gdf, _ = self._filter_and_get_gdf(sport_types)

        if gdf is None or gdf.empty:
            print("No data found for the specified parameters.")
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
            plt.savefig(output_path, dpi=600, bbox_inches='tight')
            print(f"📈 Professional efficiency plot saved to {output_path}")
            plt.close()

    def plot_performance_frontier(self, sport_types=['Run']):
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
            print("No data found.")
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

        # Fit curve to the frontier data
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
            plt.savefig(out_path, dpi=600, bbox_inches='tight')
            print(f"🚀 Frontier plot saved to {out_path}")
            plt.close()
