"""The z2 agent: coaching instructions, the tools over z2's data, and the guides it
loads when a question needs them."""

import asyncio
import dataclasses
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic_ai import (
    Agent, AgentRunResult, DeferredToolRequests, DeferredToolResults, FunctionToolset, RunContext, ToolDenied,
    capture_run_messages,
)
from pydantic_ai.agent import EventStreamHandler
from pydantic_ai.capabilities import Capability
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import Skills

from backend.agent import conversations, notes, usage
from backend.agent.tools import (
    AgentDeps, app_tools, gear_tools, history_tools, memory_tools, read_tools, workout_tools, write_tools,
)
from backend.config import settings
from backend.services import plans

HERE = Path(__file__).parent
INSTRUCTIONS = (HERE / "instructions.md").read_text()

Output = str | DeferredToolRequests
_turn_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
LOCAL_PROVIDERS = ("ollama",)
# A reply someone waits for thinks briefly: Luna's default (medium) effort made a turn up to three
# times slower, most of it reasoning, for answers no better on the questions tried
QUICK = ModelSettings(thinking="low")


def _now_and_page(ctx: RunContext[AgentDeps]) -> str:
    today = date.today()
    lines = [f"Today is {today:%A} {today.isoformat()}."]
    if ctx.deps.first_name:
        lines.append(f"The athlete's first name is {ctx.deps.first_name}: use it, or the name your notes say "
                     "they prefer, now and then, not in every message.")
    if ctx.deps.page:
        lines.append(f"The user is looking at: {ctx.deps.page}.")
    if ctx.deps.earlier:
        lines.append(ctx.deps.earlier)
    return "\n\n".join(lines)


async def _athlete_notes(ctx: RunContext[AgentDeps]) -> str | None:
    kept = await notes.athlete_notes(ctx.deps.db)
    if not kept:
        return None
    lines = "\n".join(f"- [{n['id']}] ({n['topic'] or 'note'}) {n['note']}" for n in kept)
    return f"Your notes on the athlete (ids for `forget`):\n{lines}"


async def _active_plans(ctx: RunContext[AgentDeps]) -> str | None:
    """A line per active plan, so the model knows to read its agreements in plan_detail."""
    active = await plans.list_plans(ctx.deps.db, include_done=False)
    if not active:
        return None
    lines = "\n".join(f"- plan {p['id']}: {p['name']}, {p['start_date']} to {p['end_date']}"
                      + (f", goal {p['goal']}" if p.get("goal") else "") for p in active)
    return f"Active plans; plan_detail has each one's agreements, checkpoints and log:\n{lines}"


async def _first_name(z2) -> str | None:
    """From the cached Strava profile; a turn goes on without it when Strava can't answer."""
    try:
        profile = await asyncio.to_thread(z2.strava_user_cache.get_athlete_profile)
    except Exception:
        return None
    return (profile or {}).get("firstname") or None


ON_DEMAND: dict[str, tuple[FunctionToolset[AgentDeps], str]] = {
    "gear": (gear_tools, "Shoes and bikes: km on each, when they were used, retiring a pair, which to race in."),
    "history": (history_tools, "Years and streaks: a year's totals against another year, all-time totals per "
                               "sport, the longest and current streaks."),
    "workouts": (workout_tools, "The workout library: save a new workout, change or delete a saved one (each "
                                "needs the athlete's approval)."),
}
"""Capabilities whose tools the model loads when a question needs them."""


def build_agent(model: str | Model | None = None) -> Agent[AgentDeps, Output]:
    return Agent(
        model or settings.agent_model,
        deps_type=AgentDeps,
        output_type=[str, DeferredToolRequests],
        instructions=[INSTRUCTIONS, _athlete_notes, _active_plans, _now_and_page],
        toolsets=[read_tools, memory_tools, app_tools, write_tools],
        capabilities=[
            # Its own workspace, so the guides are readable without giving the run any file access
            Skills("guides", workspace=LocalWorkspaceBackend(HERE)),
            # Asked about now and then, so their tools cost nothing until a turn loads them
            *(Capability(id=id, toolsets=[toolset], description=description, defer_loading=True)
              for id, (toolset, description) in ON_DEMAND.items()),
        ],
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
    model_settings: ModelSettings | None = QUICK,
) -> AgentRunResult[Output]:
    """One turn of a stored conversation: a new message, or the answers to the writes it
    asked approval for. The model sees the current session only (see conversations.SESSION_GAP);
    the whole conversation stays stored. Records what the turn cost. `on_events`
    sees the run as it happens: tool calls, their results, and the reply as it is written.
    `model_settings` None leaves the model's own reasoning effort, for a turn nobody waits for."""
    # Turns of one conversation run one after another: each continues from what the last one stored
    async with _turn_locks[conversation_id]:
        turn = await conversations.begin(deps.db, conversation_id, prompt=prompt is not None,
                                         approvals=approvals is not None)
        # A new message while writes wait for a yes is a no to them, in the same session
        if turn.waiting:
            approvals = DeferredToolResults(approvals={
                c.tool_call_id: ToolDenied("Not answered: the conversation moved on.") for c in turn.waiting
            })
        if turn.earlier is not None:
            deps = dataclasses.replace(deps, earlier=turn.earlier)
        if deps.first_name is None and deps.z2 is not None:
            deps = dataclasses.replace(deps, first_name=await _first_name(deps.z2))
        with capture_run_messages() as messages:
            try:
                result = await agent.run(
                    prompt, message_history=turn.history, deferred_tool_results=approvals, deps=deps, model=model,
                    model_settings=model_settings, event_stream_handler=on_events,
                )
            except Exception:
                # Keep what ran before the failure (an approved write and its result), so it
                # never shows as pending again and a second yes can't repeat it
                if messages:
                    await conversations.save(deps.db, turn, messages)
                raise
        await conversations.save(deps.db, turn, result.all_messages())
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
