from enum import StrEnum
import json
import pandas as pd
from strava.strava_activities_cache import StravaActivitiesCache
from strava.strava_user_cache import StravaUserCache
from strava.strava_utils import vo2_max, get_activities_as_gdf


class StravaAnalytics:
    def __init__(self, strava_activities_cache: StravaActivitiesCache, strava_user_cache: StravaUserCache):
        self.strava_activities_cache = strava_activities_cache # inmutable data (historical activities)
        self.strava_user_cache = strava_user_cache # mutable data (user profile, stats, zones)


    """
    ===============
    USER ANALYTICS
    ===============
    """

    def get_rest_heart_rate(self):
        """Get the athlete's resting heart rate from cached zones estimated as Z2_min / 2 as proxy."""
        zones = self.strava_user_cache.get_athlete_zones()
        hr_rest = zones['heart_rate']['zones'][1]['min'] / 2

        if hr_rest == 0:
            hr_rest = 60  # Default fallback value
        
        return hr_rest
    
    def get_max_heart_rate(self):
        """Get the athlete's max heart rate from cached zones estimated as Z4_max."""
        zones = self.strava_user_cache.get_athlete_zones()
        hr_max = zones['heart_rate']['zones'][3]['max']
        return hr_max

    def get_current_vo2_max(self):
        """
        Calculate VO2 Max based on Uth-Sørensen-Overgaard-Pedersen estimation:
            VO2 Max = 15.3 x (HR_max / HR_rest)

            It is static as Strava does not provide the historical heart rate data via API.
        """
        hr_max = self.get_max_heart_rate()
        hr_rest = self.get_rest_heart_rate()

        vo2_max_value = vo2_max(hr_max, hr_rest)
        return round(vo2_max_value, 2)
    

    """
    ==================
    ACTIVITY ANALYTICS
    ==================
    """

    def get_year_in_sport(self, year: int, main_sport: str) -> dict:
        """Get year in sport for the specified year."""
        
        # Use raw activities DataFrame (not GeoDataFrame) to include all activities
        activities = self.strava_activities_cache.activities.copy()
        activities['start_date_local'] = pd.to_datetime(activities['start_date_local'])

        # get activities for the specified year
        activities_year = activities[
            (activities['start_date_local'].dt.year == year) &
            (activities['sport_type'] == main_sport)
        ].copy()

        total_activities = len(activities_year)
        total_distance_km = activities_year['distance'].sum() / 1000.0
        total_elevation_m = activities_year['total_elevation_gain'].sum()
        total_time_hours = activities_year['moving_time'].sum() / 3600.0  # Convert seconds to hours
        active_days = activities_year['start_date_local'].dt.date.nunique()

        # get activities per month
        activities_per_month = activities_year.groupby(activities_year['start_date_local'].dt.month).size()
        if not activities_per_month.empty:
            month_most_activities = activities_per_month.idxmax()
        else:
            month_most_activities = None
        activities_per_month = activities_per_month.to_dict()

        # day of the week with most activities
        activities_per_weekday = activities_year.groupby(activities_year['start_date_local'].dt.weekday).size()
        if not activities_per_weekday.empty:
            most_active_weekday = activities_per_weekday.idxmax()
        else:
            most_active_weekday = None

        # month with most kms
        distance_per_month = activities_year.groupby(activities_year['start_date_local'].dt.month)['distance'].sum()
        if not distance_per_month.empty:
            month_most_km = distance_per_month.idxmax()
        else:
            month_most_km = None

        # month with least kms
        if not distance_per_month.empty:
            month_least_km = distance_per_month.idxmin()
        else:
            month_least_km = None


        # longest activity in kms
        if not activities_year.empty:
            longest_activity_km = activities_year['distance'].max() / 1000.0
            longest_activity_km_id = activities_year.loc[activities_year['distance'].idxmax()]['id']
        else:
            longest_activity_km = 0.0
            longest_activity_km_id = None


        # longest activity in mins
        if not activities_year.empty:
            longest_activity_mins = activities_year['moving_time'].max() / 60.0
            longest_activity_mins_id = activities_year.loc[activities_year['moving_time'].idxmax()]['id']
        else:
            longest_activity_mins = 0.0
            longest_activity_mins_id = None

        # average distance per activity
        average_distance_km = (total_distance_km / total_activities) if total_activities > 0 else 0.0

        # average speed (m/s) from total time and distance
        if total_time_hours > 0:
            average_speed = (total_distance_km * 1000) / (total_time_hours * 3600)  # m/s
        else:
            average_speed = 0.0

        # activities per week (based on weeks in year with activity)
        if not activities_year.empty:
            first_activity = activities_year['start_date_local'].min()
            last_activity = activities_year['start_date_local'].max()
            weeks_active = max(1, (last_activity - first_activity).days / 7)
            activities_per_week = total_activities / weeks_active
        else:
            activities_per_week = 0.0

        # activity with fastest speed (m/s) - highest average_speed
        if not activities_year.empty:
            fastest_activity_speed = activities_year['average_speed'].max()
            fastest_activity_speed_id = activities_year.loc[activities_year['average_speed'].idxmax()]['id']
        else:
            fastest_activity_speed = 0.0
            fastest_activity_speed_id = None


        year_in_sport_dict = {
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
            YearInSportFeatures.FASTEST_ACTIVITY_SPEED: float(fastest_activity_speed),  # m/s - format on display
            YearInSportFeatures.FASTEST_ACTIVITY_SPEED_ID: str(fastest_activity_speed_id) if fastest_activity_speed_id is not None else None,
            YearInSportFeatures.AVERAGE_SPEED: float(average_speed),  # m/s - format on display
            YearInSportFeatures.ACTIVITIES_PER_WEEK: float(round(activities_per_week, 1)),
        }

        return year_in_sport_dict


    def get_all_year_in_sport(self, year: int) -> dict:
        """Get overall year in sport stats across all sports for the specified year."""
        
        # Use raw activities DataFrame (not GeoDataFrame) to include all activities
        activities = self.strava_activities_cache.activities.copy()
        activities['start_date_local'] = pd.to_datetime(activities['start_date_local'])

        # get activities for the specified year (all sports)
        activities_year = activities[
            activities['start_date_local'].dt.year == year
        ].copy()

        # total activities and distance
        total_activities = len(activities_year)
        total_distance_km = activities_year['distance'].sum() / 1000.0
        total_time_hours = activities_year['moving_time'].sum() / 3600.0  # Convert seconds to hours
        active_days = activities_year['start_date_local'].dt.date.nunique()

        # activities per week
        if not activities_year.empty:
            first_activity = activities_year['start_date_local'].min()
            last_activity = activities_year['start_date_local'].max()
            weeks_active = max(1, (last_activity - first_activity).days / 7)
            activities_per_week = total_activities / weeks_active
        else:
            activities_per_week = 0.0

        # activities per sport
        activities_per_sport = activities_year.groupby('sport_type').size().to_dict()

        # day of the week with most activities
        activities_per_weekday = activities_year.groupby(activities_year['start_date_local'].dt.weekday).size()
        if not activities_per_weekday.empty:
            most_active_weekday = activities_per_weekday.idxmax()
        else:
            most_active_weekday = None

        # month with most activities
        activities_per_month = activities_year.groupby(activities_year['start_date_local'].dt.month).size()
        if not activities_per_month.empty:
            most_active_month = activities_per_month.idxmax()
        else:
            most_active_month = None

        # sport most done
        if activities_per_sport:
            sport_most_done = max(activities_per_sport, key=activities_per_sport.get)
        else:
            sport_most_done = None

        return {
            AllYearInSportFeatures.TOTAL_ACTIVITIES: total_activities,
            AllYearInSportFeatures.TOTAL_DISTANCE_KM: float(round(total_distance_km, 2)),
            AllYearInSportFeatures.TOTAL_TIME_HOURS: float(round(total_time_hours, 1)),
            AllYearInSportFeatures.ACTIVE_DAYS: active_days,
            AllYearInSportFeatures.ACTIVITIES_PER_WEEK: float(round(activities_per_week, 1)),
            AllYearInSportFeatures.ACTIVITIES_PER_SPORT: {sport: int(count) for sport, count in activities_per_sport.items()},
            AllYearInSportFeatures.MOST_ACTIVE_WEEKDAY: int(most_active_weekday) if most_active_weekday is not None else None,
            AllYearInSportFeatures.MOST_ACTIVE_MONTH: int(most_active_month) if most_active_month is not None else None,
            AllYearInSportFeatures.SPORT_MOST_DONE: sport_most_done,
        }


    def get_weekly_report(self, week_start_date: str | None = None) -> dict:
        """
        Get weekly report for a given week.
        
        Args:
            week_start_date: Start of the week in format 'YYYY-MM-DD'. If None, uses the last completed week.
                             The date will be adjusted to the Monday of that week.
        
        Returns:
            Dictionary with weekly statistics.
        """
        from datetime import datetime, timedelta, timezone
        
        activities = self.strava_activities_cache.activities.copy()
        activities['start_date_local'] = pd.to_datetime(activities['start_date_local'], utc=True)
        
        # Determine the week to report on
        if week_start_date is None:
            # Use the current week
            today = datetime.now(timezone.utc)
            days_since_monday = today.weekday()
            last_monday = today - timedelta(days=days_since_monday)
            week_start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            week_start = pd.to_datetime(week_start_date, utc=True)
            # Adjust to Monday of that week
            days_since_monday = week_start.weekday()
            week_start = week_start - timedelta(days=days_since_monday)
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        # Filter activities for the week
        activities_week = activities[
            (activities['start_date_local'] >= week_start) &
            (activities['start_date_local'] <= week_end)
        ].copy()
        
        # Total aggregations
        total_activities = len(activities_week)
        total_distance_km = activities_week['distance'].sum() / 1000.0
        total_elevation_m = activities_week['total_elevation_gain'].sum()
        total_time_hours = activities_week['moving_time'].sum() / 3600.0
        active_days = activities_week['start_date_local'].dt.date.nunique()
        
        # Activities per day (0=Monday, 6=Sunday)
        activities_per_day = activities_week.groupby(
            activities_week['start_date_local'].dt.weekday
        ).size().reindex(range(7), fill_value=0).to_dict()
        
        # Distance per day
        distance_per_day = activities_week.groupby(
            activities_week['start_date_local'].dt.weekday
        )['distance'].sum().reindex(range(7), fill_value=0) / 1000.0
        distance_per_day_km = distance_per_day.to_dict()
        
        # Per sport aggregations
        distance_per_sport = (
            activities_week.groupby('sport_type')['distance'].sum() / 1000.0
        ).to_dict() if not activities_week.empty else {}
        
        activities_per_sport = (
            activities_week.groupby('sport_type').size()
        ).to_dict() if not activities_week.empty else {}
        
        time_per_sport = (
            activities_week.groupby('sport_type')['moving_time'].sum() / 3600.0
        ).to_dict() if not activities_week.empty else {}
        
        # Sports per day (list of sports for each weekday)
        sports_per_day = {}
        if not activities_week.empty:
            for day in range(7):
                day_activities = activities_week[activities_week['start_date_local'].dt.weekday == day]
                sports_per_day[day] = day_activities['sport_type'].tolist()
        else:
            sports_per_day = {day: [] for day in range(7)}
        
        # Time per sport per day (minutes) - for accumulated line plot
        time_per_sport_per_day_mins = {}
        activities_titles_per_day_per_sport = {}
        if not activities_week.empty:
            for sport in activities_week['sport_type'].unique():
                sport_activities = activities_week[activities_week['sport_type'] == sport]
                time_per_day = sport_activities.groupby(
                    sport_activities['start_date_local'].dt.weekday
                )['moving_time'].sum().reindex(range(7), fill_value=0) / 60.0  # Convert to minutes
                time_per_sport_per_day_mins[sport] = {int(k): float(round(v, 1)) for k, v in time_per_day.to_dict().items()}
                
                # Activity titles per day for this sport
                titles_per_day = {}
                for day in range(7):
                    day_activities = sport_activities[sport_activities['start_date_local'].dt.weekday == day]
                    titles_per_day[day] = day_activities['name'].tolist()
                activities_titles_per_day_per_sport[sport] = titles_per_day
        
        # HR Zone distribution (based on streams heart rate if available)
        # Default zones (% of max HR): Z1: 50-60%, Z2: 60-70%, Z3: 70-80%, Z4: 80-90%, Z5: 90-100%
        # Returns percentage of measurements in each zone
        hr_zone_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        total_hr_measurements = 0
        
        if not activities_week.empty:
            hr_max = self.get_max_heart_rate()
            
            for _, activity in activities_week.iterrows():
                # Try to use streams data if available
                if 'streams' in activity and activity['streams'] is not None:
                    try:
                        streams_data = json.loads(activity['streams']) if isinstance(activity['streams'], str) else activity['streams']
                        
                        # streams_data is a list of dicts with 'time', 'heartrate', etc.
                        if isinstance(streams_data, list) and len(streams_data) > 0:
                            for point in streams_data:
                                if 'heartrate' in point and point['heartrate'] is not None:
                                    hr = point['heartrate']
                                    hr_percent = (hr / hr_max) * 100
                                    total_hr_measurements += 1
                                    
                                    # Assign to zone
                                    if hr_percent < 60:
                                        hr_zone_counts[1] += 1
                                    elif hr_percent < 70:
                                        hr_zone_counts[2] += 1
                                    elif hr_percent < 80:
                                        hr_zone_counts[3] += 1
                                    elif hr_percent < 90:
                                        hr_zone_counts[4] += 1
                                    else:
                                        hr_zone_counts[5] += 1
                    except (json.JSONDecodeError, TypeError, KeyError):
                        # If streams parsing fails, skip this activity
                        pass
        
        # Calculate percentage for each zone
        hr_zone_distribution = {}
        if total_hr_measurements > 0:
            hr_zone_distribution = {
                zone: round((count / total_hr_measurements) * 100, 1) 
                for zone, count in hr_zone_counts.items()
            }
        else:
            hr_zone_distribution = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
        
        # Most active day
        if not activities_week.empty:
            activities_per_day_series = activities_week.groupby(
                activities_week['start_date_local'].dt.weekday
            ).size()
            most_active_day = int(activities_per_day_series.idxmax()) if not activities_per_day_series.empty else None
        else:
            most_active_day = None
        
        # Longest activity
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
            WeeklyReportFeatures.MOST_ACTIVE_DAY: most_active_day,
            WeeklyReportFeatures.LONGEST_ACTIVITY_KM: float(round(longest_activity_km, 2)),
            WeeklyReportFeatures.LONGEST_ACTIVITY_NAME: longest_activity_name,
        }


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
    HR_ZONE_DISTRIBUTION = "hr_zone_distribution"  # dict: zone (1-5) -> count of activities
    MOST_ACTIVE_DAY = "most_active_day"  # weekday (0-6)
    LONGEST_ACTIVITY_KM = "longest_activity_km"
    LONGEST_ACTIVITY_NAME = "longest_activity_name"