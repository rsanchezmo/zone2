"""Today's briefing at the top of the calendar: the planned session, how
recovered you are (from Garmin, when connected), and a suggestion weighing them."""
from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from zone2.garmin_cache import GarminDailyStatsCache

# A session aimed at zone 4 or above, or with pace targets or intervals, is hard
HARD_HR_ZONE = 4
LOW_READINESS = ("POOR", "LOW")
HIGH_READINESS = ("HIGH", "PRIME")
STRAINED_HRV = ("LOW", "POOR", "UNBALANCED")
# Form as a share of fitness, on the Analytics form zones
OVERREACHING_FORM_PCT = -30
FRESH_FORM_PCT = 5
STALE_FORM_PCT = 20
# A race this close turns a hard session into a sharpener
RACE_SOON_DAYS = 3


class Day(StrEnum):
    """What today holds, in the order it is decided."""
    RACE = "race"      # a race in the calendar today
    DONE = "done"      # already trained
    REST = "rest"      # only rest planned
    HARD = "hard"
    EASY = "easy"
    FREE = "free"      # nothing planned


class Recovery(StrEnum):
    """How ready you are: Garmin readiness and HRV when available, else form."""
    LOW = "low"            # readiness poor or low, or overreaching form
    STRAINED = "strained"  # readiness fine but HRV unbalanced or low
    OK = "ok"              # moderate readiness, or optimal to neutral form
    GOOD = "good"          # high or prime readiness, or fresh form
    STALE = "stale"        # form past +20%: rested so long that fitness fades
    UNKNOWN = "unknown"    # no Garmin data and no form yet


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


def _upper_first(s: str) -> str:
    """Sentence case that leaves the rest alone (str.capitalize would turn HRV into Hrv)."""
    return s[:1].upper() + s[1:]


def classify(recovery: dict | None, form_pct: float | None) -> Recovery:
    readiness = (recovery or {}).get("readiness") or {}
    level = readiness.get("level")
    hrv_status = ((recovery or {}).get("hrv") or {}).get("status")
    if level in LOW_READINESS:
        return Recovery.LOW
    if hrv_status in STRAINED_HRV:
        return Recovery.STRAINED
    if form_pct is not None and form_pct > STALE_FORM_PCT:
        return Recovery.STALE
    if level in HIGH_READINESS:
        return Recovery.GOOD
    if level is not None:
        return Recovery.OK
    if form_pct is None:
        return Recovery.UNKNOWN
    if form_pct < OVERREACHING_FORM_PCT:
        return Recovery.LOW
    return Recovery.GOOD if form_pct > FRESH_FORM_PCT else Recovery.OK


def day_of(sessions: list[dict], trained_today: bool, race_today: dict | None) -> Day:
    if race_today:
        return Day.RACE
    if trained_today:
        return Day.DONE
    planned = [s for s in sessions if (s.get("sport_type") or "").lower() != "rest"]
    if sessions and not planned:
        return Day.REST
    if any(is_hard(s) for s in planned):
        return Day.HARD
    return Day.EASY if planned else Day.FREE


def suggest(sessions: list[dict], trained_today: bool, recovery: dict | None, form_pct: float | None,
            races: list[dict], today: date) -> dict[str, str]:
    """One line for every day: today's plan (or race) weighed against how
    ready you are. `races` are the upcoming ones (date, name). Tone is
    caution, go, rest or info."""
    race_today = next((r for r in races if r["date"] == today.isoformat()), None)
    day = day_of(sessions, trained_today, race_today)
    state = classify(recovery, form_pct)
    readiness = (recovery or {}).get("readiness") or {}
    hours = (recovery or {}).get("recovery_hours")
    hrv = (((recovery or {}).get("hrv") or {}).get("status") or "").lower()
    pct = f"{round(form_pct):+d}%" if form_pct is not None else ""
    # The reason you're low, in Garmin's terms when it has them
    why_low = (f"readiness is {readiness['level'].lower()} ({readiness['score']})" if readiness.get("level")
               else f"form is {pct} (overreaching)")
    recovery_left = f" Recovery needs about {hours} h." if hours else ""

    if day is Day.RACE:
        if state in (Recovery.LOW, Recovery.STRAINED):
            reason = why_low if state is Recovery.LOW else f"HRV is {hrv}"
            return {"tone": "caution", "text": f"Race day: {race_today['name']}. {_upper_first(reason)}, "
                                               "so start conservatively and build into it."}
        return {"tone": "go", "text": f"Race day: {race_today['name']}. Trust the training and enjoy it."}

    if day is Day.DONE:
        if state is Recovery.LOW:
            return {"tone": "caution", "text": f"Done for today, on top of a lot of fatigue.{recovery_left} "
                                               "Make tomorrow easy."}
        if state is Recovery.STRAINED:
            return {"tone": "info", "text": f"Done for today. HRV is {hrv}: an easy day tomorrow would help it settle."}
        return {"tone": "info", "text": f"Done for today.{recovery_left}"}

    if day is Day.REST:
        if state in (Recovery.LOW, Recovery.STRAINED):
            reason = why_low if state is Recovery.LOW else f"HRV is {hrv}"
            return {"tone": "rest", "text": f"Rest day, and a needed one: {reason}.{recovery_left}"}
        if state in (Recovery.GOOD, Recovery.STALE):
            return {"tone": "rest", "text": "Rest day. You're fresh, so a walk or some mobility work fits."}
        return {"tone": "rest", "text": "Rest day."}

    next_race = next((r for r in races if r["date"] > today.isoformat()), None)
    days_to_race = (date.fromisoformat(next_race["date"]) - today).days if next_race else None

    if day is Day.HARD:
        if state is Recovery.LOW:
            return {"tone": "caution", "text": f"{_upper_first(why_low)} and today's session is hard. "
                                               "Consider an easy run instead, or move it to a fresher day."}
        if days_to_race is not None and days_to_race <= RACE_SOON_DAYS:
            when = "tomorrow" if days_to_race == 1 else f"in {days_to_race} days"
            return {"tone": "caution", "text": f"{next_race['name']} is {when}: keep today's session short and sharp, "
                                               "or swap it for an easy run."}
        if state is Recovery.STRAINED:
            return {"tone": "caution", "text": f"HRV is {hrv} and today's session is hard. Ease off if it feels heavy."}
        if state is Recovery.OK:
            how = (f"Readiness is {readiness['level'].lower()} ({readiness['score']})" if readiness.get("level")
                   else f"Form is {pct}")
            return {"tone": "info", "text": f"{how}: the session is on. Hold back if the first reps feel off."}
        if state is Recovery.GOOD:
            how = (f"Readiness is {readiness['level'].lower()} ({readiness['score']})" if readiness.get("level")
                   else f"You're fresh ({pct})")
            return {"tone": "go", "text": f"{how}: a good day for this session."}
        if state is Recovery.STALE:
            return {"tone": "go", "text": f"You're well rested (form {pct}): a good day for this session."}
        return {"tone": "info", "text": "Hard session today: warm up well and let the first rep tell you how the legs are."}

    if day is Day.EASY:
        if state is Recovery.LOW:
            return {"tone": "caution", "text": "Keep it easy today: "
                                               + (f"recovery needs about {hours} h more." if hours else "you're carrying a lot of fatigue.")}
        if state is Recovery.STRAINED:
            return {"tone": "caution", "text": f"HRV is {hrv}: keep today truly easy."}
        if state is Recovery.GOOD:
            return {"tone": "info", "text": "Fresh legs: enjoy the easy session and save the effort for the next hard day."}
        if state is Recovery.STALE:
            return {"tone": "info", "text": f"You're well rested (form {pct}): the easy session can go a little longer."}
        return {"tone": "info", "text": "Easy session: keep it conversational."}

    if state in (Recovery.LOW, Recovery.STRAINED):
        reason = why_low if state is Recovery.LOW else f"HRV is {hrv}"
        return {"tone": "rest", "text": f"Nothing planned, which suits today: {reason}.{recovery_left}"}
    if state is Recovery.GOOD:
        return {"tone": "info", "text": "Fresh and nothing planned: a good day for a quality session."}
    if state is Recovery.STALE:
        return {"tone": "info", "text": f"Fitness is fading after a quiet spell (form {pct}): a session today would help."}
    if state is Recovery.OK:
        return {"tone": "info", "text": "Nothing planned: an easy run or a rest day both work."}
    return {"tone": "info", "text": "Nothing planned today."}
