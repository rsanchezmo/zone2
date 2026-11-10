"""What the coach wrote about the training: session reviews, the changes the athlete
asked for (with why, before and after), checkpoint decisions, suggestions and summaries."""

from datetime import date
from enum import StrEnum

import aiosqlite

from backend.db import insert_row, row_dict


class Kind(StrEnum):
    REVIEW = "review"          # how a session went, against its target
    CHANGE = "change"          # a change to the plan the athlete asked for
    DECISION = "decision"      # a checkpoint applied
    SUGGESTION = "suggestion"  # a change the coach recommends; nothing changes until the athlete asks
    SUMMARY = "summary"        # a week or a block in review


class SuggestionStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    DISMISSED = "dismissed"


async def add(db: aiosqlite.Connection, *, kind: Kind, title: str, body: str | None = None,
              day: str | None = None, plan_id: int | None = None, session_id: int | None = None,
              activity_id: int | None = None) -> dict:
    return row_dict(await insert_row(db, "coach_log", {
        "kind": kind, "title": title, "body": body, "date": day or date.today().isoformat(),
        "plan_id": plan_id, "session_id": session_id, "activity_id": activity_id,
        "status": SuggestionStatus.OPEN if kind == Kind.SUGGESTION else None,
    }))


async def entries(db: aiosqlite.Connection, plan_id: int | None = None, limit: int = 100) -> list[dict]:
    where, params = ("WHERE plan_id = ?", (plan_id,)) if plan_id is not None else ("", ())
    rows = await (await db.execute(
        f"SELECT * FROM coach_log {where} ORDER BY date DESC, id DESC LIMIT ?", (*params, limit),
    )).fetchall()
    return [row_dict(r) for r in rows]


async def set_status(db: aiosqlite.Connection, entry_id: int, status: SuggestionStatus) -> bool:
    cur = await db.execute(
        "UPDATE coach_log SET status = ? WHERE id = ? AND kind = ?", (status, entry_id, Kind.SUGGESTION),
    )
    await db.commit()
    return cur.rowcount > 0
