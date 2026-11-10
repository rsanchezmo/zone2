from datetime import date, datetime, timedelta
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite
import pandas as pd

from backend.db import get_db
from backend.dependencies import get_z2
from backend.scoring import compute_execution_score, has_targets
from backend.routers.activities import activities_on_dates
from backend.services import garmin_workouts, sessions as planned_sessions
from backend.services.briefing import today_briefing
from backend.services.session_scores import accomplished, activities_by_day, score_sessions, session_matches
from backend.services.sessions import session_dict
from backend.services.zones import resolve_hr_zones, set_setting
from zone2.core import Zone2

logger = logging.getLogger(__name__)

router = APIRouter()

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


@router.get("/briefing")
async def briefing(z2: Zone2 = Depends(get_z2), db: aiosqlite.Connection = Depends(get_db)):
    """Today at a glance for the top of the calendar (see `today_briefing`)."""
    done = (await run_in_threadpool(activities_on_dates, date.today().isoformat(), z2))["items"]
    return await today_briefing(z2, db, done)


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
    return [session_dict(row) for row in rows]


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
    for session, matched in session_matches(sessions, activities_by_day(z2, date_str, date_str)):
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
    sessions = [session_dict(row) for row in rows]

    sessions_with_targets = [s for s in sessions if has_targets(s)]
    if not sessions_with_targets:
        return {}

    hr_zones = None
    try:
        hr_zones = (await resolve_hr_zones(z2, db))["zones"]
    except Exception as e:
        logger.debug("Could not load HR zones for scoring: %s", e)

    return await run_in_threadpool(score_sessions, z2, sessions_with_targets, date_from, date_to, hr_zones)


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
    sessions = [session_dict(row) for row in rows]
    if not sessions:
        return {
            "total_planned": 0, "total_completed": 0, "rate": None,
            "recent_planned": 0, "recent_completed": 0, "recent_rate": None,
            "window_days": window_days,
        }

    activity_map = await run_in_threadpool(activities_by_day, z2, sessions[0]["date"], today)
    recent_from = (now - timedelta(days=window_days)).strftime("%Y-%m-%d")

    total = completed = recent_total = recent_completed = 0
    for session in sessions:
        done = accomplished(session, activity_map.get(session["date"], []))
        if session["date"] == today and not done:
            continue
        total += 1
        recent = session["date"] >= recent_from
        if recent:
            recent_total += 1
        if done:
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
    sessions_with_targets = [s for s in (session_dict(r) for r in rows) if has_targets(s)]
    if not sessions_with_targets:
        return None

    hr_zones = None
    try:
        hr_zones = (await resolve_hr_zones(z2, db))["zones"]
    except Exception as e:
        logger.debug("Could not load HR zones for scoring: %s", e)

    return await run_in_threadpool(_score_activity, z2, activity_id, date_str, sessions_with_targets, hr_zones)


@router.post("/sessions", status_code=201)
async def create_session(
    session: SessionCreate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    return await planned_sessions.create(z2, db, session.model_dump(), tasks.add_task)


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: int,
    update: SessionUpdate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    return await planned_sessions.update(z2, db, session_id, update.model_dump(exclude_unset=True), tasks.add_task)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    await planned_sessions.delete(z2, db, session_id, tasks.add_task)


class WatchWorkoutsUpdate(BaseModel):
    enabled: bool


@router.get("/watch-workouts")
async def get_watch_workouts(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """Whether saved run workouts and planned runs go to Garmin (`available`: Garmin is configured)."""
    return {"available": bool(z2.garmin_client.email), "enabled": await garmin_workouts.is_enabled(z2, db)}


@router.put("/watch-workouts")
async def set_watch_workouts(
    update: WatchWorkoutsUpdate,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    """Turn sending on, or off: then upcoming entries and the library workouts no past entry uses are removed."""
    await set_setting(db, garmin_workouts.SETTING_KEY, "1" if update.enabled else "0")
    await garmin_workouts.mark_due_pending(z2, db)
    tasks.add_task(garmin_workouts.reconcile, z2)
    return await get_watch_workouts(db, z2)
