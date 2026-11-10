"""The agent's conversations in calendar.db: the message history, so a conversation resumes
where it stopped. The app keeps one conversation; the model works from its current session."""

from datetime import datetime, timedelta, timezone

import aiosqlite
from pydantic_ai import (
    ModelMessage, ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart,
    UserPromptPart,
)

# The app's one conversation with the coach
MAIN = "coach"
# A pause this long starts a new session: the model starts fresh, with the notes and the
# coach's log carrying what lasts. The whole conversation stays stored and visible.
SESSION_GAP = timedelta(minutes=30)
# Starts a prompt the coach gave itself, such as a review after a sync; its first line is what
# the chat shows in its place ("After your run: Test 5k")
EVENT_MARK = "⟳ "


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


def _opens_turn(message: ModelMessage) -> bool:
    return isinstance(message, ModelRequest) and any(isinstance(p, UserPromptPart) for p in message.parts)


def session_starts(messages: list[ModelMessage]) -> list[int]:
    """Where each session begins: the first message, and every new message from you after a
    pause of SESSION_GAP or more (never between a tool call and its result)."""
    starts = [0] if messages else []
    for i in range(1, len(messages)):
        if _opens_turn(messages[i]) and messages[i].timestamp - messages[i - 1].timestamp >= SESSION_GAP:
            starts.append(i)
    return starts


def current_session(messages: list[ModelMessage], new_message: bool) -> int:
    """Index of the first message the model should see. A new message after a pause starts
    a session of its own; anything else continues the latest one."""
    if new_message and messages and datetime.now(timezone.utc) - messages[-1].timestamp >= SESSION_GAP:
        return len(messages)
    starts = session_starts(messages)
    return starts[-1] if starts else 0


# What a new session carries from the one before: its last exchanges, words only
RECAP_EXCHANGES = 3
RECAP_CHARS = 500


def recap(messages: list[ModelMessage]) -> str | None:
    """The end of the previous session as plain lines ("You: …", "Coach: …"), so a new session
    can follow up on it without replaying its tool calls."""
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
    tail = lines[-2 * RECAP_EXCHANGES:]
    if not tail:
        return None
    when = messages[-1].timestamp.astimezone().strftime("%a %d %b, %H:%M")
    body = "\n".join(f"{who}: {text if len(text) <= RECAP_CHARS else text[:RECAP_CHARS] + '…'}" for who, text in tail)
    return f"The end of your previous conversation ({when}), for follow-ups:\n{body}"


async def load(db: aiosqlite.Connection, conversation_id: str) -> list[ModelMessage]:
    row = await (await db.execute(
        "SELECT messages FROM agent_conversations WHERE id = ?", (conversation_id,),
    )).fetchone()
    return ModelMessagesTypeAdapter.validate_json(row["messages"]) if row else []


async def save(db: aiosqlite.Connection, conversation_id: str, messages: list[ModelMessage]) -> None:
    await db.execute(
        """INSERT INTO agent_conversations (id, messages) VALUES (?, ?)
           ON CONFLICT(id) DO UPDATE SET messages = excluded.messages, updated_at = datetime('now')""",
        (conversation_id, ModelMessagesTypeAdapter.dump_json(messages).decode()),
    )
    await db.commit()
