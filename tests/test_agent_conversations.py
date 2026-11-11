"""The coach's conversation stored a row per message: the migration from one JSON list per
conversation, turns that append, sessions, pages and the writes waiting for a yes, against a
throwaway calendar database. The model is a stub: no request leaves the machine, and every
message is made up."""
import asyncio
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from pydantic_ai import (
    Agent, DeferredToolRequests, DeferredToolResults, FunctionToolset, ModelMessage, ModelMessagesTypeAdapter,
    ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

import backend.db as calendar_db
from backend.agent import chat, conversations, message_store
from backend.agent.agent import run_turn
from backend.agent.tools import AgentDeps

CID = "coach"
NOW = datetime.now(timezone.utc)
WRITE = "add_session"  # one of chat.WRITE_TOOLS


def prompt(text: str, at: datetime) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(text, timestamp=at)], timestamp=at)


def reply(text: str, at: datetime) -> ModelResponse:
    return ModelResponse(parts=[TextPart(text)], timestamp=at)


def call(call_id: str, at: datetime, tool: str = WRITE) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(tool, {"day": "2027-03-01"}, tool_call_id=call_id)], timestamp=at)


def result(call_id: str, at: datetime, tool: str = "today") -> ModelRequest:
    return ModelRequest(parts=[ToolReturnPart(tool, "ok", tool_call_id=call_id, timestamp=at)], timestamp=at)


def exchange(n: int, at: datetime) -> list[ModelMessage]:
    """One turn: a question, a read tool between, and the answer."""
    return [prompt(f"question {n}", at), call(f"read-{n}", at + timedelta(seconds=1), tool="today"),
            result(f"read-{n}", at + timedelta(seconds=2)), reply(f"answer {n}", at + timedelta(seconds=3))]


def dumped(messages: list[ModelMessage]) -> bytes:
    return ModelMessagesTypeAdapter.dump_json(messages)


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "calendar.db"
    monkeypatch.setattr(calendar_db, "DB_PATH", path)
    asyncio.run(calendar_db.init_db())
    return path


@pytest.fixture
def run(db_path: Path) -> Iterator[Callable[[Callable[[aiosqlite.Connection], Awaitable[Any]]], Any]]:
    """Runs a coroutine function with a connection to the throwaway database."""
    async def with_db(fn: Callable[[aiosqlite.Connection], Awaitable[Any]]) -> Any:
        async with calendar_db.connect_db() as db:
            return await fn(db)
    yield lambda fn: asyncio.run(with_db(fn))


async def store(db: aiosqlite.Connection, messages: list[ModelMessage]) -> None:
    await message_store.replace_from(db, CID, None, [conversations.encode(m) for m in messages])


def row_ids(db_path: Path) -> list[int]:
    with sqlite3.connect(db_path) as c:
        return [r[0] for r in c.execute("SELECT id FROM agent_messages WHERE conversation_id = ? ORDER BY id", (CID,))]


# ── Migration ────────────────────────────────────────────────────────────

def test_migration_moves_each_conversation_once_and_keeps_the_lists(db_path: Path, run) -> None:
    earlier = NOW - timedelta(days=1)
    messages = exchange(1, earlier) + exchange(2, earlier + timedelta(minutes=5)) + exchange(3, NOW - timedelta(hours=2))
    with sqlite3.connect(db_path) as c:
        c.execute("INSERT INTO agent_conversations (id, messages) VALUES (?, ?)", (CID, dumped(messages).decode()))

    asyncio.run(calendar_db.init_db())
    asyncio.run(calendar_db.init_db())

    loaded = run(lambda db: conversations.load(db, CID))
    assert dumped(loaded) == dumped(messages)
    assert [m.timestamp for m in loaded] == [m.timestamp for m in messages]
    with sqlite3.connect(db_path) as c:
        flags = c.execute("SELECT opens_turn, opens_session FROM agent_messages ORDER BY id").fetchall()
        kept = c.execute("SELECT messages FROM agent_conversations WHERE id = ?", (CID,)).fetchone()[0]
    assert len(flags) == len(messages)
    assert [i for i, (turn, _) in enumerate(flags) if turn] == [0, 4, 8]
    # The second exchange came five minutes after the first; the third after a pause
    assert [i for i, (_, session) in enumerate(flags) if session] == [0, 8]
    assert kept == dumped(messages).decode()


def test_an_unreadable_conversation_stays_behind_without_stopping_the_app(db_path: Path, run) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute("INSERT INTO agent_conversations (id, messages) VALUES ('broken', '[{\"kind\": ')")
        c.execute("INSERT INTO agent_conversations (id, messages) VALUES (?, ?)",
                  (CID, dumped(exchange(1, NOW)).decode()))

    asyncio.run(calendar_db.init_db())

    assert len(row_ids(db_path)) == 4
    assert run(lambda db: conversations.load(db, "broken")) == []


# ── Turns ────────────────────────────────────────────────────────────────

def test_a_turn_appends_its_new_messages_only(db_path: Path, run) -> None:
    first = exchange(1, NOW - timedelta(minutes=10))
    run(lambda db: store(db, first))
    ids = row_ids(db_path)

    async def turn(db: aiosqlite.Connection) -> tuple[conversations.Turn, int]:
        loaded = await conversations.begin(db, CID, prompt=True, approvals=False)
        written = await conversations.save(db, loaded, [*loaded.history, *exchange(2, NOW)])
        return loaded, written

    loaded, written = run(turn)
    assert dumped(loaded.history) == dumped(first) and loaded.earlier is None and loaded.waiting == []
    after = row_ids(db_path)
    assert after[:4] == ids and len(after) == 8
    assert written == sum(len(conversations.encode(m).encode()) for m in exchange(2, NOW))


def test_saving_rewrites_from_the_first_message_the_run_changed(db_path: Path, run) -> None:
    messages = exchange(1, NOW - timedelta(minutes=3))
    run(lambda db: store(db, messages))
    ids = row_ids(db_path)

    async def turn(db: aiosqlite.Connection) -> list[ModelMessage]:
        loaded = await conversations.begin(db, CID, prompt=False, approvals=True)
        changed = [*loaded.history[:2], result("read-1", NOW, tool="today_again"), *loaded.history[3:], reply("more", NOW)]
        await conversations.save(db, loaded, changed)
        return changed

    changed = run(turn)
    after = row_ids(db_path)
    assert after[:2] == ids[:2] and min(after[2:]) > max(ids)
    assert dumped(run(lambda db: conversations.load(db, CID))) == dumped(changed)


def test_a_message_after_a_pause_starts_a_session_that_recaps_the_last(db_path: Path, run) -> None:
    old = exchange(1, NOW - timedelta(hours=3)) + exchange(2, NOW - timedelta(hours=2, minutes=50))
    run(lambda db: store(db, old))

    loaded = run(lambda db: conversations.begin(db, CID, prompt=True, approvals=False))
    assert loaded.history == [] and loaded.stored == []
    assert loaded.earlier == conversations.recap(old)
    assert "You: question 2" in loaded.earlier and "Coach: answer 2" in loaded.earlier

    run(lambda db: conversations.save(db, loaded, exchange(3, NOW)))
    # The next message, soon after, continues the new session only
    again = run(lambda db: conversations.begin(db, CID, prompt=True, approvals=False))
    assert dumped(again.history) == dumped(exchange(3, NOW))
    assert again.earlier == conversations.recap(old)
    history = run(lambda db: chat.history(db, CID))
    assert [m["role"] for m in history["messages"]].count("session") == 1


def test_the_recap_reads_back_past_short_sessions(db_path: Path, run) -> None:
    # Four short sessions, so the recap's three exchanges span more than one, behind long tool chains
    messages: list[ModelMessage] = []
    for n in range(4):
        at = NOW - timedelta(hours=10 - n)
        chain = [m for i in range(6) for m in (call(f"c{n}-{i}", at, tool="today"), result(f"c{n}-{i}", at))]
        messages += [prompt(f"question {n}", at), *chain, reply(f"answer {n}", at)]
    run(lambda db: store(db, messages))

    loaded = run(lambda db: conversations.begin(db, CID, prompt=True, approvals=False))
    assert loaded.earlier == conversations.recap(messages)
    assert "question 1" in loaded.earlier and "question 0" not in loaded.earlier


# ── Writes waiting for a yes ─────────────────────────────────────────────

def test_a_write_waiting_for_a_yes_survives_and_keeps_its_session(db_path: Path, run) -> None:
    long_ago = NOW - timedelta(hours=5)
    run(lambda db: store(db, [prompt("move friday", long_ago), call("w1", long_ago + timedelta(seconds=2))]))

    history = run(lambda db: chat.history(db, CID))
    assert history["pending"] == [{"id": "w1", "tool": WRITE, "args": {"day": "2027-03-01"}}]
    # A new message, even after a pause, answers it in the same session
    loaded = run(lambda db: conversations.begin(db, CID, prompt=True, approvals=False))
    assert [c.tool_call_id for c in loaded.waiting] == ["w1"] and len(loaded.history) == 2
    # The approval itself continues the session
    approving = run(lambda db: conversations.begin(db, CID, prompt=False, approvals=True))
    assert approving.waiting == [] and len(approving.history) == 2


# ── Pages ────────────────────────────────────────────────────────────────

def test_pages_of_turns_newest_first_add_up_to_the_conversation(db_path: Path, run) -> None:
    messages = [m for n in range(5) for m in exchange(n, NOW - timedelta(hours=6 - n))]
    run(lambda db: store(db, messages))

    whole = run(lambda db: chat.history(db, CID))
    assert set(whole) == {"messages", "pending"}
    pages, before = [], None
    while True:
        page = run(lambda db: chat.history(db, CID, turns=2, before=before))
        pages.insert(0, page["messages"])
        before = page["older"]
        if before is None:
            break
    assert len(pages) == 3
    assert [item for page in pages for item in page] == whole["messages"]
    assert [m["role"] for m in whole["messages"]].count("session") == 4


# ── Turns through the agent, with a stub model ───────────────────────────

def stub_agent() -> Agent[AgentDeps, str | DeferredToolRequests]:
    """An agent whose model asks to write once, then answers in words."""
    writes = FunctionToolset[AgentDeps](requires_approval=True)

    @writes.tool_plain(name=WRITE)
    def add_session(day: str) -> str:
        return f"added {day}"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        texts = [p.content for p in last.parts if isinstance(p, UserPromptPart)]
        if any("plan" in t for t in texts):
            return ModelResponse(parts=[ToolCallPart(WRITE, {"day": "2027-03-01"}, tool_call_id=f"w-{len(messages)}")])
        returns = [p for p in last.parts if isinstance(p, ToolReturnPart)]
        return ModelResponse(parts=[TextPart(f"done: {returns[0].content}" if returns else "hello")])

    return Agent(FunctionModel(respond, model_name="stub"), deps_type=AgentDeps,
                 output_type=[str, DeferredToolRequests], toolsets=[writes])


def test_turns_through_the_agent_store_approvals_and_usage(db_path: Path, run) -> None:
    agent = stub_agent()

    async def turn(db: aiosqlite.Connection, **kwargs: Any):
        deps = AgentDeps(z2=None, db=db, schedule=lambda *a: None)
        return await run_turn(agent, deps, CID, surface="test", **kwargs)

    first = run(lambda db: turn(db, prompt="hi"))
    assert first.output == "hello"
    ids = row_ids(db_path)

    asked = run(lambda db: turn(db, prompt="plan friday"))
    assert isinstance(asked.output, DeferredToolRequests)
    call_id = asked.output.approvals[0].tool_call_id
    assert row_ids(db_path)[:len(ids)] == ids
    assert [p["id"] for p in run(lambda db: chat.history(db, CID))["pending"]] == [call_id]

    approved = run(lambda db: turn(db, approvals=DeferredToolResults(approvals={call_id: True})))
    assert approved.output == "done: added 2027-03-01"
    assert run(lambda db: chat.history(db, CID))["pending"] == []

    run(lambda db: turn(db, prompt="plan saturday"))
    # A new message while that write waits is a no to it
    moved_on = run(lambda db: turn(db, prompt="never mind"))
    denied = [p for m in moved_on.new_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    assert denied and "moved on" in str(denied[0].content)
    assert run(lambda db: chat.history(db, CID))["pending"] == []

    stored = run(lambda db: conversations.load(db, CID))
    assert dumped(stored[-len(moved_on.all_messages()):]) == dumped(moved_on.all_messages())
    with sqlite3.connect(db_path) as c:
        assert c.execute("SELECT COUNT(*) FROM agent_usage WHERE conversation_id = ?", (CID,)).fetchone()[0] == 5
