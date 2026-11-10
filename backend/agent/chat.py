"""The agent behind the app's chat panel: one turn at a time, as plain JSON the panel
renders (the reply, the tools it used, the writes waiting for a yes)."""

import asyncio
import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

import aiosqlite
from pydantic_ai import (
    AgentRunResult, AgentStreamEvent, FunctionToolCallEvent, FunctionToolResultEvent, ModelAPIError,
    PartDeltaEvent, PartStartEvent, RunContext, TextPartDelta, ThinkingPart, DeferredToolRequests, DeferredToolResults, ModelMessage, ModelRequest, ModelResponse,
    TextPart, ToolCallPart, ToolDenied, ToolReturnPart, UserPromptPart,
)

from backend.agent import conversations, preferences
from backend.agent.agent import Output, build_agent, run_turn
from backend.agent.tools import AgentDeps, memory_tools, write_tools
from backend.services.sessions import Schedule
from zone2.core import Zone2

# Tools whose results change what pages show, so the panel refreshes them
CHANGING_TOOLS = set(write_tools.tools) | set(memory_tools.tools)
_agent = None


def _the_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


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


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def stream(z2: Zone2, db: aiosqlite.Connection, schedule: Schedule, *, conversation_id: str,
                 page: str | None, message: str | None = None,
                 approvals: dict[str, bool] | None = None, voice: bool = False) -> AsyncIterator[str]:
    """One turn as server-sent events, so the panel shows the run as it happens:
    `thinking`, each `tool` call and its `tool_done`, the reply's `text` as it is written,
    then `done` with the whole turn (or `error`)."""
    events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def relay(ctx: RunContext[AgentDeps], stream_events: AsyncIterable[AgentStreamEvent]) -> None:
        async for event in stream_events:
            if isinstance(event, FunctionToolCallEvent):
                await events.put({"type": "tool", "tool": event.part.tool_name, "args": event.part.args_as_dict()})
            elif isinstance(event, FunctionToolResultEvent):
                await events.put({"type": "tool_done", "tool": event.part.tool_name})
            elif isinstance(event, PartStartEvent) and isinstance(event.part, TextPart) and event.part.content:
                await events.put({"type": "text", "delta": event.part.content})
            elif isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
                await events.put({"type": "thinking"})
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta) and event.delta.content_delta:
                await events.put({"type": "text", "delta": event.delta.content_delta})

    model = await preferences.model(db)

    async def run() -> None:
        deps = AgentDeps(z2=z2, db=db, schedule=schedule, page=page, voice=voice)
        results = DeferredToolResults(approvals={
            call_id: True if yes else ToolDenied("The user said no.") for call_id, yes in approvals.items()
        }) if approvals is not None else None
        try:
            result = await run_turn(_the_agent(), deps, conversation_id, prompt=message, approvals=results,
                                    model=model, surface="chat", on_events=relay)
            await events.put({"type": "done", "turn": _turn(result, conversation_id)})
        except ModelAPIError as e:
            await events.put({"type": "error", "detail": model_error(e, model)})
        except Exception as e:  # the panel must hear the run ended, whatever ended it
            await events.put({"type": "error", "detail": f"The agent failed: {e}"})
        finally:
            await events.put(None)

    task = asyncio.create_task(run())
    try:
        while (event := await events.get()) is not None:
            yield _sse(event)
    finally:
        await task


def transcript(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """The conversation as the panel shows it: your words, the agent's, the tools between,
    and where each session after the first began."""
    out: list[dict[str, Any]] = []
    starts = set(conversations.session_starts(messages)[1:])
    for i, message in enumerate(messages):
        if i in starts:
            out.append({"role": "session", "at": message.timestamp.isoformat()})
        for part in message.parts:
            if isinstance(message, ModelRequest) and isinstance(part, UserPromptPart) and isinstance(part.content, str):
                out.append({"role": "user", "text": part.content})
            elif isinstance(message, ModelResponse) and isinstance(part, TextPart) and part.content.strip():
                out.append({"role": "agent", "text": part.content})
            elif isinstance(message, ModelResponse) and isinstance(part, ToolCallPart):
                out.append({"role": "tool", "tool": part.tool_name})
    return out


def pending_calls(messages: list[ModelMessage]) -> list[ToolCallPart]:
    """The writes the conversation's last response asked approval for and that have no answer yet."""
    responses = [i for i, m in enumerate(messages) if isinstance(m, ModelResponse)]
    if not responses:
        return []
    last = responses[-1]
    answered = {p.tool_call_id for m in messages[last + 1:] for p in m.parts if isinstance(p, ToolReturnPart)}
    writes = set(write_tools.tools)
    return [p for p in messages[last].parts
            if isinstance(p, ToolCallPart) and p.tool_name in writes and p.tool_call_id not in answered]


async def history(db: aiosqlite.Connection, conversation_id: str) -> dict[str, Any]:
    messages = await conversations.load(db, conversation_id)
    return {
        "messages": transcript(messages),
        "pending": [{"id": c.tool_call_id, "tool": c.tool_name, "args": c.args_as_dict()} for c in pending_calls(messages)],
    }
