import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.agent import notes
from backend.db import get_db
from backend.dependencies import get_z2
from backend.services import coach_log, plans
from zone2.core import Zone2

router = APIRouter()


async def _plan_or_404(db: aiosqlite.Connection, plan_id: int) -> dict:
    plan = await plans.get_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.get("/plans")
async def list_plans(db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """Every plan, latest first, with its race and how far along it is."""
    out = []
    for plan in await plans.list_plans(db):
        progress = await plans.progress(z2, db, plan, detail=False)
        out.append({
            **plan,
            "race": await plans.race_of(db, plan),
            "sessions": progress["sessions"],
            "completion_pct": progress["sessions"]["completion_pct"],
            "average_score": progress["score"]["average"],
            "days_to_race": progress["days_to_race"],
            "phase": progress["phase"],
            "prediction_s": (progress["prediction"] or {}).get("now_s"),
            "prediction_source": (progress["prediction"] or {}).get("source"),
            "result_s": (progress["result"] or {}).get("time_s"),
        })
    return out


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: int, db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """One plan in full: progress, its sessions with how each went, checkpoints, and the coach's log."""
    plan = await _plan_or_404(db, plan_id)
    progress = await plans.progress(z2, db, plan)
    status = progress.pop("session_status")
    return {
        **plan,
        "race": await plans.race_of(db, plan),
        "progress": progress,
        "sessions": [{**s, **status[s["id"]]} for s in await plans.plan_sessions(db, plan_id)],
        "checkpoints": await plans.checkpoints(db, plan_id),
        "log": await coach_log.entries(db, plan_id),
    }


class SuggestionUpdate(BaseModel):
    status: coach_log.SuggestionStatus


@router.put("/log/{entry_id}")
async def update_suggestion(entry_id: int, update: SuggestionUpdate, db: aiosqlite.Connection = Depends(get_db)):
    """Mark a suggestion done or dismissed."""
    if not await coach_log.set_status(db, entry_id, update.status):
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"id": entry_id, "status": update.status}


class NoteCreate(BaseModel):
    note: str
    topic: notes.Topic | None = None


@router.get("/notes")
async def list_notes(db: aiosqlite.Connection = Depends(get_db)):
    """What the coach keeps about the athlete."""
    return await notes.all_notes(db)


@router.post("/notes", status_code=201)
async def add_note(note: NoteCreate, db: aiosqlite.Connection = Depends(get_db)):
    return {"id": await notes.add(db, note.note, note.topic)}


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: int, db: aiosqlite.Connection = Depends(get_db)):
    if not await notes.delete(db, note_id):
        raise HTTPException(status_code=404, detail="Note not found")
