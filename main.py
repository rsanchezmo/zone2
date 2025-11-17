
from strava_endpoint import StravaEndpoint
from datetime import datetime
from activities_to_gdf import get_activities_as_gdf


if __name__ == "__main__":
    # SET THE ENVIRONMENT VARIABLES BEFORE RUNNING THIS SCRIPT
    # export STRAVA_CLIENT_ID=your_client_id
    # export STRAVA_CLIENT_SECRET=your_client_secret

    strava_endpoint = StravaEndpoint()

    athlete_info = strava_endpoint.get_athlete()
    athlete_stats = strava_endpoint.get_athlete_stats()
    activities = strava_endpoint.get_activities(from_date=datetime(2025, 10, 1), to_date=datetime(2025, 11, 30), sports=['Run', 'Ride'])

    print(athlete_info)
    print(athlete_stats)

    activities_gdf = get_activities_as_gdf(activities)
    activities_gdf.to_file("activities.geojson", driver="GeoJSON")

