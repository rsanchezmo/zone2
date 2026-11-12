from dataclasses import dataclass, field
from datetime import date, datetime
from functools import partial
import logging
from threading import RLock
from typing import Any
import pandas as pd
import numpy as np
from zone2.activities_cache import StravaActivitiesCache
from zone2.clock import Clock
from zone2.best_efforts import (
    BESTS_COLUMNS, RECORD_SPORTS, BestEffort, PersonalRecord, RankedBests, per_activity_bests,
    personal_records, rank_bests, recent_best_efforts, sport_distances, stream_best_efforts, summary_name,
)
from zone2.drift import DRIFT_VERSION, HeartRateDrift, heart_rate_drift
from zone2.hr_recovery import HR_RECOVERY_VERSION, HeartRateRecovery, heart_rate_recovery
from zone2.race_predictions import (
    GarminRacePredictions, PredictionHistoryPoint, PredictionTuning, RacePredictions, RaceResidual,
    predict_races, prediction_history, race_residuals, race_results,
)
from zone2.reports import (
    AllYearInSportFeatures, WeeklyReportFeatures, YearInSportFeatures, activities_between, all_year_in_sport,
    week_bounds, weekly_report, year_in_sport,
)
from zone2.training_load import (
    HEARTRATE_COUNTS_VERSION, RE_SPORTS, DailyLoad, FitnessForm, HeartRateCounts, HrZone, PlannedSession,
    TrainingLoadKey, WeeklyRelativeEffort, daily_training_load, fitness_form, heartrate_counts,
    training_load_key, trimp_activities, weekly_relative_effort,
)
from zone2.user_cache import StravaUserCache
from zone2.utils import SportCategory, get_sport_category

logger = logging.getLogger(__name__)


def _in_category(activities: pd.DataFrame, sport_category: SportCategory) -> pd.Series:
    return activities["sport_type"].apply(lambda st: get_sport_category(st) == sport_category)


# Activities' cache version and the race activity ids
CachesKey = tuple[int, frozenset[int]]


@dataclass
class _Caches:
    """Results derived from one state of the activities and races. A build
    stores into the instance it started from, so a result computed while they
    change lands in a discarded instance instead of the current one."""
    key: CachesKey
    hr_zones: list[HrZone] | None = None
    race_predictions: dict[tuple[SportCategory, date], RacePredictions] = field(default_factory=dict)
    race_residuals: dict[SportCategory, list[RaceResidual]] = field(default_factory=dict)
    training_load: dict[TrainingLoadKey, list[DailyLoad]] = field(default_factory=dict)
    # Per-activity best efforts per sport, reused across windowed queries
    # instead of re-reading the summaries on every history step.
    per_activity_bests: dict[SportCategory, pd.DataFrame] = field(default_factory=dict)
    ranked_bests: dict[SportCategory, RankedBests] = field(default_factory=dict)


class StravaAnalytics:
    """The analytics over the activities and user caches: gathers each
    computation's inputs from them, keeps the results that are costly to
    rebuild, and leaves the maths to best_efforts, race_predictions,
    training_load and reports."""

    RECORD_SPORTS = RECORD_SPORTS
    RE_SPORTS = RE_SPORTS

    def __init__(self, strava_activities_cache: StravaActivitiesCache, strava_user_cache: StravaUserCache,
                 garmin_cache=None, clock: Clock | None = None):
        self.strava_activities_cache = strava_activities_cache # inmutable data (historical activities)
        self.strava_user_cache = strava_user_cache # mutable data (user profile, stats, zones)
        self.garmin_cache = garmin_cache # optional GarminDailyStatsCache for measured RHR/VO2max
        self.clock = clock or Clock()
        # Races the user keeps outside Strava's race flag (see set_race_activity_ids)
        self.race_activity_ids: frozenset[int] = frozenset()
        self.prediction_tuning = PredictionTuning()
        self._cache = _Caches(self._caches_key())
        # Request threads share the best-effort tables: one build at a time, the rest reuse it.
        self._lock = RLock()

    def _caches_key(self) -> CachesKey:
        return self.strava_activities_cache.cache_version, self.race_activity_ids

    def _caches(self) -> _Caches:
        """The caches for the activities and races as they are now: fresh ones
        once either changes. Builds take them before reading their inputs."""
        cache = self._cache
        key = self._caches_key()
        if cache.key != key:
            cache = self._cache = _Caches(key)
        return cache

    def invalidate_caches(self) -> None:
        """Drop every cached result, for inputs the caches' key doesn't cover
        (the athlete's zones and resting HR)."""
        self._cache = _Caches(self._caches_key())

    def set_race_activity_ids(self, ids: frozenset[int]) -> bool:
        """Activities to treat as races besides the ones Strava flags as such
        (workout_type 1 / 11): race efforts weigh more in the predictions and
        calibrate them. Returns whether the set changed (race-based results are
        then recomputed)."""
        if ids == self.race_activity_ids:
            return False
        self.race_activity_ids = ids
        return True

    def _race_mask(self, activities: pd.DataFrame) -> pd.Series:
        """Races: flagged on Strava (workout_type 1 = run race, 11 = ride race)
        or in race_activity_ids."""
        flagged = (activities['workout_type'].isin([1, 11]) if 'workout_type' in activities.columns
                   else pd.Series(False, index=activities.index))
        return flagged | activities['id'].isin(self.race_activity_ids)

    def warm_caches(self) -> None:
        """Build the history-wide caches, and any missing per-activity stream
        summaries, ahead of the first request that needs them."""
        activities = self.strava_activities_cache.get_prepared_view()
        for category in self.RECORD_SPORTS:
            self._ranked_bests(category)
        if not activities.empty:
            self._activity_heartrate_counts(activities['id'].astype('int64').tolist())
            runs = activities[activities['sport_type'].map(get_sport_category) == SportCategory.RUNNING]
            run_ids = runs['id'].astype('int64').tolist()
            self.activity_heart_rate_drift(run_ids)
            self.activity_heart_rate_recovery(run_ids)

    def _get_hr_zones_cached(self) -> list[HrZone]:
        """Cache HR zones to avoid repeated user cache reads."""
        caches = self._caches()
        if caches.hr_zones is None:
            caches.hr_zones = self.get_hr_zones()
        return caches.hr_zones

    # ── Athlete ───────────────────────────────────────────────────────

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

    def get_max_heart_rate(self) -> int:
        """Get the athlete's max heart rate. Prefers activity data to avoid API call."""
        hr_max = self._estimate_hr_max_from_activities()
        if hr_max and hr_max > 100:
            return hr_max
        return self._strava_hr_max()

    def _strava_hr_max(self) -> int:
        """The floor of Strava's zone 5, or a typical max HR while Strava has no zones for z2
        (before it is connected)."""
        zones = self.strava_user_cache.get_athlete_zones().get('heart_rate', {}).get('zones') or []
        return zones[4]['min'] if len(zones) == 5 and zones[4].get('min') else 190

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

    @staticmethod
    def _build_default_zones(hr_max: int) -> list[HrZone]:
        """Build standard 5-zone HR zones from a max HR value."""
        boundaries = [0.60, 0.70, 0.80, 0.90]
        zones: list[HrZone] = []
        low = 0
        for pct in boundaries:
            high = round(hr_max * pct)
            zones.append({'min': low, 'max': high})
            low = high
        zones.append({'min': low, 'max': hr_max})
        return zones

    def get_hr_zones(self) -> list[HrZone]:
        """Get the athlete's heart rate zones.

        Uses Strava custom zones if available (requires API call).
        Otherwise, estimates from the highest max_heartrate in activity data (no API call).
        """
        # Custom zones from Strava, only if already fetched (no API call)
        zones = self.strava_user_cache.cached_athlete_zones()
        if zones is not None:
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
        return self._build_default_zones(self._strava_hr_max())

    def _garmin_race_predictions(self) -> GarminRacePredictions | None:
        """Latest cached Garmin race-predictor times (running only), or None,
        straight from the cached `race_predictions` daily payload — no network.
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
        out: GarminRacePredictions = {
            "date": latest.get("date"),
            "time5K": payload.get("time5K"),
            "time10K": payload.get("time10K"),
            "timeHalfMarathon": payload.get("timeHalfMarathon"),
            "timeMarathon": payload.get("timeMarathon"),
        }
        return out if any(out[k] for k in out if k != "date") else None

    # ── Year in sport and weekly report ───────────────────────────────

    def get_year_in_sport(self, year: int, main_sport: str | SportCategory,
                          cutoff_month_day: tuple[int, int] | None = None) -> dict[YearInSportFeatures, Any]:
        """Year in sport for `main_sport` (a Strava sport type, or a category), up to the
        (month, day) `cutoff_month_day` when given, for a fair year-over-year
        comparison."""
        activities = self.strava_activities_cache.get_prepared_view()
        return year_in_sport(activities, year, main_sport, cutoff_month_day, self.clock.now().replace(tzinfo=None))

    def get_all_year_in_sport(self, year: int,
                              cutoff_month_day: tuple[int, int] | None = None) -> dict[AllYearInSportFeatures, Any]:
        """Year in sport across all sports, up to `cutoff_month_day` when given."""
        activities = self.strava_activities_cache.get_prepared_view()
        return all_year_in_sport(activities, year, cutoff_month_day, self.clock.now().replace(tzinfo=None))

    def get_weekly_report(self, week_start_date: str | None = None, cutoff_date: str | None = None,
                          hr_zones: list[HrZone] | None = None) -> dict[WeeklyReportFeatures, Any]:
        """Weekly report for the week (Monday to Sunday) of `week_start_date`
        ('YYYY-MM-DD', the current week when None), truncated at `cutoff_date`
        when given to compare with a week still running. HR zones default to
        the athlete's."""
        activities = self.strava_activities_cache.get_prepared_view()
        week_start, week_end = week_bounds(week_start_date, cutoff_date, self.clock.now())
        activities_week = activities_between(activities, week_start, week_end)
        zones = hr_zones if hr_zones is not None else self._get_hr_zones_cached()
        hr_counts: list[HeartRateCounts] = []
        if not activities_week.empty and zones:
            counts = self._activity_heartrate_counts(activities_week['id'].astype('int64').tolist())
            hr_counts = [c for c in counts.values() if c is not None]
        return weekly_report(activities_week, week_start, week_end, zones, hr_counts)

    # ── Stream summaries ──────────────────────────────────────────────

    def _activity_best_efforts(self, sport_category: SportCategory, activity_ids: list[int]) -> dict[int, dict[int, float]]:
        """{activity_id: {target_m: best_time_s}} for activities with streams,
        from summaries persisted in the StreamsStore (computed once per activity)."""
        return self.strava_activities_cache.get_stream_summaries(
            summary_name(sport_category), activity_ids, partial(stream_best_efforts, sport_category=sport_category)
        )

    def _activity_heartrate_counts(self, activity_ids: list[int]) -> dict[int, HeartRateCounts | None]:
        """{activity_id: (distinct HR values, samples at each)}, None without HR
        samples, persisted in the StreamsStore (computed once per activity)."""
        return self.strava_activities_cache.get_stream_summaries(
            f"heartrate_counts:v{HEARTRATE_COUNTS_VERSION}", activity_ids, heartrate_counts
        )

    def activity_heart_rate_drift(self, activity_ids: list[int]) -> dict[int, HeartRateDrift]:
        """{activity_id: heart_rate_drift summary} for runs with streams,
        persisted in the StreamsStore (computed once per activity)."""
        return self.strava_activities_cache.get_stream_summaries(
            f"heart_rate_drift:v{DRIFT_VERSION}", activity_ids, heart_rate_drift
        )

    def activity_heart_rate_recovery(self, activity_ids: list[int]) -> dict[int, HeartRateRecovery]:
        """{activity_id: heart_rate_recovery summary} for runs with streams,
        persisted in the StreamsStore (computed once per activity)."""
        return self.strava_activities_cache.get_stream_summaries(
            f"heart_rate_recovery:v{HR_RECOVERY_VERSION}", activity_ids, heart_rate_recovery
        )

    # ── Personal records ──────────────────────────────────────────────

    def get_personal_records(self) -> dict[SportCategory, list[PersonalRecord]]:
        """Fastest best effort at each standard distance for running, cycling
        and swimming: the per-activity sliding-window bests, minimised over
        every activity (the earliest wins a tie)."""
        result: dict[SportCategory, list[PersonalRecord]] = {}
        for category in self.RECORD_SPORTS:
            records = personal_records(self._get_per_activity_bests_df(category), sport_distances(category))
            if records:
                result[category] = records
        return result

    def _get_per_activity_bests_df(self, sport_category: SportCategory) -> pd.DataFrame:
        """The sport's per-activity best efforts (best_efforts.per_activity_bests),
        built from the persisted summaries and cached; windowed queries go
        through _ranked_bests."""
        with self._lock:
            caches = self._caches()
            cached = caches.per_activity_bests.get(sport_category)
            if cached is not None:
                return cached

            activities = self.strava_activities_cache.get_prepared_view()
            if not sport_distances(sport_category) or activities.empty:
                bests = pd.DataFrame(columns=BESTS_COLUMNS)
            else:
                cat_acts = activities[_in_category(activities, sport_category)]
                cat_ids = cat_acts['id'].astype('int64').tolist() if 'id' in cat_acts.columns else []
                efforts_by_id = self._activity_best_efforts(sport_category, cat_ids)
                race_ids = set(cat_acts.loc[self._race_mask(cat_acts), 'id'].tolist())
                bests = per_activity_bests(cat_acts, efforts_by_id, race_ids)
            caches.per_activity_bests[sport_category] = bests
            return bests

    def _ranked_bests(self, sport_category: SportCategory) -> RankedBests:
        with self._lock:
            caches = self._caches()
            cached = caches.ranked_bests.get(sport_category)
            if cached is not None:
                return cached
            ranked = rank_bests(self._get_per_activity_bests_df(sport_category))
            caches.ranked_bests[sport_category] = ranked
            return ranked

    def _recent_best_efforts_list(
        self,
        sport_category: SportCategory,
        within_days: int = 365,
        end_date: datetime | None = None,
        top_k: int = 3,
    ) -> list[BestEffort]:
        """best_efforts.recent_best_efforts of the sport, up to `end_date` (now
        when None)."""
        end = self.clock.now() if end_date is None else end_date
        return recent_best_efforts(self._ranked_bests(sport_category), end, within_days, top_k)

    # ── Race predictions ──────────────────────────────────────────────

    def _compute_race_residuals(self, sport_category: SportCategory) -> list[RaceResidual]:
        """race_predictions.race_residuals of the sport's races (flagged on
        Strava or in race_activity_ids), computed once per sport and cached."""
        caches = self._caches()
        cached = caches.race_residuals.get(sport_category)
        if cached is not None:
            return cached
        residuals: list[RaceResidual] = []
        activities = self.strava_activities_cache.get_prepared_view()
        if sport_distances(sport_category) and not activities.empty:
            races = activities[_in_category(activities, sport_category) & self._race_mask(activities)]
            bests = self._get_per_activity_bests_df(sport_category)
            if not races.empty and not bests.empty:
                residuals = race_residuals(
                    race_results(races, bests, sport_category), self._ranked_bests(sport_category),
                    sport_category, self.get_max_heart_rate() or 0, self.prediction_tuning,
                )
        caches.race_residuals[sport_category] = residuals
        return residuals

    def get_race_predictions(self, sport_category: SportCategory = SportCategory.RUNNING) -> RacePredictions:
        """race_predictions.predict_races for the sport as of now, cached per
        day (the recency weights count from today)."""
        caches = self._caches()
        now = self.clock.now()
        cache_key = (sport_category, now.date())
        if cache_key in caches.race_predictions:
            return caches.race_predictions[cache_key]

        activities = self.strava_activities_cache.get_prepared_view()
        result = predict_races(
            self._ranked_bests(sport_category),
            self._compute_race_residuals(sport_category),
            sport_category,
            now,
            self.get_max_heart_rate() or 0,
            self._garmin_race_predictions() if sport_category == SportCategory.RUNNING else None,
            int(len(activities[_in_category(activities, sport_category)])),
            self.prediction_tuning,
        )
        caches.race_predictions[cache_key] = result
        return result

    def get_race_predictions_history(
        self,
        sport_category: SportCategory = SportCategory.RUNNING,
        weeks: int = 52,
        step_days: int = 7,
        window_days: int = 365,
    ) -> list[PredictionHistoryPoint]:
        """race_predictions.prediction_history for the sport up to now: one
        window query and prediction per step."""
        if not sport_distances(sport_category):
            return []
        return prediction_history(
            self._ranked_bests(sport_category),
            self._compute_race_residuals(sport_category),
            sport_category,
            self.clock.now(),
            self.get_max_heart_rate() or 0,
            weeks,
            step_days,
            window_days,
            self.prediction_tuning,
        )

    # ── Training load ─────────────────────────────────────────────────

    def get_daily_training_load(self, hr_rest: float, hr_zones: list[HrZone] | None = None) -> list[DailyLoad]:
        """Daily TRIMP from all activities (training_load.daily_training_load).

        hr_rest: resting HR (resolved from user settings).
        hr_zones: optional zones override (e.g. resolved from user settings).

        Results are memoized per distinct (resting HR, max HR, zones) key, so
        weekly Relative Effort for every sport reuses one full-cache scan
        instead of recomputing the stream-heavy TRIMP.
        """
        caches = self._caches()
        hr_max = self.get_max_heart_rate()
        if hr_zones is None:
            hr_zones = self._get_hr_zones_cached()

        cache_key = training_load_key(hr_rest, hr_max, hr_zones)
        cached = caches.training_load.get(cache_key)
        if cached is not None:
            return cached

        valid = trimp_activities(self.strava_activities_cache.get_prepared_view())
        hr_counts: dict[int, HeartRateCounts | None] = {}
        if hr_zones and not valid.empty:
            hr_counts = self._activity_heartrate_counts(
                valid['id'].astype('int64').tolist() if 'id' in valid.columns else []
            )
        result = daily_training_load(valid, hr_rest, hr_max, hr_zones, hr_counts)
        caches.training_load[cache_key] = result
        return result

    def get_weekly_relative_effort(
        self,
        hr_rest: float,
        hr_zones: list[HrZone] | None = None,
        sports: tuple[SportCategory, ...] | None = None,
        band_span: int = 6,
        band_k: float = 0.6,
    ) -> WeeklyRelativeEffort:
        """training_load.weekly_relative_effort of `sports` (running and
        swimming when None) over the daily TRIMP."""
        daily = self.get_daily_training_load(hr_zones=hr_zones, hr_rest=hr_rest)
        return weekly_relative_effort(daily, self.RE_SPORTS if sports is None else sports, band_span, band_k)

    def get_fitness_form(self, hr_rest: float, hr_zones: list[HrZone] | None, planned: list[PlannedSession],
                         days: int) -> FitnessForm:
        """training_load.fitness_form over the last `days` and the `planned`
        sessions ahead (date, sport_type, planned_duration_mins,
        planned_distance_km)."""
        daily = self.get_daily_training_load(hr_rest=hr_rest, hr_zones=hr_zones)
        return fitness_form(daily, planned, self.clock.today(), days)
