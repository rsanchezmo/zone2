import asyncio
import functools
import importlib
from datetime import timedelta

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agent import load_module, preferences, reviews
from backend.agent import usage as agent_usage
from backend.db import connect_db, get_db
from backend.dependencies import get_z2
from backend.routers import garmin as garmin_sync
from backend.services import sync as strava_sync
from zone2.core import Zone2

router = APIRouter()

# The agent itself (Pydantic AI, ~60 MB) is imported when the chat first opens, not at startup.

# Data older than this is brought up to date when the chat opens and when a message arrives
FRESH_FOR = timedelta(minutes=15)
# How long the reply waits for Strava's sync; a slower one finishes in the background
SYNC_WAIT_S = 20


@router.get("/usage")
async def usage(days: int = Query(default=30, ge=1, le=365), db: aiosqlite.Connection = Depends(get_db)):
    """What the agent has cost: totals all time and this month, per day, and per model."""
    credit = await preferences.credit(db)
    left = None
    if credit:
        amount, since = credit
        spent = await agent_usage.spent_since(db, since)
        left = {"added_usd": amount, "since": since, "spent_usd": spent, "left_usd": amount - spent}
    return {"model": await preferences.model(db), "credit": left, **await agent_usage.summary(db, days)}


@router.get("/status")
async def status(db: aiosqlite.Connection = Depends(get_db)):
    """Whether the agent can answer (a key for its model's provider), its model, and how many
    of its reviews are unread."""
    model = await preferences.model(db)
    return {"available": preferences.has_key(model), "model": model, "unread": await reviews.unread(db)}


@router.post("/seen")
async def seen(db: aiosqlite.Connection = Depends(get_db)):
    """The athlete opened the chat: its reviews so far are read."""
    await reviews.mark_seen(db)
    return {"unread": 0}


@router.post("/open")
async def opened(z2: Zone2 = Depends(get_z2)):
    """The athlete opened the chat: data older than FRESH_FOR starts syncing and the agent loads
    while they type, so their message finds both ready, or waits only for the rest."""
    strava, garmin = strava_sync.catch_up(z2, FRESH_FOR), garmin_sync.catch_up(z2, FRESH_FOR)
    asyncio.get_running_loop().run_in_executor(None, importlib.import_module, "backend.agent.chat")
    return {"strava_syncing": strava is not None, "garmin_syncing": garmin is not None}


@router.post("/review/{activity_id}")
async def review(activity_id: int):
    """Have the coach review an activity again, as it does each new one after a sync."""
    await asyncio.to_thread(reviews.queue, [activity_id], True)
    return {"status": "queued"}


@router.get("/settings")
async def get_settings(db: aiosqlite.Connection = Depends(get_db)):
    """The coach's settings on the Profile page: its model, with the models offered and their
    prices per million tokens."""
    return {"model": await preferences.model(db), "models": preferences.options()}


class SettingsUpdate(BaseModel):
    model: str | None = None
    credit_usd: float | None = None  # a top-up on the OpenAI account; counting starts today


@router.put("/settings")
async def put_settings(update: SettingsUpdate, db: aiosqlite.Connection = Depends(get_db)):
    try:
        await preferences.save(db, model_id=update.model, credit_usd=update.credit_usd)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return await get_settings(db)


@router.get("/conversations/{conversation_id}")
async def conversation(conversation_id: str, db: aiosqlite.Connection = Depends(get_db)):
    """A conversation as the chat panel shows it, with any writes still waiting for a yes."""
    chat = await load_module("chat")
    return await chat.history(db, conversation_id)


class ChatTurn(BaseModel):
    message: str
    conversation_id: str | None = None
    page: str | None = None


class ApprovalTurn(BaseModel):
    conversation_id: str
    approvals: dict[str, bool]
    page: str | None = None


async def _check_available() -> None:
    """503 unless the coach's model can answer."""
    async with connect_db() as db:
        model = await preferences.model(db)
    if not preferences.has_key(model):
        raise HTTPException(status_code=503, detail=f"The coach has no key for {model}")


@router.post("/chat")
async def chat_turn(turn: ChatTurn, z2: Zone2 = Depends(get_z2)):
    """One message to the agent, streamed as server-sent events (see `chat.stream`). Writes
    it wants to make come back as `pending` in the final `done` event, for approval."""
    await _check_available()
    chat = await load_module("chat")
    conversations = await load_module("conversations")
    conversation_id = turn.conversation_id or conversations.MAIN
    return _streamed(chat, z2, catch_up=True, conversation_id=conversation_id, page=turn.page,
                     message=turn.message)


@router.post("/approve")
async def approve_turn(turn: ApprovalTurn, z2: Zone2 = Depends(get_z2)):
    """Your yes or no to each pending write; the agent then carries on, streamed like a chat turn."""
    await _check_available()
    chat = await load_module("chat")
    return _streamed(chat, z2, conversation_id=turn.conversation_id, page=turn.page, approvals=turn.approvals)


@router.websocket("/listen")
async def listen(socket: WebSocket):
    """What you say, as you say it, for the chat's box (see `voice.listen`)."""
    if not preferences.has_key("openai:"):
        await socket.close(code=1008, reason="The coach has no key for OpenAI")
        return
    voice = await load_module("voice")
    async with connect_db() as db:
        await voice.listen(socket, db)


def _streamed(chat, z2: Zone2, *, catch_up: bool = False, **turn) -> StreamingResponse:
    """The turn as server-sent events. With `catch_up`, data older than FRESH_FOR syncs first:
    the reply waits for Strava, a `sync` step, so it answers from your latest run; Garmin's
    slower sync runs alongside, and only the tools that read Garmin wait for it."""
    async def body():
        garmin = None
        if catch_up:
            strava, garmin = strava_sync.catch_up(z2, FRESH_FOR), garmin_sync.catch_up(z2, FRESH_FOR)
            if strava:
                yield chat.sse({"type": "tool", "tool": "sync", "args": {}})
                await asyncio.wait([strava], timeout=SYNC_WAIT_S)
                yield chat.sse({"type": "tool_done", "tool": "sync"})
        async for event in chat.stream(z2, sync=functools.partial(strava_sync.sync_now, z2), garmin_sync=garmin,
                                       **turn):
            yield event
    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
