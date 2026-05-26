"""Garmin Connect watch-stats router.

Strava remains the source of truth for activities; this router exposes the
daily wellness signals Strava doesn't carry (sleep, HRV, training readiness,
body battery, etc.).

Endpoints
---------
- GET  /status             — enabled flag, sync state, cache coverage
- POST /sync?full=false    — background task; default refreshes last 14 days,
                             full=true walks history backwards until empty
- GET  /daily-stats        — raw cached payloads for one metric over a window
- GET  /trends?days=30     — pre-shaped numeric series for charts (one call)
- GET  /latest             — most-recent cached payload per metric (stat cards)
"""

from __future__ import annotations

import logging
from datetime import date as date_t, datetime, timedelta
from threading import Lock
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence

logger = logging.getLogger(__name__)
router = APIRouter()

# Independent from Strava's sync lock — both can run concurrently.
_garmin_sync_status = {"running": False, "last_error": None, "last_summary": None}
_garmin_sync_lock = Lock()


def _try_claim() -> bool:
    with _garmin_sync_lock:
        if _garmin_sync_status["running"]:
            return False
        _garmin_sync_status["running"] = True
        _garmin_sync_status["last_error"] = None
        return True


def _release(error: str | None, summary: dict | None = None) -> None:
    with _garmin_sync_lock:
        _garmin_sync_status["running"] = False
        _garmin_sync_status["last_error"] = error
        if summary is not None:
            _garmin_sync_status["last_summary"] = summary


def _run_garmin_sync(si: StravaIntelligence, full: bool) -> None:
    err: str | None = None
    summary: dict | None = None
    try:
        if full:
            summary = si.garmin_cache.sync_full()
        else:
            rows = si.garmin_cache.sync_recent(days=14)
            summary = {"rows_written": rows}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.exception("Garmin sync failed")
    finally:
        _release(err, summary)


# ---------------------------------------------------------------------- /status


@router.get("/status")
def status(si: StravaIntelligence = Depends(get_si)) -> dict[str, Any]:
    coverage = si.garmin_cache.status()
    with _garmin_sync_lock:
        syncing = _garmin_sync_status["running"]
        last_error = _garmin_sync_status["last_error"]
        last_summary = _garmin_sync_status["last_summary"]
    return {
        "enabled": si.garmin_client.enabled,
        "client_error": si.garmin_client.last_error,
        "syncing": syncing,
        "last_error": last_error,
        "last_summary": last_summary,
        **coverage,
    }


# ---------------------------------------------------------------------- /sync


@router.post("/sync")
def trigger_sync(
    background_tasks: BackgroundTasks,
    full: bool = Query(default=False),
    si: StravaIntelligence = Depends(get_si),
):
    if not si.garmin_client.enabled and not si.garmin_client.ensure_logged_in():
        raise HTTPException(
            status_code=503,
            detail=si.garmin_client.last_error or "Garmin client not configured",
        )
    if not _try_claim():
        return {"status": "already_running"}
    background_tasks.add_task(_run_garmin_sync, si, full)
    return {"status": "started", "full": full}


# ---------------------------------------------------------------------- /daily-stats


@router.get("/daily-stats")
def daily_stats(
    metric: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    si: StravaIntelligence = Depends(get_si),
) -> dict[str, Any]:
    return {
        "metric": metric,
        "start_date": start_date,
        "end_date": end_date,
        "rows": si.garmin_cache.get_range(metric, start_date, end_date),
    }


# ---------------------------------------------------------------------- /latest


@router.get("/latest")
def latest(si: StravaIntelligence = Depends(get_si)) -> dict[str, Any]:
    """Most-recent cached payload per metric — feeds the stat-card row."""
    out: dict[str, Any] = {}
    for metric in si.garmin_client.ALL_METRICS:
        out[metric] = si.garmin_cache.get_latest(metric)
    return out


# ---------------------------------------------------------------------- /trends


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


def _first_device_value(nested: Any) -> dict | None:
    """Garmin nests per-device data under {deviceId: {...}}. We don't care
    which watch — take the first entry."""
    if isinstance(nested, dict) and nested:
        for v in nested.values():
            if isinstance(v, dict):
                return v
    return None


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


_EXTRACTORS: dict[str, callable] = {
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


@router.get("/trends")
def trends(
    days: int = Query(default=30, ge=1, le=365),
    si: StravaIntelligence = Depends(get_si),
) -> dict[str, Any]:
    """Pre-shaped per-day numeric series across all metrics. One call powers
    every chart on the Garmin page."""
    end = date_t.today()
    start = end - timedelta(days=days - 1)
    s_iso, e_iso = start.isoformat(), end.isoformat()

    # date axis (string) — frontend just plots whatever's present
    out: dict[str, Any] = {
        "start_date": s_iso,
        "end_date": e_iso,
        "days": days,
        "metrics": {},
    }
    for metric, extractor in _EXTRACTORS.items():
        rows = si.garmin_cache.get_range(metric, s_iso, e_iso)
        out["metrics"][metric] = [
            {"date": r["date"], **extractor(r["payload"])} for r in rows
        ]
    return out
