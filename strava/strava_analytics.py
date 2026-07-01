from datetime import datetime, timedelta, timezone
from enum import StrEnum
import json
import logging
import math
import pandas as pd
import numpy as np
from strava.strava_activities_cache import StravaActivitiesCache
from strava.strava_user_cache import StravaUserCache
from strava.strava_utils import (
    vo2_max, get_sport_category, vdot_from_time_distance,
    predicted_time_from_vdot, riegel_predict, fit_riegel_exponent,
    compute_trimp_banister, compute_trimp_zone_weighted,
)

logger = logging.getLogger(__name__)


def _utc_now_naive() -> datetime:
    """UTC wallclock as a naive datetime. Matches the codebase's UTC-as-base
    convention while staying comparable with other naive datetimes used for
    year-boundary math."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _weighted_quantile(values: list[float], weights: list[float], q: float) -> float:
    """Linear-interpolated weighted quantile. Equivalent to numpy.percentile
    when weights are uniform. Used by the race-prediction band so the IQR
    respects the same closer-anchor weighting as the central estimate.
    """
    if not values:
        return 0.0
    pairs = sorted(zip(values, weights), key=lambda p: p[0])
    vals = np.array([v for v, _ in pairs], dtype=np.float64)
    wts = np.array([w for _, w in pairs], dtype=np.float64)
    total = wts.sum()
    if total <= 0:
        return float(np.percentile(vals, q * 100))
    # Centered staircase: each sample contributes weight at the midpoint of
    # its cumulative weight interval.
    cum = (np.cumsum(wts) - 0.5 * wts) / total
    return float(np.interp(q, cum, vals))


class StravaAnalytics:
    def __init__(self, strava_activities_cache: StravaActivitiesCache, strava_user_cache: StravaUserCache,
                 garmin_cache=None):
        self.strava_activities_cache = strava_activities_cache # inmutable data (historical activities)
        self.strava_user_cache = strava_user_cache # mutable data (user profile, stats, zones)
        self.garmin_cache = garmin_cache # optional GarminDailyStatsCache for measured RHR/VO2max
        self._prepared_activities = None
        self._prepared_activities_version = -1
        self._hr_zones_cache = None
        self._race_predictions_cache: dict = {}
        self._race_residuals_cache: dict[str, list] = {}
        self._training_load_cache: dict = {}
        self._pmc_cache: dict = {}
        self._fitness_trend_cache: dict = {}
        # Per-activity best efforts table per sport category — computed once
        # from the sliding-window scan, reused across windowed queries to
        # avoid re-scanning streams on every history step.
        self._per_activity_bests_cache: dict[str, pd.DataFrame] = {}

    def _get_prepared_activities(self) -> pd.DataFrame:
        """Return activities DF with parsed dates and parsed map JSON, cached
        to avoid repeated copy+parse.

        Streams are NOT attached to this DataFrame — they live in the cache's
        StreamsStore. Call `strava_activities_cache.get_streams(activity_id)`
        when stream data is needed.
        """
        raw = self.strava_activities_cache._load_to_memory()
        current_version = self.strava_activities_cache.cache_version
        if self._prepared_activities is None or current_version != self._prepared_activities_version:
            df = raw.copy()
            df['start_date_local'] = pd.to_datetime(df['start_date_local'], utc=True)
            if 'map' in df.columns:
                df['map'] = df['map'].apply(self._parse_json_cell)
            self._prepared_activities = df
            self._prepared_activities_version = current_version
        return self._prepared_activities

    @staticmethod
    def _parse_json_cell(val):
        """Parse a JSON cell from string to Python object, once."""
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return None
        return val

    def invalidate_caches(self):
        """Clear all analytics-level caches. Call after sync."""
        self._prepared_activities = None
        self._prepared_activities_version = -1
        self._hr_zones_cache = None
        self._race_predictions_cache = {}
        self._race_residuals_cache = {}
        self._training_load_cache = {}
        self._pmc_cache = {}
        self._fitness_trend_cache = {}
        self._per_activity_bests_cache = {}

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
        """Get the athlete's resting heart rate.

        Prefers the measured Garmin value (7-day average when present, else the
        latest nightly reading). Falls back to the Z2_min / 2 proxy from Strava
        zones when no Garmin data is cached.
        """
        garmin_rhr = self._garmin_resting_hr()
        if garmin_rhr is not None:
            return garmin_rhr

        zones = self.strava_user_cache.get_athlete_zones()
        hr_rest = zones['heart_rate']['zones'][1]['min'] / 2

        if hr_rest == 0:
            hr_rest = 60  # Default fallback value

        return hr_rest

    def _garmin_resting_hr(self) -> float | None:
        """Most recent Garmin resting HR, or None when unavailable.

        Reads the latest cached `heart_rates` daily payload — no network. The
        7-day average is preferred over the single-night value to smooth
        one-off bad nights. Values outside a physiologically plausible range
        are treated as missing.
        """
        if self.garmin_cache is None:
            return None
        try:
            latest = self.garmin_cache.get_latest("heart_rates")
        except Exception:
            logger.warning("Garmin resting HR lookup failed", exc_info=True)
            return None
        if not latest:
            return None
        payload = latest.get("payload") or {}
        rhr = payload.get("lastSevenDaysAvgRestingHeartRate") or payload.get("restingHeartRate")
        if rhr is None or not (25 <= rhr <= 100):
            return None
        return float(rhr)
    
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
        """Get the athlete's VO2 Max.

        Prefers Garmin's measured value (from the cached `training_status`
        daily payload). Falls back to the Uth-Sørensen-Overgaard-Pedersen
        estimation:
            VO2 Max = 15.3 x (HR_max / HR_rest)
        """
        garmin_vo2 = self._garmin_vo2max()
        if garmin_vo2 is not None:
            return round(garmin_vo2, 2)

        hr_max = self.get_max_heart_rate()
        hr_rest = self.get_rest_heart_rate()

        vo2_max_value = vo2_max(hr_max, hr_rest)
        return round(vo2_max_value, 2)

    def _garmin_vo2max(self) -> float | None:
        """Most recent Garmin-measured VO2max, or None when unavailable."""
        if self.garmin_cache is None:
            return None
        try:
            latest = self.garmin_cache.get_latest("training_status")
        except Exception:
            logger.warning("Garmin VO2max lookup failed", exc_info=True)
            return None
        if not latest:
            return None
        vo2 = ((latest.get("payload") or {}).get("mostRecentVO2Max") or {}).get("generic") or {}
        value = vo2.get("vo2MaxPreciseValue") or vo2.get("vo2MaxValue")
        if value is None or not (20 <= value <= 90):
            return None
        return float(value)

    def _garmin_race_predictions(self) -> dict | None:
        """Latest cached Garmin race-predictor times (running only), or None.

        Returns {date, time5K, time10K, timeHalfMarathon, timeMarathon} with
        times in seconds, straight from the cached `race_predictions` daily
        payload — no network.
        """
        if self.garmin_cache is None:
            return None
        try:
            latest = self.garmin_cache.get_latest("race_predictions")
        except Exception:
            logger.warning("Garmin race predictions lookup failed", exc_info=True)
            return None
        if not latest:
            return None
        payload = latest.get("payload") or {}
        out = {"date": latest.get("date")}
        for key in ("time5K", "time10K", "timeHalfMarathon", "timeMarathon"):
            out[key] = payload.get(key)
        return out if any(out[k] for k in out if k != "date") else None
    

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
            year_start = datetime(year, 1, 1)
            if cutoff_month_day:
                year_end_or_today = datetime(year, cutoff_month_day[0], cutoff_month_day[1])
            else:
                year_end_or_today = min(_utc_now_naive(), datetime(year, 12, 31))
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
            year_start = datetime(year, 1, 1)
            if cutoff_month_day:
                year_end_or_today = datetime(year, cutoff_month_day[0], cutoff_month_day[1])
            else:
                year_end_or_today = min(_utc_now_naive(), datetime(year, 12, 31))
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


    def get_weekly_report(self, week_start_date: str | None = None, cutoff_date: str | None = None, hr_zones: list | None = None) -> dict:
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
        hr_athlete_zones = hr_zones if hr_zones is not None else self._get_hr_zones_cached()
        hr_zone_distribution = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
        hr_histogram: dict | None = None

        if not activities_week.empty and hr_athlete_zones:
            # Collect all HR values from streams into a single numpy array.
            # Streams are lazy-loaded per-id from the StreamsStore.
            ids_in_week = activities_week['id'].astype('int64').tolist()
            streams_map = self.strava_activities_cache.get_streams_bulk(ids_in_week)
            all_hr: list = []
            for streams in streams_map.values():
                hr_arr_col = streams.get('heartrate') if isinstance(streams, dict) else None
                if not hr_arr_col:
                    continue
                all_hr.extend(v for v in hr_arr_col if v is not None)

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

                # 1 bpm-resolution histogram for the multi-zone density chart.
                # Snap range to a small margin around min/max so the curve doesn't
                # get clipped at the edges by the renderer.
                lo = int(np.floor(hr_arr.min())) - 2
                hi = int(np.ceil(hr_arr.max())) + 2
                if hi > lo:
                    counts, _ = np.histogram(hr_arr, bins=np.arange(lo, hi + 1))
                    hr_histogram = {"min_bpm": int(lo), "counts": counts.astype(int).tolist()}
        
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
            WeeklyReportFeatures.HR_HISTOGRAM: hr_histogram,
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
        (1900, "1900m"),   # Half Ironman swim leg
        (3000, "3000m"),
        (3800, "3800m"),   # Ironman swim leg
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

    @staticmethod
    def _best_effort_times(
        dist_col: list,
        time_col: list,
        moving_col: list | None,
        targets: list[int],
        max_speed: float,
    ) -> dict[int, float]:
        """Sliding-window best effort per target distance for one activity's
        streams. Returns {target_m: best_time_s}. Shared kernel for
        get_personal_records / _scan_best_efforts_in / _get_per_activity_bests_df.

        Two accuracy details over a naive searchsorted scan:
        - Stopped time is excluded: when a `moving` stream is present, a
          sample's time gap only counts while the athlete was moving (same
          semantics as Strava's moving_time). A traffic-light stop inside the
          fastest window no longer slows the effort.
        - The window end is linearly interpolated between the two samples
          bracketing the exact target distance, instead of charging the full
          gap to the effort — GPS samples can be many metres apart, which
          systematically overestimated best times.
        """
        distances = np.asarray(dist_col, dtype=np.float64)
        times = np.asarray(time_col, dtype=np.float64)
        n = len(distances)
        if n < 2:
            return {}

        # Effective elapsed time: collapse non-moving gaps when usable.
        if moving_col is not None and len(moving_col) == n:
            moving = np.asarray([bool(m) for m in moving_col])
            gaps = np.diff(times)
            eff_times = np.concatenate(([0.0], np.cumsum(np.where(moving[1:], gaps, 0.0))))
        else:
            eff_times = times

        out: dict[int, float] = {}
        total_d = distances[-1]
        for target_m in targets:
            if total_d < target_m:
                continue
            thresholds = distances + target_m
            right = np.searchsorted(distances, thresholds, side="left")
            valid = right < n
            left_idx = np.nonzero(valid)[0]
            if len(left_idx) == 0:
                continue
            right_idx = right[valid]
            # searchsorted(side="left") guarantees right > left and
            # distances[right-1] < threshold <= distances[right]: interpolate
            # the crossing time inside that bracket.
            prev_idx = right_idx - 1
            seg = distances[right_idx] - distances[prev_idx]
            seg_safe = np.where(seg > 0, seg, 1.0)
            frac = np.where(seg > 0, (thresholds[left_idx] - distances[prev_idx]) / seg_safe, 1.0)
            frac = np.clip(frac, 0.0, 1.0)
            cross_t = eff_times[prev_idx] + frac * (eff_times[right_idx] - eff_times[prev_idx])
            elapsed = cross_t - eff_times[left_idx]
            speeds = target_m / np.maximum(elapsed, 1e-9)
            ok = (elapsed > 0) & (speeds <= max_speed)
            if not np.any(ok):
                continue
            out[int(target_m)] = float(elapsed[ok].min())
        return out

    def get_personal_records(self) -> dict:
        """Compute best efforts at standard distances for running, cycling, and swimming.

        Uses a sliding window over each activity's distance/time streams to find
        the fastest elapsed time for each standard distance. Numpy searchsorted
        replaces the inner Python loop for speed.
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

        # Bulk-load streams for the relevant rows so we hit each year-pickle once.
        relevant_ids = activities['id'].astype('int64').tolist()
        streams_map = self.strava_activities_cache.get_streams_bulk(relevant_ids)

        for _, row in activities.iterrows():
            sport_type = row.get("sport_type", "")
            category = get_sport_category(sport_type)
            if category not in sport_configs:
                continue

            streams = streams_map.get(int(row.get("id"))) if row.get("id") is not None else None
            if not streams:
                continue

            dist_col = streams.get("distance")
            time_col = streams.get("time")
            if not dist_col or not time_col or len(dist_col) < 2:
                continue

            activity_id = row.get("id")
            activity_name = row.get("name", "")
            activity_date = str(row.get("start_date_local", ""))

            efforts = self._best_effort_times(
                dist_col, time_col, streams.get("moving"),
                [t for t, _ in sport_configs[category]],
                self.MAX_SPEED_MS[category],
            )
            for target_m, best_time in efforts.items():
                if best_time > 0:
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

    # ── Sliding-window best efforts (shared core) ─────────────────────

    def _scan_best_efforts_in(
        self,
        activities_df: pd.DataFrame,
        sport_category: str,
    ) -> dict[int, dict]:
        """Sliding-window scan over a pre-filtered activities DataFrame, returning
        best time per standard distance. Same numpy-backed logic as
        `get_personal_records`, but scoped to whatever subset the caller passes
        (e.g. a rolling window of recent activities).
        """
        sport_configs = {
            "running": self.RUNNING_DISTANCES,
            "cycling": self.CYCLING_DISTANCES,
            "swimming": self.SWIMMING_DISTANCES,
        }
        if sport_category not in sport_configs:
            return {}
        target_distances = sport_configs[sport_category]
        max_speed = self.MAX_SPEED_MS[sport_category]

        best: dict[int, dict] = {}
        relevant_ids = activities_df['id'].astype('int64').tolist() if 'id' in activities_df.columns else []
        streams_map = self.strava_activities_cache.get_streams_bulk(relevant_ids)
        for _, row in activities_df.iterrows():
            streams = streams_map.get(int(row.get("id"))) if row.get("id") is not None else None
            if not streams:
                continue
            dist_col = streams.get("distance")
            time_col = streams.get("time")
            if not dist_col or not time_col or len(dist_col) < 2:
                continue

            activity_id = row.get("id")
            activity_name = row.get("name", "")
            activity_date = str(row.get("start_date_local", ""))

            efforts = self._best_effort_times(
                dist_col, time_col, streams.get("moving"),
                [t for t, _ in target_distances], max_speed,
            )
            for target_m, best_time in efforts.items():
                cur = best.get(target_m)
                if cur is None or best_time < cur["time_s"]:
                    best[target_m] = {
                        "distance_m": target_m,
                        "time_s": best_time,
                        "activity_id": activity_id,
                        "activity_name": activity_name,
                        "date": activity_date,
                    }
        return best

    def _get_per_activity_bests_df(self, sport_category: str) -> pd.DataFrame:
        """Return a table of per-activity best efforts for the given sport:
            columns = activity_id, activity_name, date (pd.Timestamp UTC),
                      distance_m, time_s.
        Computed once from the full activity history and cached; windowed
        queries filter by date and take a groupby-min, avoiding repeat stream
        scans. Invalidated on sync via `invalidate_caches`.
        """
        cached = self._per_activity_bests_cache.get(sport_category)
        if cached is not None:
            return cached

        sport_configs = {
            "running": self.RUNNING_DISTANCES,
            "cycling": self.CYCLING_DISTANCES,
            "swimming": self.SWIMMING_DISTANCES,
        }
        bests_columns = ["activity_id", "activity_name", "date", "distance_m", "time_s",
                         "is_race", "avg_hr"]
        if sport_category not in sport_configs:
            empty = pd.DataFrame(columns=bests_columns)
            self._per_activity_bests_cache[sport_category] = empty
            return empty
        target_distances = sport_configs[sport_category]
        max_speed = self.MAX_SPEED_MS[sport_category]

        activities = self._get_prepared_activities()
        if activities.empty:
            empty = pd.DataFrame(columns=bests_columns)
            self._per_activity_bests_cache[sport_category] = empty
            return empty

        cat_mask = activities["sport_type"].apply(lambda st: get_sport_category(st) == sport_category)
        cat_acts = activities[cat_mask]

        # Bulk-load streams for this sport category, then iterate.
        cat_ids = cat_acts['id'].astype('int64').tolist() if 'id' in cat_acts.columns else []
        streams_map = self.strava_activities_cache.get_streams_bulk(cat_ids)

        rows: list[dict] = []
        for _, row in cat_acts.iterrows():
            streams = streams_map.get(int(row.get("id"))) if row.get("id") is not None else None
            if not streams:
                continue
            dist_col = streams.get("distance")
            time_col = streams.get("time")
            if not dist_col or not time_col or len(dist_col) < 2:
                continue

            activity_id = row.get("id")
            activity_name = row.get("name", "")
            act_date = row.get("start_date_local")
            # Strava workout_type: 1 = run race, 11 = ride race.
            wt = row.get("workout_type")
            is_race = (not pd.isna(wt)) and int(wt) in (1, 11)
            avg_hr = row.get("average_heartrate")
            avg_hr = float(avg_hr) if avg_hr is not None and not pd.isna(avg_hr) else None

            efforts = self._best_effort_times(
                dist_col, time_col, streams.get("moving"),
                [t for t, _ in target_distances], max_speed,
            )
            for target_m, best_time in efforts.items():
                rows.append({
                    "activity_id": activity_id,
                    "activity_name": activity_name,
                    "date": act_date,
                    "distance_m": target_m,
                    "time_s": best_time,
                    "is_race": is_race,
                    "avg_hr": avg_hr,
                })

        df = pd.DataFrame(rows, columns=bests_columns)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
        self._per_activity_bests_cache[sport_category] = df
        return df

    def _recent_best_efforts_list(
        self,
        sport_category: str,
        within_days: int = 365,
        end_date: datetime | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        """Top-K fastest efforts per standard distance within the window.

        Using multiple anchors per distance (rather than min-per-distance)
        prevents cliffs: when the single fastest effort ages past the
        boundary, only 1/K of the anchor weight changes instead of the whole
        distance's contribution flipping to the next-fastest effort.

        Easy-run "bests" don't pollute the set because they're ranked out by
        the top-K-fastest filter — fast training/race efforts win the top-K
        slots.

        Also marks `is_top1=True` on the per-distance fastest, so UI cards
        can surface it as the displayed PR.
        """
        df = self._get_per_activity_bests_df(sport_category)
        if df.empty:
            return []

        if end_date is None:
            end_ts = pd.Timestamp(datetime.now(timezone.utc))
        else:
            ts = pd.Timestamp(end_date)
            end_ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
        start_ts = end_ts - pd.Timedelta(days=within_days)

        in_window = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)]
        if in_window.empty:
            return []

        # Quality filter: within 120% of the per-distance top-1 time. Excludes
        # easy-run "bests" that happen to rank top-K but aren't race-quality
        # anchors. Keeps top-1 (trivially), plus any close-to-top-1 attempts.
        MAX_MULT = 1.20
        result: list[dict] = []
        for distance_m, group in in_window.groupby("distance_m"):
            top_sorted = group.nsmallest(top_k, "time_s")
            if top_sorted.empty:
                continue
            best_time = float(top_sorted["time_s"].iloc[0])
            rank = 0
            for _, r in top_sorted.iterrows():
                rank += 1
                if float(r["time_s"]) > best_time * MAX_MULT:
                    continue
                result.append({
                    "distance_m": int(distance_m),
                    "time_s": float(r["time_s"]),
                    "activity_id": r["activity_id"],
                    "activity_name": r["activity_name"],
                    "date": str(r["date"]),
                    "is_top1": rank == 1,
                    "is_race": bool(r.get("is_race", False)),
                    "avg_hr": float(r["avg_hr"]) if not pd.isna(r.get("avg_hr")) else None,
                })
        result.sort(key=lambda b: (b["distance_m"], b["time_s"]))
        return result

    # ── Race Predictions ──────────────────────────────────────────────

    # Recent-bests lookback for race predictions. The smooth recency decay
    # inside _compute_predictions does the real freshness weighting; this is
    # just the hard outer cutoff.
    PREDICTIONS_WINDOW_DAYS = 365

    # ── Race-prediction tuning knobs ──────────────────────────────────
    # Backtested against race-flagged activities (predict as-of the day
    # before each race, compare to the actual result) via
    # scripts/backtest_race_predictions.py — 18 races, 5K–HM. Defaults are
    # the *moderate* values supported by the grid marginals (the single best
    # combo sat at grid extremes — not trusted with n=18):
    #   half-life 180→90 and decay 1.5→1.0 each shaved ~0.1–0.2pp of MAE;
    #   VDOT weight was the strongest lever (0.5→3.96%, 0.7→3.70% MAE),
    #   capped at 0.7 so the Riegel family still anchors the band and the
    #   (backtest-untested) marathon prediction.
    # Override on an instance to experiment without editing source.
    RECENCY_HALF_LIFE_DAYS = 90.0   # anchor age decay half-life
    DIST_DECAY_K = 1.0              # distance-proximity decay exponent
    VDOT_FAMILY_WEIGHT = 0.7        # central-estimate share for VDOT (running)
    RACE_BOOST = 1.5                # weight multiplier for race-flagged anchors
    INTENSITY_FLOOR = 0.4           # min quality weight for low-avg-HR anchors

    # Race-day calibration: the backtest showed predictions are systematically
    # ~2–3% slower than actual race results at every distance and every knob
    # setting — training best-efforts understate a tapered, competitive race.
    # Instead of hardcoding a fudge, the correction is learned per-athlete:
    # median(actual / predicted-as-of-race-day) over past races, clamped, and
    # only applied once enough races exist.
    RACE_CALIBRATION_MIN_RACES = 3
    RACE_CALIBRATION_CLAMP = 0.05   # factor stays within [0.95, 1.05]

    def _compute_predictions(
        self,
        recent_bests: list[dict],
        sport_category: str,
        reference_date: datetime | None = None,
    ) -> dict:
        """Run the race-prediction pipeline over a list of recent best efforts
        (each: {distance_m, time_s, date, ...}) for the given sport category.

        Each input contributes to the central and band with a combined weight:
            w = distance_proximity × recency_decay × quality
        where:
            distance_proximity = exp(-|log2(d_input / d_target)|)  (anchor closeness)
            recency_decay      = exp(-ln(2) × age_days / 180)      (6-mo half-life)
            quality            = race-flagged boost (1.5×) or an intensity
                                 factor from the activity's avg HR vs HR max —
                                 a long-run "best" is weaker evidence of race
                                 ability than an actual race or hard workout.

        Recency decay replaces the old hard 24-week cutoff with a smooth
        weighting so predictions don't cliff when a single fast effort ages
        past the boundary. `reference_date` pins "now" for age calculations —
        defaults to wall-clock time; history calls pass each step's end_date
        so past weeks are evaluated as-of then.

        - Central estimate per target: Riegel family (fixed 1.06 + personalized
          exp if fit). For running, blended 50/50 with a VDOT prediction.
        - Uncertainty band: weighted p25–p75 of the projection pool, using the
          same weights as the central (so central stays inside band).

        Cycling / swimming note: Riegel's canonical 1.06 is calibrated for
        running; for other sports the fitted exponent matters more. We still
        report it and let the caller see `fitted_exponent` to judge quality.

        Returns {predictions, athlete_vdot, fitted_exponent}. No caching, no
        data_quality — caller wraps as needed.
        """
        if reference_date is None:
            reference_date = datetime.now(timezone.utc)
        ref_ts = pd.Timestamp(reference_date)
        if ref_ts.tz is None:
            ref_ts = ref_ts.tz_localize("UTC")
        sport_configs = {
            "running": self.RUNNING_DISTANCES,
            "cycling": self.CYCLING_DISTANCES,
            "swimming": self.SWIMMING_DISTANCES,
        }
        target_distances = sport_configs.get(sport_category, [])

        # Precompute recency weights per best: exp(-ln(2) × age / half-life).
        # With the default 180d half-life: today → ~1.0; 6 months → 0.5;
        # 1 year → 0.25; 2 years → 0.06.
        half_life = self.RECENCY_HALF_LIFE_DAYS

        def _recency_w(date_str: str) -> float:
            try:
                pr_date = pd.to_datetime(date_str, utc=True)
                age_days = max(0.0, (ref_ts - pr_date).total_seconds() / 86400.0)
            except Exception:
                return 0.1
            return math.exp(-0.693 * age_days / half_life)

        # Anchor quality: race-flagged efforts are true maximal demonstrations
        # and get a boost; efforts recorded at clearly sub-maximal heart rate
        # are down-weighted. Whole-activity average HR is a coarse proxy for
        # segment intensity, so the floor stays generous and missing HR is
        # neutral rather than penalized.
        hr_max = self.get_max_heart_rate() or 0
        race_boost = self.RACE_BOOST
        intensity_floor = self.INTENSITY_FLOOR

        def _quality_w(b: dict) -> float:
            if b.get("is_race"):
                return race_boost
            avg_hr = b.get("avg_hr")
            if avg_hr and hr_max > 0:
                ratio = avg_hr / hr_max
                # ~85%+ of max HR → full weight, linear down to the floor.
                return float(min(1.0, max(intensity_floor, (ratio - 0.55) / 0.30)))
            return 1.0

        anchor_weights = [
            _recency_w(b.get("date", "")) * _quality_w(b) for b in recent_bests
        ]

        # VDOT only applies to running. Each top-1 race anchor yields a VDOT;
        # these are kept as a triple (value, anchor_distance, anchor_weight)
        # so we can re-weight per target by distance proximity inside the loop.
        # Global `athlete_vdot` (weighted by recency×quality only) is still
        # returned for display/debug — the per-target VDOT is used for
        # predictions.
        vdot_anchors: list[tuple[float, int, float]] = []
        athlete_vdot: float | None = None
        if sport_category == "running":
            for b, rw in zip(recent_bests, anchor_weights):
                if not b.get("is_top1"):
                    continue
                v = vdot_from_time_distance(b["time_s"], b["distance_m"])
                if v is not None and rw > 0:
                    vdot_anchors.append((v, int(b["distance_m"]), rw))
            if vdot_anchors:
                tot = sum(rw for _, _, rw in vdot_anchors)
                athlete_vdot = (
                    round(sum(v * rw for v, _, rw in vdot_anchors) / tot, 2)
                    if tot > 0 else None
                )

        # Fit personalized Riegel exponent from the per-distance top-1 efforts
        # only — passing multiple samples per distance would bias the fit
        # toward distances with the most samples. Sub-3-minute efforts are
        # excluded: Riegel's power law is calibrated for aerobic race
        # durations, and anaerobic 400m/1K points skew the exponent that is
        # then applied to *every* distance.
        top1_bests = [b for b in recent_bests if b.get("is_top1") and b["time_s"] >= 180]
        fitted_exp = fit_riegel_exponent(top1_bests) if len(top1_bests) >= 3 else None

        # Distance-proximity decay exponent. k=1 is the classical exp(-|log2|);
        # k=1.5 dampens cross-distance contributions from far-away anchors
        # (e.g. 5K projecting to 20K) without fully zeroing them out.
        dist_decay_k = self.DIST_DECAY_K

        def _dist_weight(d_in: float, d_tgt: float) -> float:
            # exp(-k·|log2(ratio)|): 1.0 when d_in == d_tgt.
            # k=1.5 → 2× mismatch yields weight 0.354 (was 0.5), 4× → 0.125 (was 0.25).
            return math.exp(-dist_decay_k * abs(math.log2(d_in / d_tgt)))

        predictions: list[dict] = []
        for dist_m, label in target_distances:
            entry: dict = {
                "distance_m": dist_m,
                "label": label,
                "pr_time_s": None,
                "pr_date": None,
                "source": "predicted",
                "predicted_time_s": None,
                "predicted_time_low_s": None,
                "predicted_time_high_s": None,
                "models": {},
            }

            # For display: the fastest effort at this distance (top-1 among
            # the top-K samples loaded above).
            existing = next(
                (b for b in recent_bests if b["distance_m"] == dist_m and b.get("is_top1")),
                None,
            )
            if existing:
                entry["pr_time_s"] = existing["time_s"]
                entry["pr_date"] = existing.get("date")
                entry["source"] = "personal_record"

            if not recent_bests:
                predictions.append(entry)
                continue

            # Build the sample pool: every raw model value that contributes to
            # the central, tagged with its effective weight. Weighted mean of
            # this pool IS the central, and the weighted p25/p75 IS the band —
            # guarantees the central always sits inside the band regardless of
            # model-mix or distance-weight skew.
            samples: list[tuple[float, float]] = []  # (value, weight)

            # Per-input Riegel (fixed 1.06) projections weighted by distance
            # proximity AND recency×quality of the underlying best.
            riegel_inputs = [
                (riegel_predict(b["time_s"], b["distance_m"], dist_m, 1.06),
                 _dist_weight(b["distance_m"], dist_m) * rw)
                for b, rw in zip(recent_bests, anchor_weights)
            ]
            riegel_sum_w = sum(w for _, w in riegel_inputs)

            # Per-input personalized Riegel projections, if the exponent was fit.
            pers_inputs: list[tuple[float, float]] = []
            if fitted_exp is not None:
                pers_inputs = [
                    (riegel_predict(b["time_s"], b["distance_m"], dist_m, fitted_exp),
                     _dist_weight(b["distance_m"], dist_m) * rw)
                    for b, rw in zip(recent_bests, anchor_weights)
                ]
            pers_sum_w = sum(w for _, w in pers_inputs)

            # Per-target VDOT: re-weight each anchor's VDOT by its distance
            # proximity to the current target. A 5K anchor still informs
            # Marathon predictions, but much less than a 20K or Half anchor.
            vdot_pred: float | None = None
            if vdot_anchors and sport_category == "running":
                vdot_pairs = [
                    (v, rw * _dist_weight(d_anchor, dist_m))
                    for v, d_anchor, rw in vdot_anchors
                ]
                tot_vw = sum(w for _, w in vdot_pairs)
                if tot_vw > 0:
                    target_vdot = sum(v * w for v, w in vdot_pairs) / tot_vw
                    vdot_pred = predicted_time_from_vdot(target_vdot, dist_m)

            # Family weights: VDOT gets VDOT_FAMILY_WEIGHT when present; the
            # Riegel family splits the remainder evenly between fixed +
            # personalized.
            has_r = riegel_sum_w > 0
            has_p = pers_sum_w > 0
            has_v = vdot_pred is not None
            vdot_w = self.VDOT_FAMILY_WEIGHT if has_v else 0.0
            family_w = 1.0 - vdot_w
            n_families = (1 if has_r else 0) + (1 if has_p else 0)
            r_share = family_w / n_families if has_r and n_families else 0.0
            p_share = family_w / n_families if has_p and n_families else 0.0

            # Distribute each family's total share across its per-input samples
            # proportionally to each input's distance weight.
            if has_r:
                for v, w in riegel_inputs:
                    samples.append((v, r_share * w / riegel_sum_w))
            if has_p:
                for v, w in pers_inputs:
                    samples.append((v, p_share * w / pers_sum_w))
            if has_v:
                samples.append((vdot_pred, vdot_w))  # type: ignore[arg-type]

            # Populate model aggregates (unchanged API).
            if has_r:
                entry["models"]["riegel"] = round(
                    sum(v * w for v, w in riegel_inputs) / riegel_sum_w, 1
                )
            if has_p:
                entry["models"]["personalized_riegel"] = round(
                    sum(v * w for v, w in pers_inputs) / pers_sum_w, 1
                )
            if has_v:
                entry["models"]["vdot"] = vdot_pred

            # Central = weighted mean of the sample pool.
            total_w = sum(w for _, w in samples)
            if total_w > 0:
                central = sum(v * w for v, w in samples) / total_w
                entry["predicted_time_s"] = round(central, 1)

            # Uncertainty band = weighted p25/p75 of the same sample pool.
            if len(samples) >= 2:
                vals = [v for v, _ in samples]
                wts = [w for _, w in samples]
                entry["predicted_time_low_s"] = round(_weighted_quantile(vals, wts, 0.25), 1)
                entry["predicted_time_high_s"] = round(_weighted_quantile(vals, wts, 0.75), 1)
            elif len(samples) == 1 and entry["predicted_time_s"] is not None:
                entry["predicted_time_low_s"] = entry["predicted_time_s"]
                entry["predicted_time_high_s"] = entry["predicted_time_s"]

            predictions.append(entry)

        return {
            "predictions": predictions,
            "athlete_vdot": athlete_vdot,
            "fitted_exponent": fitted_exp,
        }

    def _compute_race_residuals(self, sport_category: str) -> list[tuple[pd.Timestamp, float]]:
        """(race_date, actual/predicted) for every race-flagged effort at a
        standard distance, with the prediction computed as-of the day before
        the race — a race never calibrates itself, and residuals are ordered
        by date so callers can filter to 'races before X' leak-free.

        A race maps to its primary standard distance: the largest target with
        target <= GPS distance <= target * 1.08 (GPS always over-reads the
        nominal course). The actual time is the race's own best effort at that
        distance. Computed once per sport and cached; invalidated on sync.
        """
        cached = self._race_residuals_cache.get(sport_category)
        if cached is not None:
            return cached
        sport_configs = {
            "running": self.RUNNING_DISTANCES,
            "cycling": self.CYCLING_DISTANCES,
            "swimming": self.SWIMMING_DISTANCES,
        }
        targets = sorted((d for d, _ in sport_configs.get(sport_category, [])), reverse=True)
        residuals: list[tuple[pd.Timestamp, float]] = []
        activities = self._get_prepared_activities()
        if not targets or activities.empty or "workout_type" not in activities.columns:
            self._race_residuals_cache[sport_category] = residuals
            return residuals

        cat_mask = activities["sport_type"].apply(lambda st: get_sport_category(st) == sport_category)
        races = activities[cat_mask & activities["workout_type"].isin([1, 11])]
        bests = self._get_per_activity_bests_df(sport_category)
        if races.empty or bests.empty:
            self._race_residuals_cache[sport_category] = residuals
            return residuals

        for _, row in races.iterrows():
            gps_dist = float(row.get("distance") or 0)
            primary = next((t for t in targets if t <= gps_dist <= t * 1.08), None)
            if primary is None:
                continue
            effort = bests[
                (bests["activity_id"] == row["id"]) & (bests["distance_m"] == primary)
            ]
            if effort.empty:
                continue
            race_date = row["start_date_local"]
            asof = race_date - pd.Timedelta(days=1)
            recent = self._recent_best_efforts_list(
                sport_category, within_days=self.PREDICTIONS_WINDOW_DAYS, end_date=asof
            )
            if not recent:
                continue
            core = self._compute_predictions(recent, sport_category, reference_date=asof)
            entry = next(
                (p for p in core["predictions"] if p["distance_m"] == primary), None
            )
            if not entry or not entry.get("predicted_time_s"):
                continue
            residuals.append(
                (race_date, float(effort["time_s"].iloc[0]) / float(entry["predicted_time_s"]))
            )

        residuals.sort(key=lambda r: r[0])
        self._race_residuals_cache[sport_category] = residuals
        return residuals

    def _race_calibration(self, sport_category: str, reference_date) -> dict:
        """Race-day calibration as of `reference_date`, from races strictly
        before that date:
            factor          — clamped median(actual/predicted): central correction
            band_low_mult / band_high_mult — p25/p75 of the residuals, or None
                              below the minimum race count. An *empirical*
                              uncertainty band: across past races, the middle
                              50% of actual results landed in this range around
                              the raw prediction — captures day-form, course
                              and model error together, which the model-spread
                              IQR (quantiles of a pool dominated by one VDOT
                              sample) understates.
            n_races         — residuals used
        """
        ref = pd.Timestamp(reference_date)
        if ref.tz is None:
            ref = ref.tz_localize("UTC")
        residuals = [r for d, r in self._compute_race_residuals(sport_category) if d < ref]
        n = len(residuals)
        if n < self.RACE_CALIBRATION_MIN_RACES:
            return {"factor": 1.0, "band_low_mult": None, "band_high_mult": None, "n_races": n}
        clamp = self.RACE_CALIBRATION_CLAMP
        factor = float(min(1.0 + clamp, max(1.0 - clamp, np.median(residuals))))
        # Keep the band consistent with the (possibly clamped) central factor.
        low = min(float(np.percentile(residuals, 25)), factor)
        high = max(float(np.percentile(residuals, 75)), factor)
        return {"factor": factor, "band_low_mult": low, "band_high_mult": high, "n_races": n}

    @staticmethod
    def _apply_calibration(predictions: list[dict], cal: dict) -> None:
        """Apply race-day calibration in place: scale the central by `factor`;
        replace the band with the empirical residual band when available,
        otherwise scale the model band and clamp it to contain the central."""
        factor = cal["factor"]
        low_mult, high_mult = cal["band_low_mult"], cal["band_high_mult"]
        for p in predictions:
            raw = p.get("predicted_time_s")
            if raw is None:
                continue
            central = raw * factor
            if low_mult is not None:
                p["predicted_time_low_s"] = round(raw * low_mult, 1)
                p["predicted_time_high_s"] = round(raw * high_mult, 1)
            else:
                if p.get("predicted_time_low_s") is not None:
                    p["predicted_time_low_s"] = round(min(p["predicted_time_low_s"] * factor, central), 1)
                if p.get("predicted_time_high_s") is not None:
                    p["predicted_time_high_s"] = round(max(p["predicted_time_high_s"] * factor, central), 1)
            p["predicted_time_s"] = round(central, 1)

    def get_race_predictions(self, sport_category: str = "running") -> dict:
        """Generate race predictions using a recent-bests model.

        All sports (running / cycling / swimming) use the same pipeline:
          • Inputs are sliding-window best efforts from the last 52 weeks
            (PREDICTIONS_WINDOW_DAYS) at that sport's standard distances,
            recency-decayed inside the window — reflecting *current* fitness
            rather than lifetime bests.
          • Central estimate blends VDOT (running only, 50% weight) with a
            closer-anchor-weighted Riegel family (fixed 1.06 + personalized
            exponent when ≥3 inputs are available). Race-flagged anchors are
            boosted; clearly sub-maximal anchors are down-weighted.
          • Uncertainty band is the weighted p25–p75 (IQR) of the projection
            pool.
        """
        if sport_category in self._race_predictions_cache:
            return self._race_predictions_cache[sport_category]

        recent = self._recent_best_efforts_list(
            sport_category, within_days=self.PREDICTIONS_WINDOW_DAYS
        )
        core = self._compute_predictions(recent, sport_category)
        cal = self._race_calibration(sport_category, datetime.now(timezone.utc))
        self._apply_calibration(core["predictions"], cal)

        n_recent = len({b["distance_m"] for b in recent if b.get("is_top1")})
        confidence = "high" if n_recent >= 5 else "medium" if n_recent >= 3 else "low"

        activities = self._get_prepared_activities()
        cat_activities = activities[
            activities["sport_type"].apply(lambda st: get_sport_category(st) == sport_category)
        ]

        warnings: list[str] = []
        if n_recent == 0:
            warnings.append(
                f"No {sport_category} efforts in the last 52 weeks — predictions unavailable"
            )
        elif n_recent < 3:
            warnings.append(
                f"Only {n_recent} distinct recent best effort(s) in the last 52 weeks — "
                "personalized Riegel not fit; predictions extrapolated from limited inputs"
            )
        if sport_category == "cycling":
            warnings.append(
                "Cycling predictions use a time/distance Riegel model — for power-based "
                "athletes a critical-power curve would be more accurate"
            )

        # Targets far beyond the longest recent effort are extrapolations the
        # backtest can't vouch for (e.g. Marathon predicted from ≤HM anchors).
        max_anchor = max((b["distance_m"] for b in recent), default=0)
        extrapolated = [
            label for dist_m, label in
            {"running": self.RUNNING_DISTANCES, "cycling": self.CYCLING_DISTANCES,
             "swimming": self.SWIMMING_DISTANCES}.get(sport_category, [])
            if max_anchor and dist_m > 1.6 * max_anchor
        ]
        if extrapolated:
            warnings.append(
                f"{', '.join(extrapolated)} prediction extrapolates well beyond the "
                f"longest recent effort ({max_anchor / 1000:.1f} km) — treat with caution"
            )

        # Garmin's own race predictor (running only) for side-by-side
        # comparison: attach the matching time to each standard distance.
        garmin_preds = self._garmin_race_predictions() if sport_category == "running" else None
        if garmin_preds:
            garmin_by_distance = {
                5000: garmin_preds.get("time5K"),
                10000: garmin_preds.get("time10K"),
                21097: garmin_preds.get("timeHalfMarathon"),
                42195: garmin_preds.get("timeMarathon"),
            }
            for p in core["predictions"]:
                g = garmin_by_distance.get(p["distance_m"])
                if g:
                    p["garmin_time_s"] = float(g)

        result = {
            "predictions": core["predictions"],
            "athlete_vdot": core["athlete_vdot"],
            "fitted_exponent": core["fitted_exponent"],
            "confidence": confidence,
            "sport_category": sport_category,
            "garmin_predictions": garmin_preds,
            "race_day_calibration": {
                "factor": round(cal["factor"], 4),
                "n_races": cal["n_races"],
                "band_low_mult": round(cal["band_low_mult"], 4) if cal["band_low_mult"] else None,
                "band_high_mult": round(cal["band_high_mult"], 4) if cal["band_high_mult"] else None,
            },
            "data_quality": {
                "total_activities": int(len(cat_activities)),
                "prs_available": n_recent,
                "recent_prs": n_recent,
                "sufficient": n_recent >= 2,
                "warnings": warnings,
                "window_days": self.PREDICTIONS_WINDOW_DAYS,
            },
        }
        self._race_predictions_cache[sport_category] = result
        return result

    def get_race_predictions_history(
        self,
        sport_category: str = "running",
        weeks: int = 52,
        step_days: int = 7,
        window_days: int = 365,
    ) -> list[dict]:
        """Time series of race predictions. For each step (weekly by default),
        recomputes predictions using the recent-bests window ending at that
        step's date. Runs the full pipeline per step — cost is
        O(steps · activities_in_window · distances).

        Returns a list ordered oldest→newest:
            [{end_date: 'YYYY-MM-DD', athlete_vdot, fitted_exponent,
              predictions: [{distance_m, label, predicted_time_s,
                             predicted_time_low_s, predicted_time_high_s}, ...]},
             ...]
        """
        sport_configs = {
            "running": self.RUNNING_DISTANCES,
            "cycling": self.CYCLING_DISTANCES,
            "swimming": self.SWIMMING_DISTANCES,
        }
        if sport_category not in sport_configs:
            return []

        # Require at least 3 distinct recent bests so the personalized Riegel
        # can fit and the IQR band is non-degenerate. Steps below this floor
        # are dropped — cleaner than pretending a single anchor can predict
        # the full distance range.
        MIN_INPUTS = 3

        target_distances = sport_configs[sport_category]
        empty_predictions = [
            {
                "distance_m": dist_m,
                "label": label,
                "predicted_time_s": None,
                "predicted_time_low_s": None,
                "predicted_time_high_s": None,
            }
            for dist_m, label in target_distances
        ]

        now = datetime.now(timezone.utc)
        history: list[dict] = []
        first_valid_seen = False
        for i in range(weeks - 1, -1, -1):
            step_end = now - timedelta(days=i * step_days)
            recent = self._recent_best_efforts_list(
                sport_category, within_days=window_days, end_date=step_end
            )
            distinct = len({b["distance_m"] for b in recent if b.get("is_top1")})

            if distinct < MIN_INPUTS:
                # Skip entirely until we've seen our first valid point; after that
                # emit a null-predictions entry so the chart can render a gap
                # (break the line) rather than connecting across the missing week.
                if not first_valid_seen:
                    continue
                history.append({
                    "end_date": step_end.date().isoformat(),
                    "athlete_vdot": None,
                    "fitted_exponent": None,
                    "n_inputs": len(recent),
                    "predictions": empty_predictions,
                })
                continue

            first_valid_seen = True
            core = self._compute_predictions(recent, sport_category, reference_date=step_end)
            cal = self._race_calibration(sport_category, step_end)
            self._apply_calibration(core["predictions"], cal)
            history.append(
                {
                    "end_date": step_end.date().isoformat(),
                    "athlete_vdot": core["athlete_vdot"],
                    "fitted_exponent": core["fitted_exponent"],
                    "n_inputs": len(recent),
                    "predictions": [
                        {
                            "distance_m": p["distance_m"],
                            "label": p["label"],
                            "predicted_time_s": p["predicted_time_s"],
                            "predicted_time_low_s": p["predicted_time_low_s"],
                            "predicted_time_high_s": p["predicted_time_high_s"],
                        }
                        for p in core["predictions"]
                    ],
                }
            )
        return history

    # ── Training Load & PMC ───────────────────────────────────────────

    def get_daily_training_load(self, hr_zones: list | None = None, hr_rest: float | None = None) -> list[dict]:
        """Compute daily TRIMP values from all activities.

        hr_zones: optional zones override (e.g. resolved from user settings).
        hr_rest:  optional resting-HR override (e.g. resolved from user settings).

        Results are memoized per distinct (resting HR, max HR, zones) key, so
        every caller — PMC, /training-load, weekly Relative Effort, any sport —
        reuses one full-cache scan instead of recomputing the stream-heavy TRIMP.
        Cleared by invalidate_caches() after a sync.
        """
        hr_max = self.get_max_heart_rate()
        if hr_rest is None:
            hr_rest = self.get_rest_heart_rate()
        if hr_zones is None:
            hr_zones = self._get_hr_zones_cached()

        cache_key = (
            round(float(hr_rest), 1),
            round(float(hr_max), 1),
            tuple((z.get('min'), z.get('max')) for z in (hr_zones or [])),
        )
        cached = self._training_load_cache.get(cache_key)
        if cached is not None:
            return cached

        activities = self._get_prepared_activities()
        if activities.empty:
            self._training_load_cache[cache_key] = []
            return []

        # Drop rows that can't contribute a TRIMP value up-front so we only do
        # work on rows with valid avg_hr and positive moving_time.
        mt = activities['moving_time'] if 'moving_time' in activities.columns else pd.Series(dtype=float)
        hr = activities['average_heartrate'] if 'average_heartrate' in activities.columns else pd.Series(dtype=float)
        mask = hr.notna() & (hr > 0) & mt.notna() & (mt > 0)
        valid = activities[mask]
        if valid.empty:
            self._training_load_cache[cache_key] = []
            return []

        # Vectorized Banister TRIMP across all valid rows — replaces the
        # scalar compute_trimp_banister call that ran inside the old iterrows
        # loop. Matches the male default in the scalar helper.
        duration_min_arr = valid['moving_time'].to_numpy(dtype=np.float64) / 60.0
        avg_hr_arr = valid['average_heartrate'].to_numpy(dtype=np.float64)
        hr_range = hr_max - hr_rest
        if hr_range > 0:
            delta = np.clip((avg_hr_arr - hr_rest) / hr_range, 0.0, 1.0)
            banister = duration_min_arr * delta * 0.64 * np.exp(1.92 * delta)
        else:
            banister = np.zeros(len(valid), dtype=np.float64)

        trimps = banister.copy()
        methods = np.full(len(valid), 'banister', dtype=object)

        # Zone-weighted override for rows that have usable stream data. This
        # stays per-row because stream length varies per activity, but it
        # only runs for activities that actually have streams — a huge win
        # when most of the cache is stream-less.
        if hr_zones:
            boundaries = [z['max'] for z in hr_zones[:4]]
            valid_ids = valid['id'].astype('int64').tolist() if 'id' in valid.columns else []
            streams_map = self.strava_activities_cache.get_streams_bulk(valid_ids)
            id_list = valid['id'].astype('int64').to_numpy() if 'id' in valid.columns else np.array([], dtype=np.int64)
            for idx in range(len(valid)):
                streams = streams_map.get(int(id_list[idx])) if idx < len(id_list) else None
                if not streams:
                    continue
                hr_col = streams.get('heartrate')
                if not hr_col:
                    continue
                hr_vals = [v for v in hr_col if v is not None]
                if len(hr_vals) <= 10:
                    continue
                hr_arr = np.asarray(hr_vals, dtype=np.float64)
                bins = np.digitize(hr_arr, boundaries, right=False)
                time_per_pt = duration_min_arr[idx] / len(hr_arr)
                time_in_zones = [float(np.sum(bins == i)) * time_per_pt for i in range(5)]
                zw = compute_trimp_zone_weighted(time_in_zones)
                if zw > 0:
                    trimps[idx] = zw
                    methods[idx] = 'zone_weighted'

        trimps_rounded = np.round(trimps, 1)
        date_strs = valid['start_date_local'].dt.strftime('%Y-%m-%d').to_numpy()
        names = valid.get('name', pd.Series([''] * len(valid), index=valid.index)).fillna('').to_numpy()
        sports = valid.get('sport_type', pd.Series([''] * len(valid), index=valid.index)).fillna('').to_numpy()

        daily: dict[str, dict] = {}
        for date_str, trimp, method, name, sport in zip(date_strs, trimps_rounded, methods, names, sports):
            entry = daily.get(date_str)
            if entry is None:
                entry = {"date": date_str, "trimp": 0.0, "activities": [], "trimp_method": str(method)}
                daily[date_str] = entry
            entry["trimp"] += float(trimp)
            entry["activities"].append({
                "name": str(name),
                "sport_type": str(sport),
                "trimp": float(trimp),
                "trimp_method": str(method),
            })

        result = sorted(daily.values(), key=lambda d: d["date"])
        self._training_load_cache[cache_key] = result
        return result

    # Cosmetic multiplier so weekly Relative Effort reads in a Strava-like
    # range. The band is derived from the same scaled series, so status
    # (below / in / above range) is invariant to this constant.
    RE_DISPLAY_SCALE = 1.4
    RE_SPORTS: tuple[str, ...] = ("running", "swimming")

    def get_weekly_relative_effort(
        self,
        hr_zones: list | None = None,
        hr_rest: float | None = None,
        sports: tuple[str, ...] | None = None,
        band_span: int = 6,
        band_k: float = 0.6,
    ) -> dict:
        """Weekly Relative Effort with a personalized expected-range band.

        Reuses per-activity TRIMP from get_daily_training_load (HR-zone-weighted
        where streams exist, Banister avg-HR otherwise), keeps only `sports`,
        sums per ISO week, and derives the band as EWMA ± band_k·rolling-std over
        `band_span` weeks. Gap weeks are filled with 0 so rest weeks read as dips.
        """
        if sports is None:
            sports = self.RE_SPORTS
        daily = self.get_daily_training_load(hr_zones=hr_zones, hr_rest=hr_rest)
        rows = [
            (day["date"], act.get("trimp", 0.0))
            for day in daily
            for act in day.get("activities", [])
            if get_sport_category(act.get("sport_type")) in sports
        ]
        if not rows:
            return {"weeks": [], "scale": self.RE_DISPLAY_SCALE, "sports": list(sports)}

        df = pd.DataFrame(rows, columns=["date", "trimp"])
        df["date"] = pd.to_datetime(df["date"])
        # Monday-anchored weeks: the start_time of a Sunday-ending period is Monday.
        df["week"] = df["date"].dt.to_period("W-SUN").dt.start_time
        weekly = df.groupby("week")["trimp"].sum() * self.RE_DISPLAY_SCALE
        full_idx = pd.date_range(weekly.index.min(), weekly.index.max(), freq="W-MON")
        weekly = weekly.reindex(full_idx, fill_value=0.0)

        center = weekly.ewm(span=band_span).mean()
        std = weekly.rolling(band_span, min_periods=2).std().fillna(0.0)
        band_low = (center - band_k * std).clip(lower=0.0)
        band_high = center + band_k * std

        weeks = [
            {
                "week_start": ts.strftime("%Y-%m-%d"),
                "relative_effort": float(round(re_val)),
                "band_low": float(round(lo)),
                "band_high": float(round(hi)),
                "status": "below" if re_val < lo else ("above" if re_val > hi else "in_range"),
            }
            for ts, re_val, lo, hi in zip(
                weekly.index, weekly.to_numpy(), band_low.to_numpy(), band_high.to_numpy()
            )
        ]
        return {"weeks": weeks, "scale": self.RE_DISPLAY_SCALE, "sports": list(sports)}

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
        today = pd.Timestamp(_utc_now_naive().strftime('%Y-%m-%d'))
        date_range = pd.date_range(first_date, today, freq='D')

        trimp_map = {d["date"]: d["trimp"] for d in daily_load}
        trimp_series = pd.Series(
            [trimp_map.get(d.strftime('%Y-%m-%d'), 0.0) for d in date_range],
            index=date_range,
        )

        # Coggan-standard impulse/response: CTL_t = CTL_{t-1} + (load_t − CTL_{t-1})/42,
        # i.e. alpha = 1/42. (span=42 would set alpha = 2/43 ≈ 1/21.5 — a chart
        # roughly twice as reactive as the standard 42-day CTL definition.)
        # A zero-load seed day is prepended so the EWM starts at 0 instead of
        # the first day's raw TRIMP (ewm(adjust=False) seeds at the first
        # observation, which would report "peak fitness" on day one of history).
        seed_day = date_range[0] - pd.Timedelta(days=1)
        seeded = pd.concat([pd.Series([0.0], index=[seed_day]), trimp_series])
        ctl = seeded.ewm(alpha=1 / 42, adjust=False).mean().iloc[1:]
        atl = seeded.ewm(alpha=1 / 7, adjust=False).mean().iloc[1:]
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
        with_streams = len(self.strava_activities_cache.streams.all_activity_ids())

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
        """Compute a best-effort VDOT fitness trend for running.

        Each activity is represented by the highest VDOT among its
        sliding-window best efforts at standard distances (from
        `_get_per_activity_bests_df`) — the strongest sustained segment the
        athlete actually produced that day. The previous implementation fed
        whole-activity distance/moving_time into the Daniels formula, which
        treats every easy run as a race effort, so the line tracked recent
        effort rather than fitness.

        The trend line (`rolling_avg` key, kept for API compatibility) is the
        28-day rolling *maximum*: the best fitness demonstrated in the last
        four weeks. Easy weeks hold the line flat instead of dragging it down.
        """
        cache_key = f"{sport_type}|{start_date}|{end_date}"
        if cache_key in self._fitness_trend_cache:
            return self._fitness_trend_cache[cache_key]

        category = get_sport_category(sport_type)
        bests = self._get_per_activity_bests_df(category)
        filtered = bests.dropna(subset=["date"]) if not bests.empty else bests

        if not filtered.empty and start_date:
            filtered = filtered[filtered['date'] >= pd.to_datetime(start_date, utc=True)]
        if not filtered.empty and end_date:
            filtered = filtered[filtered['date'] <= pd.to_datetime(end_date, utc=True)]

        # Vectorized VDOT over every (activity, distance) best effort: inline
        # the closed-form Daniels approximation in one pass. Same math as
        # vdot_from_time_distance, just numpy. Efforts under 3 minutes are
        # outside the formula's validity range and dropped.
        times_s = filtered['time_s'].to_numpy(dtype=np.float64) if not filtered.empty else np.array([])
        dists_m = filtered['distance_m'].to_numpy(dtype=np.float64) if not filtered.empty else np.array([])
        t_min = times_s / 60.0
        with np.errstate(divide='ignore', invalid='ignore'):
            v_mpm = np.where(t_min > 0, dists_m / t_min, 0.0)
            vo2 = -4.60 + 0.182258 * v_mpm + 0.000104 * v_mpm * v_mpm
            pct = 0.8 + 0.1894393 * np.exp(-0.012778 * t_min) + 0.2989558 * np.exp(-0.1932605 * t_min)
            vdot = np.where(pct > 0, vo2 / pct, np.nan)
        vdot = np.round(vdot, 2)
        keep = np.isfinite(vdot) & (vdot > 15) & (vdot < 85) & (times_s >= 180)

        points = []
        if keep.any():
            kept = filtered.loc[keep].copy()
            kept["vdot"] = vdot[keep]
            # One point per activity: the best effort that demonstrates the
            # most fitness (max VDOT across that activity's distances).
            top_idx = kept.groupby("activity_id")["vdot"].idxmax()
            per_act = kept.loc[top_idx].sort_values("date")
            points = [
                {
                    "date": r["date"].strftime('%Y-%m-%d'),
                    "vdot": float(r["vdot"]),
                    "activity_name": str(r.get("activity_name", "") or ""),
                    "distance_km": round(float(r["distance_m"]) / 1000, 2),
                }
                for _, r in per_act.iterrows()
            ]

        # Demonstrated-fitness envelope: 28-day rolling max of best-effort
        # VDOT. Key name kept as `rolling_avg` for API compatibility.
        rolling_avg = []
        if len(points) >= 3:
            vdot_series = pd.Series(
                [p["vdot"] for p in points],
                index=pd.to_datetime([p["date"] for p in points]),
            )
            rolled = vdot_series.rolling(window='28D', min_periods=1).max()
            for d, v in rolled.items():
                rolling_avg.append({"date": d.strftime('%Y-%m-%d'), "vdot": round(float(v), 2)})

        # Current and peak
        current_vdot = rolling_avg[-1]["vdot"] if rolling_avg else (points[-1]["vdot"] if points else None)
        peak_entry = max(rolling_avg, key=lambda x: x["vdot"]) if rolling_avg else None

        # Trend: compare current 28-day envelope vs 8 weeks ago
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
                "total_activities": int(filtered["activity_id"].nunique()) if not filtered.empty else 0,
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
    HR_HISTOGRAM = "hr_histogram"  # {min_bpm: int, counts: list[int]} 1 bpm bins (or null when no HR samples)
    MOST_ACTIVE_DAY = "most_active_day"  # weekday (0-6)
    LONGEST_ACTIVITY_KM = "longest_activity_km"
    LONGEST_ACTIVITY_NAME = "longest_activity_name"
    HR_ZONE_RANGES = "hr_zone_ranges"  # dict: zone (1-5) -> (min_hr, max_hr)
