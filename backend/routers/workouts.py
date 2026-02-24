import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import aiosqlite

from backend.db import get_db

router = APIRouter()


class WorkoutTemplateCreate(BaseModel):
    name: str
    sport_type: str
    description: str | None = None
    segments: list[dict]


class WorkoutTemplateUpdate(BaseModel):
    name: str | None = None
    sport_type: str | None = None
    description: str | None = None
    segments: list[dict] | None = None


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = {
        "id": row["id"],
        "name": row["name"],
        "sport_type": row["sport_type"],
        "description": row["description"],
        "created_at": row["created_at"],
    }
    try:
        d["segments"] = json.loads(row["segments"])
    except (json.JSONDecodeError, TypeError):
        d["segments"] = []
    return d


@router.get("")
async def list_templates(
    sport_type: str | None = None,
    db: aiosqlite.Connection = Depends(get_db),
):
    if sport_type:
        cursor = await db.execute(
            "SELECT * FROM workout_templates WHERE sport_type = ? ORDER BY created_at DESC",
            (sport_type,),
        )
    else:
        cursor = await db.execute("SELECT * FROM workout_templates ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows]


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT * FROM workout_templates WHERE id = ?", (template_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return _row_to_dict(row)


@router.post("", status_code=201)
async def create_template(
    template: WorkoutTemplateCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    segments_json = json.dumps(template.segments)
    cursor = await db.execute(
        "INSERT INTO workout_templates (name, sport_type, description, segments) VALUES (?, ?, ?, ?)",
        (template.name, template.sport_type, template.description, segments_json),
    )
    await db.commit()
    new_id = cursor.lastrowid
    cursor = await db.execute("SELECT * FROM workout_templates WHERE id = ?", (new_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    update: WorkoutTemplateUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT * FROM workout_templates WHERE id = ?", (template_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Template not found")

    fields = []
    values = []
    for field_name, value in update.model_dump(exclude_unset=True).items():
        if field_name == "segments" and value is not None:
            fields.append("segments = ?")
            values.append(json.dumps(value))
        else:
            fields.append(f"{field_name} = ?")
            values.append(value)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(template_id)
    await db.execute(f"UPDATE workout_templates SET {', '.join(fields)} WHERE id = ?", values)
    await db.commit()

    cursor = await db.execute("SELECT * FROM workout_templates WHERE id = ?", (template_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    cursor = await db.execute("SELECT id FROM workout_templates WHERE id = ?", (template_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Template not found")
    await db.execute("DELETE FROM workout_templates WHERE id = ?", (template_id,))
    await db.commit()
