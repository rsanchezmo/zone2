"""The agent's tools over z2's services. Reads return compact shapes, since every
field costs tokens; writes need the user's approval before they run."""

import asyncio
import calendar
import datetime
import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, Any, Literal

import aiosqlite
import pandas as pd
from pydantic import BaseModel, Field
from pydantic.json_schema import JsonSchemaValue
from pydantic_ai import FunctionToolset, ModelRetry, RunContext
from pydantic_ai.tools import GenerateToolJsonSchema
from pydantic_core import core_schema

from backend.agent import notes
from backend.errors import NotFound, ServiceError
from backend.services import activities as activity_service, coach_log, garmin_workouts, plans, session_scores
from backend.services import day_timeline, workout_library
from backend.services import gear as gear_service
from backend.services import goals as goal_service
from backend.services import races as race_service
from backend.services import sessions as planned_sessions
from backend.services import training
from backend.services.activity_cost import activity_cost
from backend.services.briefing import today_briefing
from backend.services.calendar_feed import format_target_pace
from backend.services.goals import GoalChanges, NewGoal
from backend.services.races import NewRace, RaceChanges
from backend.services.resting_hr import resolve_resting_hr
from backend.services.sessions import NewSession, Schedule, SessionChanges
from backend.services.workout_library import NewWorkout, WorkoutChanges
from backend.services.zones import resolve_hr_zones
from zone2.core import Zone2
from zone2.drift import heart_rate_drift
from zone2.hr_recovery import heart_rate_recovery
from zone2.streams_store import detect_stops
from zone2.utils import SportCategory, format_pace_or_speed, get_sport_category


@dataclass
class AgentDeps:
    z2: Zone2
    db: aiosqlite.Connection
    schedule: Schedule
    page: str | None = None
    """What the user is looking at, e.g. "activity 1234" or "calendar, week of 2026-11-09"."""
    earlier: str | None = None
    """The end of the previous session, when this turn is in a later one."""
    first_name: str | None = None
    """The athlete's first name on Strava, read once per turn."""
    sync: Callable[[int | None], Awaitable[str | None]] | None = None
    """Syncs Strava now, or one activity again by its id, and returns what went wrong."""
    garmin_sync: asyncio.Future[None] | None = None
    """Garmin's sync, when this message started one; the tools that read Garmin wait for it."""


# The sports with standard distances (StravaAnalytics.RECORD_SPORTS)
RecordSport = Literal["running", "cycling", "swimming"]
MAX_LIST = 50
MAX_WELLNESS_DAYS = 62
# Strava's own race flags (run, ride); races in z2's race calendar come as ids
STRAVA_RACE_TYPES = (1, 11)


def _num(value: Any, digits: int = 0) -> float | int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), digits) if digits else int(round(float(value)))


def _hms(seconds: Any) -> str | None:
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return None
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _hm(seconds: Any) -> str | None:
    """A long span such as a night's sleep as h:mm."""
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return None
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}:{m:02d}"


def _pace(speed: Any, sport_type: str | None) -> str | None:
    return format_pace_or_speed(speed, sport_type) if _num(speed, 3) else None


def _paused(lap: dict[str, Any]) -> dict[str, Any]:
    """A lap's elapsed time when pauses stretched it: auto-pause on a slow jog
    shortens a recovery's moving time, not the recovery itself."""
    elapsed, moving = lap.get("elapsed_time"), lap.get("moving_time")
    return {"elapsed": _hms(elapsed)} if elapsed and moving and elapsed - moving >= 5 else {}


PACE_FIELDS = ("target_pace_min", "target_pace_max", "target_avg_pace", "target_pace")


def _targets(row: dict[str, Any], sport_type: str | None) -> dict[str, Any]:
    """The row's target paces as stored, in the sport's unit: "4:30 /km", "28 km/h", "1:45 /100m"."""
    return {k: (format_target_pace(sport_type, v) if k in PACE_FIELDS and isinstance(v, (int, float)) else v)
            for k, v in row.items()}


def _readable(row: dict[str, Any]) -> dict[str, Any]:
    """A session, workout or race with its targets in its sport's unit, and empty or default fields dropped."""
    sport_type = row.get("sport_type")
    out = _targets({k: v for k, v in row.items() if v is not None and k not in ("created_at", "plan_name")
                    and not (k == "completed" and not v)}, sport_type)
    if isinstance(out.get("segments"), list):
        out["segments"] = [_targets({k: v for k, v in seg.items() if v is not None
                                     and not (k == "repetitions" and v == 1)}, sport_type)
                           for seg in out["segments"]]
    return out


def _compact(row: dict[str, Any], *drop: str) -> dict[str, Any]:
    return {k: v for k, v in row.items() if v is not None and k not in drop}


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _activity(row: pd.Series, race_ids: frozenset[int]) -> dict[str, Any]:
    sport_type = row.get("sport_type")
    race = int(row["id"]) in race_ids or row.get("workout_type") in STRAVA_RACE_TYPES
    return _compact({
        "id": int(row["id"]),
        "date": pd.Timestamp(row["start_date_local"]).strftime("%Y-%m-%d %H:%M"),
        "name": row.get("name"),
        "sport_type": sport_type,
        "distance_km": _num(row.get("distance", 0) / 1000, 2),
        "moving_time": _hms(row.get("moving_time")),
        "pace": _pace(row.get("average_speed"), sport_type),
        "avg_hr": _num(row.get("average_heartrate")),
        "max_hr": _num(row.get("max_heartrate")),
        "elevation_m": _num(row.get("total_elevation_gain")),
        "race": True if race else None,
    })


# How long a tool reading Garmin waits for the sync this message started
GARMIN_WAIT_S = 25


async def _garmin_synced(ctx: RunContext[AgentDeps]) -> None:
    """Let a Garmin sync this message started finish before reading Garmin's data."""
    if (sync := ctx.deps.garmin_sync) is not None and not sync.done():
        await asyncio.wait([sync], timeout=GARMIN_WAIT_S)


class _OptionalSchema(GenerateToolJsonSchema):
    """An argument that defaults to None is just optional: leaving it out means None, so the
    schema skips the null branch and the default, which every request pays for."""

    def default_schema(self, schema: core_schema.WithDefaultSchema) -> JsonSchemaValue:
        if schema["schema"]["type"] == "nullable" and self.get_default_value(schema) is None:
            return self.generate_inner(schema["schema"]["schema"])
        return super().default_schema(schema)


def _toolset(*, requires_approval: bool = False) -> FunctionToolset[AgentDeps]:
    return FunctionToolset[AgentDeps](schema_generator=_OptionalSchema, requires_approval=requires_approval)


read_tools = _toolset()


@read_tools.tool
async def today(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """Today at a glance: planned sessions, what's done, last night's recovery (readiness, sleep,
    HRV, body battery, resting HR), fitness and form, races in the next days, and z2's suggestion."""
    await _garmin_synced(ctx)
    z2 = ctx.deps.z2
    view = z2.strava_activities_cache.get_prepared_view()
    done = view[view["start_date_local"].dt.date == date.today()] if not view.empty else view
    race_ids = z2.strava_analytics.race_activity_ids
    briefing = await today_briefing(z2, ctx.deps.db, [_activity(r, race_ids) for _, r in done.iterrows()])
    briefing["sessions"] = [_readable(s) for s in briefing["sessions"]]
    if (sleep := (briefing.get("recovery") or {}).get("sleep")) and sleep.get("seconds") is not None:
        sleep["time"] = _hm(sleep.pop("seconds"))
    return _compact(briefing)


@read_tools.tool
async def athlete(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """HR zones 1 to 5 (bpm), max HR, threshold HR when Garmin has it, and resting HR, with
    where each comes from."""
    zones = await resolve_hr_zones(ctx.deps.z2, ctx.deps.db)
    rhr = await resolve_resting_hr(ctx.deps.z2, ctx.deps.db)
    return {
        "hr_zones": [{"zone": i + 1, "min_bpm": z["min"], "max_bpm": z["max"]} for i, z in enumerate(zones["zones"])],
        "max_hr": zones["max_hr"],
        "threshold_hr": zones["threshold_hr"],
        "zones_source": zones["source"],
        "resting_hr": _num(rhr["value"]),
        "resting_hr_source": rhr["source"],
    }


@read_tools.tool
async def find_activities(
    ctx: RunContext[AgentDeps],
    sport: SportCategory | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    name_contains: str | None = None,
    min_km: float | None = None,
    max_km: float | None = None,
    races_only: bool = False,
    sort_by: Literal["date", "distance", "pace", "moving_time"] = "date",
    descending: bool = True,
    limit: Annotated[int, Field(ge=1, le=MAX_LIST)] = 10,
) -> dict[str, Any]:
    """Search every activity back to the first. Dates and distances are inclusive.

    Args:
        sport: "walking" is walks and hikes, which never count as running.
        name_contains: Case-insensitive text in the name.
        races_only: Races (the race calendar's, or flagged on Strava).
        sort_by: "pace" with descending puts the fastest first.
        limit: How many to return; `total` counts every match.
    """
    z2 = ctx.deps.z2
    view = z2.strava_activities_cache.get_prepared_view()
    if view.empty:
        return {"total": 0, "activities": []}
    race_ids = z2.strava_analytics.race_activity_ids
    mask = pd.Series(True, index=view.index)
    if sport:
        mask &= view["sport_type"].map(get_sport_category) == sport
    if date_from or date_to:
        mask &= z2.strava_activities_cache.days_mask(
            date_from.isoformat() if date_from else None, date_to.isoformat() if date_to else None,
        )
    if name_contains:
        mask &= view["name"].str.contains(name_contains, case=False, na=False, regex=False)
    if min_km is not None:
        mask &= view["distance"] >= min_km * 1000
    if max_km is not None:
        mask &= view["distance"] <= max_km * 1000
    if races_only:
        mask &= view["id"].isin(race_ids) | view["workout_type"].isin(STRAVA_RACE_TYPES)
    column = {"date": "start_date_local", "distance": "distance", "pace": "average_speed",
              "moving_time": "moving_time"}[sort_by]
    matches = view[mask].sort_values(column, ascending=not descending, na_position="last")
    return {"total": len(matches), "activities": [_activity(r, race_ids) for _, r in matches.head(limit).iterrows()]}


def _lap_name(lap: dict[str, Any]) -> dict[str, str]:
    """A lap's own name; Strava's "Lap 3" only repeats its place in the list."""
    name = lap.get("name") or ""
    return {} if re.fullmatch(r"Lap \d+", name) else {"name": name}


def _hr_recovery(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "measured":
        return result
    reps = [_compact({"start_km": _num(r["start_km"], 2), "end_km": _num(r["end_km"], 2), "time": _hms(r["duration_s"]),
                      "pace": _pace(r["speed_ms"], "Run"), "peak_hr": r["peak_hr"], "drop_30": r["drop_30"],
                      "drop_60": r["drop_60"], "recovery": _hms(r["recovery_s"]), "jogged": r["jogged"]})
            for r in result["reps"]]
    return _compact({"status": "measured", "reps": reps, "drop_30_mean": result["drop_30_mean"],
                     "drop_60_mean": result["drop_60_mean"]})


@read_tools.tool
async def activity_detail(ctx: RunContext[AgentDeps], activity_id: int) -> dict[str, Any]:
    """One activity in depth: description, per-km splits, laps (the reps of intervals), best
    efforts, for runs HR drift (decoupling), the HR drop after each rep and stops, and its Garmin
    cost: body battery used, recovery time, the night after."""
    cache = ctx.deps.z2.strava_activities_cache
    row = await asyncio.to_thread(cache.get_activity_by_id, activity_id, include_detail=True)
    if row is None:
        raise ModelRetry(f"There is no activity {activity_id}; find it with find_activities first.")
    sport_type = row.get("sport_type")
    detail = _activity(row, ctx.deps.z2.strava_analytics.race_activity_ids)
    detail["elapsed_time"] = _hms(row.get("elapsed_time"))
    detail["description"] = row.get("description") or None
    detail["perceived_exertion"] = _num(row.get("perceived_exertion"))
    detail["splits_km"] = [
        {"km": s.get("split"), "pace": _pace(s.get("average_speed"), sport_type),
         "avg_hr": _num(s.get("average_heartrate")), "elevation_m": _num(s.get("elevation_difference"))}
        for s in _json(row.get("splits_metric")) or []
    ]
    laps = _json(row.get("laps")) or []
    # The watch's automatic 1 km laps repeat the splits; only manual or workout laps add anything
    if all(abs((lap.get("distance") or 0) - 1000) < 20 for lap in laps[:-1]):
        laps = []
    detail["laps"] = [
        {**_lap_name(lap), "distance_km": _num(lap.get("distance", 0) / 1000, 2),
         "time": _hms(lap.get("moving_time")), **_paused(lap), "pace": _pace(lap.get("average_speed"), sport_type),
         "avg_hr": _num(lap.get("average_heartrate")), "max_hr": _num(lap.get("max_heartrate"))}
        for lap in laps
    ]
    detail["best_efforts"] = [
        {"name": e.get("name"), "time": _hms(e.get("moving_time"))} for e in _json(row.get("best_efforts")) or []
    ]
    if get_sport_category(sport_type) == SportCategory.RUNNING:
        streams = await asyncio.to_thread(cache.get_streams, activity_id)
        if streams:
            detail["hr_drift"] = heart_rate_drift(streams)
            detail["hr_recovery"] = _hr_recovery(heart_rate_recovery(streams))
            detail["stops"] = [
                {"at_km": _num(st["start_km"], 2), "at": _hms(st["start_s"]), "seconds": _num(st["duration_s"])}
                for st in detect_stops(streams)
            ]
    await _garmin_synced(ctx)
    cost = await asyncio.to_thread(activity_cost, ctx.deps.z2, activity_id)
    if cost and any(cost.values()):
        detail["garmin"] = _compact(cost)
        if (night := detail["garmin"].get("night")) and night.get("sleep_seconds") is not None:
            night["sleep"] = _hm(night.pop("sleep_seconds"))
    return _compact(detail)


@read_tools.tool
async def similar_activities(ctx: RunContext[AgentDeps], activity_id: int,
                             limit: Annotated[int, Field(ge=1, le=20)] = 6) -> list[dict[str, Any]]:
    """The latest activities like this one (same sport, distance within 10%, climb within 20%):
    the like-for-like comparison for a run that wasn't a saved workout, e.g. pace at the same HR
    on the usual easy loop."""
    df = await asyncio.to_thread(activity_service.similar, ctx.deps.z2, activity_id, limit)
    if df is None:
        raise ModelRetry(f"There is no activity {activity_id}; find it with find_activities first.")
    race_ids = ctx.deps.z2.strava_analytics.race_activity_ids
    return [_activity(r, race_ids) for _, r in df.iterrows()]


@read_tools.tool
async def personal_records(ctx: RunContext[AgentDeps], sport: RecordSport = "running") -> list[dict[str, Any]]:
    """All-time best effort at each standard distance, with its activity."""
    records = await asyncio.to_thread(ctx.deps.z2.strava_analytics.get_personal_records)
    return [
        {"distance": r["label"], "time": _hms(r["time_s"]), "date": str(r["date"])[:10],
         "activity_id": r["activity_id"], "activity_name": r["activity_name"]}
        for r in records.get(sport, [])
    ]


# Daniels' training zones, as the predictor names them
PACE_ZONES = {"E": "easy", "M": "marathon", "T": "threshold", "I": "interval (VO2)", "R": "repetition"}


def _training_paces(paces: dict[str, Any] | None) -> dict[str, Any] | None:
    if not paces:
        return None
    zones = {}
    for p in paces.get("paces", []):
        slow, fast = _pace(p["speed_min_mps"], "Run"), _pace(p["speed_max_mps"], "Run")
        zones[PACE_ZONES.get(p["zone"], p["zone"])] = slow if slow == fast else f"{fast} to {slow}"
    return {"vdot": paces.get("vdot"), "paces": zones}


@read_tools.tool
async def race_predictions(
    ctx: RunContext[AgentDeps],
    sport: RecordSport = "running",
    history_weeks: Annotated[int, Field(ge=0, le=104)] = 0,
) -> dict[str, Any]:
    """Predicted race times with a likely range, the current best and Garmin's prediction per
    distance, training paces, and the fade: how much the athlete slows as distance grows, an
    exponent with its standard error and a verdict against the typical 1.06 (fades, typical or
    holds_pace; typical means the data can't tell speed from endurance).

    Args:
        history_weeks: Also how the predictions moved, a point a week over this many weeks.
    """
    analytics = ctx.deps.z2.strava_analytics
    result = await asyncio.to_thread(analytics.get_race_predictions, SportCategory(sport))
    out: dict[str, Any] = {
        "predictions": [
            _compact({"distance": p["label"], "predicted": _hms(p.get("predicted_time_s")),
                      "range": [_hms(p.get("predicted_time_low_s")), _hms(p.get("predicted_time_high_s"))],
                      "current_best": _hms(p.get("pr_time_s")),
                      "current_best_date": str(p.get("pr_date") or "")[:10] or None,
                      "garmin": _hms(p.get("garmin_time_s"))})
            for p in result.get("predictions", [])
        ],
        "training_paces": _training_paces(result.get("training_paces")),
        "confidence": result.get("confidence"),
        # How much the athlete slows as the distance grows, against the typical exponent
        "fade": {k: (result.get("fade") or {}).get(k) for k in ("exponent", "stderr", "typical", "verdict")},
    }
    if history_weeks:
        points = await asyncio.to_thread(analytics.get_race_predictions_history, SportCategory(sport),
                                         weeks=history_weeks, step_days=7)
        out["history"] = [
            _compact({"date": p.get("end_date"), "vdot": p.get("athlete_vdot"), "fade": p.get("fitted_exponent"),
                      "predicted": {q["label"]: _hms(q.get("predicted_time_s")) for q in p.get("predictions", [])}})
            for p in points
        ]
    return out


@read_tools.tool
async def fitness(ctx: RunContext[AgentDeps], days: Annotated[int, Field(ge=30, le=730)] = 90) -> dict[str, Any]:
    """Fitness (42-day load), fatigue (7-day load) and form (fitness minus fatigue, as a share
    of fitness) over the last `days`: a point a week, every day of the last week, and weekly
    points ahead projected from the planned sessions."""
    result = await training.fitness_form(ctx.deps.z2, ctx.deps.db, days)
    series = result.get("series", [])
    recent_from = (date.today() - timedelta(days=7)).isoformat()
    keep = [
        d for i, d in enumerate(series)
        if (d["date"] >= recent_from and not d["projected"]) or i % 7 == 0 or d is series[-1]
    ]
    fields = ("date", "fitness", "fatigue", "form_pct")
    return {"series": [{**{k: d.get(k) for k in fields}, **({"projected": True} if d.get("projected") else {})}
                       for d in keep],
            "races": result.get("races", [])}


@read_tools.tool
async def weekly_volume(
    ctx: RunContext[AgentDeps],
    weeks: Annotated[int, Field(ge=1, le=52)] = 12,
    sport: SportCategory | None = None,
) -> list[dict[str, Any]]:
    """Km and activities per week, this week included.

    Args:
        sport: All sports when omitted. "walking" is walks and hikes, which never count as running.
    """
    result = await asyncio.to_thread(training.weekly_totals, ctx.deps.z2, weeks, category=sport)
    return [{"week_start": w["week_start"], "km": w["total_distance_km"], "activities": w["total_activities"]}
            for w in result["data"]]


@read_tools.tool
async def planned_sessions_between(ctx: RunContext[AgentDeps], date_from: date, date_to: date) -> list[dict[str, Any]]:
    """The training calendar between two days, inclusive: sessions with their ids, targets,
    steps and plan, and for those done their execution score (0-100) and activity."""
    db = ctx.deps.db
    sessions = await planned_sessions.between(db, date_from.isoformat(), date_to.isoformat())
    today_iso = date.today().isoformat()
    past = [s for s in sessions if s["date"] <= today_iso]
    scores = await session_scores.scores(ctx.deps.z2, db, past, date_from.isoformat(), date_to.isoformat()) if past else {}
    out = []
    for s in sessions:
        if score := scores.get(s["id"]):
            s = {**s, "score": score["overall_score"], "activity_id": score["matched_activity_id"]}
        out.append(_readable(s))
    return out


@read_tools.tool
async def workout_history(
    ctx: RunContext[AgentDeps],
    session_id: int | None = None,
    workout_template_id: int | None = None,
    limit: Annotated[int, Field(ge=1, le=20)] = 6,
) -> list[dict[str, Any]]:
    """Past sessions planned from the same saved workout (give the session or the workout),
    latest first, with that day's activities of the session's sport: the like-for-like
    comparison for a session."""
    db = ctx.deps.db
    if workout_template_id is None:
        if session_id is None:
            raise ModelRetry("Give session_id or workout_template_id.")
        try:
            workout_template_id = (await planned_sessions.get(db, session_id))["workout_template_id"]
        except NotFound:
            workout_template_id = None
        if workout_template_id is None:
            raise ModelRetry(f"Session {session_id} isn't planned from a saved workout; try find_activities by name.")
    rows = await planned_sessions.from_workout(db, workout_template_id, date.today().isoformat(), limit)
    z2 = ctx.deps.z2
    view = z2.strava_activities_cache.get_prepared_view()
    race_ids = z2.strava_analytics.race_activity_ids
    if view.empty:
        return [{"session_id": r["id"], "date": r["date"], "title": r["title"], "activities": []} for r in rows]
    day = view["start_date_local"].dt.strftime("%Y-%m-%d")
    category = view["sport_type"].map(get_sport_category)
    out = []
    for r in rows:
        done = view[(day == r["date"]) & (category == get_sport_category(r["sport_type"]))]
        out.append({"session_id": r["id"], "date": r["date"], "title": r["title"],
                    "activities": [_activity(a, race_ids) for _, a in done.iterrows()]})
    return out


@read_tools.tool
async def races(ctx: RunContext[AgentDeps], include_past: bool = False) -> list[dict[str, Any]]:
    """The race calendar: date, name, sport, distance and target pace."""
    db = ctx.deps.db
    rows = await (race_service.races_between(db) if include_past else race_service.upcoming(db))
    return [_readable(r) for r in rows]


# What each wellness metric carries to the model; the rest of Garmin's summary it never uses
WELLNESS_FIELDS: dict[str, tuple[str, ...]] = {
    "sleep": ("score", "qualifier", "total_seconds", "deep_seconds", "rem_seconds", "avg_hr"),
    "hrv": ("last_night_avg", "weekly_avg", "status", "balanced_low", "balanced_upper", "low_upper"),
    "training_readiness": ("score", "level", "recovery_time_min", "feedback_short"),
    "body_battery": ("charged", "drained", "end_of_day"),
    "stress": ("avg",),
    "heart_rates": ("resting", "last_7d_avg_resting"),
    "training_status": ("status_phrase", "acwr_ratio", "acwr_status", "daily_load_acute", "daily_load_chronic",
                        "load_balance_phrase"),
    "race_predictions": ("time_5k_s", "time_10k_s", "time_half_s", "time_marathon_s"),
    "max_metrics": ("vo2max",),
}


def _wellness_day(metric: str, summary: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in WELLNESS_FIELDS.get(metric, tuple(summary)):
        value = summary.get(key)
        if value is None:
            continue
        if key.endswith("_seconds") and metric == "sleep":
            out[key.replace("_seconds", "")] = _hm(value)
        elif key.startswith("time_") and key.endswith("_s"):
            out[key[5:-2]] = _hms(value)
        else:
            out[key] = value
    return out


WellnessMetric = Literal[
    "sleep", "hrv", "training_readiness", "body_battery", "stress", "heart_rates", "training_status",
    "race_predictions", "max_metrics",
]


@read_tools.tool
async def wellness(
    ctx: RunContext[AgentDeps],
    date_from: date,
    date_to: date,
    metrics: list[WellnessMetric] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Garmin's daily wellness, at most 62 days: sleep, HRV, training readiness, body battery,
    stress, resting HR (`heart_rates`), training status (acute and chronic load), Garmin's race
    predictions and VO2 max (`max_metrics`).

    Args:
        metrics: All of them when omitted.
    """
    if (date_to - date_from).days >= MAX_WELLNESS_DAYS:
        raise ModelRetry(f"Ask for at most {MAX_WELLNESS_DAYS} days at a time.")
    await _garmin_synced(ctx)
    cache = ctx.deps.z2.garmin_cache
    wanted = metrics or list(WellnessMetric.__args__)
    out: dict[str, list[dict[str, Any]]] = {}
    for metric in wanted:
        rows = await asyncio.to_thread(cache.get_summary_range, metric, date_from.isoformat(), date_to.isoformat())
        out[metric] = [{"date": r["date"], **_wellness_day(metric, r["summary"])} for r in rows]
    return out


@read_tools.tool
async def saved_workouts(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
    """The workout library: saved workouts and their steps."""
    library = await workout_library.library(ctx.deps.z2, ctx.deps.db)
    return [_workout_view(t) for t in sorted(library, key=lambda t: t["name"])]


@read_tools.tool
async def plans_overview(ctx: RunContext[AgentDeps], include_done: bool = False) -> list[dict[str, Any]]:
    """The training plans: each block toward a race with its goal, dates, sessions done of
    those due, and average execution score."""
    out = []
    for plan in await plans.list_plans(ctx.deps.db, include_done):
        progress = await plans.progress(ctx.deps.z2, ctx.deps.db, plan, await plans.race_of(ctx.deps.db, plan),
                                        detail=False)
        out.append({"id": plan["id"], "name": plan["name"], "status": plan["status"], "goal": plan.get("goal"),
                    "start_date": plan["start_date"], "end_date": plan["end_date"],
                    "days_to_race": progress["days_to_race"], "phase": progress["phase"],
                    "sessions": progress["sessions"], "average_score": progress["score"]["average"]})
    return out


@read_tools.tool
async def plan_detail(ctx: RunContext[AgentDeps], plan_id: int) -> dict[str, Any]:
    """One plan in full: phases, weekly km (target, planned, run), the prediction against the
    goal, its sessions (done, execution score), checkpoints, the agreements kept for it, and the
    latest coach's log entries with their ids."""
    db = ctx.deps.db
    plan = await plans.get_plan(db, plan_id)
    if plan is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    race = await plans.race_of(db, plan)
    progress = await plans.progress(ctx.deps.z2, db, plan, race)
    status = progress.pop("session_status")
    pred = progress["prediction"]
    if pred:
        # Race times as h:mm:ss, so a trend reads the right way round (lower is faster)
        garmin = pred["garmin"][::7] + pred["garmin"][-1:] if pred["garmin"] else []
        progress["prediction"] = {
            "distance": pred["distance"],
            "predicted_now": _hms(pred["now_s"]),
            "predicted_by": pred["source"],
            "z2_predicted_now": _hms(pred["z2_now_s"]),
            "z2_range": [_hms(t) for t in pred["range_s"]],
            "z2_weekly": [{"date": d["date"], "predicted": _hms(d["time_s"])} for d in pred["z2"]],
            "garmin_daily": [{"date": d["date"], "predicted": _hms(d["time_s"])} for d in garmin],
        }
    if progress.get("result"):
        progress["result"] = {**progress["result"], "time": _hms(progress["result"].pop("time_s"))}
    if "weeks" in progress:
        progress["weeks"] = [_compact(w) for w in progress["weeks"]]
    keep = ("id", "date", "title", "sport_type", "planned_distance_km", "planned_intensity", "garmin_sync_state")
    goal_s = plan.get("goal_time_s")
    return _compact({
        **_compact(plan, "created_at", "goal_time_s"),
        "goal_time": _hms(goal_s) if goal_s is not None else None,
        "race": _readable(race) if race else None,
        "progress": _compact(progress, "today"),
        "sessions": [_compact({**{k: s.get(k) for k in keep}, **status[s["id"]]})
                     for s in await plans.plan_sessions(db, plan_id)],
        "checkpoints": [_compact(c, "plan_id", "created_at") for c in await plans.checkpoints(db, plan_id)],
        "agreements": [{"id": n["id"], "note": n["note"]} for n in await notes.plan_notes(db, plan_id)],
        "log": [{**_compact(e, "plan_id", "created_at", "body"), "body": (e.get("body") or "")[:240]}
                for e in await coach_log.entries(db, plan_id, limit=8)],
    })


@read_tools.tool
async def goals(ctx: RunContext[AgentDeps], year: int | None = None) -> list[dict[str, Any]]:
    """Goals for a year (this year when omitted): a target per week, month or year for a sport
    or all sports, with the value so far this period."""
    ref = date.today() if year is None or year == date.today().year else date(year, 12, 31)
    rows = await goal_service.progress(ctx.deps.z2, ctx.deps.db, ref)
    keep = ("id", "year", "sport_type", "metric", "period", "target_value", "current_value", "percentage",
            "period_start", "period_end")
    return [{k: g[k] for k in keep if k in g} for g in rows]


# ── Notes: the agent's memory of this athlete and of each plan's agreements ──

memory_tools = _toolset()


@memory_tools.tool
async def remember(ctx: RunContext[AgentDeps], note: str,
                   topic: Literal["kit", "body", "rules", "preferences"] | None = None,
                   plan_id: int | None = None) -> str:
    """Keep a durable fact z2's data doesn't hold: one fact per note, dated when the date
    matters ("HR sensor changed to a chest strap on 3 March: don't compare HR across that
    date"). Not zones, max or threshold HR: they're set in Profile and `athlete` reads them.
    A fact about the athlete takes a `topic` and reaches every conversation: kit
    (sensors, GPS, devices), body (baselines, injuries), rules (how their week is
    built) or preferences (how they like to be coached, habits). An agreement for one plan (the
    block's structure, the race-day plan, a guardrail for this block) takes its `plan_id`
    instead and stays with the plan, in plan_detail. A checkpoint's thresholds go in
    add_checkpoint."""
    if plan_id is not None:
        if await plans.get_plan(ctx.deps.db, plan_id) is None:
            raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
        return f"Noted for plan {plan_id} ({await notes.add(ctx.deps.db, note, plan_id=plan_id)})."
    if topic is None:
        raise ModelRetry("Give the note a topic, or the plan_id of the plan it was agreed for.")
    return f"Noted ({await notes.add(ctx.deps.db, note, notes.Topic(topic))})."


@memory_tools.tool
async def forget(ctx: RunContext[AgentDeps], note_id: int) -> str:
    """Drop a note that is wrong or no longer true."""
    if not await notes.delete(ctx.deps.db, note_id):
        raise ModelRetry(f"There is no note {note_id}.")
    return f"Forgot note {note_id}."


@memory_tools.tool
async def log_entry(
    ctx: RunContext[AgentDeps],
    kind: Literal["review", "decision", "suggestion", "summary"],
    title: str,
    body: str,
    day: datetime.date | None = None,
    plan_id: int | None = None,
    session_id: int | None = None,
    activity_id: int | None = None,
) -> str:
    """Write to the coach's log on the Coach page: a session `review` against its target and
    guardrail, a checkpoint `decision`, a week's `summary`, or a `suggestion` for a change you
    recommend. A suggestion changes nothing: the plan changes only when the athlete asks.

    Args:
        title: One line, e.g. "2×4 km: guardrail broken at 1.5 km".
        body: The detail in a few lines; tables are fine.
        day: The day it is about; today when omitted.
    """
    entry = await coach_log.add(ctx.deps.db, kind=coach_log.Kind(kind), title=title, body=body,
                                day=day.isoformat() if day else None, plan_id=plan_id,
                                session_id=session_id, activity_id=activity_id)
    return f"Logged ({entry['id']})."


# ── Writes ──────────────────────────────────────────────────────────────

def _set_fields(changes: BaseModel) -> list[str]:
    """The fields a change gives, in the model's order."""
    return list(changes.model_dump(exclude_unset=True))


def _changes(before: dict[str, Any], after: dict[str, Any], fields: list[str]) -> str:
    def short(v: Any) -> str:
        text = "steps" if isinstance(v, list) else str(v)
        return text if len(text) <= 60 else text[:57] + "…"
    return "\n".join(f"{k.replace('_', ' ')}: {short(before.get(k))} → {short(after.get(k))}"
                     for k in fields if before.get(k) != after.get(k))


async def _log_change(ctx: RunContext[AgentDeps], session: dict[str, Any], title: str, reason: str,
                      detail: str | None = None) -> None:
    body = reason if not detail else f"{reason}\n{detail}"
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=title, body=body, day=session["date"],
                        plan_id=session.get("plan_id"), session_id=session["id"])


@memory_tools.tool
async def close_suggestion(ctx: RunContext[AgentDeps], entry_id: int, status: Literal["done", "dismissed"]) -> str:
    """Close your open suggestion in the coach's log (plan_detail lists them): `done` once its
    change is made, `dismissed` when the athlete turned it down."""
    if not await coach_log.set_status(ctx.deps.db, entry_id, coach_log.SuggestionStatus(status)):
        raise ModelRetry(f"Log entry {entry_id} isn't a suggestion; plan_detail lists the log with its ids.")
    return f"Suggestion {entry_id} is {status}."


app_tools = _toolset()
"""Acting in the app without asking: syncing, and taking the athlete to a page."""


@app_tools.tool
async def sync_now(ctx: RunContext[AgentDeps], activity_id: int | None = None) -> str:
    """Sync Strava, once, before saying a session they mention isn't in z2 (each message
    already syncs data over 15 minutes old). With `activity_id`, fetch that activity again with
    its streams: its HR or GPS looks wrong, or it was edited on Strava."""
    if ctx.deps.sync is None:
        return "Syncing isn't available here."
    cache = ctx.deps.z2.strava_activities_cache
    before = len(cache.activities_raw)
    if error := await ctx.deps.sync(activity_id):
        return f"The sync didn't finish: {error}"
    if activity_id is not None:
        return f"Activity {activity_id} is fetched again; read it with activity_detail."
    new = len(cache.activities_raw) - before
    return f"Synced: {new} new {'activity' if new == 1 else 'activities'}." if new else "Synced: nothing new on Strava."


Page = Literal["activity", "plan", "gear", "calendar", "activities", "coach", "records", "workouts", "races",
               "analytics", "garmin", "dashboard", "coverage", "profile"]
PAGE_WITH_ID = {"activity": "/activities/{}", "plan": "/coach/{}", "gear": "/gear/{}"}


@app_tools.tool
async def open_page(ctx: RunContext[AgentDeps], page: Page, id: str | None = None) -> str:
    """Take the athlete to a page when they ask to see something ("show me that run"). `id` is
    the activity's, plan's or gear's id for those pages."""
    if page in PAGE_WITH_ID:
        if not id:
            raise ModelRetry(f"Give the {page}'s id to open it.")
        return PAGE_WITH_ID[page].format(id)
    return f"/{page}"


gear_tools = _toolset()
"""Shoes and bikes, loaded with the gear capability."""
GEAR_FIELDS = ("id", "label", "kind", "primary", "retired", "distance_km", "strava_distance_km", "activities",
               "first_activity", "last_activity")


@gear_tools.tool
async def gear(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
    """Every shoe and bike, latest used first: km in z2's history and on Strava's odometer
    (which also counts km from before that history), activities, first and last use, whether it
    is retired or the default."""
    listed = await asyncio.to_thread(gear_service.gear_list, ctx.deps.z2)
    return [{k: g[k] for k in GEAR_FIELDS if g.get(k) is not None} for g in listed["gear"]]


@gear_tools.tool
async def gear_detail(ctx: RunContext[AgentDeps], gear_id: str) -> dict[str, Any]:
    """One shoe or bike in depth: average pace, distance and HR, km per month, the best efforts
    run in it (and whether each is the all-time best), its longest and fastest outings, and how
    far the others of its kind went before retiring."""
    detail = await asyncio.to_thread(gear_service.gear_detail, ctx.deps.z2, gear_id)
    if detail is None:
        raise ModelRetry(f"There is no gear {gear_id}; list it with gear first.")
    item = detail["gear"]
    sport = "Ride" if item["kind"] == "bikes" else "Run"
    totals = detail["totals"] or {}

    def outing(a: dict[str, Any] | None) -> dict[str, Any] | None:
        return a and {"id": a["id"], "name": a["name"], "date": a["date"], "distance_km": a["distance_km"],
                      "pace": _pace(a.get("speed_ms"), sport), "elevation_m": a.get("elevation_m")}

    return {
        **{k: item[k] for k in GEAR_FIELDS if item.get(k) is not None},
        "average": {"pace": _pace(totals.get("avg_speed_ms"), sport), "distance_km": totals.get("avg_distance_km"),
                    "hr": totals.get("avg_heartrate"), "days_between_uses": totals.get("days_per_activity")},
        "monthly": [{"month": m["month"], "km": m["distance_km"], "activities": m["activities"]} for m in detail["monthly"]],
        "best_efforts": [{"distance": e["name"], "time": _hms(e["elapsed_time"]), "date": e["date"],
                          "activity_id": e["activity_id"], "all_time_best": e["all_time_best"]}
                         for e in detail["best_efforts"]],
        "longest": outing(detail["extremes"].get("longest")),
        "fastest": outing(detail["extremes"].get("fastest")),
        "others_of_its_kind": detail["peers"],
    }


history_tools = _toolset()
"""Years, all-time totals and streaks, loaded with the history capability."""


def _year(features: dict[Any, Any], sport_type: str) -> dict[str, Any]:
    f = {str(k): v for k, v in features.items()}
    for key in ("average_speed", "fastest_activity_speed"):
        if key in f:
            f[key.replace("speed", "pace")] = _pace(f.pop(key), sport_type)
    if "fastest_activity_speed_id" in f:
        f["fastest_activity_id"] = f.pop("fastest_activity_speed_id")
    if (weekday := f.get("most_active_weekday")) is not None:
        f["most_active_weekday"] = calendar.day_name[int(weekday)]
    return {k: v for k, v in f.items() if v is not None}


@history_tools.tool
async def year_stats(ctx: RunContext[AgentDeps], year: int | None = None, sport_type: str = "Run",
                     compare_to: int | None = None) -> dict[str, Any]:
    """A year in sport: totals for `sport_type` (km, time, climb, activities, per month, the
    longest and fastest, its activity ids) and for all sports (count per sport). The year in
    progress counts up to today, and so does `compare_to`, so "this year vs last year" is like for like.

    Args:
        year: This year when omitted.
        sport_type: A Strava sport type such as "Run" or "Ride".
        compare_to: Another year, counted up to the same day.
    """
    today = date.today()
    year = year or today.year
    cutoff = (today.month, today.day) if year == today.year else None
    z2 = ctx.deps.z2

    def one(y: int) -> dict[str, Any]:
        data = training.year_in_sport(z2, y, sport_type, cutoff)
        return {"year": y, sport_type: _year(data["main"], sport_type), "all_sports": _year(data["all"], sport_type)}

    result = await asyncio.to_thread(one, year)
    if cutoff:
        result["counted_up_to"] = today.strftime("%d %b")
    if compare_to:
        result["compared"] = await asyncio.to_thread(one, compare_to)
    return result


@history_tools.tool
async def totals(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """All-time totals per sport (running, cycling, swimming): km, moving time and activities."""
    result = await asyncio.to_thread(training.sport_totals, ctx.deps.z2)
    return {sport: {"km": t["distance_km"], "time": _hms(t["time_s"]), "activities": t["count"]}
            for sport, t in result.items()}


@history_tools.tool
async def streaks(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """Streaks of consecutive days, and of consecutive weeks, with any activity: the current
    ones and the longest ever, with their dates."""
    return await asyncio.to_thread(training.streaks, ctx.deps.z2)


# Always on, unlike the other detail tools: "how did I sleep?" is an everyday question, and loading
# a capability first costs a model request (about 2 s on the Pi)
@read_tools.tool
async def night(ctx: RunContext[AgentDeps], day: date | None = None) -> dict[str, Any] | str:
    """One night in detail: when they fell asleep and woke, Garmin's score with each stage
    against its ideal share, awake spells, restlessness, breathing and SpO2, then hour by hour
    the minutes deep, light, REM and awake with the average heart rate, HRV, stress and body
    battery. `day` is the morning the night ended; today when omitted."""
    await _garmin_synced(ctx)
    result = await asyncio.to_thread(day_timeline.night, ctx.deps.z2, day or date.today())
    if result is None:
        return "Garmin has no sleep for that night."
    result["asleep"] = _hm(result.pop("asleep_seconds"))
    awake = result.pop("awake_seconds")
    result["awake_min"] = None if awake is None else round(awake / 60)
    for stage in ("deep", "light", "rem"):
        result[stage]["time"] = _hm(result[stage].pop("seconds"))
    return result


write_tools = _toolset(requires_approval=True)


@write_tools.tool
async def add_session(ctx: RunContext[AgentDeps], session: NewSession, reason: str) -> dict[str, Any]:
    """Add a session to the calendar, only when the athlete asked for it. Planned from a saved
    workout (`workout_template_id`), it takes the workout's steps. A run with steps also goes to
    the watch."""
    try:
        created = await planned_sessions.create(ctx.deps.z2, ctx.deps.db, session, ctx.deps.schedule)
    except ServiceError as e:
        raise ModelRetry(f"It wasn't added: {e.message}") from e
    await _log_change(ctx, created, f"Added {created['title']} on {created['date']}", reason)
    return _readable(created)


@write_tools.tool
async def change_session(ctx: RunContext[AgentDeps], session_id: int, changes: SessionChanges,
                         reason: str) -> dict[str, Any]:
    """Change a planned session, only when the athlete asked for it: its day, title, targets or
    steps. Only the fields given change; a saved workout given (`workout_template_id`) brings its
    steps."""
    try:
        before = await planned_sessions.get(ctx.deps.db, session_id)
    except NotFound as e:
        raise ModelRetry(f"There is no session {session_id}; look it up with planned_sessions_between.") from e
    try:
        after = await planned_sessions.update(ctx.deps.z2, ctx.deps.db, session_id, changes, ctx.deps.schedule)
    except ServiceError as e:
        raise ModelRetry(f"That change didn't apply: {e.message}") from e
    await _log_change(ctx, after, f"Changed {before['title']}", reason, _changes(before, after, _set_fields(changes)))
    return _readable(after)


@write_tools.tool
async def remove_session(ctx: RunContext[AgentDeps], session_id: int, reason: str) -> str:
    """Remove a planned session (and its entry on the watch), only when the athlete asked for it."""
    try:
        session = await planned_sessions.delete(ctx.deps.z2, ctx.deps.db, session_id, ctx.deps.schedule)
    except NotFound as e:
        raise ModelRetry(f"There is no session {session_id}; look it up with planned_sessions_between.") from e
    await _log_change(ctx, session, f"Removed {session['title']} on {session['date']}", reason)
    return f"Session {session_id} removed."


@write_tools.tool
async def resync_watch(ctx: RunContext[AgentDeps]) -> str:
    """Send the upcoming sessions to the watch again, when a `garmin_sync_state` reads failed."""
    z2 = ctx.deps.z2
    if not await garmin_workouts.is_enabled(z2, ctx.deps.db):
        return "Sending workouts to the watch is off in z2 (Profile, Garmin watch)."
    await garmin_workouts.mark_due_pending(z2, ctx.deps.db)
    ctx.deps.schedule(garmin_workouts.reconcile, z2)
    return "Upcoming sessions are queued for the watch again."


class PlanPhase(BaseModel):
    name: str
    start: datetime.date
    end: datetime.date
    target_km: float | None = Field(None, description="Weekly running km the phase aims for")


class PlanFields(BaseModel):
    name: str | None = None
    race_event_id: int | None = Field(None, description="The goal race, from races")
    goal: str | None = Field(None, description='The goal in words, e.g. "sub-1:45 half marathon"')
    goal_time_s: float | None = Field(None, description="The goal as a race time in seconds, when it is one")
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    summary: str | None = Field(None, description="The plan's logic in a few lines")
    phases: list[PlanPhase] | None = None


class NewPlan(PlanFields):
    name: str
    start_date: datetime.date
    end_date: datetime.date


class PlanChanges(PlanFields):
    status: Literal["active", "done", "abandoned"] | None = None


@write_tools.tool
async def create_plan(ctx: RunContext[AgentDeps], plan: NewPlan, session_ids: list[int] | None = None) -> dict[str, Any]:
    """Create a training plan toward a race once the athlete agreed to it, with the given
    sessions in it. Add more with add_session (plan_id), and its tests with add_checkpoint."""
    created = await plans.create_plan(ctx.deps.db, plan.model_dump(mode="json"))
    linked = await plans.link_sessions(ctx.deps.db, created["id"], session_ids or [])
    return {**created, "sessions_linked": linked}


@write_tools.tool
async def change_plan(ctx: RunContext[AgentDeps], plan_id: int, changes: PlanChanges, reason: str) -> dict[str, Any]:
    """Change a plan's goal, dates, phases, summary or status, only when the athlete asked for it."""
    values = changes.model_dump(mode="json", exclude_unset=True)
    before = await plans.get_plan(ctx.deps.db, plan_id)
    if before is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    try:
        after = await plans.update_plan(ctx.deps.db, plan_id, values)
    except ServiceError as e:
        raise ModelRetry(f"That change didn't apply: {e.message}") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed the plan {after['name']}",
                        body=f"{reason}\n{_changes(before, after, list(values))}", plan_id=plan_id)
    return after


@write_tools.tool
async def link_sessions(ctx: RunContext[AgentDeps], plan_id: int, session_ids: list[int]) -> str:
    """Put planned sessions in a plan, so they count toward it."""
    if await plans.get_plan(ctx.deps.db, plan_id) is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    return f"{await plans.link_sessions(ctx.deps.db, plan_id, session_ids)} sessions now in plan {plan_id}."


@write_tools.tool
async def add_checkpoint(
    ctx: RunContext[AgentDeps], plan_id: int, day: datetime.date, title: str, rule: str, session_id: int | None = None,
) -> dict[str, Any]:
    """Add a checkpoint: a test or key session whose result decides how the plan goes on. `rule`
    holds the thresholds agreed beforehand, e.g. "22:00 or faster keeps the goal; about 22:30
    moves it a minute slower"."""
    if await plans.get_plan(ctx.deps.db, plan_id) is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    return await plans.add_checkpoint(ctx.deps.db, {"plan_id": plan_id, "date": day.isoformat(), "title": title,
                                                    "rule": rule, "session_id": session_id})


@write_tools.tool
async def record_checkpoint(ctx: RunContext[AgentDeps], checkpoint_id: int, result: str, decision: str) -> dict[str, Any]:
    """Record a checkpoint's result and the decision its rule gives. Sessions don't change:
    propose those changes, and make them once the athlete agrees."""
    try:
        checkpoint = await plans.update_checkpoint(ctx.deps.db, checkpoint_id, {"result": result, "decision": decision})
    except NotFound as e:
        raise ModelRetry(f"There is no checkpoint {checkpoint_id}; see plan_detail.") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.DECISION, title=f"{checkpoint['title']}: {result}",
                        body=decision, day=checkpoint["date"], plan_id=checkpoint["plan_id"],
                        session_id=checkpoint.get("session_id"))
    return checkpoint


@write_tools.tool
async def add_race(ctx: RunContext[AgentDeps], race: NewRace, reason: str) -> dict[str, Any]:
    """Add a race to the race calendar, when the athlete asks. Races decide which runs count as
    races in the predictions, and a plan can aim at one."""
    try:
        row = await race_service.create(ctx.deps.z2, ctx.deps.db, race)
    except ServiceError as e:
        raise ModelRetry(f"It wasn't added: {e.message}") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Added the race {row['name']} on {row['date']}",
                        body=reason)
    return _readable(row)


@write_tools.tool
async def change_race(ctx: RunContext[AgentDeps], race_id: int, changes: RaceChanges, reason: str) -> dict[str, Any]:
    """Change a race (date, distance, goal pace…), when the athlete asks. Only the fields given
    change."""
    try:
        row = await race_service.update(ctx.deps.z2, ctx.deps.db, race_id, changes)
    except NotFound as e:
        raise ModelRetry(f"There is no race {race_id}; see races with include_past.") from e
    except ServiceError as e:
        raise ModelRetry(f"That change didn't apply: {e.message}") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed the race {row['name']}",
                        body=f"{reason}\n" + ", ".join(_set_fields(changes)))
    return _readable(row)


@write_tools.tool
async def set_goal(ctx: RunContext[AgentDeps], goal: NewGoal, reason: str) -> dict[str, Any]:
    """Add a goal, when the athlete asks: e.g. 2000 km of running in 2027 (yearly), or 3 strength
    sessions a week (activities, weekly)."""
    row = await goal_service.create(ctx.deps.db, goal)
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, body=reason,
                        title=f"Set a goal: {row['target_value']:g} {row['metric']} {row['period']} ({row['sport_type']}, {row['year']})")
    return row


@write_tools.tool
async def change_goal(ctx: RunContext[AgentDeps], goal_id: int, changes: GoalChanges, reason: str) -> dict[str, Any]:
    """Change a goal's target, period, sport or metric, when the athlete asks."""
    try:
        row = await goal_service.update(ctx.deps.db, goal_id, changes)
    except NotFound as e:
        raise ModelRetry(f"There is no goal {goal_id}; see goals.") from e
    except ServiceError as e:
        raise ModelRetry(f"That change didn't apply: {e.message}") from e
    given = changes.model_dump(exclude_unset=True)
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed goal {goal_id}",
                        body=f"{reason}\n" + ", ".join(f"{k}: {v}" for k, v in given.items()))
    return row


@write_tools.tool
async def remove_goal(ctx: RunContext[AgentDeps], goal_id: int, reason: str) -> str:
    """Remove a goal, when the athlete asks."""
    try:
        await goal_service.delete(ctx.deps.db, goal_id)
    except NotFound as e:
        raise ModelRetry(f"There is no goal {goal_id}; see goals.") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Removed goal {goal_id}", body=reason)
    return f"Goal {goal_id} removed."


workout_tools = _toolset(requires_approval=True)
"""The workout library's writes, loaded with the workouts capability; each needs approval."""
WORKOUT_FIELDS = ("id", "name", "sport_type", "description", "segments")


def _workout_view(row: dict[str, Any]) -> dict[str, Any]:
    return _readable({k: row.get(k) for k in WORKOUT_FIELDS})


@workout_tools.tool
async def save_workout(ctx: RunContext[AgentDeps], workout: NewWorkout, reason: str) -> dict[str, Any]:
    """Save a workout to the library, when the athlete asks, so sessions can reuse it; a run goes
    to the Garmin library too."""
    try:
        row = await workout_library.create(ctx.deps.z2, ctx.deps.db, workout, ctx.deps.schedule)
    except ServiceError as e:
        raise ModelRetry(f"It wasn't saved: {e.message}") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Saved the workout {row['name']}", body=reason)
    return _workout_view(row)


@workout_tools.tool
async def change_workout(ctx: RunContext[AgentDeps], workout_id: int, changes: WorkoutChanges,
                         reason: str) -> dict[str, Any]:
    """Change a saved workout's name, description or steps, when the athlete asks. Upcoming
    sessions planned from it take the new steps; past ones keep theirs."""
    try:
        before = await workout_library.get(ctx.deps.db, workout_id)
    except NotFound as e:
        raise ModelRetry(f"There is no saved workout {workout_id}; see saved_workouts.") from e
    try:
        after = await workout_library.update(ctx.deps.z2, ctx.deps.db, workout_id, changes, ctx.deps.schedule)
    except ServiceError as e:
        raise ModelRetry(f"That change didn't apply: {e.message}") from e
    body = f"{reason}\n{_changes(before, after, _set_fields(changes))}"
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed the workout {before['name']}", body=body)
    return _workout_view(after)


@workout_tools.tool
async def remove_workout(ctx: RunContext[AgentDeps], workout_id: int, reason: str) -> str:
    """Delete a saved workout and its Garmin copy, when the athlete asks. Sessions planned from it
    keep their steps."""
    try:
        workout = await workout_library.delete(ctx.deps.z2, ctx.deps.db, workout_id, ctx.deps.schedule)
    except NotFound as e:
        raise ModelRetry(f"There is no saved workout {workout_id}; see saved_workouts.") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Deleted the workout {workout['name']}",
                        body=reason)
    return f"Workout {workout_id} deleted."
