"""The agent behind the app's chat panel: one turn at a time, as plain JSON the panel
renders (the reply, the tools it used, the writes waiting for a yes)."""

import asyncio
import inspect
import json
import logging
import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from typing import Any

import aiosqlite
from pydantic_ai import (
    AgentRunResult, AgentStreamEvent, FunctionToolCallEvent, FunctionToolResultEvent, ModelAPIError,
    PartDeltaEvent, PartStartEvent, RunContext, TextPartDelta, ThinkingPart, DeferredToolRequests, DeferredToolResults, ModelMessage, ModelRequest, ModelResponse,
    TextPart, ToolCallPart, ToolDenied, ToolReturnPart, UserPromptPart,
)

from backend.agent import conversations, message_store, preferences
from backend.agent.agent import Output, build_agent, run_turn
from backend.agent.tools import AgentDeps, memory_tools, workout_tools, write_tools
from backend.db import connect_db
from zone2.core import Zone2
from zone2.utils import SportCategory, get_sport_category

logger = logging.getLogger(__name__)

# The tools that wait for the user's yes
WRITE_TOOLS = set(write_tools.tools) | set(workout_tools.tools)
# Tools whose results change what pages show, so the panel refreshes them
CHANGING_TOOLS = WRITE_TOOLS | set(memory_tools.tools) | {"sync_now"}
_agent = None
# Turns and their follow-ups run on their own, so they finish when the panel closes or the
# phone locks; this keeps them referenced until they do
_running: set[asyncio.Task] = set()


def the_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def _keep(task: asyncio.Task) -> None:
    _running.add(task)
    task.add_done_callback(_running.discard)


def spawn(fn: Callable[..., Any], *args: Any) -> None:
    """Run a write's follow-up (a Garmin push) in the background, the `schedule` of turns that
    may outlive the request that started them."""
    async def call() -> None:
        try:
            if inspect.iscoroutinefunction(fn):
                await fn(*args)
            else:
                await asyncio.to_thread(fn, *args)
        except Exception:
            logger.exception("%s failed in the background", getattr(fn, "__name__", fn))
    _keep(asyncio.create_task(call()))


def model_error(e: ModelAPIError, model: str) -> str:
    """The provider's own words for a failed request, e.g. "You have no credits remaining"."""
    body = getattr(e, "body", None)
    message = body.get("message") if isinstance(body, dict) else None
    return f"{model}: {message or e.message}"


def _turn(result: AgentRunResult[Output], conversation_id: str) -> dict[str, Any]:
    tools, changed = [], False
    for message in result.new_messages():
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                tools.append({"tool": part.tool_name, "args": part.args_as_dict()})
            elif isinstance(part, ToolReturnPart) and part.tool_name in CHANGING_TOOLS:
                changed = True
    output = result.output
    pending = (
        [{"id": c.tool_call_id, "tool": c.tool_name, "args": c.args_as_dict()} for c in output.approvals]
        if isinstance(output, DeferredToolRequests) else []
    )
    u = result.usage
    return {
        "conversation_id": conversation_id,
        "reply": output if isinstance(output, str) else None,
        "tools": tools,
        "pending": pending,
        "changed": changed,
        "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                  "cost_usd": float(u.cost) if u.cost is not None else None},
    }


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def stream(z2: Zone2, *, conversation_id: str, page: str | None, message: str | None = None,
                 approvals: dict[str, bool] | None = None,
                 sync: Callable[[int | None], Awaitable[str | None]] | None = None,
                 garmin_sync: asyncio.Future[None] | None = None) -> AsyncIterator[str]:
    """One turn as server-sent events, so the panel shows the run as it happens:
    `thinking`, each `tool` call and its `tool_done`, the reply's `text` as it is written,
    then `done` with the whole turn (or `error`). The turn runs on its own with its own
    connection: if the panel goes away mid-turn, it still finishes and is saved."""
    events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    started = time.monotonic()
    tool_started: dict[str, float] = {}
    tool_times: list[str] = []

    async def relay(ctx: RunContext[AgentDeps], stream_events: AsyncIterable[AgentStreamEvent]) -> None:
        async for event in stream_events:
            if isinstance(event, FunctionToolCallEvent):
                tool_started[event.part.tool_call_id] = time.monotonic()
                await events.put({"type": "tool", "tool": event.part.tool_name, "args": event.part.args_as_dict()})
            elif isinstance(event, FunctionToolResultEvent):
                took = time.monotonic() - tool_started.pop(event.part.tool_call_id, time.monotonic())
                tool_times.append(f"{event.part.tool_name} {took:.1f}s")
                await events.put({"type": "tool_done", "tool": event.part.tool_name})
                if event.part.tool_name == "open_page" and isinstance(event.part, ToolReturnPart):
                    await events.put({"type": "open", "path": event.part.content})
            elif isinstance(event, PartStartEvent) and isinstance(event.part, TextPart) and event.part.content:
                await events.put({"type": "text", "delta": event.part.content})
            elif isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
                await events.put({"type": "thinking"})
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta) and event.delta.content_delta:
                await events.put({"type": "text", "delta": event.delta.content_delta})

    results = DeferredToolResults(approvals={
        call_id: True if yes else ToolDenied("The user said no.") for call_id, yes in approvals.items()
    }) if approvals is not None else None

    async def run() -> None:
        model = "the coach's model"
        try:
            async with connect_db() as db:
                model = await preferences.model(db)
                deps = AgentDeps(z2=z2, db=db, schedule=spawn, page=page, sync=sync,
                                 garmin_sync=garmin_sync)
                result = await run_turn(the_agent(), deps, conversation_id, prompt=message, approvals=results,
                                        model=model, surface="chat", on_events=relay)
            logger.info("Coach turn took %.1fs on %s: %d model requests; tools: %s", time.monotonic() - started,
                        model, result.usage.requests, ", ".join(tool_times) or "none")
            await events.put({"type": "done", "turn": _turn(result, conversation_id)})
        except ModelAPIError as e:
            await events.put({"type": "error", "detail": model_error(e, model)})
        except Exception as e:  # the panel must hear the run ended, whatever ended it
            await events.put({"type": "error", "detail": f"The agent failed: {e}"})
        finally:
            await events.put(None)

    _keep(asyncio.create_task(run()))
    while (event := await events.get()) is not None:
        yield sse(event)


REVIEW_PROMPT = """{mark}After your {kind}: {name}
The athlete isn't here: z2 just synced activity {activity_id} ({name}, {when}), which fulfils the \
planned session {session_id} ("{title}" on {date}{plan}). Review it the way you review a session, and \
log the review. Then write it to them as your message, which they'll read later: the verdict first, \
then the one or two numbers that matter, in a few lines. If the session is a plan's checkpoint, apply \
its rule, looking up any metric it names, and propose record_checkpoint and any change the rule calls \
for as write calls, with your message: they wait for the athlete's yes. Change nothing else, and ask \
nothing."""
KIND = {SportCategory.RUNNING: "run", SportCategory.WALKING: "walk", SportCategory.CYCLING: "ride",
        SportCategory.SWIMMING: "swim"}


async def review(z2: Zone2, activity_id: int, session: dict[str, Any]) -> None:
    """The coach's review of a new activity against the planned session it fulfils, left in
    the conversation for the athlete to read later. Writes it proposes wait for their yes."""
    started = time.monotonic()
    row = z2.strava_activities_cache.get_activity_by_id(activity_id)
    prompt = REVIEW_PROMPT.format(
        mark=conversations.EVENT_MARK, kind=KIND.get(get_sport_category(row.get("sport_type")), "session"),
        name=row.get("name"), activity_id=activity_id, when=str(row.get("start_date_local"))[:16],
        session_id=session["id"], title=session["title"], date=session["date"],
        plan=f", plan {session['plan_id']} ({session['plan_name']})" if session.get("plan_id") else "",
    )
    async with connect_db() as db:
        model = await preferences.model(db)
        deps = AgentDeps(z2=z2, db=db, schedule=spawn)
        result = await run_turn(the_agent(), deps, message_store.MAIN, prompt=prompt, model=model, surface="review",
                                model_settings=None)
    logger.info("Coach review of activity %s took %.1fs on %s: %d model requests", activity_id,
                time.monotonic() - started, model, result.usage.requests)


def transcript(messages: list[ModelMessage], starts: set[int]) -> list[dict[str, Any]]:
    """The conversation as the panel shows it: your words, the agent's, the tools between,
    and where each session after the first began (`starts`, indices into `messages`). A review
    the coach gave itself that ended on a write waiting for a yes, without a word, shows the
    review it logged instead."""
    out: list[dict[str, Any]] = []
    event_turn, said, logged = False, False, None

    def close_turn() -> None:
        if event_turn and not said and logged:
            out.append({"role": "agent", "text": logged})

    for i, message in enumerate(messages):
        if i in starts:
            out.append({"role": "session", "at": message.timestamp.isoformat()})
        for part in message.parts:
            if isinstance(message, ModelRequest) and isinstance(part, UserPromptPart) and isinstance(part.content, str):
                close_turn()
                title = conversations.event_title(part.content)
                event_turn, said, logged = title is not None, False, None
                out.append({"role": "event", "text": title, "at": message.timestamp.isoformat()} if title
                           else {"role": "user", "text": part.content})
            elif isinstance(message, ModelResponse) and isinstance(part, TextPart) and part.content.strip():
                said = True
                out.append({"role": "agent", "text": part.content})
            elif isinstance(message, ModelResponse) and isinstance(part, ToolCallPart):
                if part.tool_name == "log_entry":
                    entry = part.args_as_dict()
                    logged = f"**{entry.get('title', '')}**\n\n{entry.get('body') or ''}".strip()
                out.append({"role": "tool", "tool": part.tool_name})
    close_turn()
    return out


def pending_calls(messages: list[ModelMessage]) -> list[ToolCallPart]:
    """The writes the conversation's last response asked approval for and that have no answer yet."""
    return [c for c in conversations.unanswered_calls(messages) if c.tool_name in WRITE_TOOLS]


async def history(db: aiosqlite.Connection, conversation_id: str, turns: int | None = None,
                  before: int | None = None) -> dict[str, Any]:
    """The conversation as the panel shows it, with the writes waiting for a yes. With `turns` or
    `before`, a page: the last `turns` turns before the cursor `before`, and `older`, the cursor
    for the page before it (None once the page starts the conversation)."""
    page = await conversations.page(db, conversation_id, turns, before)
    pending = pending_calls(await conversations.tail(db, conversation_id))
    out: dict[str, Any] = {
        "messages": transcript(page.messages, page.session_starts),
        "pending": [{"id": c.tool_call_id, "tool": c.tool_name, "args": c.args_as_dict()} for c in pending],
    }
    if turns is not None or before is not None:
        out["older"] = page.older
    return out
