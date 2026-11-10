"""The z2 agent: coaching instructions, the tools over z2's data, and the guides it
loads when a question needs them."""

import asyncio
import dataclasses
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic_ai import (
    Agent, AgentRunResult, DeferredToolRequests, DeferredToolResults, RunContext, capture_run_messages,
)
from pydantic_ai.agent import EventStreamHandler
from pydantic_ai.models import Model
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import Skills

from backend.agent import conversations, notes, usage
from backend.agent.tools import AgentDeps, memory_tools, read_tools, write_tools
from backend.config import settings

HERE = Path(__file__).parent
INSTRUCTIONS = (HERE / "instructions.md").read_text()

Output = str | DeferredToolRequests
_turn_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
LOCAL_PROVIDERS = ("ollama",)


def _now_and_page(ctx: RunContext[AgentDeps]) -> str:
    today = date.today()
    lines = [f"Today is {today:%A} {today.isoformat()}."]
    if ctx.deps.first_name:
        lines.append(f"The athlete's first name is {ctx.deps.first_name}. Call them that, or the name your "
                     "notes say they prefer, now and then; not in every message.")
    if ctx.deps.page:
        lines.append(f"The user is looking at: {ctx.deps.page}.")
    if ctx.deps.voice:
        lines.append("The user is talking to you and will hear your reply read aloud: answer in two or three "
                     "short spoken sentences, with no tables, lists or markdown. Offer the detail if they want it.")
    if ctx.deps.earlier:
        lines.append(ctx.deps.earlier)
    return "\n\n".join(lines)


async def _athlete_notes(ctx: RunContext[AgentDeps]) -> str | None:
    kept = await notes.all_notes(ctx.deps.db)
    if not kept:
        return None
    lines = "\n".join(f"- [{n['id']}] ({n['topic'] or 'note'}) {n['note']}" for n in kept)
    return f"What you know about this athlete (your notes; `forget` one by its id when it stops being true):\n{lines}"


async def _first_name(z2) -> str | None:
    """From the cached Strava profile; a turn goes on without it when Strava can't answer."""
    try:
        profile = await asyncio.to_thread(z2.strava_user_cache.get_athlete_profile)
    except Exception:
        return None
    return (profile or {}).get("firstname") or None


def build_agent(model: str | Model | None = None) -> Agent[AgentDeps, Output]:
    return Agent(
        model or settings.agent_model,
        deps_type=AgentDeps,
        output_type=[str, DeferredToolRequests],
        instructions=[INSTRUCTIONS, _athlete_notes, _now_and_page],
        toolsets=[read_tools, memory_tools, write_tools],
        # Its own workspace, so the guides are readable without giving the run any file access
        capabilities=[Skills("guides", workspace=LocalWorkspaceBackend(HERE))],
        defer_model_check=True,
    )


async def run_turn(
    agent: Agent[AgentDeps, Output],
    deps: AgentDeps,
    conversation_id: str,
    *,
    prompt: str | None = None,
    approvals: DeferredToolResults | None = None,
    model: str | Model | None = None,
    surface: str,
    record: bool = True,
    on_events: EventStreamHandler[AgentDeps] | None = None,
) -> AgentRunResult[Output]:
    """One turn of a stored conversation: a new message, or the answers to the writes it
    asked approval for. The model sees the current session only (see conversations.SESSION_GAP);
    the whole conversation is saved. Records what the turn cost. `on_events`
    sees the run as it happens: tool calls, their results, and the reply as it is written."""
    # Turns of one conversation run one after another: each saves the whole history it loaded
    async with _turn_locks[conversation_id]:
        stored = await conversations.load(deps.db, conversation_id)
        start = conversations.current_session(stored, new_message=prompt is not None)
        if start > 0:
            deps = dataclasses.replace(deps, earlier=conversations.recap(stored[:start]))
        if deps.first_name is None and deps.z2 is not None:
            deps = dataclasses.replace(deps, first_name=await _first_name(deps.z2))
        with capture_run_messages() as messages:
            try:
                result = await agent.run(
                    prompt, message_history=stored[start:], deferred_tool_results=approvals, deps=deps, model=model,
                    event_stream_handler=on_events,
                )
            except Exception:
                # Keep what ran before the failure (an approved write and its result), so it
                # never shows as pending again and a second yes can't repeat it
                if messages:
                    await conversations.save(deps.db, conversation_id, stored[:start] + messages)
                raise
        await conversations.save(deps.db, conversation_id, stored[:start] + result.all_messages())
    if record:
        spent = result.usage
        # A local model costs nothing; genai-prices just has no price for it
        if spent.cost is None and result.response.provider_name in LOCAL_PROVIDERS:
            spent = dataclasses.replace(spent, cost=Decimal(0))
        await usage.record(
            deps.db, conversation_id=conversation_id, surface=surface,
            model=result.response.model_name or str(model or settings.agent_model), usage=spent,
        )
    return result
