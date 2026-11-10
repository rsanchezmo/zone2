"""Talking to the coach: what you say appears in the chat's box as you say it, for you to
review and send. The words come from an OpenAI Realtime transcription session opened here,
so the key never reaches the browser."""

import asyncio
import base64
import contextlib
import math
import re
from datetime import date, timedelta
from decimal import Decimal

import aiosqlite
from fastapi import WebSocket
from openai import AsyncOpenAI
from openai.resources.realtime.realtime import AsyncRealtimeConnection
from pydantic_ai import RunUsage

from backend.agent import usage
from backend.config import settings

# Words a general transcriber gets wrong in a running conversation; the athlete's own race and
# plan names are added from z2's data (see `_keywords`)
KEYWORDS = ("z2", "Garmin", "Strava", "HRV", "threshold", "tempo", "intervals", "strides", "reps", "5K", "10K",
            "half marathon", "marathon", "pace per km")
# Races this recent or later are likely to come up
RACES_SINCE = timedelta(days=60)
MAX_KEYWORDS = 30
# The mic's audio: 24 kHz 16-bit mono PCM, the one format the Realtime API takes
SAMPLE_RATE = 24000
BYTES_PER_SECOND = SAMPLE_RATE * 2
# A mic left on is cut off here
MAX_LISTEN_S = 120
# OpenAI bills transcription per second of audio, at this rate per minute
TRANSCRIBE_USD_PER_MINUTE = {"gpt-live-transcribe": Decimal("0.017")}

_client: AsyncOpenAI | None = None


def _openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


async def _keywords(db: aiosqlite.Connection) -> list[str]:
    """The general hints plus the names of the athlete's recent and coming races and of their
    plans, which no transcriber knows."""
    since = (date.today() - RACES_SINCE).isoformat()
    races = await (await db.execute(
        "SELECT name FROM race_events WHERE date >= ? ORDER BY date LIMIT 10", (since,))).fetchall()
    plans = await (await db.execute(
        "SELECT name FROM training_plans WHERE status = 'active' ORDER BY start_date")).fetchall()
    names = [r[0] for r in (*races, *plans) if r[0]]
    return list(dict.fromkeys([*KEYWORDS, *names]))[:MAX_KEYWORDS]


def _echoes_keywords(text: str, keywords: list[str]) -> bool:
    """Audio without speech can come back as the keyword hints themselves."""
    hinted = set(re.findall(r"\w+", " ".join(keywords).lower()))
    words = re.findall(r"\w+", text.lower())
    return len(words) >= 4 and sum(w in hinted for w in words) / len(words) > 0.8


async def _captions(conn: AsyncRealtimeConnection, socket: WebSocket) -> str:
    """Passes the words on as they are heard; returns the transcript once the audio is committed."""
    text = ""
    async for event in conn:
        if event.type == "conversation.item.input_audio_transcription.delta":
            text += event.delta
            await socket.send_json({"type": "partial", "text": text.strip()})
        elif event.type == "conversation.item.input_audio_transcription.completed":
            return event.transcript
        elif event.type in ("error", "conversation.item.input_audio_transcription.failed"):
            raise RuntimeError(event.error.message or event.type)
    return text


async def listen(socket: WebSocket, db: aiosqlite.Connection) -> None:
    """What you say, while you say it. The browser sends the mic as binary PCM frames and "stop"
    when you let go; it gets {"type": "partial", "text"} as words are heard, then
    {"type": "final", "text"} ("" when nothing was said), or {"type": "error", "detail"}."""
    audio: asyncio.Queue[bytes | None] = asyncio.Queue()
    sent = 0  # bytes passed on to OpenAI, which bills per second of them
    keywords = await _keywords(db)

    async def transcribe() -> None:
        nonlocal sent
        async with _openai().realtime.connect(extra_query={"intent": "transcription"}) as conn:
            await conn.session.update(session={"type": "transcription", "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                "transcription": {"model": settings.agent_transcribe_model, "keywords": keywords, "delay": "low"},
                # gpt-live-transcribe has no turn detection: the turn ends when the button is let go
                "turn_detection": None,
            }}})
            words = asyncio.create_task(_captions(conn, socket))
            try:
                while (chunk := await audio.get()) is not None:
                    await conn.input_audio_buffer.append(audio=base64.b64encode(chunk).decode())
                    sent += len(chunk)
                text = ""
                # A commit needs at least 100 ms of audio
                if sent >= BYTES_PER_SECOND // 10:
                    await conn.input_audio_buffer.commit()
                    text = (await asyncio.wait_for(words, timeout=10)).strip()
                # Sent from inside: closing the session waits on OpenAI's close handshake, about 2 s
                await socket.send_json({"type": "final", "text": "" if _echoes_keywords(text, keywords) else text})
            finally:
                words.cancel()

    await socket.accept()
    task = asyncio.create_task(transcribe())
    stopped, received = False, 0
    try:
        while not task.done():
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if chunk := message.get("bytes"):
                audio.put_nowait(chunk)
                received += len(chunk)
            stopped = message.get("text") == "stop" or received >= MAX_LISTEN_S * BYTES_PER_SECOND
            if stopped:
                break
        audio.put_nowait(None)
        if not stopped and not task.done():  # the browser went away
            task.cancel()
            return
        await task
    except Exception as e:
        task.cancel()
        with contextlib.suppress(Exception):
            await socket.send_json({"type": "error", "detail": f"Couldn't hear that: {e}"})
    finally:
        with contextlib.suppress(Exception):
            await socket.close()
        if sent:
            rate = TRANSCRIBE_USD_PER_MINUTE.get(settings.agent_transcribe_model)
            seconds = math.ceil(sent / BYTES_PER_SECOND)
            await usage.record(db, conversation_id="voice", surface="voice", model=settings.agent_transcribe_model,
                               usage=RunUsage(requests=1, cost=rate * seconds / 60 if rate is not None else None))
