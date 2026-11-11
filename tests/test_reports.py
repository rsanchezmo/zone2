"""Year-in-sport and weekly report figures as pure functions over made-up activities."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from zone2.reports import (
    AllYearInSportFeatures as A, WeeklyReportFeatures as W, YearInSportFeatures as Y, activities_between,
    activities_per_week, all_year_in_sport, week_bounds, weekly_report, year_activities, year_in_sport,
)
from tests.synthetic import ZONES, activities_frame

NOW = datetime(2026, 11, 11, 12)


def act(activity_id: int, sport_type: str, start: str, distance: float, moving_time: int,
        elevation: float = 0.0) -> dict:
    return {"id": activity_id, "name": f"Activity {activity_id}", "sport_type": sport_type, "start_date_local": start,
            "distance": distance, "moving_time": moving_time, "total_elevation_gain": elevation,
            "average_speed": distance / moving_time}


def test_a_cutoff_keeps_the_whole_cutoff_day():
    activities = activities_frame([
        act(1, "Run", "2026-02-20T23:30:00Z", 5000, 1500),
        act(2, "Run", "2026-02-21T00:10:00Z", 5000, 1500),
        act(3, "Run", "2025-02-01T08:00:00Z", 5000, 1500),
        act(4, "Ride", "2026-01-05T08:00:00Z", 20000, 2400),
    ])
    assert year_activities(activities, 2026, (2, 20))["id"].tolist() == [4, 1]
    assert year_activities(activities, 2026, (2, 20), "Run")["id"].tolist() == [1]
    assert year_activities(activities, 2026, None, "Run")["id"].tolist() == [1, 2]


def test_activities_per_week_count_the_weeks_elapsed():
    # 364 days of 2025 are 52 weeks
    assert activities_per_week(104, 2025, None, NOW) == 2.0
    # To Feb 20: 50 days
    assert activities_per_week(10, 2026, (2, 20), NOW) == 10 / (50 / 7)
    # Never less than a week
    assert activities_per_week(3, 2026, None, datetime(2026, 1, 3)) == 3.0
    assert activities_per_week(0, 2026, None, NOW) == 0.0


def runs_2026() -> pd.DataFrame:
    return activities_frame([
        act(1, "Run", "2026-01-05T08:00:00Z", 10000, 3000, elevation=50),   # Monday
        act(2, "Run", "2026-01-07T08:00:00Z", 21100, 6000, elevation=120),  # Wednesday
        act(3, "Run", "2026-03-02T08:00:00Z", 5000, 1200, elevation=10),    # Monday, the fastest
        act(4, "Ride", "2026-03-03T08:00:00Z", 40000, 4800),
        act(5, "Swim", "2026-03-04T08:00:00Z", 2000, 2400),
    ])


def test_year_in_sport():
    year = year_in_sport(runs_2026(), 2026, "Run", None, NOW)
    assert (year[Y.TOTAL_ACTIVITIES], year[Y.TOTAL_DISTANCE_KM], year[Y.TOTAL_ELEVATION_M]) == (3, 36.1, 180.0)
    assert (year[Y.TOTAL_TIME_HOURS], year[Y.ACTIVE_DAYS], year[Y.AVERAGE_DISTANCE_KM]) == (2.8, 3, 12.03)
    assert year[Y.ACTIVITIES_PER_MONTH] == {1: 2, 3: 1}
    assert year[Y.DISTANCE_PER_MONTH_KM] == {1: 31.1, 3: 5.0}
    assert (year[Y.MONTH_MOST_ACTIVITIES], year[Y.MONTH_MOST_KM], year[Y.MONTH_LEAST_KM]) == (1, 1, 3)
    assert year[Y.MOST_ACTIVE_WEEKDAY] == 0
    assert (year[Y.LONGEST_ACTIVITY_KM], year[Y.LONGEST_ACTIVITY_KM_ID]) == (21.1, "2")
    assert (year[Y.LONGEST_ACTIVITY_MINS], year[Y.LONGEST_ACTIVITY_MINS_ID]) == (100.0, "2")
    assert (year[Y.FASTEST_ACTIVITY_SPEED], year[Y.FASTEST_ACTIVITY_SPEED_ID]) == (5000 / 1200, "3")
    assert year[Y.AVERAGE_SPEED] == 36100 / 10200
    # Jan 1 to Nov 11: 314 days
    assert year[Y.ACTIVITIES_PER_WEEK] == round(3 / (314 / 7), 1)


def test_an_empty_year_in_sport():
    year = year_in_sport(runs_2026(), 2010, "Run", None, NOW)
    assert (year[Y.TOTAL_ACTIVITIES], year[Y.LONGEST_ACTIVITY_KM_ID], year[Y.MONTH_MOST_KM]) == (0, None, None)
    assert (year[Y.AVERAGE_SPEED], year[Y.ACTIVITIES_PER_WEEK]) == (0.0, 0.0)


def test_all_year_in_sport():
    year = all_year_in_sport(runs_2026(), 2026, (3, 3), NOW)
    assert (year[A.TOTAL_ACTIVITIES], year[A.TOTAL_DISTANCE_KM], year[A.ACTIVE_DAYS]) == (4, 76.1, 4)
    assert year[A.ACTIVITIES_PER_SPORT] == {"Ride": 1, "Run": 3}
    assert (year[A.SPORT_MOST_DONE], year[A.MOST_ACTIVE_MONTH], year[A.MOST_ACTIVE_WEEKDAY]) == ("Run", 1, 0)
    # Jan 1 to Mar 3: 61 days
    assert year[A.ACTIVITIES_PER_WEEK] == round(4 / (61 / 7), 1)


def test_week_bounds():
    start, end = week_bounds("2026-11-05", None, NOW)
    assert (start, end) == (pd.Timestamp("2026-11-02", tz="UTC"), pd.Timestamp("2026-11-08T23:59:59", tz="UTC"))
    assert week_bounds("2026-11-02", "2026-11-04", NOW)[1] == pd.Timestamp("2026-11-04T23:59:59", tz="UTC")
    start, end = week_bounds(None, None, datetime(2026, 11, 11, 15, 30, tzinfo=timezone.utc))
    assert (start, end) == (datetime(2026, 11, 9, tzinfo=timezone.utc), datetime(2026, 11, 15, 23, 59, 59, tzinfo=timezone.utc))


def test_weekly_report_zones_and_histogram_come_from_every_hr_sample():
    activities = activities_frame([act(1, "Run", "2026-11-02T07:00:00Z", 10000, 3000),
                                   act(2, "Ride", "2026-11-05T18:00:00Z", 30000, 3600),
                                   act(3, "Run", "2026-11-09T07:00:00Z", 5000, 1500)])
    start, end = week_bounds("2026-11-05", None, NOW)
    week = activities_between(activities, start, end)
    counts = [(np.array([130.0, 150.0]), np.array([3, 1]))]
    report = weekly_report(week, start, end, ZONES, counts)
    assert (report[W.WEEK_START], report[W.WEEK_END], report[W.TOTAL_ACTIVITIES]) == ("2026-11-02", "2026-11-08", 2)
    assert report[W.HR_ZONE_DISTRIBUTION] == {1: 0.0, 2: 75.0, 3: 25.0, 4: 0.0, 5: 0.0}
    # 1 bpm bins from 2 under the lowest sample to 2 over the highest
    histogram = report[W.HR_HISTOGRAM]
    assert histogram["min_bpm"] == 128 and len(histogram["counts"]) == 24
    assert (histogram["counts"][2], histogram["counts"][22], sum(histogram["counts"])) == (3, 1, 4)
    assert report[W.TIME_PER_SPORT_PER_DAY_MINS]["Ride"][3] == 60.0
    assert report[W.ACTIVITIES_TITLES_PER_DAY_PER_SPORT]["Run"][0] == ["Activity 1"]
    assert (report[W.LONGEST_ACTIVITY_KM], report[W.LONGEST_ACTIVITY_NAME]) == (30.0, "Activity 2")
    assert report[W.HR_ZONE_RANGES][2] == (120, 140)

    no_hr = weekly_report(week, start, end, ZONES, [])
    assert (no_hr[W.HR_ZONE_DISTRIBUTION][2], no_hr[W.HR_HISTOGRAM]) == (0.0, None)
    empty = weekly_report(activities_between(activities, *week_bounds("2010-01-04", None, NOW)), start, end, None, [])
    assert (empty[W.TOTAL_ACTIVITIES], empty[W.SPORTS_PER_DAY][6], empty[W.HR_ZONE_RANGES]) == (0, [], {})
