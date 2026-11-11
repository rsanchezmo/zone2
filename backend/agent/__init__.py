import asyncio
import importlib
import os
from types import ModuleType

# Pydantic AI prints an observability banner on the first run otherwise
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


async def load_module(name: str) -> ModuleType:
    """backend.agent.<name>, imported off the event loop: the first import of the agent loads
    Pydantic AI (~60 MB), which takes seconds on the Pi and stays out of the app's startup."""
    return await asyncio.to_thread(importlib.import_module, f"{__name__}.{name}")
