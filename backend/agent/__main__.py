"""Talk to the z2 agent from a terminal, against this machine's z2 data.

    python -m backend.agent tools                      what the model sees: its tools and guides
    python -m backend.agent call TOOL '{"arg": 1}'     run one tool through the agent, no model
    python -m backend.agent ask "…" [-c ID]            one turn; -c continues a conversation
    python -m backend.agent approve -c ID [--deny ID]  answer the writes a turn asked approval for
    python -m backend.agent chat [-c ID]               a conversation, approving writes as they come
    python -m backend.agent notes [add TEXT | rm ID]   what the agent keeps about the athlete

`ask`, `approve` and `chat` use the configured model (STRAVA_WEB_AGENT_MODEL, or --model)
and record what each turn cost. Garmin pushes after a calendar write are skipped unless
--push-garmin is given: this machine's calendar is not the one the watch follows.
"""

import argparse
import asyncio
import inspect
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

from pydantic_ai import (
    AgentRunResult, ModelAPIError, DeferredToolRequests, DeferredToolResults, ModelMessage, ModelRequest, ModelResponse,
    TextPart, ToolCallPart, ToolDenied, ToolReturnPart,
)
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.agent import conversations, notes
from backend.agent.agent import Output, build_agent, run_turn
from backend.agent.chat import model_error, pending_calls
from backend.agent.tools import AgentDeps
from backend.config import settings
from backend.db import connect_db, init_db
from backend.services.races import refresh_race_activities
from zone2.core import Zone2

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def _scripted(tool: str, args: dict[str, Any]) -> FunctionModel:
    """A stand-in model that calls one tool, then answers with what it returned."""
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        for part in last.parts if isinstance(last, ModelRequest) else []:
            if isinstance(part, ToolReturnPart):
                return ModelResponse(parts=[TextPart(part.model_response_str())])
            if isinstance(part, RetryPromptPart):
                return ModelResponse(parts=[TextPart(f"(the tool asked for a retry) {part.model_response()}")])
        return ModelResponse(parts=[ToolCallPart(tool, args)])
    return FunctionModel(respond, model_name="scripted")


def _listing() -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        lines = []
        for t in info.function_tools:
            params = ", ".join(t.parameters_json_schema.get("properties", {}))
            lines.append(f"{BOLD}{t.name}{RESET}({params})\n  {DIM}{(t.description or '').strip().splitlines()[0]}{RESET}")
        return ModelResponse(parts=[TextPart("\n".join(lines))])
    return FunctionModel(respond, model_name="listing")


def _show_steps(result: AgentRunResult[Output]) -> None:
    for message in result.new_messages():
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                print(f"{DIM}· {part.tool_name}({part.args_as_json_str()}){RESET}")


def _show_usage(result: AgentRunResult[Output]) -> None:
    u = result.usage
    cost = f"${u.cost:.4f}" if u.cost is not None else "no price"
    print(f"{DIM}{u.requests} requests, {u.tool_calls} tool calls, "
          f"{u.input_tokens} in ({u.cache_read_tokens} cached) / {u.output_tokens} out, {cost}{RESET}")


def _show_pending(requests: DeferredToolRequests) -> None:
    print(f"{BOLD}Asks to change the calendar:{RESET}")
    for call in requests.approvals:
        print(f"  [{call.tool_call_id}] {call.tool_name} {call.args_as_json_str()}")


class _Garmin:
    """Collects the Garmin pushes a write queues, and runs them only when allowed."""

    def __init__(self, allowed: bool):
        self.allowed = allowed
        self.queued: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def schedule(self, fn: Callable[..., Any], *args: Any) -> None:
        self.queued.append((fn, args))

    async def flush(self) -> None:
        for fn, args in self.queued:
            if not self.allowed:
                print(f"{DIM}Garmin push skipped: {fn.__name__}{RESET}")
            elif inspect.iscoroutinefunction(fn):
                await fn(*args)
            else:
                await asyncio.to_thread(fn, *args)
        self.queued.clear()


async def main(args: argparse.Namespace) -> None:
    os.environ.setdefault("GARMINTOKENS", ".strava/garmin")
    z2 = Zone2(workdir=settings.workdir, auto_sync=False, sync_max_age_hours=settings.sync_max_age_hours)
    await init_db()
    await asyncio.to_thread(refresh_race_activities, z2)
    garmin = _Garmin(allowed=args.push_garmin)
    agent = build_agent(args.model)

    async with connect_db() as db:
        deps = AgentDeps(z2=z2, db=db, schedule=garmin.schedule, page=args.page)

        if args.command == "tools":
            print((await agent.run("list", deps=deps, model=_listing())).output)
            return

        if args.command == "notes":
            if args.action == "add":
                print(f"Noted ({await notes.add(db, ' '.join(args.text))}).")
            elif args.action == "rm":
                print("Forgot it." if await notes.delete(db, int(args.text[0])) else "No such note.")
            for n in await notes.all_notes(db):
                print(f"[{n['id']}] {n['note']} {DIM}({n['added']}){RESET}")
            return

        if args.command == "call":
            result = await agent.run(f"call {args.tool}", deps=deps, model=_scripted(args.tool, json.loads(args.args)))
            if isinstance(result.output, DeferredToolRequests):
                _show_pending(result.output)
                if not args.approve:
                    print(f"{DIM}Not run: pass --approve to run it.{RESET}")
                    return
                approvals = DeferredToolResults(approvals={c.tool_call_id: True for c in result.output.approvals})
                result = await agent.run(message_history=result.all_messages(), deferred_tool_results=approvals,
                                         deps=deps, model=_scripted(args.tool, json.loads(args.args)))
                await garmin.flush()
            print(result.output)
            return

        conversation = args.conversation or f"cli-{uuid.uuid4().hex[:8]}"
        turn = dict(conversation_id=conversation, surface="cli")

        async def report(result: AgentRunResult[Output]) -> None:
            await garmin.flush()
            _show_steps(result)
            if isinstance(result.output, DeferredToolRequests):
                _show_pending(result.output)
            else:
                print(result.output)
            _show_usage(result)

        if args.command == "ask":
            await report(await run_turn(agent, deps, prompt=args.prompt, **turn))
            print(f"{DIM}conversation {conversation}{RESET}")
            return

        if args.command == "approve":
            pending = pending_calls(await conversations.load(db, conversation))
            if not pending:
                print("Nothing is waiting for approval in this conversation.")
                return
            denied = set(args.deny or [])
            approvals = DeferredToolResults(approvals={
                c.tool_call_id: ToolDenied(args.reason or "The user said no.") if c.tool_call_id in denied else True
                for c in pending
            })
            await report(await run_turn(agent, deps, approvals=approvals, **turn))
            return

        print(f"{DIM}conversation {conversation} · {args.model or settings.agent_model} · empty line to quit{RESET}")
        while prompt := input(f"\n{BOLD}you ›{RESET} ").strip():
            result = await run_turn(agent, deps, prompt=prompt, **turn)
            while isinstance(result.output, DeferredToolRequests):
                await report(result)
                answers: dict[str, bool | ToolDenied] = {}
                for call in result.output.approvals:
                    yes = input(f"Run {call.tool_name}? [y/N] ").strip().lower() == "y"
                    answers[call.tool_call_id] = True if yes else ToolDenied("The user said no.")
                result = await run_turn(agent, deps, approvals=DeferredToolResults(approvals=answers), **turn)
            print()
            await report(result)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.agent", description="Talk to the z2 agent.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", help="a Pydantic AI model string, e.g. openai:gpt-6.1-terra or ollama:qwen3")
    common.add_argument("--page", help='what the user is looking at, e.g. "activity 1234"')
    common.add_argument("--push-garmin", action="store_true", help="let calendar writes push to Garmin")
    common.add_argument("-c", "--conversation", help="conversation id to continue")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tools", parents=[common])
    call = sub.add_parser("call", parents=[common])
    call.add_argument("tool")
    call.add_argument("args", nargs="?", default="{}")
    call.add_argument("--approve", action="store_true", help="run a write without asking")
    ask = sub.add_parser("ask", parents=[common])
    ask.add_argument("prompt")
    approve = sub.add_parser("approve", parents=[common])
    approve.add_argument("--deny", nargs="*", metavar="CALL_ID", help="tool call ids to refuse; the rest run")
    approve.add_argument("--reason", help="what to tell the agent about a refusal")
    sub.add_parser("chat", parents=[common])
    notes_cmd = sub.add_parser("notes", parents=[common])
    notes_cmd.add_argument("action", nargs="?", choices=["add", "rm"])
    notes_cmd.add_argument("text", nargs="*")
    return parser


if __name__ == "__main__":
    try:
        asyncio.run(main(_parser().parse_args()))
    except ModelAPIError as e:
        raise SystemExit(f"The model failed: {model_error(e, 'the model')}") from None
