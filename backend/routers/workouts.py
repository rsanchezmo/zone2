from fastapi import APIRouter, Depends
from pydantic import BaseModel
import aiosqlite

from backend.db import delete_row, get_db, insert_row, row_dict, update_row

_JSON_COLS = ("segments",)

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


def _template(row: aiosqlite.Row) -> dict:
    return row_dict(row, json_cols=("segments",))


@router.get("")
async def list_templates(db: aiosqlite.Connection = Depends(get_db)):
    cursor = await db.execute("SELECT * FROM workout_templates ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    return [_template(row) for row in rows]


@router.post("", status_code=201)
async def create_template(
    template: WorkoutTemplateCreate,
    db: aiosqlite.Connection = Depends(get_db),
):
    return _template(await insert_row(db, "workout_templates", template.model_dump(), json_cols=_JSON_COLS))


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    update: WorkoutTemplateUpdate,
    db: aiosqlite.Connection = Depends(get_db),
):
    return _template(await update_row(db, "workout_templates", template_id, update.model_dump(exclude_unset=True),
                                      "Template not found", json_cols=_JSON_COLS))


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    db: aiosqlite.Connection = Depends(get_db),
):
    await delete_row(db, "workout_templates", template_id, "Template not found")
