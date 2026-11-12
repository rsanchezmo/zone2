from datetime import timedelta
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite
import pandas as pd

from backend.db import get_db
from backend.dependencies import get_z2
from backend.scoring import compute_execution_score, has_targets
from backend.services import activities, garmin_workouts, session_scores, sessions as planned_sessions
from backend.services.briefing import today_briefing
from backend.services.session_scores import accomplished, activities_by_day, session_matches
from backend.services.sessions import NewSession, SessionChanges, session_dict
from backend.services.zones import resolve_hr_zones, set_setting
from zone2.core import Zone2

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/briefing")
async def briefing(z2: Zone2 = Depends(get_z2), db: aiosqlite.Connection = Depends(get_db)):
    """Today at a glance for the top of the calendar (see `today_briefing`)."""
    done = await run_in_threadpool(activities.on_dates, z2, {z2.clock.today().isoformat()})
    return await today_briefing(z2, db, done)


@router.get("/sessions")
async def list_sessions(
    date_from: str | None = None,
    date_to: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await planned_sessions.between(db, date_from, date_to)


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
    sessions = [session_dict(row) for row in await cursor.fetchall()]
    return await session_scores.scores(z2, db, sessions, date_from, date_to)


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
    today_date = z2.clock.today()
    today = today_date.isoformat()
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
    recent_from = (today_date - timedelta(days=window_days)).isoformat()

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
    session: NewSession,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    return await planned_sessions.create(z2, db, session, tasks.add_task)


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: int,
    update: SessionChanges,
    tasks: BackgroundTasks,
    db: aiosqlite.Connection = Depends(get_db),
    z2: Zone2 = Depends(get_z2),
):
    return await planned_sessions.update(z2, db, session_id, update, tasks.add_task)


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
    return {"available": z2.garmin_client.configured, "enabled": await garmin_workouts.is_enabled(z2, db)}


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
