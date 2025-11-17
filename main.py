
from strava_endpoint import StravaEndpoint
from datetime import datetime


if __name__ == "__main__":
    # SET THE ENVIRONMENT VARIABLES BEFORE RUNNING THIS SCRIPT
    # export STRAVA_CLIENT_ID=your_client_id
    # export STRAVA_CLIENT_SECRET=your_client_secret

    strava_endpoint = StravaEndpoint()

    athlete_info = strava_endpoint.get_athlete()
    athlete_stats = strava_endpoint.get_athlete_stats()
    activities = strava_endpoint.get_activities(from_date=datetime(2025, 10, 1), to_date=datetime(2025, 11, 30))

    print(athlete_info)
    print(athlete_stats)
    print(f"Fetched {len(activities)} activities")
    print(activities[0] if activities else "No activities found")