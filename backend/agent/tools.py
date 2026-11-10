"""The agent's tools over z2's services. Reads return compact shapes, since every
field costs tokens; writes need the user's approval before they run."""

import asyncio
import calendar
import datetime
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, Any, Literal

import aiosqlite
import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from backend.db import delete_row, insert_row, row_dict, update_row
from backend.agent import notes
from backend.services import activities as activity_service, coach_log, garmin_workouts, plans, session_scores
from backend.services import day_timeline, workout_library
from backend.services import gear as gear_service
from backend.services import goals as goal_service
from backend.services.races import races_changed
from backend.services import sessions as planned_sessions
from backend.services import training
from backend.services.activity_cost import activity_cost
from backend.services.briefing import today_briefing
from backend.services.resting_hr import resolve_resting_hr
from backend.services.sessions import Schedule, session_dict
from backend.services.zones import resolve_hr_zones
from zone2.core import Zone2
from zone2.drift import heart_rate_drift
from zone2.hr_recovery import heart_rate_recovery
from zone2.streams_store import detect_stops
from zone2.utils import format_pace_or_speed, get_sport_category


@dataclass
class AgentDeps:
    z2: Zone2
    db: aiosqlite.Connection
    schedule: Schedule
    page: str | None = None
    """What the user is looking at, e.g. "activity 1234" or "calendar, week of 2026-11-09"."""
    voice: bool = False
    """The user is talking, and hears the reply."""
    earlier: str | None = None
    """The end of the previous session, when this turn is in a later one."""
    first_name: str | None = None
    """The athlete's first name on Strava, read once per turn."""
    sync: Callable[[int | None], Awaitable[str | None]] | None = None
    """Syncs Strava and Garmin now, or one activity again by its id, and returns what went wrong."""


SportCategory = Literal["running", "cycling", "swimming"]
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


def _pace(speed: Any, sport_type: str | None) -> str | None:
    return format_pace_or_speed(speed, sport_type) if _num(speed, 3) else None


def _paused(lap: dict[str, Any]) -> dict[str, Any]:
    """A lap's elapsed time when pauses stretched it: auto-pause on a slow jog
    shortens a recovery's moving time, not the recovery itself."""
    elapsed, moving = lap.get("elapsed_time"), lap.get("moving_time")
    return {"elapsed": _hms(elapsed)} if elapsed and moving and elapsed - moving >= 5 else {}


PACE_FIELDS = ("target_pace_min", "target_pace_max", "target_avg_pace", "target_pace")


def _clock_pace(decimal_min: Any) -> Any:
    """Decimal minutes per km as m:ss/km (4.5 → "4:30/km"), the way people read a pace."""
    if not isinstance(decimal_min, (int, float)):
        return decimal_min
    m, s = divmod(round(decimal_min * 60), 60)
    return f"{m}:{s:02d}/km"


def _readable(row: dict[str, Any]) -> dict[str, Any]:
    """A session, workout or race with its paces as m:ss/km and empty fields dropped."""
    out = {k: (_clock_pace(v) if k in PACE_FIELDS else v) for k, v in row.items()
           if v is not None and k != "created_at"}
    if isinstance(out.get("segments"), list):
        out["segments"] = [{k: (_clock_pace(v) if k in PACE_FIELDS else v) for k, v in seg.items() if v is not None}
                           for seg in out["segments"]]
    return out


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _activity(row: pd.Series, race_ids: frozenset[int]) -> dict[str, Any]:
    sport_type = row.get("sport_type")
    return {
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
        "race": int(row["id"]) in race_ids or row.get("workout_type") in STRAVA_RACE_TYPES,
    }


read_tools = FunctionToolset[AgentDeps]()


@read_tools.tool
async def today(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """Today at a glance: planned sessions, what's already done, last night's recovery
    (Garmin readiness, sleep, HRV, body battery, resting HR), current fitness and form,
    races in the next few days, and z2's own suggestion weighing them."""
    z2 = ctx.deps.z2
    view = z2.strava_activities_cache.get_prepared_view()
    done = view[view["start_date_local"].dt.date == date.today()] if not view.empty else view
    race_ids = z2.strava_analytics.race_activity_ids
    return await today_briefing(z2, ctx.deps.db, [_activity(r, race_ids) for _, r in done.iterrows()])


@read_tools.tool
async def athlete(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """The athlete's heart-rate zones (bpm, zone 1 to 5), max HR, lactate-threshold HR when
    Garmin provides it, and resting HR, with where each comes from."""
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
    """Search the full activity history (every recorded activity, back to the first one).

    Args:
        sport: Only this sport category.
        date_from: First local day included.
        date_to: Last local day included.
        name_contains: Case-insensitive text in the activity name.
        min_km: Shortest distance included.
        max_km: Longest distance included.
        races_only: Only activities that were races (from the race calendar).
        sort_by: "pace" sorts by average speed, so descending puts the fastest first.
        descending: Largest (or latest) first.
        limit: How many to return; `total` still counts every match.
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


@read_tools.tool
async def activity_detail(ctx: RunContext[AgentDeps], activity_id: int) -> dict[str, Any]:
    """One activity in depth: its description, per-km splits, laps (intervals show up here),
    best efforts, for runs the heart-rate drift (decoupling) and the HR drop after each rep,
    and what it cost by Garmin: body battery used, recovery time, and the night after it."""
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
        {"name": lap.get("name"), "distance_km": _num(lap.get("distance", 0) / 1000, 2),
         "time": _hms(lap.get("moving_time")), **_paused(lap), "pace": _pace(lap.get("average_speed"), sport_type),
         "avg_hr": _num(lap.get("average_heartrate")), "max_hr": _num(lap.get("max_heartrate"))}
        for lap in laps
    ]
    detail["best_efforts"] = [
        {"name": e.get("name"), "time": _hms(e.get("moving_time"))} for e in _json(row.get("best_efforts")) or []
    ]
    if get_sport_category(sport_type) == "running":
        streams = await asyncio.to_thread(cache.get_streams, activity_id)
        if streams:
            detail["hr_drift"] = heart_rate_drift(streams)
            detail["hr_recovery"] = heart_rate_recovery(streams)
            detail["stops"] = [
                {"at_km": _num(st["start_km"], 2), "at": _hms(st["start_s"]), "seconds": _num(st["duration_s"])}
                for st in detect_stops(streams)
            ]
    cost = await asyncio.to_thread(activity_cost, ctx.deps.z2, activity_id)
    if cost and any(cost.values()):
        detail["garmin"] = {k: v for k, v in cost.items() if v is not None}
    return detail


@read_tools.tool
async def similar_activities(ctx: RunContext[AgentDeps], activity_id: int,
                             limit: Annotated[int, Field(ge=1, le=20)] = 6) -> list[dict[str, Any]]:
    """The latest activities like this one: same sport, within 10% of its distance and 20% of
    its climb. The like-for-like comparison for a run that wasn't a saved workout, e.g. pace at
    the same heart rate on the usual easy loop."""
    df = await asyncio.to_thread(activity_service.similar, ctx.deps.z2, activity_id, limit)
    if df is None:
        raise ModelRetry(f"There is no activity {activity_id}; find it with find_activities first.")
    race_ids = ctx.deps.z2.strava_analytics.race_activity_ids
    return [_activity(r, race_ids) for _, r in df.iterrows()]


@read_tools.tool
async def personal_records(ctx: RunContext[AgentDeps], sport: SportCategory = "running") -> list[dict[str, Any]]:
    """All-time fastest best effort at each standard distance, with the activity it came from."""
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
    sport: SportCategory = "running",
    history_weeks: Annotated[int, Field(ge=0, le=104)] = 0,
) -> dict[str, Any]:
    """Predicted race times now, with a likely range, the current best at each distance,
    Garmin's own prediction, and training paces derived from them.

    Args:
        sport: Sport category.
        history_weeks: Also return how the predictions moved, one point a week, over this many weeks.
    """
    analytics = ctx.deps.z2.strava_analytics
    result = await asyncio.to_thread(analytics.get_race_predictions, sport)
    out: dict[str, Any] = {
        "predictions": [
            {"distance": p["label"], "predicted": _hms(p.get("predicted_time_s")),
             "range": [_hms(p.get("predicted_time_low_s")), _hms(p.get("predicted_time_high_s"))],
             "current_best": _hms(p.get("pr_time_s")), "current_best_date": str(p.get("pr_date") or "")[:10] or None,
             "garmin": _hms(p.get("garmin_time_s"))}
            for p in result.get("predictions", [])
        ],
        "training_paces": _training_paces(result.get("training_paces")),
        "confidence": result.get("confidence"),
    }
    if history_weeks:
        points = await asyncio.to_thread(analytics.get_race_predictions_history, sport, weeks=history_weeks, step_days=7)
        out["history"] = points
    return out


@read_tools.tool
async def fitness(ctx: RunContext[AgentDeps], days: Annotated[int, Field(ge=30, le=730)] = 90) -> dict[str, Any]:
    """Fitness (42-day load), fatigue (7-day load) and form (fitness minus fatigue, as a
    share of fitness) over the last `days`: weekly points, every day of the last week, and
    weekly points ahead projected from the planned sessions."""
    result = await training.fitness_form(ctx.deps.z2, ctx.deps.db, days)
    series = result.get("series", [])
    recent_from = (date.today() - timedelta(days=7)).isoformat()
    keep = [
        d for i, d in enumerate(series)
        if (d["date"] >= recent_from and not d["projected"]) or i % 7 == 0 or d is series[-1]
    ]
    fields = ("date", "fitness", "fatigue", "form_pct", "projected")
    return {"series": [{k: d.get(k) for k in fields} for d in keep], "races": result.get("races", [])}


@read_tools.tool
async def weekly_volume(
    ctx: RunContext[AgentDeps],
    weeks: Annotated[int, Field(ge=1, le=52)] = 12,
    sport_type: str | None = None,
) -> list[dict[str, Any]]:
    """Distance and number of activities per week (Monday to Sunday), this week included.

    Args:
        weeks: How many weeks back.
        sport_type: A Strava sport type such as "Run" or "Ride"; all sports when omitted.
    """
    result = await asyncio.to_thread(training.weekly_totals, ctx.deps.z2, weeks, sport_type)
    return [{"week_start": w["week_start"], "km": w["total_distance_km"], "activities": w["total_activities"]}
            for w in result["data"]]


@read_tools.tool
async def planned_sessions_between(ctx: RunContext[AgentDeps], date_from: date, date_to: date) -> list[dict[str, Any]]:
    """The training calendar: planned sessions between two days, inclusive, with their ids,
    targets, steps and plan, and for those already done their execution score (0-100) and the
    activity that fulfilled them."""
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
    """Past sessions planned from the same saved workout, latest first, each with what was
    actually run that day: the like-for-like comparison for a session. Give the session or
    its saved workout. Open a run with activity_detail to compare reps."""
    db = ctx.deps.db
    if workout_template_id is None:
        if session_id is None:
            raise ModelRetry("Give session_id or workout_template_id.")
        row = await (await db.execute(
            "SELECT workout_template_id FROM training_sessions WHERE id = ?", (session_id,),
        )).fetchone()
        if row is None or row["workout_template_id"] is None:
            raise ModelRetry(f"Session {session_id} isn't planned from a saved workout; try find_activities by name.")
        workout_template_id = row["workout_template_id"]
    rows = await (await db.execute(
        "SELECT id, date, title FROM training_sessions WHERE workout_template_id = ? AND date <= ? "
        "ORDER BY date DESC LIMIT ?",
        (workout_template_id, date.today().isoformat(), limit),
    )).fetchall()
    z2 = ctx.deps.z2
    view = z2.strava_activities_cache.get_prepared_view()
    race_ids = z2.strava_analytics.race_activity_ids
    day = view["start_date_local"].dt.strftime("%Y-%m-%d") if not view.empty else None
    out = []
    for r in rows:
        done = view[day == r["date"]] if day is not None else view
        out.append({"session_id": r["id"], "date": r["date"], "title": r["title"],
                    "activities": [_activity(a, race_ids) for _, a in done.iterrows()]})
    return out


@read_tools.tool
async def races(ctx: RunContext[AgentDeps], include_past: bool = False) -> list[dict[str, Any]]:
    """Races in the race calendar: date, name, sport, distance and target pace."""
    query = "SELECT * FROM race_events" + ("" if include_past else " WHERE date >= ?") + " ORDER BY date"
    params = () if include_past else (date.today().isoformat(),)
    rows = await (await ctx.deps.db.execute(query, params)).fetchall()
    return [_readable(row_dict(r)) for r in rows]


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
            out[key.replace("_seconds", "")] = _hms(value)[:-3] if value >= 3600 else f"0:{int(value) // 60:02d}"
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
    """Garmin's daily wellness: sleep, HRV, training readiness, body battery, stress, resting HR
    (`heart_rates`), training status (acute and chronic load), Garmin's own race predictions
    (`race_predictions`) and VO2 max (`max_metrics`). At most 62 days.

    Args:
        date_from: First day.
        date_to: Last day.
        metrics: Which metrics; all of them when omitted.
    """
    if (date_to - date_from).days >= MAX_WELLNESS_DAYS:
        raise ModelRetry(f"Ask for at most {MAX_WELLNESS_DAYS} days at a time.")
    cache = ctx.deps.z2.garmin_cache
    wanted = metrics or list(WellnessMetric.__args__)
    out: dict[str, list[dict[str, Any]]] = {}
    for metric in wanted:
        rows = await asyncio.to_thread(cache.get_summary_range, metric, date_from.isoformat(), date_to.isoformat())
        out[metric] = [{"date": r["date"], **_wellness_day(metric, r["summary"])} for r in rows]
    return out


@read_tools.tool
async def saved_workouts(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
    """The workout library: saved workouts with their steps, which sessions can reuse."""
    rows = await (await ctx.deps.db.execute(
        "SELECT id, name, sport_type, description, segments FROM workout_templates ORDER BY name",
    )).fetchall()
    return [_readable(row_dict(r, json_cols=("segments",))) for r in rows]


@read_tools.tool
async def plans_overview(ctx: RunContext[AgentDeps], include_done: bool = False) -> list[dict[str, Any]]:
    """The coach's training plans: each block toward a race with its goal, dates, sessions done
    of those due, and average execution score."""
    out = []
    for plan in await plans.list_plans(ctx.deps.db, include_done):
        progress = await plans.progress(ctx.deps.z2, ctx.deps.db, plan, detail=False)
        out.append({"id": plan["id"], "name": plan["name"], "status": plan["status"], "goal": plan.get("goal"),
                    "start_date": plan["start_date"], "end_date": plan["end_date"],
                    "days_to_race": progress["days_to_race"], "phase": progress["phase"],
                    "sessions": progress["sessions"], "average_score": progress["score"]["average"]})
    return out


@read_tools.tool
async def plan_detail(ctx: RunContext[AgentDeps], plan_id: int) -> dict[str, Any]:
    """One plan in full: phases, weekly km (target, planned, run), the race prediction against the
    goal, its sessions with whether each was done and its execution score, its checkpoints,
    and the latest entries of the coach's log."""
    db = ctx.deps.db
    plan = await plans.get_plan(db, plan_id)
    if plan is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    progress = await plans.progress(ctx.deps.z2, db, plan)
    status = progress.pop("session_status")
    pred = progress["prediction"]
    if pred:
        # Race times as h:mm:ss, so a trend reads the right way round (lower is faster)
        garmin = pred["garmin"][::7] + pred["garmin"][-1:] if pred["garmin"] else []
        progress["prediction"] = {
            "distance": pred["distance"],
            "predicted_now": _hms(pred["now_s"]),
            "range": [_hms(t) for t in pred["range_s"]],
            "z2_weekly": [{"date": d["date"], "predicted": _hms(d["time_s"])} for d in pred["z2"]],
            "garmin_daily": [{"date": d["date"], "predicted": _hms(d["time_s"])} for d in garmin],
        }
    if progress.get("result"):
        progress["result"] = {**progress["result"], "time": _hms(progress["result"].pop("time_s"))}
    keep = ("id", "date", "title", "sport_type", "planned_distance_km", "planned_intensity", "garmin_sync_state")
    goal_s = plan.get("goal_time_s")
    return {
        **{k: v for k, v in plan.items() if k not in ("created_at", "goal_time_s")},
        "goal_time": _hms(goal_s) if goal_s is not None else None,
        "race": await plans.race_of(db, plan),
        "progress": progress,
        "sessions": [{**{k: s.get(k) for k in keep if s.get(k) is not None}, **status[s["id"]]}
                     for s in await plans.plan_sessions(db, plan_id)],
        "checkpoints": await plans.checkpoints(db, plan_id),
        "log": [{**{k: v for k, v in e.items() if v is not None and k not in ("created_at", "body")},
                 "body": (e.get("body") or "")[:240]}
                for e in await coach_log.entries(db, plan_id, limit=8)],
    }


@read_tools.tool
async def goals(ctx: RunContext[AgentDeps], year: int | None = None) -> list[dict[str, Any]]:
    """The athlete's goals for a year (this year when omitted): each a target per week, month
    or year for a sport (or all sports), with the value so far in the current period."""
    ref = date.today() if year is None or year == date.today().year else date(year, 12, 31)
    rows = await goal_service.progress(ctx.deps.z2, ctx.deps.db, ref)
    keep = ("id", "year", "sport_type", "metric", "period", "target_value", "current_value", "percentage",
            "period_start", "period_end")
    return [{k: g[k] for k in keep if k in g} for g in rows]


# ── Athlete notes: the agent's memory of this athlete ───────────────────

memory_tools = FunctionToolset[AgentDeps]()


@memory_tools.tool
async def remember(ctx: RunContext[AgentDeps], note: str,
                   topic: Literal["kit", "body", "plan", "rules", "preferences"]) -> str:
    """Keep a durable fact about the athlete for every later conversation: a preference, a
    constraint, a baseline, an equipment change, or a lesson from a session ("HR sensor changed
    to a chest strap on 3 March: don't compare HR across that date"). One fact per note,
    dated when the date matters. Not for anything z2's data already holds. `topic`: kit (sensors,
    GPS, devices), body (HR limits, baselines, injuries), plan (goal, agreed thresholds), rules
    (how the week is built) or preferences (how they like to be coached, habits)."""
    note_id = await notes.add(ctx.deps.db, note, notes.Topic(topic))
    return f"Noted ({note_id})."


@memory_tools.tool
async def forget(ctx: RunContext[AgentDeps], note_id: int) -> str:
    """Drop a note that is wrong or no longer true. Its id is shown in the notes."""
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
    """Write to the coach's log, which the Coach page shows: a session `review` against its
    target and guardrail, a checkpoint `decision`, a `summary` of a week, or a `suggestion`
    for a change you recommend. A suggestion changes nothing: the plan changes only when the
    athlete asks for it.

    Args:
        kind: What the entry is.
        title: One line, e.g. "2×4 km: guardrail broken at 1.5 km".
        body: The detail, in a few lines; tables are fine.
        day: The day it is about; today when omitted.
        plan_id: The plan it belongs to.
        session_id: The planned session it is about.
        activity_id: The activity it is about.
    """
    entry = await coach_log.add(ctx.deps.db, kind=coach_log.Kind(kind), title=title, body=body,
                                day=day.isoformat() if day else None, plan_id=plan_id,
                                session_id=session_id, activity_id=activity_id)
    return f"Logged ({entry['id']})."


# ── Writes ──────────────────────────────────────────────────────────────

Pace = Annotated[float, Field(gt=2, lt=15, description="Decimal minutes per km: 4.5 means 4:30/km")]


class Step(BaseModel):
    """One step of a structured session. A `work` step with repetitions > 1 repeats with
    its recovery in between."""
    type: Literal["warmup", "work", "recovery", "cooldown", "rest"]
    distance_km: float | None = None
    duration_mins: float | None = None
    repetitions: int = 1
    recovery_distance_km: float | None = None
    recovery_duration_mins: float | None = None
    target_pace_min: Pace | None = Field(None, description="Fastest end of the pace target")
    target_pace_max: Pace | None = Field(None, description="Slowest end of the pace target")
    target_hr_zone: Annotated[int, Field(ge=1, le=5)] | None = None
    label: str | None = None


class SessionFields(BaseModel):
    title: str | None = None
    sport_type: str | None = Field(None, description='A Strava sport type: "Run", "Ride", "Swim", "WeightTraining", "Rest"…')
    description: str | None = None
    planned_distance_km: float | None = None
    planned_duration_mins: float | None = None
    planned_intensity: Literal["easy", "moderate", "hard", "race"] | None = None
    target_avg_pace: Pace | None = None
    target_pace_min: Pace | None = None
    target_pace_max: Pace | None = None
    target_hr_zone: Annotated[int, Field(ge=1, le=5)] | None = None
    segments: list[Step] | None = Field(None, description="Steps, for a structured session such as intervals")
    workout_template_id: int | None = Field(None, description="A saved workout to reuse")


class NewSession(SessionFields):
    plan_id: int | None = Field(None, description="The plan the session belongs to")
    date: datetime.date
    title: str
    sport_type: str = Field(description='A Strava sport type: "Run", "Ride", "Swim", "WeightTraining", "Rest"…')


class SessionChanges(SessionFields):
    date: datetime.date | None = None
    completed: bool | None = None


def _values(fields: BaseModel, **dump: Any) -> dict[str, Any]:
    """The columns to write, with steps holding only the fields they set."""
    values = fields.model_dump(mode="json", **dump)
    if values.get("segments"):
        values["segments"] = [{k: v for k, v in step.items() if v is not None} for step in values["segments"]]
    return values


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
    """Close one of your open suggestions in the coach's log: `done` once the change it proposed
    is made, `dismissed` when the athlete turned it down. plan_detail lists them with their ids."""
    if not await coach_log.set_status(ctx.deps.db, entry_id, coach_log.SuggestionStatus(status)):
        raise ModelRetry(f"Log entry {entry_id} isn't a suggestion; plan_detail lists the log with its ids.")
    return f"Suggestion {entry_id} is {status}."


app_tools = FunctionToolset[AgentDeps]()
"""Acting in the app without asking: syncing, and taking the athlete to a page."""


@app_tools.tool
async def sync_now(ctx: RunContext[AgentDeps], activity_id: int | None = None) -> str:
    """Sync Strava and Garmin now, when the athlete just finished something that isn't in z2
    yet (a message already syncs when the data is over 15 minutes old). With `activity_id`,
    fetch that activity again with its streams: its HR or GPS looks wrong, or it was edited on
    Strava."""
    if ctx.deps.sync is None:
        return "Syncing isn't available here."
    cache = ctx.deps.z2.strava_activities_cache
    before = len(cache.activities)
    if error := await ctx.deps.sync(activity_id):
        return f"The sync didn't finish: {error}"
    if activity_id is not None:
        return f"Activity {activity_id} is fetched again; read it with activity_detail."
    new = len(cache.activities) - before
    return f"Synced: {new} new {'activity' if new == 1 else 'activities'}." if new else "Synced: nothing new on Strava."


Page = Literal["activity", "plan", "gear", "calendar", "activities", "coach", "records", "workouts", "races",
               "analytics", "garmin", "dashboard", "coverage", "profile"]
PAGE_WITH_ID = {"activity": "/activities/{}", "plan": "/coach/{}", "gear": "/gear/{}"}


@app_tools.tool
async def open_page(ctx: RunContext[AgentDeps], page: Page, id: str | None = None) -> str:
    """Take the athlete to a page of the app when they ask to see something ("show me that run").
    `id` is the activity id for `activity`, the plan id for `plan` and the gear id for `gear`."""
    if page in PAGE_WITH_ID:
        if not id:
            raise ModelRetry(f"Give the {page}'s id to open it.")
        return PAGE_WITH_ID[page].format(id)
    return f"/{page}"


gear_tools = FunctionToolset[AgentDeps]()
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


history_tools = FunctionToolset[AgentDeps]()
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
    progress counts up to today, and so does `compare_to`, so "this year vs two years ago" is like for like.

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


sleep_tools = FunctionToolset[AgentDeps]()
"""One night in detail, loaded with the sleep capability."""


@sleep_tools.tool
async def night(ctx: RunContext[AgentDeps], day: date | None = None) -> dict[str, Any] | str:
    """One night in detail: when they fell asleep and woke, Garmin's score with each stage
    against its ideal share, awake spells, restlessness, breathing and SpO2, then hour by hour
    the minutes deep, light, REM and awake with the average heart rate, HRV, stress and body
    battery. `day` is the morning the night ended; today when omitted."""
    result = await asyncio.to_thread(day_timeline.night, ctx.deps.z2, day or date.today())
    if result is None:
        return "Garmin has no sleep for that night."
    for key in ("asleep", "awake"):
        result[key] = _hms(result.pop(f"{key}_seconds"))
    for stage in ("deep", "light", "rem"):
        result[stage]["time"] = _hms(result[stage].pop("seconds"))
    return result


write_tools = FunctionToolset[AgentDeps](requires_approval=True)


@write_tools.tool
async def add_session(ctx: RunContext[AgentDeps], session: NewSession, reason: str) -> dict[str, Any]:
    """Add a session to the training calendar, only when the athlete asked for it. A run with
    steps also goes to the watch. `reason` is what the athlete asked, for the coach's log."""
    created = await planned_sessions.create(ctx.deps.z2, ctx.deps.db, _values(session), ctx.deps.schedule)
    await _log_change(ctx, created, f"Added {created['title']} on {created['date']}", reason)
    return _readable(created)


@write_tools.tool
async def change_session(ctx: RunContext[AgentDeps], session_id: int, changes: SessionChanges,
                         reason: str) -> dict[str, Any]:
    """Change a planned session, only when the athlete asked for it: move it to another day, or
    change its title, targets or steps. Only the fields given change. `reason` is what the
    athlete asked, for the coach's log."""
    values = _values(changes, exclude_unset=True)
    row = await (await ctx.deps.db.execute("SELECT * FROM training_sessions WHERE id = ?", (session_id,))).fetchone()
    if row is None:
        raise ModelRetry(f"There is no session {session_id}; look it up with planned_sessions_between.")
    before = session_dict(row)
    try:
        after = await planned_sessions.update(ctx.deps.z2, ctx.deps.db, session_id, values, ctx.deps.schedule)
    except HTTPException as e:
        raise ModelRetry(f"That change didn't apply: {e.detail}") from e
    await _log_change(ctx, after, f"Changed {before['title']}", reason,
                      _changes(before, after, list(values)))
    return _readable(after)


@write_tools.tool
async def remove_session(ctx: RunContext[AgentDeps], session_id: int, reason: str) -> str:
    """Remove a planned session from the calendar (and its entry on the watch), only when the
    athlete asked for it. `reason` is what the athlete asked, for the coach's log."""
    row = await (await ctx.deps.db.execute("SELECT * FROM training_sessions WHERE id = ?", (session_id,))).fetchone()
    if row is None:
        raise ModelRetry(f"There is no session {session_id}; look it up with planned_sessions_between.")
    session = session_dict(row)
    await planned_sessions.delete(ctx.deps.z2, ctx.deps.db, session_id, ctx.deps.schedule)
    await _log_change(ctx, session, f"Removed {session['title']} on {session['date']}", reason)
    return f"Session {session_id} removed."


@write_tools.tool
async def resync_watch(ctx: RunContext[AgentDeps]) -> str:
    """Send the upcoming planned sessions to the watch again, when a session's
    `garmin_sync_state` reads failed."""
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
    goal: str | None = Field(None, description='The goal in words, e.g. "sub-50 10K"')
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
    """Create a training plan toward a race, once the athlete agreed to it, and put the given
    planned sessions in it. Add its sessions with add_session (plan_id) and its tests with
    add_checkpoint."""
    created = await plans.create_plan(ctx.deps.db, plan.model_dump(mode="json"))
    linked = await plans.link_sessions(ctx.deps.db, created["id"], session_ids or [])
    return {**created, "sessions_linked": linked}


@write_tools.tool
async def change_plan(ctx: RunContext[AgentDeps], plan_id: int, changes: PlanChanges, reason: str) -> dict[str, Any]:
    """Change a plan's goal, dates, phases, summary or status, only when the athlete asked for
    it. `reason` is what the athlete asked, for the coach's log."""
    values = changes.model_dump(mode="json", exclude_unset=True)
    before = await plans.get_plan(ctx.deps.db, plan_id)
    if before is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    try:
        after = await plans.update_plan(ctx.deps.db, plan_id, values)
    except HTTPException as e:
        raise ModelRetry(f"That change didn't apply: {e.detail}") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed the plan {after['name']}",
                        body=f"{reason}\n{_changes(before, after, list(values))}", plan_id=plan_id)
    return after


@write_tools.tool
async def link_sessions(ctx: RunContext[AgentDeps], plan_id: int, session_ids: list[int]) -> str:
    """Put existing planned sessions in a plan, so they count toward it."""
    if await plans.get_plan(ctx.deps.db, plan_id) is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    return f"{await plans.link_sessions(ctx.deps.db, plan_id, session_ids)} sessions now in plan {plan_id}."


@write_tools.tool
async def add_checkpoint(
    ctx: RunContext[AgentDeps], plan_id: int, day: datetime.date, title: str, rule: str, session_id: int | None = None,
) -> dict[str, Any]:
    """Add a checkpoint to a plan: a test or key session whose result decides how the plan goes on.
    `rule` holds the thresholds agreed with the athlete, written before it happens, e.g.
    "22:00 or faster keeps the goal; about 22:30 moves the target to the slower goal"."""
    if await plans.get_plan(ctx.deps.db, plan_id) is None:
        raise ModelRetry(f"There is no plan {plan_id}; see plans_overview.")
    return await plans.add_checkpoint(ctx.deps.db, {"plan_id": plan_id, "date": day.isoformat(), "title": title,
                                                    "rule": rule, "session_id": session_id})


@write_tools.tool
async def record_checkpoint(ctx: RunContext[AgentDeps], checkpoint_id: int, result: str, decision: str) -> dict[str, Any]:
    """Record a checkpoint's result and the decision its rule gives. This doesn't change the
    sessions: propose those changes, and make them once the athlete agrees."""
    try:
        checkpoint = await plans.update_checkpoint(ctx.deps.db, checkpoint_id, {"result": result, "decision": decision})
    except HTTPException as e:
        raise ModelRetry(f"There is no checkpoint {checkpoint_id}; see plan_detail.") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.DECISION, title=f"{checkpoint['title']}: {result}",
                        body=decision, day=checkpoint["date"], plan_id=checkpoint["plan_id"],
                        session_id=checkpoint.get("session_id"))
    return checkpoint


class RaceFields(BaseModel):
    name: str | None = None
    date: datetime.date | None = None
    sport_type: str | None = Field(None, description='A Strava sport type: "Run", "Ride", "Swim"…')
    distance_km: float | None = None
    target_pace: Pace | None = Field(None, description="Goal pace, decimal minutes per km")
    location: str | None = None
    url: str | None = Field(None, description="The race's public page. Never a registration link with a personal "
                                               "token: race links go out in the calendar feed.")
    description: str | None = None


class NewRace(RaceFields):
    name: str
    date: datetime.date
    sport_type: str = "Run"


@write_tools.tool
async def add_race(ctx: RunContext[AgentDeps], race: NewRace, reason: str) -> dict[str, Any]:
    """Add a race to the race calendar, when the athlete asks for it. Races decide which runs
    count as races in the predictions, and a plan can aim at one. `reason` goes in the coach's log."""
    row = row_dict(await insert_row(ctx.deps.db, "race_events", race.model_dump(mode="json")))
    await races_changed(ctx.deps.z2)
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Added the race {row['name']} on {row['date']}",
                        body=reason)
    return _readable(row)


@write_tools.tool
async def change_race(ctx: RunContext[AgentDeps], race_id: int, changes: RaceFields, reason: str) -> dict[str, Any]:
    """Change a race in the race calendar (its date, distance, goal pace…), when the athlete asks.
    Only the fields given change. `reason` goes in the coach's log."""
    values = changes.model_dump(mode="json", exclude_unset=True)
    try:
        row = row_dict(await update_row(ctx.deps.db, "race_events", race_id, values, "Race not found"))
    except HTTPException as e:
        raise ModelRetry(f"There is no race {race_id}; see races with include_past.") from e
    await races_changed(ctx.deps.z2)
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed the race {row['name']}",
                        body=f"{reason}\n" + ", ".join(values))
    return _readable(row)


GoalMetric = Literal["distance_km", "time_hours", "activities", "elevation_m"]
GoalPeriod = Literal["weekly", "monthly", "yearly"]


class GoalFields(BaseModel):
    year: int | None = None
    sport_type: str | None = Field(None, description='A Strava sport type ("Run", "Ride", "Swim"…) or "__all__"')
    metric: GoalMetric | None = None
    period: GoalPeriod | None = None
    target_value: Annotated[float, Field(gt=0)] | None = None


class NewGoal(GoalFields):
    year: int
    sport_type: str = Field(description='A Strava sport type ("Run", "Ride", "Swim"…) or "__all__"')
    metric: GoalMetric
    period: GoalPeriod
    target_value: Annotated[float, Field(gt=0)]


@write_tools.tool
async def set_goal(ctx: RunContext[AgentDeps], goal: NewGoal, reason: str) -> dict[str, Any]:
    """Add a goal, when the athlete asks: e.g. 2000 km of running in 2027 (yearly), or 3 strength
    sessions a week (activities, weekly). `reason` goes in the coach's log."""
    row = row_dict(await insert_row(ctx.deps.db, "goals", goal.model_dump()))
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, body=reason,
                        title=f"Set a goal: {row['target_value']:g} {row['metric']} {row['period']} ({row['sport_type']}, {row['year']})")
    return row


@write_tools.tool
async def change_goal(ctx: RunContext[AgentDeps], goal_id: int, changes: GoalFields, reason: str) -> dict[str, Any]:
    """Change a goal's target, period, sport or metric, when the athlete asks. `reason` goes in the coach's log."""
    values = changes.model_dump(exclude_unset=True)
    try:
        row = row_dict(await update_row(ctx.deps.db, "goals", goal_id, values, "Goal not found"))
    except HTTPException as e:
        raise ModelRetry(f"There is no goal {goal_id}; see goals.") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed goal {goal_id}",
                        body=f"{reason}\n" + ", ".join(f"{k}: {v}" for k, v in values.items()))
    return row


@write_tools.tool
async def remove_goal(ctx: RunContext[AgentDeps], goal_id: int, reason: str) -> str:
    """Remove a goal, when the athlete asks. `reason` goes in the coach's log."""
    try:
        await delete_row(ctx.deps.db, "goals", goal_id, "Goal not found")
    except HTTPException as e:
        raise ModelRetry(f"There is no goal {goal_id}; see goals.") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Removed goal {goal_id}", body=reason)
    return f"Goal {goal_id} removed."


workout_tools = FunctionToolset[AgentDeps](requires_approval=True)
"""The workout library's writes, loaded with the workouts capability; each needs approval."""
WORKOUT_FIELDS = ("id", "name", "sport_type", "description", "segments")


class WorkoutFields(BaseModel):
    name: str | None = Field(None, description='How it shows in the library and on the watch, e.g. "6×1 km @ threshold"')
    sport_type: str | None = Field(None, description='A Strava sport type: "Run", "Ride", "Swim"…')
    description: str | None = None
    segments: list[Step] | None = Field(None, description="Its steps")


class NewWorkout(WorkoutFields):
    name: str
    sport_type: str
    segments: list[Step]


async def _saved_workout(db: aiosqlite.Connection, workout_id: int) -> dict[str, Any]:
    row = await (await db.execute("SELECT * FROM workout_templates WHERE id = ?", (workout_id,))).fetchone()
    if row is None:
        raise ModelRetry(f"There is no saved workout {workout_id}; see saved_workouts.")
    return workout_library.template_dict(row)


def _workout_view(row: dict[str, Any]) -> dict[str, Any]:
    return _readable({k: row.get(k) for k in WORKOUT_FIELDS})


@workout_tools.tool
async def save_workout(ctx: RunContext[AgentDeps], workout: NewWorkout, reason: str) -> dict[str, Any]:
    """Save a workout to the library, when the athlete asks, so sessions can reuse it; a run goes
    to the Garmin library too. `reason` goes in the coach's log."""
    try:
        row = await workout_library.create(ctx.deps.z2, ctx.deps.db, _values(workout), ctx.deps.schedule)
    except HTTPException as e:
        raise ModelRetry(f"It wasn't saved: {e.detail}") from e
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Saved the workout {row['name']}", body=reason)
    return _workout_view(row)


@workout_tools.tool
async def change_workout(ctx: RunContext[AgentDeps], workout_id: int, changes: WorkoutFields,
                         reason: str) -> dict[str, Any]:
    """Change a saved workout, when the athlete asks: its name, description or steps. Upcoming
    sessions planned from it take the new steps; past ones keep theirs. `reason` goes in the
    coach's log."""
    before = await _saved_workout(ctx.deps.db, workout_id)
    values = _values(changes, exclude_unset=True)
    try:
        after = await workout_library.update(ctx.deps.z2, ctx.deps.db, workout_id, values, ctx.deps.schedule)
    except HTTPException as e:
        raise ModelRetry(f"That change didn't apply: {e.detail}") from e
    body = f"{reason}\n{_changes(before, after, list(values))}"
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Changed the workout {before['name']}", body=body)
    return _workout_view(after)


@workout_tools.tool
async def remove_workout(ctx: RunContext[AgentDeps], workout_id: int, reason: str) -> str:
    """Delete a saved workout and its Garmin copy, when the athlete asks. Sessions planned from it
    stay in the calendar with their steps. `reason` goes in the coach's log."""
    workout = await _saved_workout(ctx.deps.db, workout_id)
    await workout_library.delete(ctx.deps.z2, ctx.deps.db, workout_id, ctx.deps.schedule)
    await coach_log.add(ctx.deps.db, kind=coach_log.Kind.CHANGE, title=f"Deleted the workout {workout['name']}",
                        body=reason)
    return f"Workout {workout_id} deleted."
