from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import aiosqlite
import json
import pandas as pd
import numpy as np

from backend.db import get_db
from backend.dependencies import get_si
from backend.scoring import match_activity, compute_execution_score, has_targets
from strava.strava_intelligence import StravaIntelligence

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


def _row_to_dict(row: aiosqlite.Row) -> dict:
    segments = None
    raw_segments = row["segments"]
    if raw_segments:
        try:
            segments = json.loads(raw_segments) if isinstance(raw_segments, str) else raw_segments
        except (json.JSONDecodeError, TypeError):
            segments = None
    return {
        "id": row["id"],
        "date": row["date"],
        "title": row["title"],
        "sport_type": row["sport_type"],
        "description": row["description"],
        "planned_distance_km": row["planned_distance_km"],
        "planned_duration_mins": row["planned_duration_mins"],
        "planned_intensity": row["planned_intensity"],
        "target_avg_pace": row["target_avg_pace"],
        "target_pace_min": row["target_pace_min"],
        "target_pace_max": row["target_pace_max"],
        "target_hr_zone": row["target_hr_zone"],
        "target_zone_pct": row["target_zone_pct"],
        "segments": segments,
        "workout_template_id": row["workout_template_id"],
        "completed": bool(row["completed"]),
        "created_at": row["created_at"],
    }


@router.get("/sessions")
async def list_sessions(
    month: int | None = None,
    year: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    if date_from and date_to:
        query = "SELECT * FROM training_sessions WHERE date >= ? AND date <= ? ORDER BY date"
        cursor = await db.execute(query, (date_from, date_to))
    elif month and year:
        query = "SELECT * FROM training_sessions WHERE strftime('%Y', date) = ? AND strftime('%m', date) = ? ORDER BY date"
        cursor = await db.execute(query, (str(year), f"{month:02d}"))
    else:
        cursor = await db.execute("SELECT * FROM training_sessions ORDER BY date")
    rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


def _sanitize(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    return val


def _activity_row_to_dict(row: pd.Series) -> dict:
    """Minimal activity dict for scoring — includes streams."""
    d = {}
    for col in ("id", "sport_type", "distance", "moving_time", "average_speed",
                 "start_date_local", "average_heartrate"):
        if col in row.index:
            d[col] = _sanitize(row[col])
    if d.get("distance") is not None:
        d["distance_km"] = round(d["distance"] / 1000, 2)
    if "streams" in row.index and row["streams"] is not None:
        try:
            streams = row["streams"] if isinstance(row["streams"], (list, dict)) else json.loads(row["streams"])
            d["streams"] = streams
        except (json.JSONDecodeError, TypeError):
            d["streams"] = None
    return d


@router.get("/sessions/scores")
async def get_session_scores(
    date_from: str = Query(...),
    date_to: str = Query(...),
    db: aiosqlite.Connection = Depends(get_db),
    si: StravaIntelligence = Depends(get_si),
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

    activities_df = si.strava_activities_cache.load_activities()
    if not activities_df.empty:
        activities_df = activities_df.copy()
        activities_df["start_date_local"] = pd.to_datetime(activities_df["start_date_local"])
        dt_from = pd.to_datetime(date_from)
        dt_to = pd.to_datetime(date_to) + pd.Timedelta(days=1)  # inclusive
        if activities_df["start_date_local"].dt.tz is not None:
            dt_from = dt_from.tz_localize(activities_df["start_date_local"].dt.tz)
            dt_to = dt_to.tz_localize(activities_df["start_date_local"].dt.tz)
        activities_df = activities_df[
            (activities_df["start_date_local"] >= dt_from)
            & (activities_df["start_date_local"] < dt_to)
        ]

    activity_map: dict[str, list[dict]] = {}
    if not activities_df.empty:
        for _, row in activities_df.iterrows():
            sdt = row.get("start_date_local")
            if sdt is not None:
                if hasattr(sdt, "strftime"):
                    date_str = sdt.strftime("%Y-%m-%d")
                else:
                    date_str = str(sdt)[:10]
                if date_str not in activity_map:
                    activity_map[date_str] = []
                activity_map[date_str].append(_activity_row_to_dict(row))

    hr_zones = None
    try:
        hr_zones = si.strava_analytics.get_hr_zones()
    except Exception:
        pass

    result: dict[int, dict | None] = {}
    for session in sessions_with_targets:
        sid = session["id"]
        day_activities = activity_map.get(session["date"], [])
        matched = match_activity(session, day_activities)
        if matched is None:
            result[sid] = None
            continue

        streams = matched.get("streams") if isinstance(matched.get("streams"), list) else None
        score = compute_execution_score(session, matched, hr_zones, streams)
        result[sid] = score

    return result


@router.get("/sessions/score-by-activity/{activity_id}")
async def get_score_by_activity(
    activity_id: int,
    db: aiosqlite.Connection = Depends(get_db),
    si: StravaIntelligence = Depends(get_si),
):
    """Get execution score for a specific Strava activity, if a matching session exists."""
    # Find the activity to get its date
    activities_df = si.strava_activities_cache.load_activities()
    if activities_df.empty:
        return None

    match = activities_df[activities_df["id"] == activity_id]
    if match.empty:
        return None

    row = match.iloc[0]
    sdt = row.get("start_date_local")
    if sdt is None:
        return None
    date_str = sdt.strftime("%Y-%m-%d") if hasattr(sdt, "strftime") else str(sdt)[:10]

    # Find sessions on that date with targets
    cursor = await db.execute(
        "SELECT * FROM training_sessions WHERE date = ? ORDER BY id", (date_str,),
    )
    rows = await cursor.fetchall()
    sessions = [_row_to_dict(r) for r in rows]
    sessions_with_targets = [s for s in sessions if has_targets(s)]
    if not sessions_with_targets:
        return None

    # Build activity dict for scoring
    activity_dict = _activity_row_to_dict(row)

    hr_zones = None
    try:
        hr_zones = si.strava_analytics.get_hr_zones()
    except Exception:
        pass

    # Find the session that matches this activity
    for session in sessions_with_targets:
        if session.get("sport_type") != activity_dict.get("sport_type"):
            continue
        streams = activity_dict.get("streams") if isinstance(activity_dict.get("streams"), list) else None
        score = compute_execution_score(session, activity_dict, hr_zones, streams)
        return {
            "session": session,
            "score": score,
        }

    return None


@router.post("/sessions", status_code=201)
async def create_session(
    session: SessionCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    segments_json = json.dumps(session.segments) if session.segments else None
    cursor = await db.execute(
        """INSERT INTO training_sessions (date, title, sport_type, description,
           planned_distance_km, planned_duration_mins, planned_intensity,
           target_avg_pace, target_pace_min, target_pace_max, target_hr_zone, target_zone_pct,
           segments, workout_template_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session.date, session.title, session.sport_type, session.description,
         session.planned_distance_km, session.planned_duration_mins, session.planned_intensity,
         session.target_avg_pace, session.target_pace_min, session.target_pace_max,
         session.target_hr_zone, session.target_zone_pct,
         segments_json, session.workout_template_id),
    )
    await db.commit()
    new_id = cursor.lastrowid
    cursor = await db.execute("SELECT * FROM training_sessions WHERE id = ?", (new_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: int,
    update: SessionUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT * FROM training_sessions WHERE id = ?", (session_id,))
    existing = await cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Session not found")

    fields = []
    values = []
    for field_name, value in update.model_dump(exclude_unset=True).items():
        if field_name == "segments":
            fields.append("segments = ?")
            values.append(json.dumps(value) if value is not None else None)
        else:
            fields.append(f"{field_name} = ?")
            values.append(value)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(session_id)
    await db.execute(f"UPDATE training_sessions SET {', '.join(fields)} WHERE id = ?", values)
    await db.commit()

    cursor = await db.execute("SELECT * FROM training_sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT id FROM training_sessions WHERE id = ?", (session_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Session not found")
    await db.execute("DELETE FROM training_sessions WHERE id = ?", (session_id,))
    await db.commit()
