from enum import StrEnum
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