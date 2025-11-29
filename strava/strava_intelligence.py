from pathlib import Path
from strava.strava_analytics import StravaAnalytics
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