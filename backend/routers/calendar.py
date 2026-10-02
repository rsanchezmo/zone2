from datetime import datetime, timedelta
import logging
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import aiosqlite
import pandas as pd

from backend._serialize import sanitize as _sanitize
from backend.db import delete_row, get_db, insert_row, row_dict, update_row
from backend.dependencies import get_z2
from backend.scoring import match_activity, compute_execution_score, has_targets
from backend.services.zones import resolve_hr_zones
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


@router.post("/sessions", status_code=201)
async def create_session(
    session: SessionCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    values = session.model_dump()
    values["segments"] = values["segments"] or None
    return _row_to_dict(await insert_row(db, "training_sessions", values, json_cols=_JSON_COLS))


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: int,
    update: SessionUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    return _row_to_dict(await update_row(db, "training_sessions", session_id, update.model_dump(exclude_unset=True),
                                         "Session not found", json_cols=_JSON_COLS))


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    await delete_row(db, "training_sessions", session_id, "Session not found")
