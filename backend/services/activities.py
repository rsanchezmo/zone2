"""Activity lookups shared by the activities router and the agent."""

import pandas as pd

from zone2.core import Zone2


def similar(z2: Zone2, activity_id: int, limit: int) -> pd.DataFrame | None:
    """The latest activities of the same sport within 10% of its distance and, when it climbs,
    20% of its elevation. None when there is no such activity."""
    target = z2.strava_activities_cache.get_activity_by_id(activity_id)
    if target is None:
        return None
    activities = z2.strava_activities_cache.activities_raw
    sport = target.get("sport_type")
    distance = target.get("distance")
    elevation = target.get("total_elevation_gain")
    if activities.empty or not sport or distance is None or pd.isna(distance):
        return activities.iloc[0:0]

    df = activities[(activities["sport_type"] == sport) & (activities["id"] != activity_id)]
    df = df[df["distance"].between(float(distance) * 0.9, float(distance) * 1.1)]
    if elevation is not None and not pd.isna(elevation) and float(elevation) > 0:
        df = df[df["total_elevation_gain"].fillna(0).between(float(elevation) * 0.8, float(elevation) * 1.2)]
    df = df.assign(start_date_local=pd.to_datetime(df["start_date_local"]))
    return df.sort_values("start_date_local", ascending=False).head(limit)
