from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import aiosqlite

from backend.db import get_db

router = APIRouter()


class SessionCreate(BaseModel):
    date: str  # YYYY-MM-DD
    title: str
    sport_type: str
    description: str | None = None
    planned_distance_km: float | None = None
    planned_duration_mins: float | None = None
    planned_intensity: str | None = None  # easy/moderate/hard/race


class SessionUpdate(BaseModel):
    date: str | None = None
    title: str | None = None
    sport_type: str | None = None
    description: str | None = None
    planned_distance_km: float | None = None
    planned_duration_mins: float | None = None
    planned_intensity: str | None = None
    completed: bool | None = None


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "date": row["date"],
        "title": row["title"],
        "sport_type": row["sport_type"],
        "description": row["description"],
        "planned_distance_km": row["planned_distance_km"],
        "planned_duration_mins": row["planned_duration_mins"],
        "planned_intensity": row["planned_intensity"],
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


@router.post("/sessions", status_code=201)
async def create_session(
    session: SessionCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute(
        """INSERT INTO training_sessions (date, title, sport_type, description,
           planned_distance_km, planned_duration_mins, planned_intensity)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session.date, session.title, session.sport_type, session.description,
         session.planned_distance_km, session.planned_duration_mins, session.planned_intensity),
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
