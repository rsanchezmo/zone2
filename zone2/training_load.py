"""Training load from heart rate: TRIMP per activity and per day, weekly
Relative Effort against its expected range, and fitness, fatigue and form."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from statistics import median
from typing import Literal, NotRequired, TypedDict

import numpy as np
import pandas as pd

from zone2.utils import (
    SportCategory, compute_trimp_banister, compute_trimp_zone_weighted, get_sport_category, hr_zone_counts,
)

# Bump whenever heartrate_counts changes: it names the persisted summaries.
HEARTRATE_COUNTS_VERSION = 1

# Cosmetic multiplier so weekly Relative Effort reads in a Strava-like
# range. The band is derived from the same scaled series, so status
# (below / in / above range) is invariant to this constant.
RE_DISPLAY_SCALE = 1.4
RE_SPORTS: tuple[SportCategory, ...] = (SportCategory.RUNNING, SportCategory.SWIMMING)

# Exponentially weighted daily load over the Banister model's classic spans
FITNESS_DAYS = 42
FATIGUE_DAYS = 7
# Planned sessions are costed from this much of your own recent training
PLAN_HISTORY_DAYS = 180

# (distinct HR values, samples at each)
HeartRateCounts = tuple[np.ndarray, np.ndarray]
TrimpMethod = Literal["banister", "zone_weighted"]
RelativeEffortStatus = Literal["below", "in_range", "above"]
# Resting HR, max HR and the zones' bounds
TrainingLoadKey = tuple[float, float, tuple[tuple[int | None, int | None], ...]]


class HrZone(TypedDict):
    min: int
    max: int


class ActivityLoad(TypedDict):
    name: str
    sport_type: str
    trimp: float
    trimp_method: TrimpMethod
    minutes: float
    km: float


class DailyLoad(TypedDict):
    date: str
    trimp: float
    activities: list[ActivityLoad]
    # The method of the day's first activity
    trimp_method: TrimpMethod


class RelativeEffortWeek(TypedDict):
    week_start: str
    relative_effort: float
    band_low: float
    band_high: float
    status: RelativeEffortStatus


class WeeklyRelativeEffort(TypedDict):
    weeks: list[RelativeEffortWeek]
    scale: float
    sports: list[SportCategory]


class PlannedSession(TypedDict):
    date: str
    sport_type: str | None
    planned_duration_mins: float | None
    planned_distance_km: float | None


class FitnessDay(TypedDict):
    date: str
    load: float
    fitness: float
    fatigue: float
    form: float
    # Form as a share of fitness, None before there is any fitness
    form_pct: float | None
    projected: bool


class FitnessForm(TypedDict):
    series: list[FitnessDay]
    fitness_days: NotRequired[int]
    fatigue_days: NotRequired[int]


def heartrate_counts(streams: dict) -> HeartRateCounts | None:
    """One activity's HR samples as distinct values and their counts, None
    without any. Time in any zones follows from these without the streams."""
    hr_col = streams.get("heartrate")
    if not hr_col:
        return None
    values = np.asarray([v for v in hr_col if v is not None], dtype=np.float64)
    if not len(values):
        return None
    return np.unique(values, return_counts=True)


def training_load_key(hr_rest: float, hr_max: float, hr_zones: list[HrZone] | None) -> TrainingLoadKey:
    return (
        round(float(hr_rest), 1),
        round(float(hr_max), 1),
        tuple((z.get('min'), z.get('max')) for z in (hr_zones or [])),
    )


def trimp_activities(activities: pd.DataFrame) -> pd.DataFrame:
    """The activities a TRIMP can be computed for: with an average HR and a
    moving time."""
    if activities.empty:
        return activities
    mt = activities['moving_time'] if 'moving_time' in activities.columns else pd.Series(dtype=float)
    hr = activities['average_heartrate'] if 'average_heartrate' in activities.columns else pd.Series(dtype=float)
    mask = hr.notna() & (hr > 0) & mt.notna() & (mt > 0)
    return activities[mask]


def daily_training_load(
    activities: pd.DataFrame,
    hr_rest: float,
    hr_max: float,
    hr_zones: list[HrZone] | None,
    hr_counts: dict[int, HeartRateCounts | None],
) -> list[DailyLoad]:
    """TRIMP per day of `activities` (trimp_activities' rows), oldest first.
    An activity with more than 10 HR samples in `hr_counts` is zone-weighted
    (each sample an equal share of its moving time); the rest, and every
    activity without `hr_zones`, are Banister from the average HR."""
    if activities.empty:
        return []

    duration_min_arr = activities['moving_time'].to_numpy(dtype=np.float64) / 60.0
    banister = compute_trimp_banister(duration_min_arr, activities['average_heartrate'].to_numpy(dtype=np.float64),
                                      hr_rest, hr_max)

    trimps = banister.copy()
    methods = np.full(len(activities), 'banister', dtype=object)

    if hr_zones:
        id_list = activities['id'].astype('int64').tolist() if 'id' in activities.columns else []
        for idx, activity_id in enumerate(id_list):
            counts = hr_counts.get(activity_id)
            if counts is None:
                continue
            hr_values, hr_weights = counts
            n_samples = int(hr_weights.sum())
            if n_samples <= 10:
                continue
            in_zone = hr_zone_counts(hr_values, hr_zones, hr_weights)
            time_per_pt = duration_min_arr[idx] / n_samples
            time_in_zones = [float(in_zone[i]) * time_per_pt for i in range(5)]
            zw = compute_trimp_zone_weighted(time_in_zones)
            if zw > 0:
                trimps[idx] = zw
                methods[idx] = 'zone_weighted'

    trimps_rounded = np.round(trimps, 1)
    date_strs = activities['start_date_local'].dt.strftime('%Y-%m-%d').to_numpy()
    blank = pd.Series([''] * len(activities), index=activities.index)
    names = activities.get('name', blank).fillna('').to_numpy()
    sports = activities.get('sport_type', blank).fillna('').to_numpy()
    km_arr = activities.get('distance', pd.Series(0.0, index=activities.index)).fillna(0.0).to_numpy(
        dtype=np.float64) / 1000.0

    daily: dict[str, DailyLoad] = {}
    for date_str, trimp, method, name, sport, minutes, km in zip(
            date_strs, trimps_rounded, methods, names, sports, duration_min_arr, km_arr):
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
            "minutes": float(minutes),
            "km": float(km),
        })

    return sorted(daily.values(), key=lambda d: d["date"])


def weekly_relative_effort(
    daily: list[DailyLoad],
    sports: tuple[SportCategory, ...],
    band_span: int,
    band_k: float,
) -> WeeklyRelativeEffort:
    """Weekly Relative Effort of `sports` with a personalized expected-range
    band: the activities' TRIMP summed per ISO week and scaled by
    RE_DISPLAY_SCALE, the band EWMA ± band_k·rolling-std over `band_span`
    weeks. Weeks without activities count 0, so rest weeks read as dips."""
    rows = [
        (day["date"], act["trimp"])
        for day in daily
        for act in day["activities"]
        if get_sport_category(act["sport_type"]) in sports
    ]
    if not rows:
        return {"weeks": [], "scale": RE_DISPLAY_SCALE, "sports": list(sports)}

    df = pd.DataFrame(rows, columns=["date", "trimp"])
    df["date"] = pd.to_datetime(df["date"])
    # Monday-anchored weeks: the start_time of a Sunday-ending period is Monday.
    df["week"] = df["date"].dt.to_period("W-SUN").dt.start_time
    weekly = df.groupby("week")["trimp"].sum() * RE_DISPLAY_SCALE
    full_idx = pd.date_range(weekly.index.min(), weekly.index.max(), freq="W-MON")
    weekly = weekly.reindex(full_idx, fill_value=0.0)

    center = weekly.ewm(span=band_span).mean()
    std = weekly.rolling(band_span, min_periods=2).std().fillna(0.0)
    band_low = (center - band_k * std).clip(lower=0.0)
    band_high = center + band_k * std

    weeks: list[RelativeEffortWeek] = [
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
    return {"weeks": weeks, "scale": RE_DISPLAY_SCALE, "sports": list(sports)}


def fitness_form(daily: list[DailyLoad], planned: list[PlannedSession], today: date, days: int) -> FitnessForm:
    """Fitness (42-day load average), fatigue (7-day) and form (their
    difference) per day over the last `days` before `today`, from the daily
    TRIMP, then continued over `planned` sessions as a projection. TRIMP
    isn't on the TSS scale the usual absolute form zones assume, so form is
    also given as a share of fitness, which doesn't depend on the scale."""
    if not daily:
        return {"series": []}
    loads = {d["date"]: d["trimp"] for d in daily}
    cost = planned_load_estimator(daily, today)
    planned_load: dict[str, float] = {}
    for session in planned:
        if session["date"] >= today.isoformat():
            planned_load[session["date"]] = planned_load.get(session["date"], 0.0) + cost(session)

    end = max([today, *(date.fromisoformat(d) for d in planned_load)])
    window_start = today - timedelta(days=days)
    fitness = fatigue = 0.0
    series: list[FitnessDay] = []
    for day in pd.date_range(daily[0]["date"], end, freq="D").date:
        key = day.isoformat()
        # Today stays actual once an activity is logged; until then the plan stands in
        projected = day > today or (day == today and key not in loads)
        load = planned_load.get(key, 0.0) if projected else loads.get(key, 0.0)
        fitness += (load - fitness) / FITNESS_DAYS
        fatigue += (load - fatigue) / FATIGUE_DAYS
        if day >= window_start:
            form = fitness - fatigue
            series.append({
                "date": key,
                "load": round(load, 1),
                "fitness": round(fitness, 1),
                "fatigue": round(fatigue, 1),
                "form": round(form, 1),
                "form_pct": round(100 * form / fitness, 1) if fitness > 0 else None,
                "projected": projected,
            })
    return {"series": series, "fitness_days": FITNESS_DAYS, "fatigue_days": FATIGUE_DAYS}


def planned_load_estimator(daily: list[DailyLoad], today: date) -> Callable[[PlannedSession], float]:
    """Load of a planned session, from your own sessions of the last
    PLAN_HISTORY_DAYS: its minutes (planned, or planned km at your usual
    pace) times your load per minute for that sport, or your typical
    session of that sport when the plan gives neither. Sports with too
    little history fall back to all sports."""
    since = (today - timedelta(days=PLAN_HISTORY_DAYS)).isoformat()
    samples: dict[str, list[ActivityLoad]] = {}
    everything: list[ActivityLoad] = []
    for d in daily:
        if d["date"] >= since:
            for a in d["activities"]:
                samples.setdefault(a["sport_type"], []).append(a)
                everything.append(a)

    def rates(acts: list[ActivityLoad]) -> tuple[float | None, float | None, float]:
        per_min = [a["trimp"] / a["minutes"] for a in acts if a["minutes"] > 0]
        min_per_km = [a["minutes"] / a["km"] for a in acts if a["km"] > 0.5]
        return (median(per_min) if per_min else None, median(min_per_km) if min_per_km else None,
                median([a["trimp"] for a in acts]) if acts else 0.0)

    overall = rates(everything)
    by_sport = {sport: rates(acts) for sport, acts in samples.items() if len(acts) >= 3}

    def cost(session: PlannedSession) -> float:
        sport = session.get("sport_type") or ""
        if sport.lower() == "rest":
            return 0.0
        per_min, min_per_km, typical = by_sport.get(sport, overall)
        minutes = session.get("planned_duration_mins")
        if not minutes and session.get("planned_distance_km") and min_per_km:
            minutes = session["planned_distance_km"] * min_per_km
        return float(minutes * per_min) if minutes and per_min else float(typical)
    return cost
