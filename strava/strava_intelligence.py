from pathlib import Path
from strava.strava_analytics import StravaAnalytics, YearInSportFeatures
from strava.strava_user_cache import StravaUserCache
from strava.strava_activities_cache import StravaActivitiesCache
from strava.strava_endpoint import StravaEndpoint
from strava.strava_utils import *
from strava.strava_visualizer import StravaVisualizer
from datetime import timedelta


class StravaIntelligence:
    def __init__(self, workdir: Path, auto_sync: bool = True, sync_max_age_hours: int = 12):
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)

        self.strava_endpoint = StravaEndpoint()
        self.strava_activities_cache = StravaActivitiesCache()
        self.strava_user_cache = StravaUserCache(self.strava_endpoint)
        self.strava_analytics = StravaAnalytics(self.strava_activities_cache, self.strava_user_cache)
        self.strava_visualizer = StravaVisualizer(self.strava_analytics, workdir)

        if auto_sync and self.strava_activities_cache.needs_sync(max_age_hours=sync_max_age_hours):
            # only enable include_streams on full sync to avoid long sync times on incremental syncs
            self.sync_activities(include_streams=True)


    def sync_activities(self, full_sync: bool = False, include_streams: bool = False):
        """Sync activities from Strava API to local cache."""
        
        if full_sync:
            print("🔄 Performing full sync (all activities)...")
            activities = self.strava_endpoint.get_activities()

        else:
            last_date = self.strava_activities_cache.get_last_activity_date()
            if last_date:
                print(f"🔄 Syncing activities from {last_date.date()}...")
                from_date = last_date - timedelta(days=1)
                activities = self.strava_endpoint.get_activities(from_date=from_date)
            else:
                print("🔄 No cached activities found. Performing full sync...")
                activities = self.strava_endpoint.get_activities()

        self.strava_activities_cache.save_activities(activities)
        print(f"✓ Synced {len(activities)} activities")

        # Now, fetch streams and zones if requested for the saved activities
        if include_streams:
            print("🔄 Syncing streams for activities...")
            self.strava_activities_cache.sync_streams(
                strava_endpoint=self.strava_endpoint,
                activity_ids=[activity['id'] for activity in activities]
            )


    def ensure_activities_with_streams(self):
        """Ensure all cached activities have streams and zones data."""
        print("🔄 Ensuring all activities have streams and zones data...")
        activities = self.strava_activities_cache.activities
        self.strava_activities_cache.sync_streams(
            strava_endpoint=self.strava_endpoint,
            activity_ids=activities['id'].tolist() if not activities.empty else None
        )


    def save_geojson_activities(self):
        """Save activities as GeoJSON file."""
        gdf = get_activities_as_gdf(self.strava_activities_cache.activities)
        filepath = self.workdir / "activities.geojson"
        gdf.to_file(filepath, driver="GeoJSON")
        print(f"✓ Saved activities to {filepath}")

    
    def plot_last_activity(self, sport_type: str):
        """Plot the last activity of the specified sport type."""
        activities = self.strava_activities_cache.activities

        # filter by sport type
        activities = activities[activities['sport_type'] == sport_type]
        if activities.empty:
            print(f"No activities found for sport type: {sport_type}")
            return
        
        # activities are already ordered by start_date ascending
        last_activity = activities.iloc[-1]["id"]
        self.strava_visualizer.plot_activity(last_activity, self.strava_endpoint, folder=self.strava_visualizer.output_dir, title=f"Last {sport_type} Activity")


    def get_year_in_sport(self, year: int, main_sport: str, neon_color: str = "#fc0101", comparison_year: int | None = None, comparison_neon_color: str = "#00aaff") -> dict:
        """Get year in sport for the specified year and main sport, with an optional comparison year."""
        
        year_in_sport_main_sport = self.strava_analytics.get_year_in_sport(year, main_sport)
        year_in_sport = {
            main_sport : year_in_sport_main_sport,
            'all': self.strava_analytics.get_all_year_in_sport(year)
            }
        
        output_folder = self.workdir / "year_in_sport" / str(year)

        # comparison year
        year_in_sport_comparison = None
        if comparison_year is not None:
            year_in_sport_comparison = {
                main_sport: self.strava_analytics.get_year_in_sport(comparison_year, main_sport),
                'all': self.strava_analytics.get_all_year_in_sport(comparison_year)
            }

        # Plot year in sport summary - main sport
        self.strava_visualizer.plot_year_in_sport_main(
            year=year,
            year_in_sport=year_in_sport,
            main_sport=main_sport,
            folder=output_folder,
            neon_color=neon_color,
            comparison_year=comparison_year,
            comparison_data=year_in_sport_comparison,
            comparison_neon_color=comparison_neon_color
        )
        
        # Plot year in sport summary - totals across all sports
        self.strava_visualizer.plot_year_in_sport_totals(
            year=year,
            year_in_sport=year_in_sport,
            folder=output_folder,
            neon_color=neon_color,
            comparison_year=comparison_year,
            comparison_data=year_in_sport_comparison,
            comparison_neon_color=comparison_neon_color
        )
        
        # plot longest activity (by time), fastest activity and longest distance activity
        self.strava_visualizer.plot_activity(
            year_in_sport_main_sport[YearInSportFeatures.LONGEST_ACTIVITY_MINS_ID], 
            self.strava_endpoint,
            folder=output_folder, 
            title="Longest Activity (Time)",
            neon_color=neon_color,
            filename="longest_time_activity.png"
        )
        self.strava_visualizer.plot_activity(
            year_in_sport_main_sport[YearInSportFeatures.FASTEST_ACTIVITY_SPEED_ID], 
            self.strava_endpoint,
            folder=output_folder, 
            title="Fastest Activity",
            neon_color=neon_color,
            filename="fastest_activity.png"
        )
        self.strava_visualizer.plot_activity(
            year_in_sport_main_sport[YearInSportFeatures.LONGEST_ACTIVITY_KM_ID], 
            self.strava_endpoint,
            folder=output_folder, 
            title="Longest Activity (Distance)",
            neon_color=neon_color,
            filename="longest_distance_activity.png"
        )
        return year_in_sport


    def get_weekly_report(self, week_start_date: str | None = None, neon_color: str = "#fc0101") -> dict:
        """
        Generate a weekly report with statistics and visualization.
        
        Args:
            week_start_date: Start of the week in 'YYYY-MM-DD' format. 
                             If None, uses the last completed week.
                             The date will be adjusted to the Monday of that week.
            neon_color: Primary color for the visualization (default: red).
        
        Returns:
            Dictionary with weekly statistics.
        """
        weekly_report = self.strava_analytics.get_weekly_report(week_start_date)
        
        output_folder = self.workdir / "weekly_reports"
        
        self.strava_visualizer.plot_weekly_report(
            weekly_report=weekly_report,
            folder=output_folder,
            neon_color=neon_color
        )
        
        return weekly_report