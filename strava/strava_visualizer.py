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
