"""Slim projections of Garmin daily payloads — the handful of scalar fields the
trends charts actually plot, pulled out of the fat raw payloads.

These run at *sync time* (see GarminDailyStatsCache.upsert_many) so the trends
endpoint reads a few hundred bytes per day from `garmin_daily_summary` instead
of deserializing the full payloads (a year of `sleep` alone is ~95MB of JSON).
Keeping them here, not in the router, lets the cache writer and the API share
one definition.

When a projection changes, bump nothing — just rebuild the summary table
(GarminDailyStatsCache.backfill_missing_summaries re-derives missing rows; a
full rebuild means clearing the table first).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_get(d: Any, *path, default=None):
    """Walk a nested dict/list following path keys, returning default on miss."""
    cur = d
    for k in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int) and -len(cur) <= k < len(cur):
            cur = cur[k]
        else:
            return default
    return cur if cur is not None else default


def _first_device_value(nested: Any) -> dict | None:
    """Garmin nests per-device data under {deviceId: {...}}. We don't care
    which watch — take the first entry."""
    if isinstance(nested, dict) and nested:
        for v in nested.values():
            if isinstance(v, dict):
                return v
    return None


def _extract_sleep(p: dict) -> dict[str, Any]:
    dto = p.get("dailySleepDTO") or {}
    overall = (dto.get("sleepScores") or {}).get("overall") or {}
    return {
        "score": overall.get("value"),
        "qualifier": overall.get("qualifierKey"),
        "total_seconds": dto.get("sleepTimeSeconds"),
        "deep_seconds": dto.get("deepSleepSeconds"),
        "rem_seconds": dto.get("remSleepSeconds"),
        "light_seconds": dto.get("lightSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "avg_hr": dto.get("avgHeartRate"),
        "avg_stress": dto.get("avgSleepStress"),
        "avg_spo2": dto.get("averageSpO2Value"),
        "avg_respiration": dto.get("averageRespirationValue"),
    }


def _extract_hrv(p: dict) -> dict[str, Any]:
    s = p.get("hrvSummary") or {}
    return {
        "last_night_avg": s.get("lastNightAvg"),
        "weekly_avg": s.get("weeklyAvg"),
        "last_night_5min_high": s.get("lastNight5MinHigh"),
        "status": s.get("status"),
        "feedback_phrase": s.get("feedbackPhrase"),
    }


def _extract_training_readiness(p: dict) -> dict[str, Any]:
    return {
        "score": p.get("score"),
        "level": p.get("level"),
        "sleep_score": p.get("sleepScore"),
        "recovery_time_min": p.get("recoveryTime"),
        "acwr_percent": p.get("acwrFactorPercent"),
        "hrv_factor_percent": p.get("hrvFactorPercent"),
        "stress_history_percent": p.get("stressHistoryFactorPercent"),
        "sleep_history_percent": p.get("sleepHistoryFactorPercent"),
        "feedback_short": p.get("feedbackShort"),
    }


def _extract_heart_rates(p: dict) -> dict[str, Any]:
    return {
        "resting": p.get("restingHeartRate"),
        "min": p.get("minHeartRate"),
        "max": p.get("maxHeartRate"),
        "last_7d_avg_resting": p.get("lastSevenDaysAvgRestingHeartRate"),
    }


def _extract_stress(p: dict) -> dict[str, Any]:
    return {
        "avg": p.get("avgStressLevel"),
        "max": p.get("maxStressLevel"),
    }


def _extract_body_battery(p: dict) -> dict[str, Any]:
    return {
        "charged": p.get("charged"),
        "drained": p.get("drained"),
        # endOfDay value lives in feedback event if present
        "end_of_day": _safe_get(p, "endOfDayBodyBatteryDynamicFeedbackEvent", "endOfDayBodyBattery"),
    }


def _extract_daily_steps(p: dict) -> dict[str, Any]:
    return {
        "total_steps": p.get("totalSteps"),
        "step_goal": p.get("stepGoal"),
        "total_distance_m": p.get("totalDistance"),
    }


def _extract_intensity_minutes(p: dict) -> dict[str, Any]:
    return {
        "moderate": p.get("moderateMinutes"),
        "vigorous": p.get("vigorousMinutes"),
        "weekly_goal": p.get("weeklyGoal"),
    }


def _extract_user_summary(p: dict) -> dict[str, Any]:
    return {
        "active_kcal": p.get("activeKilocalories"),
        "bmr_kcal": p.get("bmrKilocalories"),
        "total_kcal": p.get("totalKilocalories"),
        "avg_stress": p.get("averageStressLevel"),
        "avg_spo2": p.get("averageSpo2"),
        "avg_respiration": p.get("avgWakingRespirationValue"),
        "floors_climbed": p.get("floorsAscended"),
    }


def _extract_training_status(p: dict) -> dict[str, Any]:
    vo2 = _safe_get(p, "mostRecentVO2Max", "generic") or {}
    load_dev = _first_device_value(_safe_get(p, "mostRecentTrainingLoadBalance",
                                             "metricsTrainingLoadBalanceDTOMap"))
    status_dev = _first_device_value(_safe_get(p, "mostRecentTrainingStatus",
                                               "latestTrainingStatusData"))
    acute = (status_dev or {}).get("acuteTrainingLoadDTO") or {}
    return {
        "vo2max": vo2.get("vo2MaxPreciseValue") or vo2.get("vo2MaxValue"),
        "vo2max_date": vo2.get("calendarDate"),
        "fitness_age": vo2.get("fitnessAge"),
        # Training status (PRODUCTIVE / MAINTAINING / RECOVERY / PEAKING / …)
        "status_phrase": (status_dev or {}).get("trainingStatusFeedbackPhrase"),
        "sport": (status_dev or {}).get("sport"),
        # ACWR (acute-chronic workload ratio): the headline overtraining signal
        "acwr_ratio": acute.get("dailyAcuteChronicWorkloadRatio"),
        "acwr_status": acute.get("acwrStatus"),
        "daily_load_acute": acute.get("dailyTrainingLoadAcute"),
        "daily_load_chronic": acute.get("dailyTrainingLoadChronic"),
        # Monthly training-load balance (per intensity bucket vs personal target)
        "load_aerobic_low": (load_dev or {}).get("monthlyLoadAerobicLow"),
        "load_aerobic_high": (load_dev or {}).get("monthlyLoadAerobicHigh"),
        "load_anaerobic": (load_dev or {}).get("monthlyLoadAnaerobic"),
        "load_aerobic_low_target": [
            (load_dev or {}).get("monthlyLoadAerobicLowTargetMin"),
            (load_dev or {}).get("monthlyLoadAerobicLowTargetMax"),
        ],
        "load_aerobic_high_target": [
            (load_dev or {}).get("monthlyLoadAerobicHighTargetMin"),
            (load_dev or {}).get("monthlyLoadAerobicHighTargetMax"),
        ],
        "load_anaerobic_target": [
            (load_dev or {}).get("monthlyLoadAnaerobicTargetMin"),
            (load_dev or {}).get("monthlyLoadAnaerobicTargetMax"),
        ],
        "load_balance_phrase": (load_dev or {}).get("trainingBalanceFeedbackPhrase"),
    }


def _extract_spo2(p: dict) -> dict[str, Any]:
    return {
        "avg": p.get("averageSpO2"),
        "lowest": p.get("lowestSpO2"),
        "last_7d_avg": p.get("lastSevenDaysAvgSpO2"),
        "avg_sleep": p.get("avgSleepSpO2"),
    }


def _extract_respiration(p: dict) -> dict[str, Any]:
    return {
        "avg_waking": p.get("avgWakingRespirationValue"),
        "avg_sleep": p.get("avgSleepRespirationValue"),
        "lowest": p.get("lowestRespirationValue"),
        "highest": p.get("highestRespirationValue"),
    }


# metric -> projection. The keys here are exactly the metrics the trends charts
# read; metrics absent from this map (e.g. body_composition) get no summary.
EXTRACTORS: dict[str, Any] = {
    "sleep": _extract_sleep,
    "hrv": _extract_hrv,
    "training_readiness": _extract_training_readiness,
    "training_status": _extract_training_status,
    "heart_rates": _extract_heart_rates,
    "stress": _extract_stress,
    "body_battery": _extract_body_battery,
    "daily_steps": _extract_daily_steps,
    "intensity_minutes": _extract_intensity_minutes,
    "user_summary": _extract_user_summary,
    "spo2": _extract_spo2,
    "respiration": _extract_respiration,
}

# Iteration order used by the trends endpoint and the summary writer.
SUMMARY_METRICS: tuple[str, ...] = tuple(EXTRACTORS)


def extract(metric: str, payload: Any) -> dict[str, Any] | None:
    """Project a raw payload to its slim chart summary. Returns None for metrics
    with no extractor, a null payload, or a payload whose shape the extractor
    can't handle (logged, never raised — a bad day shouldn't break a sync)."""
    fn = EXTRACTORS.get(metric)
    if fn is None or payload is None:
        return None
    try:
        return fn(payload)
    except Exception as e:
        logger.warning("Garmin summary extract failed for %s: %s: %s",
                       metric, type(e).__name__, e)
        return None


def is_finalized(metric: str, payload: Any) -> bool:
    """Has a stable overnight metric (sleep/hrv) been scored for the night yet?

    The morning auto-sync can fetch sleep/hrv before Garmin finishes processing
    the night and persist an empty placeholder — sleep with no `sleepScores`,
    hrv with no `hrvSummary`. Stable metrics are normally never re-fetched once
    cached (GarminClient.STABLE_METRICS), so without this check that placeholder
    sticks for good and the score never arrives. sync_day uses this to re-fetch a
    present-but-unscored placeholder on a later same-day sync, then leaves it
    alone once finalized. Non-stable metrics accumulate through the day rather
    than landing as one nightly result, so they're always considered finalized."""
    if metric == "sleep":
        dto = (payload or {}).get("dailySleepDTO") or {}
        return ((dto.get("sleepScores") or {}).get("overall") or {}).get("value") is not None
    if metric == "hrv":
        # A scored night always carries an hrvSummary object (some sub-values may
        # be null on a genuine no-reading night); an early placeholder has none.
        return bool((payload or {}).get("hrvSummary"))
    return True
