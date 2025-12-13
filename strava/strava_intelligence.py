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
            self.sync_activities()


    def sync_activities(self, full_sync: bool = False, include_streams: bool = False):
        """Sync activities from Strava API to local cache."""
        
        if full_sync:
            print("🔄 Performing full sync (all activities)...")
            activities = self.strava_endpoint.get_activities(include_streams=include_streams)
        else:
            last_date = self.strava_activities_cache.get_last_activity_date()
            if last_date:
                print(f"🔄 Syncing activities from {last_date.date()}...")
                from_date = last_date - timedelta(days=1)
                activities = self.strava_endpoint.get_activities(from_date=from_date, include_streams=include_streams)
            else:
                print("🔄 No cached activities found. Performing full sync...")
                activities = self.strava_endpoint.get_activities(include_streams=include_streams)

        self.strava_activities_cache.save_activities(activities)
        print(f"✓ Synced {len(activities)} activities")


    def save_geojson_activities(self):
        """Save activities as GeoJSON file."""
        gdf = get_activities_as_gdf(self.strava_activities_cache.activities)
        filepath = self.workdir / "activities.geojson"
        gdf.to_file(filepath, driver="GeoJSON")
        print(f"✓ Saved activities to {filepath}")


    def get_year_in_sport(self, year: int, main_sport: str, neon_color: str = "#fc0101") -> dict:
        """Get year in sport for the specified year."""
        
        year_in_sport_main_sport = self.strava_analytics.get_year_in_sport(year, main_sport)
        year_in_sport = {
            main_sport : year_in_sport_main_sport,
            'all': self.strava_analytics.get_all_year_in_sport(year)
            }
        
        output_folder = self.workdir / "year_in_sport" / str(year)
        
        # Plot year in sport summary - main sport
        self.strava_visualizer.plot_year_in_sport_main(
            year=year,
            year_in_sport=year_in_sport,
            main_sport=main_sport,
            folder=output_folder,
            neon_color=neon_color
        )
        
        # Plot year in sport summary - totals across all sports
        self.strava_visualizer.plot_year_in_sport_totals(
            year=year,
            year_in_sport=year_in_sport,
            folder=output_folder,
            neon_color=neon_color
        )
        
        # plot longest activity (by time), fastest activity and longest distance activity
        self.strava_visualizer.plot_activity(
            year_in_sport_main_sport[YearInSportFeatures.LONGEST_ACTIVITY_MINS_ID], 
            self.strava_endpoint,
            folder=output_folder, 
            title="Longest Activity (Time)",
            neon_color=neon_color
        )
        self.strava_visualizer.plot_activity(
            year_in_sport_main_sport[YearInSportFeatures.FASTEST_ACTIVITY_PACE_ID], 
            self.strava_endpoint,
            folder=output_folder, 
            title="Fastest Activity",
            neon_color=neon_color
        )
        self.strava_visualizer.plot_activity(
            year_in_sport_main_sport[YearInSportFeatures.LONGEST_ACTIVITY_KM_ID], 
            self.strava_endpoint,
            folder=output_folder, 
            title="Longest Activity (Distance)",
            neon_color=neon_color
        )
        return year_in_sport