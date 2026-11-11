"""The agent's conversations in calendar.db, a row per message as Pydantic AI's JSON: a turn appends
its messages, and readers load the current session, a page of turns or the whole conversation.
Imports nothing from Pydantic AI, so the app migrates and serves it without loading the agent."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiosqlite

logger = logging.getLogger(__name__)

# A pause this long starts a new session: the model starts fresh, with the notes and the
# coach's log carrying what lasts. The whole conversation stays stored and visible.
SESSION_GAP = timedelta(minutes=30)
_COLUMNS = "id, kind, opens_turn, opens_session, at, message"


@dataclass(frozen=True)
class Row:
    id: int
    kind: str              # Pydantic AI's: "request" or "response"
    opens_turn: bool       # a request with the athlete's words, or an event the coach gave itself
    opens_session: bool    # the conversation's first message, or a turn after SESSION_GAP
    at: datetime
    message: str           # the message as Pydantic AI's JSON


@dataclass(frozen=True)
class Page:
    rows: list[Row]
    older: int | None      # the cursor for the turns before these, None when they start the conversation


def _row(r: aiosqlite.Row | tuple) -> Row:
    return Row(id=r[0], kind=r[1], opens_turn=bool(r[2]), opens_session=bool(r[3]),
               at=datetime.fromisoformat(r[4]), message=r[5])


def _fields(message: dict) -> tuple[str, bool, datetime]:
    """A message's kind, whether it opens a turn, and its timestamp, from its JSON."""
    kind = message["kind"]
    opens_turn = kind == "request" and any(p.get("part_kind") == "user-prompt" for p in message["parts"])
    return kind, opens_turn, datetime.fromisoformat(message["timestamp"])


def _new_rows(conversation_id: str, messages: list[str], previous: datetime | None) -> list[tuple]:
    """Rows for messages appended after one stamped `previous` (None: they start the conversation).
    A session never begins between a tool call and its result: only a turn opens one."""
    rows = []
    for encoded in messages:
        kind, opens_turn, at = _fields(json.loads(encoded))
        opens_session = previous is None or (opens_turn and at - previous >= SESSION_GAP)
        rows.append((conversation_id, kind, opens_turn, opens_session, at.isoformat(), encoded))
        previous = at
    return rows


async def _insert(db: aiosqlite.Connection, rows: list[tuple]) -> None:
    await db.executemany(
        """INSERT INTO agent_messages (conversation_id, kind, opens_turn, opens_session, at, message)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )


async def _select(db: aiosqlite.Connection, where: str, params: tuple) -> list[Row]:
    rows = await (await db.execute(
        f"SELECT {_COLUMNS} FROM agent_messages WHERE conversation_id = ? AND {where} ORDER BY id", params,
    )).fetchall()
    return [_row(r) for r in rows]


async def conversation(db: aiosqlite.Connection, conversation_id: str) -> list[Row]:
    return await _select(db, "1", (conversation_id,))


async def latest_session(db: aiosqlite.Connection, conversation_id: str) -> list[Row]:
    """The messages of the conversation's latest session."""
    return await _select(db, """id >= (SELECT COALESCE(MAX(id), 0) FROM agent_messages
                                       WHERE conversation_id = ? AND opens_session = 1)""",
                         (conversation_id, conversation_id))


async def from_last_response(db: aiosqlite.Connection, conversation_id: str) -> list[Row]:
    """The conversation's last response and what follows it: where writes wait for a yes."""
    return await _select(db, """id >= (SELECT id FROM agent_messages WHERE conversation_id = ? AND kind = 'response'
                                       ORDER BY id DESC LIMIT 1)""",
                         (conversation_id, conversation_id))


async def before(db: aiosqlite.Connection, conversation_id: str, before_id: int | None, limit: int) -> list[Row]:
    """The `limit` messages before `before_id` (the conversation's last ones when None), oldest first."""
    rows = await (await db.execute(
        f"""SELECT {_COLUMNS} FROM agent_messages WHERE conversation_id = ? AND id < ?
            ORDER BY id DESC LIMIT ?""",
        (conversation_id, before_id if before_id is not None else 2 ** 63 - 1, limit),
    )).fetchall()
    return [_row(r) for r in reversed(rows)]


async def page(db: aiosqlite.Connection, conversation_id: str, turns: int, before_id: int | None) -> Page:
    """The last `turns` turns before the cursor `before_id` (the latest ones when None)."""
    upto = before_id if before_id is not None else 2 ** 63 - 1
    start = await (await db.execute(
        """SELECT id FROM agent_messages WHERE conversation_id = ? AND opens_turn = 1 AND id < ?
           ORDER BY id DESC LIMIT 1 OFFSET ?""",
        (conversation_id, upto, turns - 1),
    )).fetchone()
    rows = await _select(db, "id >= ? AND id < ?", (conversation_id, start[0] if start else 0, upto))
    if not rows:
        return Page(rows=[], older=None)
    older = await (await db.execute(
        "SELECT 1 FROM agent_messages WHERE conversation_id = ? AND id < ? LIMIT 1", (conversation_id, rows[0].id),
    )).fetchone()
    return Page(rows=rows, older=rows[0].id if older else None)


async def replace_from(db: aiosqlite.Connection, conversation_id: str, from_id: int | None,
                       messages: list[str]) -> None:
    """Drop the messages from `from_id` on (none when None) and append `messages` after the rest,
    in one transaction."""
    if from_id is not None:
        await db.execute("DELETE FROM agent_messages WHERE conversation_id = ? AND id >= ?", (conversation_id, from_id))
    if messages:
        last = await (await db.execute(
            "SELECT at FROM agent_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", (conversation_id,),
        )).fetchone()
        await _insert(db, _new_rows(conversation_id, messages, datetime.fromisoformat(last[0]) if last else None))
    await db.commit()


async def migrate(db: aiosqlite.Connection) -> int:
    """Split each conversation stored as one JSON list (agent_conversations) into rows, once: a
    conversation with rows already is left alone, and agent_conversations keeps the lists.
    Returns how many messages it moved."""
    pending = await (await db.execute(
        """SELECT id, messages FROM agent_conversations c
           WHERE NOT EXISTS (SELECT 1 FROM agent_messages m WHERE m.conversation_id = c.id)""",
    )).fetchall()
    moved = 0
    for conversation_id, blob in pending:
        try:
            messages = [json.dumps(m, ensure_ascii=False, separators=(",", ":")) for m in json.loads(blob)]
            rows = _new_rows(conversation_id, messages, None)
        except (ValueError, KeyError, TypeError):
            # Left in agent_conversations: an unreadable conversation mustn't keep the app from starting
            logger.exception("Agent conversation %s couldn't be moved to agent_messages", conversation_id)
            continue
        await _insert(db, rows)
        await db.commit()
        moved += len(messages)
    return moved
