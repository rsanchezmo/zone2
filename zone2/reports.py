"""Year-in-sport and weekly report figures from the activities table, keyed by
the StrEnum feature classes the visualizer and the API read."""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from zone2.training_load import HeartRateCounts, HrZone
from zone2.utils import SportCategory, hr_zone_counts, sport_mask


class YearInSportFeatures(StrEnum):
    TOTAL_ACTIVITIES = "total_activities"
    TOTAL_DISTANCE_KM = "total_distance_km"
    TOTAL_ELEVATION_M = "total_elevation_m"
    TOTAL_TIME_HOURS = "total_time_hours"
    ACTIVE_DAYS = "active_days"
    ACTIVITIES_PER_MONTH = "activities_per_month"
    DISTANCE_PER_MONTH_KM = "distance_per_month_km"
    MOST_ACTIVE_WEEKDAY = "most_active_weekday"
    MONTH_MOST_ACTIVITIES = "month_most_activities"
    MONTH_MOST_KM = "month_most_km"
    MONTH_LEAST_KM = "month_least_km"
    LONGEST_ACTIVITY_KM = "longest_activity_km"
    LONGEST_ACTIVITY_KM_ID = "longest_activity_km_id"
    LONGEST_ACTIVITY_MINS = "longest_activity_mins"
    LONGEST_ACTIVITY_MINS_ID = "longest_activity_mins_id"
    FASTEST_ACTIVITY_SPEED = "fastest_activity_speed"  # m/s
    FASTEST_ACTIVITY_SPEED_ID = "fastest_activity_speed_id"
    AVERAGE_DISTANCE_KM = "average_distance_km"
    AVERAGE_SPEED = "average_speed"  # m/s
    ACTIVITIES_PER_WEEK = "activities_per_week"


class AllYearInSportFeatures(StrEnum):
    TOTAL_ACTIVITIES = "total_activities"
    TOTAL_DISTANCE_KM = "total_distance_km"
    TOTAL_TIME_HOURS = "total_time_hours"
    ACTIVE_DAYS = "active_days"
    ACTIVITIES_PER_WEEK = "activities_per_week"
    ACTIVITIES_PER_SPORT = "activities_per_sport"
    MOST_ACTIVE_WEEKDAY = "most_active_weekday"
    MOST_ACTIVE_MONTH = "most_active_month"
    SPORT_MOST_DONE = "sport_most_done"


class WeeklyReportFeatures(StrEnum):
    WEEK_START = "week_start"
    WEEK_END = "week_end"
    TOTAL_ACTIVITIES = "total_activities"
    TOTAL_DISTANCE_KM = "total_distance_km"
    TOTAL_ELEVATION_M = "total_elevation_m"
    TOTAL_TIME_HOURS = "total_time_hours"
    ACTIVE_DAYS = "active_days"
    ACTIVITIES_PER_DAY = "activities_per_day"  # dict: weekday (0-6) -> count
    DISTANCE_PER_DAY_KM = "distance_per_day_km"  # dict: weekday (0-6) -> km
    DISTANCE_PER_SPORT_KM = "distance_per_sport_km"  # dict: sport -> km
    ACTIVITIES_PER_SPORT = "activities_per_sport"  # dict: sport -> count
    TIME_PER_SPORT_HOURS = "time_per_sport_hours"  # dict: sport -> hours
    SPORTS_PER_DAY = "sports_per_day"  # dict: weekday (0-6) -> list of sports
    TIME_PER_SPORT_PER_DAY_MINS = "time_per_sport_per_day_mins"  # dict: sport -> dict: weekday (0-6) -> minutes
    ACTIVITIES_TITLES_PER_DAY_PER_SPORT = "activities_titles_per_day_per_sport"  # dict: sport -> dict: weekday (0-6) -> list of activity titles
    HR_ZONE_DISTRIBUTION = "hr_zone_distribution"  # dict: zone (1-5) -> % of the week's HR samples
    HR_HISTOGRAM = "hr_histogram"  # {min_bpm: int, counts: list[int]} 1 bpm bins (or null when no HR samples)
    MOST_ACTIVE_DAY = "most_active_day"  # weekday (0-6)
    LONGEST_ACTIVITY_KM = "longest_activity_km"
    LONGEST_ACTIVITY_NAME = "longest_activity_name"
    HR_ZONE_RANGES = "hr_zone_ranges"  # dict: zone (1-5) -> (min_hr, max_hr)


def year_activities(activities: pd.DataFrame, year: int, cutoff_month_day: tuple[int, int] | None,
                    sport: str | SportCategory | None = None) -> pd.DataFrame:
    """The activities of `year` (of `sport` when given, see sport_mask), up to
    the end of the (month, day) `cutoff_month_day` when given."""
    dates = activities['start_date_local']
    mask = dates.dt.year == year
    if sport is not None:
        mask = mask & sport_mask(activities['sport_type'], sport)
    if cutoff_month_day:
        cutoff = pd.Timestamp(year, cutoff_month_day[0], cutoff_month_day[1], 23, 59, 59)
        if dates.dt.tz is not None:
            cutoff = cutoff.tz_localize(dates.dt.tz)
        mask = mask & (dates <= cutoff)
    return activities[mask].copy()


def activities_per_week(total_activities: int, year: int, cutoff_month_day: tuple[int, int] | None,
                        now: datetime) -> float:
    """Activities per week elapsed in `year`: up to the cutoff when given,
    otherwise up to `now` (the athlete's wall clock, naive) or the year's end."""
    if not total_activities:
        return 0.0
    year_start = datetime(year, 1, 1)
    if cutoff_month_day:
        year_end_or_today = datetime(year, cutoff_month_day[0], cutoff_month_day[1])
    else:
        year_end_or_today = min(now, datetime(year, 12, 31))
    weeks_in_year = max(1, (year_end_or_today - year_start).days / 7)
    return total_activities / weeks_in_year


def year_in_sport(activities: pd.DataFrame, year: int, main_sport: str | SportCategory,
                  cutoff_month_day: tuple[int, int] | None, now: datetime) -> dict[YearInSportFeatures, Any]:
    """A year of `main_sport` (a Strava sport type, or a category), up to `cutoff_month_day`
    when given for a fair comparison with a year in progress (e.g. only up
    to Feb 20). `now` is the athlete's wall clock, naive."""
    activities_year = year_activities(activities, year, cutoff_month_day, main_sport)

    total_activities = len(activities_year)
    total_distance_km = activities_year['distance'].sum() / 1000.0
    total_elevation_m = activities_year['total_elevation_gain'].sum()
    total_time_hours = activities_year['moving_time'].sum() / 3600.0
    active_days = activities_year['start_date_local'].dt.date.nunique()

    activities_per_month = activities_year.groupby(activities_year['start_date_local'].dt.month).size()
    month_most_activities = activities_per_month.idxmax() if not activities_per_month.empty else None
    activities_per_month = activities_per_month.to_dict()

    activities_per_weekday = activities_year.groupby(activities_year['start_date_local'].dt.weekday).size()
    most_active_weekday = activities_per_weekday.idxmax() if not activities_per_weekday.empty else None

    distance_per_month = activities_year.groupby(activities_year['start_date_local'].dt.month)['distance'].sum()
    month_most_km = distance_per_month.idxmax() if not distance_per_month.empty else None
    month_least_km = distance_per_month.idxmin() if not distance_per_month.empty else None

    if not activities_year.empty:
        longest_activity_km = activities_year['distance'].max() / 1000.0
        longest_activity_km_id = activities_year.loc[activities_year['distance'].idxmax()]['id']
        longest_activity_mins = activities_year['moving_time'].max() / 60.0
        longest_activity_mins_id = activities_year.loc[activities_year['moving_time'].idxmax()]['id']
        # The fastest by average speed (m/s)
        fastest_activity_speed = activities_year['average_speed'].max()
        fastest_activity_speed_id = activities_year.loc[activities_year['average_speed'].idxmax()]['id']
    else:
        longest_activity_km = 0.0
        longest_activity_km_id = None
        longest_activity_mins = 0.0
        longest_activity_mins_id = None
        fastest_activity_speed = 0.0
        fastest_activity_speed_id = None

    average_distance_km = (total_distance_km / total_activities) if total_activities > 0 else 0.0
    # m/s, from total time and distance
    average_speed = (total_distance_km * 1000) / (total_time_hours * 3600) if total_time_hours > 0 else 0.0

    return {
        YearInSportFeatures.TOTAL_ACTIVITIES: total_activities,
        YearInSportFeatures.TOTAL_DISTANCE_KM: float(round(total_distance_km, 2)),
        YearInSportFeatures.TOTAL_ELEVATION_M: float(round(total_elevation_m)),
        YearInSportFeatures.TOTAL_TIME_HOURS: float(round(total_time_hours, 1)),
        YearInSportFeatures.AVERAGE_DISTANCE_KM: float(round(average_distance_km, 2)),
        YearInSportFeatures.ACTIVE_DAYS: active_days,
        YearInSportFeatures.ACTIVITIES_PER_MONTH: {month: int(count) for month, count in activities_per_month.items()},
        YearInSportFeatures.DISTANCE_PER_MONTH_KM: {month: float(round(dist / 1000.0, 2)) for month, dist in distance_per_month.items()},
        YearInSportFeatures.MOST_ACTIVE_WEEKDAY: int(most_active_weekday) if most_active_weekday is not None else None,
        YearInSportFeatures.MONTH_MOST_ACTIVITIES: int(month_most_activities) if month_most_activities is not None else None,
        YearInSportFeatures.MONTH_MOST_KM: int(month_most_km) if month_most_km is not None else None,
        YearInSportFeatures.MONTH_LEAST_KM: int(month_least_km) if month_least_km is not None else None,
        YearInSportFeatures.LONGEST_ACTIVITY_KM: float(round(longest_activity_km, 2)),
        YearInSportFeatures.LONGEST_ACTIVITY_MINS: float(round(longest_activity_mins, 2)),
        YearInSportFeatures.LONGEST_ACTIVITY_KM_ID: str(longest_activity_km_id) if longest_activity_km_id is not None else None,
        YearInSportFeatures.LONGEST_ACTIVITY_MINS_ID: str(longest_activity_mins_id) if longest_activity_mins_id is not None else None,
        YearInSportFeatures.FASTEST_ACTIVITY_SPEED: float(fastest_activity_speed),
        YearInSportFeatures.FASTEST_ACTIVITY_SPEED_ID: str(fastest_activity_speed_id) if fastest_activity_speed_id is not None else None,
        YearInSportFeatures.AVERAGE_SPEED: float(average_speed),
        YearInSportFeatures.ACTIVITIES_PER_WEEK: float(round(activities_per_week(total_activities, year, cutoff_month_day, now), 1)),
    }


def all_year_in_sport(activities: pd.DataFrame, year: int, cutoff_month_day: tuple[int, int] | None,
                      now: datetime) -> dict[AllYearInSportFeatures, Any]:
    """A year across all sports, up to `cutoff_month_day` when given. `now`
    is the athlete's wall clock, naive."""
    activities_year = year_activities(activities, year, cutoff_month_day)

    total_activities = len(activities_year)
    total_distance_km = activities_year['distance'].sum() / 1000.0
    total_time_hours = activities_year['moving_time'].sum() / 3600.0
    active_days = activities_year['start_date_local'].dt.date.nunique()

    activities_per_sport = activities_year.groupby('sport_type').size().to_dict()

    activities_per_weekday = activities_year.groupby(activities_year['start_date_local'].dt.weekday).size()
    most_active_weekday = activities_per_weekday.idxmax() if not activities_per_weekday.empty else None

    activities_per_month = activities_year.groupby(activities_year['start_date_local'].dt.month).size()
    most_active_month = activities_per_month.idxmax() if not activities_per_month.empty else None

    sport_most_done = max(activities_per_sport, key=activities_per_sport.get) if activities_per_sport else None

    return {
        AllYearInSportFeatures.TOTAL_ACTIVITIES: total_activities,
        AllYearInSportFeatures.TOTAL_DISTANCE_KM: float(round(total_distance_km, 2)),
        AllYearInSportFeatures.TOTAL_TIME_HOURS: float(round(total_time_hours, 1)),
        AllYearInSportFeatures.ACTIVE_DAYS: active_days,
        AllYearInSportFeatures.ACTIVITIES_PER_WEEK: float(round(activities_per_week(total_activities, year, cutoff_month_day, now), 1)),
        AllYearInSportFeatures.ACTIVITIES_PER_SPORT: {sport: int(count) for sport, count in activities_per_sport.items()},
        AllYearInSportFeatures.MOST_ACTIVE_WEEKDAY: int(most_active_weekday) if most_active_weekday is not None else None,
        AllYearInSportFeatures.MOST_ACTIVE_MONTH: int(most_active_month) if most_active_month is not None else None,
        AllYearInSportFeatures.SPORT_MOST_DONE: sport_most_done,
    }


def week_bounds(week_start_date: str | None, cutoff_date: str | None, now: datetime) -> tuple[datetime, datetime]:
    """Monday 00:00 of the week of `week_start_date` ('YYYY-MM-DD', `now`'s
    week when None) and the end of its Sunday, or of `cutoff_date` when given
    to compare a full week with one still running. `now` is the athlete's wall
    clock labelled UTC, like start_date_local (Clock.now)."""
    if week_start_date is None:
        last_monday = now - timedelta(days=now.weekday())
        week_start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        week_start = pd.to_datetime(week_start_date, utc=True)
        week_start = week_start - timedelta(days=week_start.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    if cutoff_date:
        week_end = pd.to_datetime(cutoff_date, utc=True).replace(hour=23, minute=59, second=59)
    else:
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return week_start, week_end


def activities_between(activities: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    return activities[
        (activities['start_date_local'] >= start) &
        (activities['start_date_local'] <= end)
    ].copy()


def weekly_report(activities_week: pd.DataFrame, week_start: datetime, week_end: datetime,
                  hr_zones: list[HrZone] | None, hr_counts: list[HeartRateCounts]) -> dict[WeeklyReportFeatures, Any]:
    """The week's activities (activities_between the week_bounds) summed per
    day and sport, with the zone distribution and a 1 bpm histogram of every
    HR sample of the week (`hr_counts`, one per activity with HR)."""
    total_activities = len(activities_week)
    total_distance_km = activities_week['distance'].sum() / 1000.0
    total_elevation_m = activities_week['total_elevation_gain'].sum()
    total_time_hours = activities_week['moving_time'].sum() / 3600.0
    active_days = activities_week['start_date_local'].dt.date.nunique()

    # 0 = Monday, 6 = Sunday
    activities_per_day = activities_week.groupby(
        activities_week['start_date_local'].dt.weekday
    ).size().reindex(range(7), fill_value=0).to_dict()

    distance_per_day = activities_week.groupby(
        activities_week['start_date_local'].dt.weekday
    )['distance'].sum().reindex(range(7), fill_value=0) / 1000.0
    distance_per_day_km = distance_per_day.to_dict()

    distance_per_sport = (
        activities_week.groupby('sport_type')['distance'].sum() / 1000.0
    ).to_dict() if not activities_week.empty else {}

    activities_per_sport = (
        activities_week.groupby('sport_type').size()
    ).to_dict() if not activities_week.empty else {}

    time_per_sport = (
        activities_week.groupby('sport_type')['moving_time'].sum() / 3600.0
    ).to_dict() if not activities_week.empty else {}

    sports_per_day: dict[int, list[str]] = {}
    if not activities_week.empty:
        for day in range(7):
            day_activities = activities_week[activities_week['start_date_local'].dt.weekday == day]
            sports_per_day[day] = day_activities['sport_type'].tolist()
    else:
        sports_per_day = {day: [] for day in range(7)}

    # Minutes per sport per day, for the accumulated line plot, and the titles
    time_per_sport_per_day_mins: dict[str, dict[int, float]] = {}
    activities_titles_per_day_per_sport: dict[str, dict[int, list[str]]] = {}
    if not activities_week.empty:
        for sport in activities_week['sport_type'].unique():
            sport_activities = activities_week[activities_week['sport_type'] == sport]
            time_per_day = sport_activities.groupby(
                sport_activities['start_date_local'].dt.weekday
            )['moving_time'].sum().reindex(range(7), fill_value=0) / 60.0
            time_per_sport_per_day_mins[sport] = {int(k): float(round(v, 1)) for k, v in time_per_day.to_dict().items()}

            titles_per_day: dict[int, list[str]] = {}
            for day in range(7):
                day_activities = sport_activities[sport_activities['start_date_local'].dt.weekday == day]
                titles_per_day[day] = day_activities['name'].tolist()
            activities_titles_per_day_per_sport[sport] = titles_per_day

    hr_zone_distribution = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
    hr_histogram: dict | None = None
    if not activities_week.empty and hr_zones and hr_counts:
        hr_values = np.concatenate([values for values, _ in hr_counts])
        hr_weights = np.concatenate([counts for _, counts in hr_counts])
        total = int(hr_weights.sum())
        in_zone = hr_zone_counts(hr_values, hr_zones, hr_weights)
        for zone_idx in range(5):
            hr_zone_distribution[zone_idx + 1] = round((float(in_zone[zone_idx]) / total) * 100, 1)

        # Snapped to a small margin around min/max so the renderer doesn't
        # clip the curve at the edges.
        lo = int(np.floor(hr_values.min())) - 2
        hi = int(np.ceil(hr_values.max())) + 2
        if hi > lo:
            counts, _ = np.histogram(hr_values, bins=np.arange(lo, hi + 1), weights=hr_weights)
            hr_histogram = {"min_bpm": int(lo), "counts": counts.astype(int).tolist()}

    if not activities_week.empty:
        activities_per_day_series = activities_week.groupby(
            activities_week['start_date_local'].dt.weekday
        ).size()
        most_active_day = int(activities_per_day_series.idxmax()) if not activities_per_day_series.empty else None
    else:
        most_active_day = None

    if not activities_week.empty:
        longest_idx = activities_week['distance'].idxmax()
        longest_activity_km = activities_week.loc[longest_idx, 'distance'] / 1000.0
        longest_activity_name = activities_week.loc[longest_idx, 'name']
    else:
        longest_activity_km = 0.0
        longest_activity_name = None

    return {
        WeeklyReportFeatures.WEEK_START: week_start.strftime('%Y-%m-%d'),
        WeeklyReportFeatures.WEEK_END: week_end.strftime('%Y-%m-%d'),
        WeeklyReportFeatures.TOTAL_ACTIVITIES: total_activities,
        WeeklyReportFeatures.TOTAL_DISTANCE_KM: float(round(total_distance_km, 2)),
        WeeklyReportFeatures.TOTAL_ELEVATION_M: float(round(total_elevation_m, 1)),
        WeeklyReportFeatures.TOTAL_TIME_HOURS: float(round(total_time_hours, 2)),
        WeeklyReportFeatures.ACTIVE_DAYS: active_days,
        WeeklyReportFeatures.ACTIVITIES_PER_DAY: {int(k): int(v) for k, v in activities_per_day.items()},
        WeeklyReportFeatures.DISTANCE_PER_DAY_KM: {int(k): float(round(v, 2)) for k, v in distance_per_day_km.items()},
        WeeklyReportFeatures.DISTANCE_PER_SPORT_KM: {k: float(round(v, 2)) for k, v in distance_per_sport.items()},
        WeeklyReportFeatures.ACTIVITIES_PER_SPORT: {k: int(v) for k, v in activities_per_sport.items()},
        WeeklyReportFeatures.TIME_PER_SPORT_HOURS: {k: float(round(v, 2)) for k, v in time_per_sport.items()},
        WeeklyReportFeatures.SPORTS_PER_DAY: sports_per_day,
        WeeklyReportFeatures.TIME_PER_SPORT_PER_DAY_MINS: time_per_sport_per_day_mins,
        WeeklyReportFeatures.ACTIVITIES_TITLES_PER_DAY_PER_SPORT: activities_titles_per_day_per_sport,
        WeeklyReportFeatures.HR_ZONE_DISTRIBUTION: hr_zone_distribution,
        WeeklyReportFeatures.HR_HISTOGRAM: hr_histogram,
        WeeklyReportFeatures.MOST_ACTIVE_DAY: most_active_day,
        WeeklyReportFeatures.LONGEST_ACTIVITY_KM: float(round(longest_activity_km, 2)),
        WeeklyReportFeatures.LONGEST_ACTIVITY_NAME: longest_activity_name,
        WeeklyReportFeatures.HR_ZONE_RANGES: {
            i: (zone['min'], zone['max']) for i, zone in enumerate(hr_zones, start=1)
        } if hr_zones else {},
    }
