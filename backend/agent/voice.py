"""Voice around the text agent: what you say is transcribed into the same conversation, and
the reply is read aloud. One coach, whether typed or spoken."""

import re
from collections.abc import AsyncIterator
from decimal import Decimal

import aiosqlite
from openai import AsyncOpenAI
from pydantic_ai import RunUsage

from backend.agent import usage
from backend.config import settings

# Words a general transcriber gets wrong in a running conversation
VOCABULARY = ("Running coach conversation in z2. Terms: z2, Garmin, Strava, HRV, threshold, tempo, intervals, "
              "strides, reps, 5K, 10K, half marathon, marathon, pace per km.")
# Speech is priced per minute of audio; about 15 characters are spoken per second, so this
# per-character rate is an estimate of gpt-4o-mini-tts's price, for the Profile's totals.
SPEECH_USD_PER_CHAR = Decimal("0.000017")

_client: AsyncOpenAI | None = None


def _openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


_VOCABULARY_WORDS = set(re.findall(r"\w+", VOCABULARY.lower()))


def _echoes_prompt(text: str) -> bool:
    """A recording without speech can come back as the vocabulary prompt itself."""
    words = re.findall(r"\w+", text.lower())
    return len(words) >= 4 and sum(w in _VOCABULARY_WORDS for w in words) / len(words) > 0.8


async def transcribe(db: aiosqlite.Connection, audio: bytes, filename: str, content_type: str) -> str:
    """What was said, or "" when nothing was."""
    result = await _openai().audio.transcriptions.create(
        model=settings.agent_transcribe_model, file=(filename, audio, content_type), prompt=VOCABULARY,
    )
    spent = getattr(result, "usage", None)
    tokens = getattr(spent, "input_tokens", None) or 0
    # gpt-4o-mini-transcribe: $3 per million audio tokens
    cost = Decimal(tokens) * Decimal("0.000003") if tokens else None
    await usage.record(db, conversation_id="voice", surface="voice", model=settings.agent_transcribe_model,
                       usage=RunUsage(requests=1, input_tokens=tokens, cost=cost))
    text = result.text.strip()
    return "" if _echoes_prompt(text) else text


async def speak(db: aiosqlite.Connection, text: str) -> AsyncIterator[bytes]:
    await usage.record(db, conversation_id="voice", surface="voice", model=settings.agent_speech_model,
                       usage=RunUsage(requests=1, cost=SPEECH_USD_PER_CHAR * len(text)))
    async with _openai().audio.speech.with_streaming_response.create(
        model=settings.agent_speech_model, voice=settings.agent_voice, input=text, response_format="mp3",
        instructions="A calm, encouraging running coach. Speak naturally and briskly.",
    ) as response:
        async for chunk in response.iter_bytes(4096):
            yield chunk
