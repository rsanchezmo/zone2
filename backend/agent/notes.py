"""What the agent keeps across conversations that z2's data doesn't hold. Notes about the
athlete (preferences, constraints, baselines, kit) reach every turn. An agreement for one
plan (its thresholds, the block's structure, the race-day plan) is kept with that plan and
reaches the model through plan_detail."""

from enum import StrEnum

import aiosqlite


class Topic(StrEnum):
    KIT = "kit"                  # sensors, GPS, devices, data quirks
    BODY = "body"                # max and threshold HR, baselines, injuries
    RULES = "rules"              # how the week is built: days, caps, other sports
    PREFERENCES = "preferences"  # how they like to be coached, habits to coach


async def _notes(db: aiosqlite.Connection, where: str = "", params: tuple = ()) -> list[dict]:
    rows = await (await db.execute(
        f"SELECT id, note, topic, plan_id, date(created_at) AS added FROM agent_notes {where} ORDER BY id", params,
    )).fetchall()
    return [dict(r) for r in rows]


async def all_notes(db: aiosqlite.Connection) -> list[dict]:
    return await _notes(db)


async def athlete_notes(db: aiosqlite.Connection) -> list[dict]:
    return await _notes(db, "WHERE plan_id IS NULL")


async def plan_notes(db: aiosqlite.Connection, plan_id: int) -> list[dict]:
    return await _notes(db, "WHERE plan_id = ?", (plan_id,))


async def add(db: aiosqlite.Connection, note: str, topic: Topic | None = None, plan_id: int | None = None) -> int:
    cur = await db.execute(
        "INSERT INTO agent_notes (note, topic, plan_id) VALUES (?, ?, ?)", (note.strip(), topic, plan_id),
    )
    await db.commit()
    return cur.lastrowid


async def delete(db: aiosqlite.Connection, note_id: int) -> bool:
    cur = await db.execute("DELETE FROM agent_notes WHERE id = ?", (note_id,))
    await db.commit()
    return cur.rowcount > 0
