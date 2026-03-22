from enum import StrEnum
import json
import pandas as pd
import numpy as np
from strava.strava_activities_cache import StravaActivitiesCache
from strava.strava_user_cache import StravaUserCache
from strava.strava_utils import (
    vo2_max, get_sport_category, vdot_from_time_distance,
    predicted_time_from_vdot, riegel_predict, fit_riegel_exponent,
    compute_trimp_banister, compute_trimp_zone_weighted,
)


class StravaAnalytics:
    def __init__(self, strava_activities_cache: StravaActivitiesCache, strava_user_cache: StravaUserCache):
        self.strava_activities_cache = strava_activities_cache # inmutable data (historical activities)
        self.strava_user_cache = strava_user_cache # mutable data (user profile, stats, zones)
        self._prepared_activities = None
        self._prepared_activities_len = -1
        self._hr_zones_cache = None
        self._race_predictions_cache: dict = {}
        self._training_load_cache = None
        self._pmc_cache: dict = {}
        self._fitness_trend_cache: dict = {}

    def _get_prepared_activities(self) -> pd.DataFrame:
        """Return activities DF with parsed dates, cached to avoid repeated copy+parse.

        Reads directly from the cache's memory store to avoid the extra .copy()
        that load_activities() does on every call. We do a single copy here and
        cache it with parsed dates.
        """
        # Access the internal memory cache directly (triggers lazy load if needed)
        raw = self.strava_activities_cache._load_to_memory()
        current_len = len(raw)
        if self._prepared_activities is None or current_len != self._prepared_activities_len:
            df = raw.copy()
            df['start_date_local'] = pd.to_datetime(df['start_date_local'], utc=True)
            self._prepared_activities = df
            self._prepared_activities_len = current_len
        return self._prepared_activities

    def invalidate_caches(self):
        """Clear all analytics-level caches. Call after sync."""
        self._prepared_activities = None
        self._prepared_activities_len = -1
        self._hr_zones_cache = None
        self._race_predictions_cache = {}
        self._training_load_cache = None
        self._pmc_cache = {}
        self._fitness_trend_cache = {}

    def _get_hr_zones_cached(self):
        """Cache HR zones to avoid repeated user cache reads."""
        if self._hr_zones_cache is None:
            self._hr_zones_cache = self.get_hr_zones()
        return self._hr_zones_cache


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
        """Get the athlete's max heart rate. Prefers activity data to avoid API call."""
        hr_max = self._estimate_hr_max_from_activities()
        if hr_max and hr_max > 100:
            return hr_max
        zones = self.strava_user_cache.get_athlete_zones()
        return zones['heart_rate']['zones'][4]['min']
    
    def _estimate_hr_max_from_activities(self) -> int | None:
        """Estimate max HR from activity data using the 99th percentile.
        Uses percentile instead of absolute max to filter out sensor glitches."""
        df = self.strava_activities_cache._load_to_memory()
        if df.empty or 'max_heartrate' not in df.columns:
            return None
        hr_values = df['max_heartrate'].dropna()
        if hr_values.empty:
            return None
        # Use 99th percentile to ignore sensor spikes
        return int(np.percentile(hr_values, 99))

    def _build_default_zones(self, hr_max: int) -> list[dict]:
        """Build standard 5-zone HR zones from a max HR value."""
        boundaries = [0.60, 0.70, 0.80, 0.90]
        zones = []
        low = 0
        for pct in boundaries:
            high = int(hr_max * pct)
            zones.append({'min': low, 'max': high})
            low = high
        zones.append({'min': low, 'max': hr_max})
        return zones

    def get_hr_zones(self):
        """Get the athlete's heart rate zones.

        Uses Strava custom zones if available (requires API call).
        Otherwise, estimates from the highest max_heartrate in activity data (no API call).
        """
        # Try to get custom zones from Strava (only if already cached to avoid API call)
        if self.strava_user_cache._zones_cache is not None:
            zones = self.strava_user_cache._zones_cache
            if zones.get('heart_rate', {}).get('custom_zones'):
                return zones['heart_rate']['zones']

        # Fast path: estimate from activity data, no API call needed
        hr_max = self._estimate_hr_max_from_activities()
        if hr_max and hr_max > 100:
            return self._build_default_zones(hr_max)

        # Fallback: fetch from API (only if we have no activity data at all)
        zones = self.strava_user_cache.get_athlete_zones()
        if zones.get('heart_rate', {}).get('custom_zones'):
            return zones['heart_rate']['zones']
        hr_max = zones.get('heart_rate', {}).get('zones', [{}] * 5)[4].get('min', 190)
        return self._build_default_zones(hr_max)

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

    def get_year_in_sport(self, year: int, main_sport: str, cutoff_month_day: tuple[int, int] | None = None) -> dict:
        """Get year in sport for the specified year.

        Args:
            cutoff_month_day: Optional (month, day) tuple to filter activities up to that date.
                              Used for fair year-over-year comparison (e.g. only up to Feb 20).
        """

        activities = self._get_prepared_activities()

        # get activities for the specified year
        mask = (activities['start_date_local'].dt.year == year) & (activities['sport_type'] == main_sport)
        if cutoff_month_day:
            cutoff = pd.Timestamp(year, cutoff_month_day[0], cutoff_month_day[1], 23, 59, 59)
            # Match timezone if dates are tz-aware
            if activities['start_date_local'].dt.tz is not None:
                cutoff = cutoff.tz_localize(activities['start_date_local'].dt.tz)
            mask = mask & (activities['start_date_local'] <= cutoff)
        activities_year = activities[mask].copy()

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

        # activities per week (based on weeks elapsed in the year)
        if not activities_year.empty:
            from datetime import datetime, date
            year_start = datetime(year, 1, 1)
            if cutoff_month_day:
                year_end_or_today = datetime(year, cutoff_month_day[0], cutoff_month_day[1])
            else:
                year_end_or_today = min(datetime.now(), datetime(year, 12, 31))
            weeks_in_year = max(1, (year_end_or_today - year_start).days / 7)
            activities_per_week = total_activities / weeks_in_year
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


    def get_all_year_in_sport(self, year: int, cutoff_month_day: tuple[int, int] | None = None) -> dict:
        """Get overall year in sport stats across all sports for the specified year.

        Args:
            cutoff_month_day: Optional (month, day) tuple to filter activities up to that date.
        """

        activities = self._get_prepared_activities()

        # get activities for the specified year (all sports)
        mask = activities['start_date_local'].dt.year == year
        if cutoff_month_day:
            cutoff = pd.Timestamp(year, cutoff_month_day[0], cutoff_month_day[1], 23, 59, 59)
            if activities['start_date_local'].dt.tz is not None:
                cutoff = cutoff.tz_localize(activities['start_date_local'].dt.tz)
            mask = mask & (activities['start_date_local'] <= cutoff)
        activities_year = activities[mask].copy()

        # total activities and distance
        total_activities = len(activities_year)
        total_distance_km = activities_year['distance'].sum() / 1000.0
        total_time_hours = activities_year['moving_time'].sum() / 3600.0  # Convert seconds to hours
        active_days = activities_year['start_date_local'].dt.date.nunique()

        # activities per week (based on weeks elapsed in the year)
        if not activities_year.empty:
            from datetime import datetime
            year_start = datetime(year, 1, 1)
            if cutoff_month_day:
                year_end_or_today = datetime(year, cutoff_month_day[0], cutoff_month_day[1])
            else:
                year_end_or_today = min(datetime.now(), datetime(year, 12, 31))
            weeks_in_year = max(1, (year_end_or_today - year_start).days / 7)
            activities_per_week = total_activities / weeks_in_year
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


    def get_weekly_report(self, week_start_date: str | None = None, cutoff_date: str | None = None) -> dict:
        """
        Get weekly report for a given week.

        Args:
            week_start_date: Start of the week in format 'YYYY-MM-DD'. If None, uses the last completed week.
                             The date will be adjusted to the Monday of that week.
            cutoff_date: Optional 'YYYY-MM-DD' to truncate the week (e.g. only count Mon-Thu).
                         Used for fair comparison with an incomplete current week.

        Returns:
            Dictionary with weekly statistics.
        """
        from datetime import datetime, timedelta, timezone

        activities = self._get_prepared_activities()

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

        if cutoff_date:
            cutoff = pd.to_datetime(cutoff_date, utc=True).replace(hour=23, minute=59, second=59)
            week_end = cutoff
        else:
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
        
        # HR Zone distribution (vectorized with numpy for speed)
        hr_athlete_zones = self._get_hr_zones_cached()
        hr_zone_distribution = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}

        if not activities_week.empty and hr_athlete_zones and 'streams' in activities_week.columns:
            # Collect all HR values from streams into a single numpy array
            all_hr = []
            for streams_raw in activities_week['streams'].dropna():
                try:
                    streams_data = json.loads(streams_raw) if isinstance(streams_raw, str) else streams_raw
                    if isinstance(streams_data, list):
                        all_hr.extend(
                            p['heartrate'] for p in streams_data
                            if p.get('heartrate') is not None
                        )
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass

            if all_hr:
                hr_arr = np.array(all_hr, dtype=np.float64)
                total = len(hr_arr)
                # Build zone boundaries: [z1_min, z1_max, z2_max, z3_max, z4_max]
                boundaries = [z['max'] for z in hr_athlete_zones[:4]]
                # np.digitize bins: < z1_max → 0, < z2_max → 1, etc.
                bins = np.digitize(hr_arr, boundaries, right=False)
                for zone_idx in range(5):
                    count = int(np.sum(bins == zone_idx))
                    hr_zone_distribution[zone_idx + 1] = round((count / total) * 100, 1)
        
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
            WeeklyReportFeatures.HR_ZONE_RANGES: {
                i: (zone['min'], zone['max']) for i, zone in enumerate(hr_athlete_zones, start=1)
            } if hr_athlete_zones else {}
        }

    # ── Personal Records ──────────────────────────────────────────────

    # Standard distances per sport category (meters)
    RUNNING_DISTANCES = [
        (400, "400m"),
        (1000, "1K"),
        (5000, "5K"),
        (10000, "10K"),
        (15000, "15K"),
        (20000, "20K"),
        (21097, "Half Marathon"),
        (42195, "Marathon"),
    ]
    CYCLING_DISTANCES = [
        (10000, "10K"),
        (20000, "20K"),
        (40000, "40K"),
        (100000, "100K"),
        (160000, "100 mi"),
    ]
    SWIMMING_DISTANCES = [
        (100, "100m"),
        (200, "200m"),
        (400, "400m"),
        (800, "800m"),
        (1500, "1500m"),
    ]

    # Maximum plausible speed per sport (m/s) — used to filter GPS drift / bad data
    # Running: 2:20/km = ~7.14 m/s (world record ~800m pace)
    # Cycling: 75 km/h = 20.8 m/s (pro sprint)
    # Swimming: 0:50/100m = 2.0 m/s (world record 100m freestyle)
    MAX_SPEED_MS = {
        "running": 7.2,
        "cycling": 21.0,
        "swimming": 2.0,
    }

    def get_personal_records(self) -> dict:
        """Compute best efforts at standard distances for running, cycling, and swimming.

        Uses a sliding window over each activity's distance/time streams to find
        the fastest elapsed time for each standard distance.
        """
        from strava.strava_utils import get_sport_category

        activities = self._get_prepared_activities()

        sport_configs = {
            "running": self.RUNNING_DISTANCES,
            "cycling": self.CYCLING_DISTANCES,
            "swimming": self.SWIMMING_DISTANCES,
        }

        # best[category][distance_m] = {time_s, activity_id, activity_name, date}
        best: dict[str, dict[int, dict]] = {cat: {} for cat in sport_configs}

        for _, row in activities.iterrows():
            sport_type = row.get("sport_type", "")
            category = get_sport_category(sport_type)
            if category not in sport_configs:
                continue

            streams = row.get("streams")
            if streams is None:
                continue
            if isinstance(streams, str):
                try:
                    streams = json.loads(streams)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(streams, list) or len(streams) < 2:
                continue

            # Extract distance and time arrays
            distances = []
            times = []
            for pt in streams:
                d = pt.get("distance")
                t = pt.get("time")
                if d is not None and t is not None:
                    distances.append(float(d))
                    times.append(float(t))

            if len(distances) < 2:
                continue

            activity_id = row.get("id")
            activity_name = row.get("name", "")
            activity_date = str(row.get("start_date_local", ""))
            total_distance = distances[-1]
            max_speed = self.MAX_SPEED_MS[category]

            target_distances = sport_configs[category]

            for target_m, _ in target_distances:
                if total_distance < target_m:
                    continue

                # Sliding window: find min time to cover target_m meters
                left = 0
                best_time = None
                for right in range(len(distances)):
                    while distances[right] - distances[left] >= target_m:
                        elapsed = times[right] - times[left]
                        if elapsed > 0:
                            avg_speed = target_m / elapsed
                            # Reject physically impossible speeds (GPS drift)
                            if avg_speed <= max_speed:
                                if best_time is None or elapsed < best_time:
                                    best_time = elapsed
                        left += 1

                if best_time is not None and best_time > 0:
                    current_best = best[category].get(target_m)
                    if current_best is None or best_time < current_best["time_s"]:
                        best[category][target_m] = {
                            "time_s": best_time,
                            "activity_id": activity_id,
                            "activity_name": activity_name,
                            "date": activity_date,
                        }

        # Format results
        result = {}
        for category, target_distances in sport_configs.items():
            records = []
            for target_m, label in target_distances:
                record = best[category].get(target_m)
                if record:
                    records.append({
                        "distance_m": target_m,
                        "label": label,
                        "time_s": record["time_s"],
                        "activity_id": record["activity_id"],
                        "activity_name": record["activity_name"],
                        "date": record["date"],
                    })
            if records:
                result[category] = records

        return result

    # ── Race Predictions ──────────────────────────────────────────────

    @staticmethod
    def _pr_recency_weight(date_str: str, half_life_days: float = 180.0) -> float:
        """Exponential decay weight based on PR age. Half-life = 6 months by default.

        A PR from today gets weight ~1.0, from 6 months ago ~0.5, from 1 year ~0.25,
        from 2 years ago ~0.06 — practically irrelevant.
        """
        from datetime import datetime, timezone
        try:
            pr_date = pd.to_datetime(date_str, utc=True)
            now = pd.Timestamp(datetime.now(timezone.utc))
            age_days = max(0, (now - pr_date).days)
        except Exception:
            return 0.1  # unknown date — low weight
        import math
        return math.exp(-0.693 * age_days / half_life_days)  # ln(2) ≈ 0.693

    def get_race_predictions(self, sport_category: str = "running") -> dict:
        """Generate race predictions using VDOT and Riegel models from personal records.

        PRs are weighted by recency — old PRs (>1 year) have minimal influence.
        """
        if sport_category in self._race_predictions_cache:
            return self._race_predictions_cache[sport_category]

        prs_all = self.get_personal_records()
        prs = prs_all.get(sport_category, [])

        sport_configs = {
            "running": self.RUNNING_DISTANCES,
            "cycling": self.CYCLING_DISTANCES,
            "swimming": self.SWIMMING_DISTANCES,
        }
        target_distances = sport_configs.get(sport_category, [])

        # Compute recency weight for each PR
        for pr in prs:
            pr["_weight"] = self._pr_recency_weight(pr.get("date", ""))

        # Fit personalized Riegel exponent (only from recent-enough PRs)
        recent_prs = [pr for pr in prs if pr["_weight"] >= 0.15]  # ~11 months cutoff
        fitted_exp = fit_riegel_exponent(recent_prs) if len(recent_prs) >= 3 else None
        use_exp = fitted_exp if fitted_exp is not None else 1.06

        # Compute recency-weighted VDOT (running only)
        athlete_vdot = None
        if sport_category == "running":
            vdots_w = []
            for pr in prs:
                v = vdot_from_time_distance(pr["time_s"], pr["distance_m"])
                if v is not None:
                    vdots_w.append((v, pr["_weight"]))
            if vdots_w:
                total_w = sum(w for _, w in vdots_w)
                athlete_vdot = round(sum(v * w for v, w in vdots_w) / total_w, 2)

        # Build predictions for each standard distance
        pr_map = {pr["distance_m"]: pr for pr in prs}
        predictions = []

        for dist_m, label in target_distances:
            entry: dict = {
                "distance_m": dist_m,
                "label": label,
                "pr_time_s": None,
                "pr_date": None,
                "source": "predicted",
                "predicted_time_s": None,
                "models": {},
            }

            existing = pr_map.get(dist_m)
            if existing:
                entry["pr_time_s"] = existing["time_s"]
                entry["pr_date"] = existing.get("date")
                entry["source"] = "personal_record"

            # Riegel predictions — weighted median from PRs
            riegel_pairs = []      # (predicted_time, weight)
            personalized_pairs = []
            for pr in prs:
                if pr["distance_m"] == dist_m:
                    continue
                w = pr["_weight"]
                riegel_pairs.append((riegel_predict(pr["time_s"], pr["distance_m"], dist_m, 1.06), w))
                personalized_pairs.append((riegel_predict(pr["time_s"], pr["distance_m"], dist_m, use_exp), w))

            def _weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
                if not pairs:
                    return None
                total_w = sum(w for _, w in pairs)
                if total_w <= 0:
                    return None
                return sum(v * w for v, w in pairs) / total_w

            r_avg = _weighted_avg(riegel_pairs)
            if r_avg is not None:
                entry["models"]["riegel"] = round(r_avg, 1)
            if fitted_exp is not None:
                p_avg = _weighted_avg(personalized_pairs)
                if p_avg is not None:
                    entry["models"]["personalized_riegel"] = round(p_avg, 1)

            # VDOT prediction (running only)
            if athlete_vdot and sport_category == "running":
                vdot_pred = predicted_time_from_vdot(athlete_vdot, dist_m)
                if vdot_pred is not None:
                    entry["models"]["vdot"] = vdot_pred

            # Average available model predictions
            model_vals = list(entry["models"].values())
            if model_vals:
                entry["predicted_time_s"] = round(float(np.mean(model_vals)), 1)

            predictions.append(entry)

        # Confidence: based on recent PR count
        n_recent = len(recent_prs)
        n_total = len(prs)
        confidence = "high" if n_recent >= 5 else "medium" if n_recent >= 3 else "low"

        # Data quality info
        activities = self._get_prepared_activities()
        cat_activities = activities[activities['sport_type'].apply(
            lambda st: get_sport_category(st) == sport_category
        )]

        warnings = []
        if n_total > 0 and n_recent < n_total:
            stale = n_total - n_recent
            warnings.append(f"{stale} of {n_total} PRs are older than ~11 months and have low weight in predictions")
        if n_recent < 3:
            warnings.append(f"Only {n_recent} recent PR(s) — predictions less reliable for extrapolated distances")

        result = {
            "predictions": predictions,
            "athlete_vdot": athlete_vdot,
            "fitted_exponent": fitted_exp,
            "confidence": confidence,
            "sport_category": sport_category,
            "data_quality": {
                "total_activities": int(len(cat_activities)),
                "prs_available": n_total,
                "recent_prs": n_recent,
                "sufficient": n_recent >= 2,
                "warnings": warnings,
            },
        }

        # Clean up temp keys
        for pr in prs:
            pr.pop("_weight", None)

        self._race_predictions_cache[sport_category] = result
        return result

    # ── Training Load & PMC ───────────────────────────────────────────

    def get_daily_training_load(self) -> list[dict]:
        """Compute daily TRIMP values from all activities."""
        if self._training_load_cache is not None:
            return self._training_load_cache

        hr_max = self.get_max_heart_rate()
        hr_rest = self.get_rest_heart_rate()
        hr_zones = self._get_hr_zones_cached()

        activities = self._get_prepared_activities()
        daily: dict[str, dict] = {}

        for _, row in activities.iterrows():
            avg_hr = row.get("average_heartrate")
            moving_time = row.get("moving_time", 0)
            if pd.isna(avg_hr) or not avg_hr or moving_time <= 0:
                continue

            duration_min = moving_time / 60.0
            trimp = 0.0
            trimp_method = "banister"

            # Try zone-weighted TRIMP from streams
            streams = row.get("streams")
            if streams is not None and hr_zones:
                if isinstance(streams, str):
                    try:
                        streams = json.loads(streams)
                    except (json.JSONDecodeError, TypeError):
                        streams = None
                if isinstance(streams, list) and len(streams) >= 2:
                    hr_vals = [p.get('heartrate') for p in streams if p.get('heartrate') is not None]
                    if len(hr_vals) > 10:
                        hr_arr = np.array(hr_vals, dtype=np.float64)
                        boundaries = [z['max'] for z in hr_zones[:4]]
                        bins = np.digitize(hr_arr, boundaries, right=False)
                        # Estimate time per data point (assume uniform sampling)
                        time_per_pt = duration_min / len(hr_arr)
                        time_in_zones = [float(np.sum(bins == i)) * time_per_pt for i in range(5)]
                        trimp = compute_trimp_zone_weighted(time_in_zones)
                        trimp_method = "zone_weighted"

            # Fallback to Banister
            if trimp == 0.0:
                trimp = compute_trimp_banister(duration_min, float(avg_hr), hr_rest, hr_max)
                trimp_method = "banister"

            date_str = row['start_date_local'].strftime('%Y-%m-%d')
            if date_str not in daily:
                daily[date_str] = {"date": date_str, "trimp": 0.0, "activities": [], "trimp_method": trimp_method}
            daily[date_str]["trimp"] += round(trimp, 1)
            daily[date_str]["activities"].append({
                "name": row.get("name", ""),
                "sport_type": row.get("sport_type", ""),
                "trimp": round(trimp, 1),
                "trimp_method": trimp_method,
            })

        result = sorted(daily.values(), key=lambda d: d["date"])
        self._training_load_cache = result
        return result

    def get_pmc_chart(self, start_date: str | None = None, end_date: str | None = None) -> dict:
        """Compute Performance Management Chart (CTL/ATL/TSB) from daily TRIMP."""
        cache_key = f"{start_date}|{end_date}"
        if cache_key in self._pmc_cache:
            return self._pmc_cache[cache_key]

        from datetime import datetime, timedelta

        daily_load = self.get_daily_training_load()
        if not daily_load:
            empty = {"data": [], "current": {"ctl": 0, "atl": 0, "tsb": 0}, "peak_fitness": {"ctl": 0, "date": None}}
            self._pmc_cache[cache_key] = empty
            return empty

        # Build date-indexed series from first activity to today
        first_date = pd.to_datetime(daily_load[0]["date"])
        today = pd.Timestamp(datetime.now().strftime('%Y-%m-%d'))
        date_range = pd.date_range(first_date, today, freq='D')

        trimp_map = {d["date"]: d["trimp"] for d in daily_load}
        trimp_series = pd.Series(
            [trimp_map.get(d.strftime('%Y-%m-%d'), 0.0) for d in date_range],
            index=date_range,
        )

        ctl = trimp_series.ewm(span=42, adjust=False).mean()
        atl = trimp_series.ewm(span=7, adjust=False).mean()
        tsb = ctl - atl

        # Filter to requested range for output
        mask = pd.Series(True, index=date_range)
        if start_date:
            mask = mask & (date_range >= pd.to_datetime(start_date))
        if end_date:
            mask = mask & (date_range <= pd.to_datetime(end_date))

        data = []
        for d in date_range[mask]:
            ds = d.strftime('%Y-%m-%d')
            data.append({
                "date": ds,
                "trimp": round(float(trimp_series[d]), 1),
                "ctl": round(float(ctl[d]), 1),
                "atl": round(float(atl[d]), 1),
                "tsb": round(float(tsb[d]), 1),
            })

        # Peak fitness
        peak_idx = ctl.idxmax()
        peak_ctl = round(float(ctl[peak_idx]), 1)

        # HR data quality
        activities = self._get_prepared_activities()
        total = len(activities)
        with_hr = int(activities['average_heartrate'].dropna().count()) if 'average_heartrate' in activities.columns else 0
        with_streams = int(activities['streams'].dropna().count()) if 'streams' in activities.columns else 0

        result = {
            "data": data,
            "current": {
                "ctl": round(float(ctl.iloc[-1]), 1) if len(ctl) else 0,
                "atl": round(float(atl.iloc[-1]), 1) if len(atl) else 0,
                "tsb": round(float(tsb.iloc[-1]), 1) if len(tsb) else 0,
            },
            "peak_fitness": {
                "ctl": peak_ctl,
                "date": peak_idx.strftime('%Y-%m-%d'),
            },
            "data_quality": {
                "total_activities": total,
                "activities_with_hr": with_hr,
                "activities_with_streams": with_streams,
                "sufficient": with_hr >= 1,
                "warnings": (
                    ["No activities with heart rate data found"]
                    if with_hr == 0 else []
                ),
            },
        }
        self._pmc_cache[cache_key] = result
        return result

    # ── Fitness Trend (VDOT over time) ────────────────────────────────

    def get_fitness_trend(self, sport_type: str = "Run", start_date: str | None = None, end_date: str | None = None) -> dict:
        """Compute per-activity VDOT and rolling average trend for running."""
        cache_key = f"{sport_type}|{start_date}|{end_date}"
        if cache_key in self._fitness_trend_cache:
            return self._fitness_trend_cache[cache_key]

        activities = self._get_prepared_activities()
        filtered = activities[
            (activities['sport_type'] == sport_type) &
            (activities['moving_time'] >= 180) &
            (activities['distance'] > 0)
        ].sort_values('start_date_local').copy()

        if start_date:
            filtered = filtered[filtered['start_date_local'] >= pd.to_datetime(start_date, utc=True)]
        if end_date:
            filtered = filtered[filtered['start_date_local'] <= pd.to_datetime(end_date, utc=True)]

        points = []
        for _, row in filtered.iterrows():
            v = vdot_from_time_distance(float(row['moving_time']), float(row['distance']))
            if v is not None and 15 < v < 85:  # reasonable VDOT range
                points.append({
                    "date": row['start_date_local'].strftime('%Y-%m-%d'),
                    "vdot": v,
                    "activity_name": row.get('name', ''),
                    "distance_km": round(float(row['distance']) / 1000, 2),
                })

        # Rolling average
        rolling_avg = []
        if len(points) >= 3:
            vdot_series = pd.Series(
                [p["vdot"] for p in points],
                index=pd.to_datetime([p["date"] for p in points]),
            )
            rolled = vdot_series.rolling(window='28D', min_periods=1).mean()
            for d, v in rolled.items():
                rolling_avg.append({"date": d.strftime('%Y-%m-%d'), "vdot": round(float(v), 2)})

        # Current and peak
        current_vdot = rolling_avg[-1]["vdot"] if rolling_avg else (points[-1]["vdot"] if points else None)
        peak_entry = max(rolling_avg, key=lambda x: x["vdot"]) if rolling_avg else None

        # Trend: compare current 28-day avg vs 8 weeks ago
        trend = "stable"
        if len(rolling_avg) >= 2:
            recent = rolling_avg[-1]["vdot"]
            # Find entry ~56 days ago
            target_date = pd.to_datetime(rolling_avg[-1]["date"]) - pd.Timedelta(days=56)
            older = [r for r in rolling_avg if pd.to_datetime(r["date"]) <= target_date]
            if older:
                diff = recent - older[-1]["vdot"]
                if diff > 0.5:
                    trend = "improving"
                elif diff < -0.5:
                    trend = "declining"

        result = {
            "activities": points,
            "rolling_avg": rolling_avg,
            "current_vdot": current_vdot,
            "peak_vdot": {"vdot": peak_entry["vdot"], "date": peak_entry["date"]} if peak_entry else None,
            "trend": trend,
            "sport_type": sport_type,
            "data_quality": {
                "total_activities": len(filtered),
                "activities_with_vdot": len(points),
                "sufficient": len(points) >= 5,
                "warnings": (
                    ["Only {} activities with valid VDOT — need at least 5 for reliable trend".format(len(points))]
                    if len(points) < 5 else []
                ),
            },
        }
        self._fitness_trend_cache[cache_key] = result
        return result


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
    HR_ZONE_RANGES = "hr_zone_ranges"  # dict: zone (1-5) -> (min_hr, max_hr)