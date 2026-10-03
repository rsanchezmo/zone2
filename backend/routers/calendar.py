from datetime import date, datetime, timedelta
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite
import pandas as pd

from backend._serialize import sanitize as _sanitize
from backend.db import delete_row, get_db, insert_row, row_dict, update_row
from backend.dependencies import get_z2
from backend.scoring import match_activity, compute_execution_score, has_targets
from backend.routers.activities import activities_on_dates
from backend.services import garmin_workouts
from backend.services.briefing import RACE_SOON_DAYS, recovery_today, suggest
from backend.services.resting_hr import resolve_resting_hr
from backend.services.zones import resolve_hr_zones, set_setting
from zone2.core import Zone2

logger = logging.getLogger(__name__)

router = APIRouter()

_JSON_COLS = ("segments",)


class SessionCreate(BaseModel):
    date: str  # YYYY-MM-DD
    title: str
    sport_type: str
    description: str | None = None
    planned_distance_km: float | None = None
    planned_duration_mins: float | None = None
    planned_intensity: str | None = None  # easy/moderate/hard/race
    target_avg_pace: float | None = None
    target_pace_min: float | None = None
    target_pace_max: float | None = None
    target_hr_zone: int | None = None
    target_zone_pct: float | None = None
    segments: list[dict] | None = None
    workout_template_id: int | None = None


class SessionUpdate(BaseModel):
    date: str | None = None
    title: str | None = None
    sport_type: str | None = None
    description: str | None = None
    planned_distance_km: float | None = None
    planned_duration_mins: float | None = None
    planned_intensity: str | None = None
    target_avg_pace: float | None = None
    target_pace_min: float | None = None
    target_pace_max: float | None = None
    target_hr_zone: int | None = None
    target_zone_pct: float | None = None
    segments: list[dict] | None = None
    workout_template_id: int | None = None
    completed: bool | None = None


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return row_dict(row, json_cols=_JSON_COLS, bool_cols=("completed",))


@router.get("/briefing")
async def briefing(z2: Zone2 = Depends(get_z2), db: aiosqlite.Connection = Depends(get_db)):
    """Today at a glance for the top of the calendar: the planned sessions,
    what's already done, last night's recovery (Garmin), current form and a
    suggestion weighing them."""
    today = date.today()
    cur = await db.execute("SELECT * FROM training_sessions WHERE date = ? ORDER BY id", (today.isoformat(),))
    sessions = [_row_to_dict(r) for r in await cur.fetchall()]
    done = (await run_in_threadpool(activities_on_dates, today.isoformat(), z2))["items"]
    recovery = await run_in_threadpool(recovery_today, z2.garmin_cache, today)
    zones = await resolve_hr_zones(z2, db)
    rhr = await resolve_resting_hr(z2, db)
    fitness = await run_in_threadpool(z2.strava_analytics.get_fitness_form, rhr["value"], zones["zones"], [], 1)
    # Today's row stands in for the plan until something is logged; form is yesterday's until then
    now = next((d for d in reversed(fitness["series"]) if not d["projected"]), None)
    form = {k: now[k] for k in ("date", "fitness", "fatigue", "form_pct")} if now else None
    cur = await db.execute(
        "SELECT date, name FROM race_events WHERE date BETWEEN ? AND ? ORDER BY date",
        (today.isoformat(), (today + timedelta(days=RACE_SOON_DAYS)).isoformat()),
    )
    races = [{"date": r["date"], "name": r["name"]} for r in await cur.fetchall()]
    return {
        "date": today.isoformat(),
        "sessions": sessions,
        "done": done,
        "recovery": recovery,
        "form": form,
        "suggestion": suggest(sessions, bool(done), recovery, form["form_pct"] if form else None, races, today),
    }


@router.get("/sessions")
async def list_sessions(
    date_from: str | None = None,
    date_to: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    if date_from and date_to:
        query = "SELECT * FROM training_sessions WHERE date >= ? AND date <= ? ORDER BY date"
        cursor = await db.execute(query, (date_from, date_to))
    else:
        cursor = await db.execute("SELECT * FROM training_sessions ORDER BY date")
    rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


_SCORING_COLUMNS = ("id", "sport_type", "distance", "moving_time", "average_speed",
                    "start_date_local", "average_heartrate")


def _activity_row_to_dict(row: pd.Series | dict) -> dict:
    """Minimal activity dict for scoring. Streams are fetched separately
    via the cache's StreamsStore — not attached to this dict."""
    d = {}
    for col in _SCORING_COLUMNS:
        if col in row:
            d[col] = _sanitize(row[col])
    if d.get("distance") is not None:
        d["distance_km"] = round(d["distance"] / 1000, 3)
    return d


def _activities_by_day(z2: Zone2, date_from: str, date_to: str) -> dict[str, list[dict]]:
    """Bucket cached activities within [date_from, date_to] (inclusive) by local day."""
    cache = z2.strava_activities_cache
    activities_df = cache.get_prepared_view()
    if activities_df.empty:
        return {}
    activities_df = activities_df[cache.days_mask(date_from, date_to)]

    activity_map: dict[str, list[dict]] = {}
    records = activities_df[[c for c in _SCORING_COLUMNS if c in activities_df.columns]].to_dict("records")
    for date_str, record in zip(activities_df["start_date_local"].dt.strftime("%Y-%m-%d"), records):
        activity_map.setdefault(date_str, []).append(_activity_row_to_dict(record))
    return activity_map


def _session_matches(sessions: list[dict], activity_map: dict[str, list[dict]]) -> list[tuple[dict, dict]]:
    """(session, activity) for each session an activity on its day matches."""
    pairs = []
    for session in sessions:
        matched = match_activity(session, activity_map.get(session["date"], []))
        if matched is not None:
            pairs.append((session, matched))
    return pairs


def _score_sessions(z2: Zone2, sessions: list[dict], date_from: str, date_to: str,
                    hr_zones: list | None) -> dict[int, dict | None]:
    """Execution score per session, None when no activity matches it."""
    pairs = _session_matches(sessions, _activities_by_day(z2, date_from, date_to))

    # Bulk-load only the matched activities' streams.
    matched_ids = [m["id"] for _, m in pairs if m.get("id") is not None]
    streams_map = z2.strava_activities_cache.get_streams_bulk(matched_ids) if matched_ids else {}

    result: dict[int, dict | None] = {s["id"]: None for s in sessions}
    for session, matched in pairs:
        streams = streams_map.get(int(matched["id"])) if matched.get("id") is not None else None
        result[session["id"]] = compute_execution_score(session, matched, hr_zones, streams)
    return result


def _activity_day(z2: Zone2, activity_id: int) -> str | None:
    row = z2.strava_activities_cache.get_activity_by_id(activity_id)
    if row is None or row.get("start_date_local") is None:
        return None
    sdt = row["start_date_local"]
    sdt = pd.to_datetime(sdt) if not hasattr(sdt, "strftime") else sdt
    return sdt.strftime("%Y-%m-%d")


def _score_activity(z2: Zone2, activity_id: int, date_str: str, sessions: list[dict],
                    hr_zones: list | None) -> dict | None:
    """Score of the session the calendar matches this activity to, if any."""
    for session, matched in _session_matches(sessions, _activities_by_day(z2, date_str, date_str)):
        if matched.get("id") is not None and int(matched["id"]) == activity_id:
            streams = z2.strava_activities_cache.get_streams(activity_id)
            return {"session": session, "score": compute_execution_score(session, matched, hr_zones, streams)}
    return None


@router.get("/sessions/scores")
async def get_session_scores(
    date_from: str = Query(...),
    date_to: str = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Bulk compute execution scores for sessions with targets in date range."""
    cursor = await db.execute(
        "SELECT * FROM training_sessions WHERE date >= ? AND date <= ? ORDER BY date",
        (date_from, date_to),
    )
    rows = await cursor.fetchall()
    sessions = [_row_to_dict(row) for row in rows]

    sessions_with_targets = [s for s in sessions if has_targets(s)]
    if not sessions_with_targets:
        return {}

    hr_zones = None
    try:
        hr_zones = (await resolve_hr_zones(z2, db))["zones"]
    except Exception as e:
        logger.debug("Could not load HR zones for scoring: %s", e)

    return await run_in_threadpool(_score_sessions, z2, sessions_with_targets, date_from, date_to, hr_zones)


@router.get("/sessions/accomplishment")
async def get_plan_accomplishment(
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Share of planned sessions that were actually executed.

    A session counts as accomplished when an activity of its sport exists on
    its day (rest days: when no activity does) or it was manually marked
    completed. Sessions planned for today that are still unfulfilled are
    excluded rather than counted as missed. Reported for all time and for a
    recent 28-day window.
    """
    window_days = 28
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    cursor = await db.execute(
        "SELECT * FROM training_sessions WHERE date <= ? ORDER BY date", (today,),
    )
    rows = await cursor.fetchall()
    sessions = [_row_to_dict(row) for row in rows]
    if not sessions:
        return {
            "total_planned": 0, "total_completed": 0, "rate": None,
            "recent_planned": 0, "recent_completed": 0, "recent_rate": None,
            "window_days": window_days,
        }

    activity_map = await run_in_threadpool(_activities_by_day, z2, sessions[0]["date"], today)
    recent_from = (now - timedelta(days=window_days)).strftime("%Y-%m-%d")

    total = completed = recent_total = recent_completed = 0
    for session in sessions:
        day_activities = activity_map.get(session["date"], [])
        if session["sport_type"].lower() == "rest":
            accomplished = len(day_activities) == 0
        else:
            accomplished = session["completed"] or match_activity(session, day_activities) is not None
        if session["date"] == today and not accomplished:
            continue
        total += 1
        recent = session["date"] >= recent_from
        if recent:
            recent_total += 1
        if accomplished:
            completed += 1
            if recent:
                recent_completed += 1

    return {
        "total_planned": total,
        "total_completed": completed,
        "rate": round(completed / total * 100, 1) if total else None,
        "recent_planned": recent_total,
        "recent_completed": recent_completed,
        "recent_rate": round(recent_completed / recent_total * 100, 1) if recent_total else None,
        "window_days": window_days,
    }


@router.get("/sessions/score-by-activity/{activity_id}")
async def get_score_by_activity(
    activity_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Get execution score for a specific Strava activity, if a matching session exists."""
    date_str = await run_in_threadpool(_activity_day, z2, activity_id)
    if date_str is None:
        return None

    cursor = await db.execute(
        "SELECT * FROM training_sessions WHERE date = ? ORDER BY id", (date_str,),
    )
    rows = await cursor.fetchall()
    sessions_with_targets = [s for s in (_row_to_dict(r) for r in rows) if has_targets(s)]
    if not sessions_with_targets:
        return None

    hr_zones = None
    try:
        hr_zones = (await resolve_hr_zones(z2, db))["zones"]
    except Exception as e:
        logger.debug("Could not load HR zones for scoring: %s", e)

    return await run_in_threadpool(_score_activity, z2, activity_id, date_str, sessions_with_targets, hr_zones)


async def _queue_watch_sync(tasks: BackgroundTasks, z2: Zone2, db: aiosqlite.Connection, session: dict,
                            previous_date: str | None = None) -> dict:
    """Queue the change the session's Garmin workout needs, if any, and return the session as it now stands."""
    if await garmin_workouts.mark_pending(z2, db, session, previous_date):
        tasks.add_task(garmin_workouts.sync_session, z2, session["id"])
        return {**session, "garmin_sync_state": garmin_workouts.SyncState.PENDING}
    return session


@router.post("/sessions", status_code=201)
async def create_session(
    session: SessionCreate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    values = session.model_dump()
    values["segments"] = values["segments"] or None
    row = _row_to_dict(await insert_row(db, "training_sessions", values, json_cols=_JSON_COLS))
    return await _queue_watch_sync(tasks, z2, db, row)


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: int,
    update: SessionUpdate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    before = await (await db.execute("SELECT date FROM training_sessions WHERE id = ?", (session_id,))).fetchone()
    row = _row_to_dict(await update_row(db, "training_sessions", session_id, update.model_dump(exclude_unset=True),
                                        "Session not found", json_cols=_JSON_COLS))
    return await _queue_watch_sync(tasks, z2, db, row, before["date"] if before else None)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    before = await (await db.execute("SELECT date, garmin_workout_id FROM training_sessions WHERE id = ?",
                                     (session_id,))).fetchone()
    await delete_row(db, "training_sessions", session_id, "Session not found")
    if before["garmin_workout_id"] is not None and before["date"] >= date.today().isoformat():
        tasks.add_task(garmin_workouts.remove_workout, z2, before["garmin_workout_id"])


class WatchWorkoutsUpdate(BaseModel):
    enabled: bool


@router.get("/watch-workouts")
async def get_watch_workouts(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """Whether planned runs go to the Garmin watch (`available`: Garmin is configured)."""
    return {"available": bool(z2.garmin_client.email), "enabled": await garmin_workouts.is_enabled(z2, db)}


@router.put("/watch-workouts")
async def set_watch_workouts(
    update: WatchWorkoutsUpdate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Turn sending on (upcoming runs go to the watch) or off (their workouts are removed)."""
    await set_setting(db, garmin_workouts.SETTING_KEY, "1" if update.enabled else "0")
    await garmin_workouts.mark_pending_upcoming(z2, db)
    tasks.add_task(garmin_workouts.reconcile, z2)
    return await get_watch_workouts(db, z2)
