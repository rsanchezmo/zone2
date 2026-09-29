import sqlite3

import pandas as pd

from backend.db import DB_PATH
from zone2.core import Zone2
from zone2.utils import get_sport_category

# An event's activity is within this share of the event's distance: GPS
# over- and under-reads a course by a few percent, a warm-up is far shorter.
RACE_DISTANCE_TOLERANCE = 0.25


def race_activity_ids(activities: pd.DataFrame, events: list[tuple[str, str, float | None]]) -> frozenset[int]:
    """The activity of each race event (date, sport_type, distance_km): the one
    that day of the event's sport whose distance is closest to the event's."""
    if activities.empty or not events:
        return frozenset()
    days = activities['start_date_local'].dt.strftime('%Y-%m-%d')
    categories = activities['sport_type'].map(get_sport_category)
    ids = set()
    for day, sport_type, distance_km in events:
        candidates = activities[(days == day) & (categories == get_sport_category(sport_type))]
        if distance_km:
            off = (candidates['distance'] / 1000 - distance_km).abs()
            candidates = candidates[off <= RACE_DISTANCE_TOLERANCE * distance_km]
            off = off[candidates.index]
        else:
            off = -candidates['distance']   # no distance given: the longest that day
        if not candidates.empty:
            ids.add(int(candidates.loc[off.idxmin(), 'id']))
    return frozenset(ids)


def refresh_race_activities(z2: Zone2) -> bool:
    """Point the analytics at the activities of the user's race calendar, so a
    race counts as one without being flagged on Strava. Returns whether the
    set changed (race-based stats then need recomputing)."""
    with sqlite3.connect(DB_PATH) as c:
        events = c.execute("SELECT date, sport_type, distance_km FROM race_events").fetchall()
    ids = race_activity_ids(z2.strava_activities_cache.get_prepared_view(), events)
    return z2.strava_analytics.set_race_activity_ids(ids)
