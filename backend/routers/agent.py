import asyncio
import functools
from datetime import timedelta

import aiosqlite
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agent import preferences
from backend.agent import usage as agent_usage
from backend.db import connect_db, get_db
from backend.dependencies import get_z2
from backend.routers import garmin as garmin_sync, sync as strava_sync
from zone2.core import Zone2

router = APIRouter()

# The agent itself (Pydantic AI, ~60 MB) is imported on the first chat, not at startup.

# Data older than this is brought up to date when a message arrives
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
    """Whether the agent can answer (a key for its model's provider), its model, and whether
    spoken questions get their reply read aloud."""
    model = await preferences.model(db)
    return {"available": preferences.has_key(model), "model": model,
            "speak_replies": await preferences.speak_replies(db)}


@router.get("/settings")
async def get_settings(db: aiosqlite.Connection = Depends(get_db)):
    """The coach's settings on the Profile page: its model (with the models offered and their
    prices per million tokens) and reading replies aloud."""
    return {"model": await preferences.model(db), "speak_replies": await preferences.speak_replies(db),
            "models": preferences.options()}


class SettingsUpdate(BaseModel):
    model: str | None = None
    speak_replies: bool | None = None
    credit_usd: float | None = None  # a top-up on the OpenAI account; counting starts today


@router.put("/settings")
async def put_settings(update: SettingsUpdate, db: aiosqlite.Connection = Depends(get_db)):
    try:
        await preferences.save(db, model_id=update.model, speak=update.speak_replies, credit_usd=update.credit_usd)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return await get_settings(db)


@router.get("/conversations/{conversation_id}")
async def conversation(conversation_id: str, db: aiosqlite.Connection = Depends(get_db)):
    """A conversation as the chat panel shows it, with any writes still waiting for a yes."""
    from backend.agent import chat
    return await chat.history(db, conversation_id)


class ChatTurn(BaseModel):
    message: str
    conversation_id: str | None = None
    page: str | None = None
    voice: bool = False  # spoken: the reply is short, for reading aloud


class ApprovalTurn(BaseModel):
    conversation_id: str
    approvals: dict[str, bool]
    page: str | None = None
    voice: bool = False


async def _check_available(model: str | None = None) -> None:
    """503 unless the model can answer; voice always needs an OpenAI key."""
    if model is None:
        async with connect_db() as db:
            model = await preferences.model(db)
    if not preferences.has_key(model):
        raise HTTPException(status_code=503, detail=f"The coach has no key for {model}")


@router.post("/chat")
async def chat_turn(turn: ChatTurn, tasks: BackgroundTasks, z2: Zone2 = Depends(get_z2)):
    """One message to the agent, streamed as server-sent events (see `chat.stream`). Writes
    it wants to make come back as `pending` in the final `done` event, for approval."""
    await _check_available()
    from backend.agent import chat
    from backend.agent.conversations import MAIN
    conversation_id = turn.conversation_id or MAIN
    return _streamed(chat, z2, tasks, catch_up=True, conversation_id=conversation_id, page=turn.page,
                     message=turn.message, voice=turn.voice)


@router.post("/approve")
async def approve_turn(turn: ApprovalTurn, tasks: BackgroundTasks, z2: Zone2 = Depends(get_z2)):
    """Your yes or no to each pending write; the agent then carries on, streamed like a chat turn."""
    await _check_available()
    from backend.agent import chat
    return _streamed(chat, z2, tasks, conversation_id=turn.conversation_id, page=turn.page, approvals=turn.approvals,
                     voice=turn.voice)


# A spoken message can't usefully run longer than this; it also caps the upload
MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.post("/transcribe")
async def transcribe(audio: UploadFile, db: aiosqlite.Connection = Depends(get_db)):
    """What you said, as text, for the chat."""
    await _check_available("openai:")
    from backend.agent import voice
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That recording is too long")
    try:
        return {"text": await voice.transcribe(db, data, audio.filename or "speech.webm", audio.content_type or "audio/webm")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't transcribe that: {e}") from e


class Speech(BaseModel):
    text: str


@router.post("/speak")
async def speak(speech: Speech):
    """A reply read aloud, as streamed MP3."""
    await _check_available("openai:")
    from backend.agent import voice

    async def body():
        async with connect_db() as db:
            async for chunk in voice.speak(db, speech.text[:4000]):
                yield chunk
    return StreamingResponse(body(), media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


def _streamed(chat, z2: Zone2, tasks: BackgroundTasks, *, catch_up: bool = False, **turn) -> StreamingResponse:
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
        # Its own connection: the stream outlives the request's dependencies
        async with connect_db() as db:
            async for event in chat.stream(z2, db, tasks.add_task, sync=functools.partial(strava_sync.sync_now, z2),
                                           garmin_sync=garmin, **turn):
                yield event
    # The Garmin pushes a write queues run once the stream ends
    return StreamingResponse(body(), media_type="text/event-stream", background=tasks,
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
