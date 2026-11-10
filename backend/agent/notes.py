"""What the agent keeps about the athlete across conversations: preferences, constraints,
baselines and lessons that z2's data doesn't hold. Every turn sees all of them."""

from enum import StrEnum

import aiosqlite


class Topic(StrEnum):
    KIT = "kit"                  # sensors, GPS, devices, data quirks
    BODY = "body"                # max and threshold HR, baselines, injuries
    PLAN = "plan"                # the goal, agreed checkpoints and thresholds
    RULES = "rules"              # how the week is built: days, caps, other sports
    PREFERENCES = "preferences"  # how they like to be coached, habits to coach


async def all_notes(db: aiosqlite.Connection) -> list[dict]:
    rows = await (await db.execute(
        "SELECT id, note, topic, date(created_at) AS added FROM agent_notes ORDER BY id",
    )).fetchall()
    return [dict(r) for r in rows]


async def add(db: aiosqlite.Connection, note: str, topic: Topic | None = None) -> int:
    cur = await db.execute("INSERT INTO agent_notes (note, topic) VALUES (?, ?)", (note.strip(), topic))
    await db.commit()
    return cur.lastrowid


async def delete(db: aiosqlite.Connection, note_id: int) -> bool:
    cur = await db.execute("DELETE FROM agent_notes WHERE id = ?", (note_id,))
    await db.commit()
    return cur.rowcount > 0
