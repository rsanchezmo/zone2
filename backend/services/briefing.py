"""Today's briefing at the top of the calendar: the planned session, how
recovered you are (from Garmin, when connected), and a suggestion weighing them."""
from __future__ import annotations

from datetime import date
from typing import Any

from zone2.garmin_cache import GarminDailyStatsCache

# A session aimed at zone 4 or above, or with pace targets or intervals, is hard
HARD_HR_ZONE = 4
LOW_READINESS = ("POOR", "LOW")
HIGH_READINESS = ("HIGH", "PRIME")
STRAINED_HRV = ("LOW", "POOR", "UNBALANCED")
# Form below this share of fitness is overreaching (see the Analytics form zones)
OVERREACHING_FORM_PCT = -30
FRESH_FORM_PCT = 5


def recovery_today(cache: GarminDailyStatsCache, today: date) -> dict[str, Any] | None:
    """Last night's recovery from the stored Garmin day: wake-up readiness
    (or the latest snapshot until the wake-up one exists), sleep, HRV, body
    battery and resting HR. None when nothing is stored for today."""
    readiness_day = cache.get(today, "training_readiness") or {}
    readiness = readiness_day.get("wakeup") or readiness_day
    sleep = (cache.get(today, "sleep") or {}).get("dailySleepDTO") or {}
    hrv = (cache.get(today, "hrv") or {}).get("hrvSummary") or {}
    summary = cache.get(today, "user_summary") or {}
    if not (readiness or sleep or hrv or summary):
        return None
    sleep_score = ((sleep.get("sleepScores") or {}).get("overall") or {})
    recovery_min = readiness.get("recoveryTime")
    return {
        "readiness": {
            "score": readiness.get("score"),
            "level": readiness.get("level"),
            "feedback": readiness.get("feedbackShort"),
            "at_wakeup": readiness.get("inputContext") == "AFTER_WAKEUP_RESET",
            "time": readiness.get("timestampLocal"),
        } if readiness.get("score") is not None else None,
        "recovery_hours": round(recovery_min / 60) if recovery_min else None,
        "sleep": {
            "score": sleep_score.get("value"),
            "qualifier": sleep_score.get("qualifierKey"),
            "seconds": sleep.get("sleepTimeSeconds"),
        } if sleep_score.get("value") is not None else None,
        "hrv": {
            "last_night": hrv.get("lastNightAvg"),
            "weekly": hrv.get("weeklyAvg"),
            "status": hrv.get("status"),
        } if hrv.get("lastNightAvg") is not None else None,
        "body_battery": {
            "at_wake": summary.get("bodyBatteryAtWakeTime"),
            "now": summary.get("bodyBatteryMostRecentValue"),
        } if summary.get("bodyBatteryAtWakeTime") is not None else None,
        "resting_hr": {
            "today": summary.get("restingHeartRate"),
            "avg_7d": summary.get("lastSevenDaysAvgRestingHeartRate"),
        } if summary.get("restingHeartRate") is not None else None,
    }


def is_hard(session: dict[str, Any]) -> bool:
    """Pace targets, a high HR zone, or repeated work segments."""
    if any(session.get(k) for k in ("target_avg_pace", "target_pace_min", "target_pace_max")):
        return True
    if (session.get("target_hr_zone") or 0) >= HARD_HR_ZONE:
        return True
    for seg in session.get("segments") or []:
        if seg.get("type") != "work":
            continue
        if (seg.get("repetitions") or 1) > 1 or seg.get("target_pace_min") or seg.get("target_pace_max"):
            return True
        if (seg.get("target_hr_zone") or 0) >= HARD_HR_ZONE:
            return True
    return False


def suggest(sessions: list[dict], trained_today: bool, recovery: dict | None,
            form_pct: float | None) -> dict[str, str] | None:
    """One line weighing today's plan against recovery, or None when there's
    nothing worth saying. Tone is caution, go, rest or info."""
    if trained_today:
        return None
    readiness = (recovery or {}).get("readiness") or {}
    level = readiness.get("level")
    score = readiness.get("score")
    hrv_status = ((recovery or {}).get("hrv") or {}).get("status")
    hours = (recovery or {}).get("recovery_hours")
    planned = [s for s in sessions if (s.get("sport_type") or "").lower() != "rest"]

    if sessions and not planned:
        return {"tone": "rest", "text": f"Rest day. Garmin puts recovery at {hours} h." if hours else "Rest day."}
    if any(is_hard(s) for s in planned):
        if level in LOW_READINESS:
            return {"tone": "caution", "text": f"Readiness is {level.lower()} ({score}) and today's session is hard. "
                                               "Consider an easy run instead, or move it to a fresher day."}
        if hrv_status in STRAINED_HRV:
            return {"tone": "caution", "text": f"HRV is {hrv_status.lower()} and today's session is hard. Ease off if it feels heavy."}
        if level is None and form_pct is not None and form_pct < OVERREACHING_FORM_PCT:
            return {"tone": "caution", "text": f"Form is {round(form_pct)}%, deep in overreaching, and today's session is hard. "
                                               "Consider an easy day."}
        if level in HIGH_READINESS:
            return {"tone": "go", "text": f"Readiness is {level.lower()}: a good day for this session."}
        return None
    if planned:
        if level in LOW_READINESS and hours and hours >= 24:
            return {"tone": "caution", "text": f"Keep it easy today: recovery needs about {hours} h more."}
        return None
    if level in HIGH_READINESS and form_pct is not None and form_pct > FRESH_FORM_PCT:
        return {"tone": "info", "text": "Fresh and nothing planned: a good day for a quality session."}
    if level in LOW_READINESS or (level is None and form_pct is not None and form_pct < OVERREACHING_FORM_PCT):
        reason = f"readiness is {level.lower()}" if level else f"form is {round(form_pct)}%"
        return {"tone": "rest", "text": f"Nothing planned, which suits today: {reason}"
                                        + (f" and recovery needs about {hours} h." if hours else ".")}
    return None
