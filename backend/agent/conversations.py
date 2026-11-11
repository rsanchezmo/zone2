"""The agent's conversations in calendar.db (stored by message_store), so a conversation resumes
where it stopped. The app keeps one conversation; the model works from its current session."""

from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite
from pydantic import ConfigDict, TypeAdapter
from pydantic_ai import (
    ModelMessage, ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart,
    UserPromptPart,
)

from backend.agent import message_store
from backend.agent.message_store import SESSION_GAP

# The app's one conversation with the coach
MAIN = "coach"
# Starts a prompt the coach gave itself, such as a review after a sync; its first line is what
# the chat shows in its place ("After your run: Test 5k")
EVENT_MARK = "⟳ "
# One message as ModelMessagesTypeAdapter writes each in a list
_MESSAGE = TypeAdapter(ModelMessage, config=ConfigDict(defer_build=True, ser_json_bytes="base64",
                                                       val_json_bytes="base64"))


def event_title(prompt: str) -> str | None:
    """The line the chat shows for a prompt the coach gave itself; None for the athlete's own."""
    return prompt[len(EVENT_MARK):].split("\n", 1)[0] if prompt.startswith(EVENT_MARK) else None


def unanswered_calls(messages: list[ModelMessage]) -> list[ToolCallPart]:
    """The last response's tool calls that have no result yet: the writes waiting for a yes."""
    responses = [i for i, m in enumerate(messages) if isinstance(m, ModelResponse)]
    if not responses:
        return []
    last = responses[-1]
    answered = {p.tool_call_id for m in messages[last + 1:] for p in m.parts if isinstance(p, ToolReturnPart)}
    return [p for p in messages[last].parts if isinstance(p, ToolCallPart) and p.tool_call_id not in answered]


# What a new session carries from the one before: its last exchanges, words only
RECAP_EXCHANGES = 3
RECAP_CHARS = 500
# Messages read at a time when looking back for the recap's exchanges
_RECAP_READ = 16


def _recap_lines(messages: list[ModelMessage]) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for message in messages:
        for part in message.parts:
            if isinstance(message, ModelRequest) and isinstance(part, UserPromptPart) and isinstance(part.content, str):
                title = event_title(part.content)
                lines.append(("Event", title) if title else ("You", part.content))
            elif isinstance(message, ModelResponse) and isinstance(part, TextPart) and part.content.strip():
                if lines and lines[-1][0] == "Coach":
                    lines[-1] = ("Coach", f"{lines[-1][1]}\n{part.content}")
                else:
                    lines.append(("Coach", part.content))
    return lines


def recap(messages: list[ModelMessage]) -> str | None:
    """The end of the previous session as plain lines ("You: …", "Coach: …"), so a new session
    can follow up on it without replaying its tool calls."""
    tail = _recap_lines(messages)[-2 * RECAP_EXCHANGES:]
    if not tail:
        return None
    when = messages[-1].timestamp.astimezone().strftime("%a %d %b, %H:%M")
    body = "\n".join(f"{who}: {text if len(text) <= RECAP_CHARS else text[:RECAP_CHARS] + '…'}" for who, text in tail)
    return f"The end of your previous conversation ({when}), for follow-ups:\n{body}"


async def _recap_before(db: aiosqlite.Connection, conversation_id: str, before_id: int | None) -> str | None:
    """recap() of the messages before `before_id` (all when None), reading back only as far as
    its exchanges go: one line more than it keeps, so the oldest kept is whole."""
    messages: list[ModelMessage] = []
    while True:
        rows = await message_store.before(db, conversation_id, before_id, _RECAP_READ)
        if not rows:
            break
        messages = decode(rows) + messages
        before_id = rows[0].id
        if len(_recap_lines(messages)) > 2 * RECAP_EXCHANGES:
            break
    return recap(messages) if messages else None


def decode(rows: list[message_store.Row]) -> list[ModelMessage]:
    return ModelMessagesTypeAdapter.validate_json(f"[{','.join(r.message for r in rows)}]") if rows else []


def encode(message: ModelMessage) -> str:
    return _MESSAGE.dump_json(message).decode()


async def load(db: aiosqlite.Connection, conversation_id: str) -> list[ModelMessage]:
    """The whole conversation."""
    return decode(await message_store.conversation(db, conversation_id))


async def tail(db: aiosqlite.Connection, conversation_id: str) -> list[ModelMessage]:
    """The conversation's last response and what follows it: all unanswered_calls needs."""
    return decode(await message_store.from_last_response(db, conversation_id))


@dataclass(frozen=True)
class Turn:
    """What a turn continues from. `history` is what the model sees; `stored` holds its rows'
    ids and JSON as loaded, so saving writes only the messages that changed or are new."""
    conversation_id: str
    history: list[ModelMessage]
    waiting: list[ToolCallPart]
    earlier: str | None
    stored: list[tuple[int, str]]


async def begin(db: aiosqlite.Connection, conversation_id: str, *, prompt: bool, approvals: bool) -> Turn:
    """Load what a turn needs: the latest session, which the model continues unless a new message
    after a pause of SESSION_GAP starts one of its own; the recap of what came before it; and,
    for a new message, the writes still waiting for a yes, which it answers no in the same session."""
    rows = await message_store.latest_session(db, conversation_id)
    session = decode(rows)
    calls: list[ToolCallPart] = []
    if prompt and not approvals:
        has_response = any(isinstance(m, ModelResponse) for m in session)
        calls = unanswered_calls(session if has_response else await tail(db, conversation_id))
    starts_session = (prompt and not calls and bool(rows)
                      and datetime.now(timezone.utc) - rows[-1].at >= SESSION_GAP)
    if starts_session:
        rows, session = [], []
    first = rows[0].id if rows else None
    return Turn(
        conversation_id=conversation_id,
        history=session,
        waiting=calls,
        earlier=await _recap_before(db, conversation_id, first),
        # Encoded from the loaded objects, so a change the run makes to one in place shows
        stored=[(r.id, encode(m)) for r, m in zip(rows, session)],
    )


async def save(db: aiosqlite.Connection, turn: Turn, messages: list[ModelMessage]) -> int:
    """Store the turn's messages (`history` and what the run added after it), writing from the
    first one that differs from what was loaded. Returns the bytes written."""
    encoded = [encode(m) for m in messages]
    same = 0
    for (_, before), after in zip(turn.stored, encoded):
        if before != after:
            break
        same += 1
    from_id = turn.stored[same][0] if same < len(turn.stored) else None
    await message_store.replace_from(db, turn.conversation_id, from_id, encoded[same:])
    return sum(len(e.encode()) for e in encoded[same:])


# Turns per page when a page is asked for without a size
PAGE_TURNS = 20


@dataclass(frozen=True)
class Page:
    messages: list[ModelMessage]
    session_starts: set[int]  # where a session after the conversation's first begins
    older: int | None         # the cursor for the page before, None when this one starts the conversation


async def page(db: aiosqlite.Connection, conversation_id: str, turns: int | None = None,
               before: int | None = None) -> Page:
    """The conversation's last `turns` turns before the cursor `before`; all of it when neither is given."""
    if turns is None and before is None:
        loaded = message_store.Page(rows=await message_store.conversation(db, conversation_id), older=None)
    else:
        loaded = await message_store.page(db, conversation_id, turns or PAGE_TURNS, before)
    starts = {i for i, r in enumerate(loaded.rows) if r.opens_session}
    if loaded.older is None:
        starts.discard(0)
    return Page(messages=decode(loaded.rows), session_starts=starts, older=loaded.older)

