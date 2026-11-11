"""The coach's training plans: a block of sessions toward a race, its checkpoints, and
how it is going (sessions done, execution scores, weekly km, the prediction against the
goal). Shared by the coach router and the agent."""

import asyncio
import math
from datetime import date, timedelta
from typing import Any

import aiosqlite

from backend.db import insert_row, row_dict, update_row
from backend.services import training
from backend.services.session_scores import accomplished, activities_by_day, score_sessions, session_matches
from backend.services.sessions import session_dict
from backend.services.stats_cache import get_race_predictions_history_cached
from backend.services.zones import resolve_hr_zones
from backend.scoring import has_targets
from zone2.core import Zone2
from zone2.utils import SportCategory, get_sport_category

PLAN_JSON = ("phases",)
# Garmin's daily race predictions, by the distance they predict
GARMIN_PREDICTIONS = {5000: "time_5k_s", 10000: "time_10k_s", 21097.5: "time_half_s", 42195: "time_marathon_s"}
# Garmin's prediction is the plan's when it is this recent; older, the plan falls back to z2's
GARMIN_FRESH_DAYS = 7


def plan_dict(row: aiosqlite.Row) -> dict:
    return row_dict(row, json_cols=PLAN_JSON)


async def list_plans(db: aiosqlite.Connection, include_done: bool = True) -> list[dict]:
    where = "" if include_done else " WHERE status = 'active'"
    rows = await (await db.execute(f"SELECT * FROM training_plans{where} ORDER BY start_date DESC")).fetchall()
    return [plan_dict(r) for r in rows]


async def get_plan(db: aiosqlite.Connection, plan_id: int) -> dict | None:
    row = await (await db.execute("SELECT * FROM training_plans WHERE id = ?", (plan_id,))).fetchone()
    return plan_dict(row) if row else None


async def create_plan(db: aiosqlite.Connection, values: dict) -> dict:
    return plan_dict(await insert_row(db, "training_plans", values, json_cols=PLAN_JSON))


async def update_plan(db: aiosqlite.Connection, plan_id: int, values: dict) -> dict:
    return plan_dict(await update_row(db, "training_plans", plan_id, values, "Plan not found", json_cols=PLAN_JSON))


async def link_sessions(db: aiosqlite.Connection, plan_id: int | None, session_ids: list[int]) -> int:
    """Put sessions in a plan (or out of any, with None); returns how many changed."""
    if not session_ids:
        return 0
    marks = ",".join("?" * len(session_ids))
    cur = await db.execute(f"UPDATE training_sessions SET plan_id = ? WHERE id IN ({marks})", (plan_id, *session_ids))
    await db.commit()
    return cur.rowcount


async def plan_sessions(db: aiosqlite.Connection, plan_id: int) -> list[dict]:
    rows = await (await db.execute(
        "SELECT * FROM training_sessions WHERE plan_id = ? ORDER BY date, id", (plan_id,),
    )).fetchall()
    return [session_dict(r) for r in rows]


async def race_of(db: aiosqlite.Connection, plan: dict) -> dict | None:
    if plan.get("race_event_id") is None:
        return None
    row = await (await db.execute("SELECT * FROM race_events WHERE id = ?", (plan["race_event_id"],))).fetchone()
    return row_dict(row) if row else None


async def checkpoints(db: aiosqlite.Connection, plan_id: int) -> list[dict]:
    rows = await (await db.execute(
        "SELECT * FROM plan_checkpoints WHERE plan_id = ? ORDER BY date, id", (plan_id,),
    )).fetchall()
    return [row_dict(r) for r in rows]


async def add_checkpoint(db: aiosqlite.Connection, values: dict) -> dict:
    return row_dict(await insert_row(db, "plan_checkpoints", values))


async def update_checkpoint(db: aiosqlite.Connection, checkpoint_id: int, values: dict) -> dict:
    return row_dict(await update_row(db, "plan_checkpoints", checkpoint_id, values, "Checkpoint not found"))


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _phase_on(phases: list[dict] | None, day: str) -> dict | None:
    return next((p for p in phases or [] if p.get("start", "") <= day <= p.get("end", "")), None)


async def _prediction(z2: Zone2, db: aiosqlite.Connection, plan: dict, race: dict | None,
                      sport: SportCategory, trend: bool) -> dict[str, Any] | None:
    """The race distance's prediction now and its weekly trend over the plan, z2's and Garmin's.
    `now_s` is Garmin's when it predicts the distance and predicted it lately (its `source`),
    else z2's; `z2_now_s` and `range_s` are z2's either way."""
    if not race or not race.get("distance_km") or sport not in z2.strava_analytics.RECORD_SPORTS:
        return None
    metres = race["distance_km"] * 1000
    analytics = z2.strava_analytics
    now = await asyncio.to_thread(analytics.get_race_predictions, sport)
    candidates = now.get("predictions") or []
    if not candidates:
        return None
    target = min(candidates, key=lambda p: abs(p["distance_m"] - metres))
    z2_now = target.get("predicted_time_s")
    now_only = {"distance": target["label"], "goal_s": plan.get("goal_time_s"), "now_s": z2_now, "source": "z2",
                "z2_now_s": z2_now, "range_s": [target.get("predicted_time_low_s"), target.get("predicted_time_high_s")],
                "z2": [], "garmin": []}
    # Garmin predicts four distances; it counts only when it predicts the same one as z2
    garmin_distance = min(GARMIN_PREDICTIONS, key=lambda m: abs(m - target["distance_m"]))
    garmin_key = (GARMIN_PREDICTIONS[garmin_distance]
                  if sport == SportCategory.RUNNING and abs(garmin_distance - target["distance_m"]) < 0.01 * garmin_distance else None)
    if garmin_key:
        recent = await asyncio.to_thread(z2.garmin_cache.get_summary_range, "race_predictions",
                                         (date.today() - timedelta(days=GARMIN_FRESH_DAYS)).isoformat(),
                                         date.today().isoformat())
        latest = next((r["summary"][garmin_key] for r in reversed(recent) if r["summary"].get(garmin_key)), None)
        if latest:
            now_only.update(now_s=latest, source="garmin")
    if not trend:
        return now_only
    # A finished plan's trend stops at its end
    upto = min(date.today().isoformat(), plan["end_date"])
    weeks = max(1, math.ceil((date.today() - date.fromisoformat(plan["start_date"])).days / 7) + 1)
    history = await asyncio.to_thread(get_race_predictions_history_cached, z2, sport, min(weeks, 104), 7)
    z2_trend = [
        {"date": point["end_date"], "time_s": p["predicted_time_s"]}
        for point in history
        for p in point.get("predictions", [])
        if p["distance_m"] == target["distance_m"] and plan["start_date"] <= point["end_date"] <= upto
    ]
    garmin: list[dict] = []
    if garmin_key:
        rows = await asyncio.to_thread(z2.garmin_cache.get_summary_range, "race_predictions",
                                       plan["start_date"], upto)
        garmin = [{"date": r["date"], "time_s": r["summary"][garmin_key]} for r in rows if r["summary"].get(garmin_key)]
    return {**now_only, "z2": z2_trend, "garmin": garmin}


async def progress(z2: Zone2, db: aiosqlite.Connection, plan: dict, race: dict | None, *,
                   detail: bool = True) -> dict[str, Any]:
    """How the plan is going today: sessions done of those due, execution scores, km per
    week (target, planned, run), the race prediction against the goal, and current form.
    `race` is the plan's (race_of). Without `detail` (a list of plans), the prediction's
    trend and the form are left out."""
    today = date.today()
    today_iso = today.isoformat()
    sessions = await plan_sessions(db, plan["id"])
    sport = get_sport_category((race or {}).get("sport_type") or "Run")
    span_start = min([plan["start_date"], *(s["date"] for s in sessions)])
    span_end = min(today_iso, max([plan["end_date"], *(s["date"] for s in sessions)]))
    activity_map = (await asyncio.to_thread(activities_by_day, z2, span_start, span_end)
                    if span_start <= span_end else {})

    status: dict[int, dict[str, Any]] = {}
    due = done = 0
    # The activity that fulfilled each session, scored or not, so every done session links to it
    fulfilled = {s["id"]: a.get("id") for s, a in session_matches(sessions, activity_map)}
    for s in sessions:
        is_done = s["date"] <= today_iso and accomplished(s, activity_map.get(s["date"], []))
        # Today's session isn't missed until the day is over
        if s["date"] < today_iso or is_done:
            due += 1
            done += is_done
        status[s["id"]] = {"done": is_done, "score": None, "activity_id": fulfilled.get(s["id"]) if is_done else None}

    scorable = [s for s in sessions if s["date"] <= today_iso and has_targets(s)]
    if scorable:
        zones = (await resolve_hr_zones(z2, db))["zones"]
        scores = await asyncio.to_thread(score_sessions, z2, scorable, span_start, span_end, zones)
        for session_id, score in scores.items():
            if score:
                status[session_id].update(score=score["overall_score"], activity_id=score["matched_activity_id"])
    scored = [v["score"] for v in status.values() if v["score"] is not None]

    weeks = []
    monday = _monday(date.fromisoformat(plan["start_date"]))
    while monday.isoformat() <= plan["end_date"]:
        sunday = monday + timedelta(days=6)
        lo, hi = monday.isoformat(), sunday.isoformat()
        run_km = sum(
            a.get("distance_km") or 0
            for d, acts in activity_map.items() if lo <= d <= hi
            for a in acts if get_sport_category(a.get("sport_type")) == sport
        )
        phase = _phase_on(plan.get("phases"), lo) or _phase_on(plan.get("phases"), hi)
        weeks.append({
            "week_start": lo,
            "phase": phase.get("name") if phase else None,
            "target_km": phase.get("target_km") if phase else None,
            "planned_km": round(sum(s.get("planned_distance_km") or 0 for s in sessions if lo <= s["date"] <= hi), 1),
            "done_km": round(run_km, 1) if lo <= today_iso else None,
        })
        monday += timedelta(weeks=1)

    result = None
    if race and race.get("date") and race["date"] <= today_iso:
        # The race itself: the activity of its sport on its day closest to its distance
        runs = [a for a in activity_map.get(race["date"], []) if get_sport_category(a.get("sport_type")) == sport]
        if runs:
            target_km = race.get("distance_km") or 0
            raced = min(runs, key=lambda a: abs((a.get("distance_km") or 0) - target_km))
            result = {"activity_id": raced.get("id"), "time_s": raced.get("elapsed_time") or raced.get("moving_time"),
                      "distance_km": raced.get("distance_km")}

    now = None
    if detail:
        fitness = await training.fitness_form(z2, db, 30)
        now = next((d for d in reversed(fitness.get("series", [])) if not d["projected"]), None)
    race_day = (race or {}).get("date") or plan["end_date"]
    phase_now = _phase_on(plan.get("phases"), today_iso)
    return {
        "today": today_iso,
        "days_to_race": (date.fromisoformat(race_day) - today).days,
        "phase": phase_now.get("name") if phase_now else None,
        "sessions": {"total": len(sessions), "due": due, "done": done,
                     "completion_pct": round(done / due * 100) if due else None},
        "score": {"average": round(sum(scored) / len(scored)) if scored else None, "scored": len(scored)},
        "weeks": weeks,
        "prediction": await _prediction(z2, db, plan, race, sport, trend=detail),
        "result": result,
        "form": {k: now[k] for k in ("date", "fitness", "fatigue", "form_pct")} if now else None,
        "session_status": status,
    }
