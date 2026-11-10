"""The athlete's choices for the coach, set on the Profile page: which model answers, whether
spoken questions get their reply read aloud, and the credit topped up on the provider's
account. Imports nothing from Pydantic AI."""

import os
from datetime import date
from decimal import Decimal
from typing import Any

import aiosqlite

from backend.config import settings
from backend.services.zones import get_setting, set_setting

MODEL_KEY = "agent_model"
SPEAK_KEY = "agent_speak_replies"
# OpenAI has no API for an account's prepaid balance: the athlete enters a top-up, and z2
# counts down from it with the spend it records
CREDIT_KEY = "agent_credit_usd"
CREDIT_SINCE_KEY = "agent_credit_since"

# The models offered, cheapest first; STRAVA_WEB_AGENT_MODEL can still name any other
MODELS: tuple[tuple[str, str], ...] = (
    ("openai:gpt-6-luna", "GPT-6 Luna"),
    ("openai:gpt-5.6-luna", "GPT-5.6 Luna"),
    ("openai:gpt-6.1-terra", "GPT-6.1 Terra"),
    ("openai:gpt-6.1-sol", "GPT-6.1 Sol"),
)
# Providers that need no API key
KEYLESS = ("ollama:", "test")


async def model(db: aiosqlite.Connection) -> str:
    """The model the coach answers with: the athlete's choice, else the configured default."""
    return await get_setting(db, MODEL_KEY) or settings.agent_model


async def speak_replies(db: aiosqlite.Connection) -> bool:
    """Whether a spoken question gets its reply read aloud. On unless turned off."""
    return await get_setting(db, SPEAK_KEY) != "0"


async def credit(db: aiosqlite.Connection) -> tuple[float, str] | None:
    """The top-up the athlete entered, and the day it starts counting from."""
    amount, since = await get_setting(db, CREDIT_KEY), await get_setting(db, CREDIT_SINCE_KEY)
    return (float(amount), since) if amount and since else None


async def save(db: aiosqlite.Connection, *, model_id: str | None = None, speak: bool | None = None,
               credit_usd: float | None = None) -> None:
    if model_id is not None:
        if model_id not in {m for m, _ in MODELS}:
            raise ValueError(f"{model_id} isn't one of the offered models")
        await set_setting(db, MODEL_KEY, model_id)
    if speak is not None:
        await set_setting(db, SPEAK_KEY, "1" if speak else "0")
    if credit_usd is not None:
        if credit_usd < 0:
            raise ValueError("A credit can't be negative")
        await set_setting(db, CREDIT_KEY, str(credit_usd))
        await set_setting(db, CREDIT_SINCE_KEY, date.today().isoformat())


def has_key(model_id: str) -> bool:
    """Whether the model can answer: a key for its provider, or a provider that needs none."""
    if model_id.startswith(KEYLESS):
        return True
    provider = model_id.split(":", 1)[0].split("-", 1)[0].upper()
    return bool(os.environ.get(f"{provider}_API_KEY"))


def _base(price: Any) -> Decimal | None:
    """A per-million-token price, taking the base rate of a tiered one."""
    if price is None:
        return None
    return getattr(price, "base", price)


def options() -> list[dict[str, Any]]:
    """The offered models with their price per million tokens, from the price list Pydantic AI uses."""
    from genai_prices import data_snapshot

    openai = next((p for p in data_snapshot.get_snapshot().providers if p.id == "openai"), None)
    prices = {m.id: (m.prices[-1].prices if isinstance(m.prices, list) else m.prices) for m in (openai.models if openai else [])}
    out = []
    for model_id, name in MODELS:
        price = prices.get(model_id.split(":", 1)[1])
        out.append({
            "id": model_id,
            "name": name,
            "input_usd": float(v) if (v := _base(getattr(price, "input_mtok", None))) is not None else None,
            "output_usd": float(v) if (v := _base(getattr(price, "output_mtok", None))) is not None else None,
        })
    return out
