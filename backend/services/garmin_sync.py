"""Garmin wellness sync, one at a time: the API, the auto-sync loop and the chat's catch-up share
one slot, independent of Strava's. A sync then brings the watch's planned workouts in line with
the calendar and refreshes Garmin's HR zones. Refreshes whose state lives elsewhere (the PNG
exports) are hooks the app registers at startup."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from backend.db import connect_db
from backend.services.garmin_workouts import reconcile as reconcile_workouts
from backend.services.stats_cache import clear_stats_cache
from backend.services.zones import get_setting, refresh_garmin_zones
from zone2.core import Zone2

logger = logging.getLogger(__name__)


@dataclass
class GarminSyncStatus:
    running: bool = False
    last_error: str | None = None
    last_summary: dict[str, Any] | None = None


# Syncs run in worker threads while the API reads the status on the event loop: a
# threading.Lock serves both.
_status = GarminSyncStatus()
_lock = Lock()

_zones_changed_hooks: list[Callable[[], None]] = []

# The catch-up running now, which a later caller waits for instead of starting another
_catching_up: asyncio.Future[None] | None = None


def on_zones_changed(hook: Callable[[], None]) -> None:
    """Run `hook` when a sync finds Garmin's HR zones moved while they are the zones in use."""
    _zones_changed_hooks.append(hook)


def status() -> GarminSyncStatus:
    """A snapshot of the sync slot."""
    with _lock:
        return replace(_status)


def try_claim() -> bool:
    """Atomic check-and-set: whether the caller now owns the sync slot."""
    with _lock:
        if _status.running:
            return False
        _status.running = True
        _status.last_error = None
        return True


def _release(error: str | None, summary: dict[str, Any] | None) -> None:
    with _lock:
        _status.running = False
        _status.last_error = error
        if summary is not None:
            _status.last_summary = summary


def _sync_wellness(z2: Zone2, full: bool, days: int) -> None:
    """Fetch the wellness payloads and free the sync slot."""
    err: str | None = None
    summary: dict[str, Any] | None = None
    try:
        if full:
            summary = z2.garmin_cache.sync_full()
        else:
            summary = {"rows_written": z2.garmin_cache.sync_recent(days=days)}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.exception("Garmin sync failed")
    finally:
        _release(err, summary)


async def _sync_zones(z2: Zone2) -> None:
    """Refresh Garmin's zones, rebuilding what uses them when they moved and are the zones in use."""
    if not await refresh_garmin_zones(z2):
        return
    async with connect_db() as db:
        if await get_setting(db, "hr_zones_source") != "garmin":
            return
    logger.info("Garmin HR zones changed: rebuilding zone-based stats")
    z2.strava_analytics.invalidate_caches()
    clear_stats_cache()
    for hook in _zones_changed_hooks:
        hook()


async def run(z2: Zone2, full: bool, days: int = 14) -> None:
    """In the slot the caller claimed, sync the last `days` of wellness (or walk the history
    back with `full`), then the watch's planned workouts and Garmin's HR zones."""
    await asyncio.to_thread(_sync_wellness, z2, full, days)
    await reconcile_workouts(z2)
    await _sync_zones(z2)


def _running_catch_up() -> asyncio.Future[None] | None:
    if _catching_up is None or _catching_up.done():
        return None
    return _catching_up


async def catch_up(z2: Zone2, max_age: timedelta) -> asyncio.Future[None] | None:
    """Today's and yesterday's wellness when Garmin's last sync is older than `max_age`, the
    client is logged in and no other Garmin sync is running, or the catch-up already running."""
    global _catching_up
    if (running := _running_catch_up()) is not None:
        return running
    if not z2.garmin_client.enabled:
        return None
    last = await asyncio.to_thread(z2.garmin_cache.last_sync_at)
    if last is not None and datetime.now(UTC) - last < max_age:
        return None
    # Another caller may have started one while this one read the cache
    if (running := _running_catch_up()) is not None:
        return running
    if not try_claim():
        return None
    loop = asyncio.get_running_loop()
    started = loop.time()
    synced = loop.run_in_executor(None, _sync_wellness, z2, False, 2)
    synced.add_done_callback(lambda _: logger.info("Garmin catch-up took %.1fs", loop.time() - started))
    _catching_up = synced
    return synced
