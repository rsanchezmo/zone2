"""Strava sync, one at a time: the API, the auto-sync loop and the agent share one slot. A sync
that changes the cached activities refreshes what depends on them and queues the new ones for the
coach to review. Refreshes whose state lives elsewhere (the PNG exports, the coverage map) are
hooks: `register_hooks` wires them in every process that syncs, the app and the agent's terminal."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import Lock

from backend.agent import reviews
from backend.services import garmin_sync
from backend.services.coverage import sync_all_cities
from backend.services.export_cache import clear_export_cache
from backend.services.gear import clear_gear_cache
from backend.services.races import refresh_race_activities
from backend.services.stats_cache import clear_stats_cache
from zone2.core import Zone2

logger = logging.getLogger(__name__)

_BUSY = "A sync is already running; try again in a minute."


@dataclass
class SyncStatus:
    running: bool = False
    last_error: str | None = None


# Syncs run in worker threads while the API reads the status on the event loop: a
# threading.Lock serves both.
_status = SyncStatus()
_lock = Lock()

_changed_hooks: list[Callable[[], None]] = []
_synced_hooks: list[Callable[[Zone2], None]] = []

# The catch-up running now, which a later caller waits for instead of starting another
_catching_up: asyncio.Future[str | None] | None = None


def on_changed(hook: Callable[[], None]) -> None:
    """Run `hook` with the cache refreshes of each sync that changes the cached activities; if
    it raises, the sync's cleanup fails."""
    _changed_hooks.append(hook)


def on_synced(hook: Callable[[Zone2], None]) -> None:
    """Run `hook` after each activities sync that succeeds, once the slot is free."""
    _synced_hooks.append(hook)


def register_hooks() -> None:
    """Have syncs refresh the PNG exports and the coverage map too; once per process."""
    if clear_export_cache in _changed_hooks:
        return
    on_changed(clear_export_cache)
    on_synced(sync_all_cities)
    garmin_sync.on_zones_changed(clear_export_cache)


def status() -> SyncStatus:
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


def _release(error: str | None) -> None:
    with _lock:
        _status.running = False
        _status.last_error = error


def _finalize(z2: Zone2, error: str | None, version_before: int) -> str | None:
    """Invalidate/warm dependent caches when the sync changed the data (its version moved past
    `version_before`), and always release the sync slot."""
    try:
        if z2.strava_activities_cache.cache_version == version_before:
            logger.info("Sync changed nothing: caches kept")
            return error
        clear_stats_cache()
        clear_gear_cache()
        for hook in _changed_hooks:
            hook()
        # Warmed eagerly so the first read after the sync doesn't pay the parquet reload
        z2.strava_activities_cache.warm()
        # A new activity may be the one of a race event; stats a request built since the clear
        # above counted the old races
        if refresh_race_activities(z2):
            clear_stats_cache()
    except Exception as e:
        logger.exception("Sync cleanup failed")
        cleanup_error = f"cleanup failed: {type(e).__name__}: {e}"
        error = f"{error}; {cleanup_error}" if error else cleanup_error
    else:
        try:
            z2.strava_analytics.warm_caches()
        except Exception:
            logger.exception("Warming the stats caches after the sync failed")
    finally:
        _release(error)
    return error


def _sync_activities(z2: Zone2, full_sync: bool, include_streams: bool) -> str | None:
    """Fetch and store new activities, refresh what depends on them, free the sync slot and
    queue the new ones for the coach to review. Returns the error, if any."""
    err: str | None = None
    version = z2.strava_activities_cache.cache_version
    before: set[int] = set()
    try:
        before = reviews.activity_ids(z2)
        z2.sync_activities(full_sync=full_sync, include_streams=include_streams)
    except Exception as e:
        logger.exception("Strava sync failed")
        err = str(e)
    err = _finalize(z2, err, version)
    if err is None and z2.strava_activities_cache.cache_version != version:
        try:
            reviews.queue_new(z2, before)
        except Exception:
            logger.exception("Queueing the new activities for review failed")
    return err


def _after_sync(z2: Zone2) -> None:
    for hook in _synced_hooks:
        try:
            hook(z2)
        except Exception:
            logger.exception("Post-sync hook %r failed", hook)


def run(z2: Zone2, full_sync: bool, include_streams: bool) -> None:
    """Sync activities, then run the post-sync hooks, in the slot the caller claimed."""
    if _sync_activities(z2, full_sync, include_streams) is None:
        _after_sync(z2)


def backfill_streams(z2: Zone2) -> None:
    """Fetch the streams of the activities without them, in the slot the caller claimed."""
    err: str | None = None
    version = z2.strava_activities_cache.cache_version
    try:
        z2.ensure_activities_with_streams()
    except Exception as e:
        logger.exception("Stream backfill failed")
        err = str(e)
    finally:
        _finalize(z2, err, version)


def resync_activity(z2: Zone2, activity_id: int, include_streams: bool) -> tuple[bool, str | None]:
    """Fetch one activity again, in the slot the caller claimed: whether Strava returned it, and
    the error, if any."""
    err: str | None = None
    found = False
    version = z2.strava_activities_cache.cache_version
    try:
        found = z2.strava_activities_cache.resync_activity(
            activity_id=activity_id,
            strava_endpoint=z2.strava_endpoint,
            include_streams=include_streams,
        )
    except Exception as e:
        logger.exception("Resyncing activity %s failed", activity_id)
        err = str(e)
    return found, _finalize(z2, err, version)


def catch_up(z2: Zone2, max_age: timedelta) -> asyncio.Future[str | None] | None:
    """An incremental sync, with the new activities' streams, when the last one is older than
    `max_age` and no other sync is running, or the catch-up already running. The future
    resolves once the new activities are stored and the caches refreshed; the post-sync hooks
    carry on after it."""
    global _catching_up
    if _catching_up is not None and not _catching_up.done():
        return _catching_up
    last = z2.strava_activities_cache.get_last_sync_time()
    if last is not None and datetime.now() - last < max_age:
        return None
    if not try_claim():
        return None
    loop = asyncio.get_running_loop()
    started = loop.time()
    # Executor futures keep running when the caller stops waiting, unlike a dropped task
    synced = loop.run_in_executor(None, _sync_activities, z2, False, True)

    def then_hooks(done: asyncio.Future[str | None]) -> None:
        logger.info("Strava catch-up took %.1fs", loop.time() - started)
        if not done.cancelled() and done.result() is None:
            loop.run_in_executor(None, _after_sync, z2)

    synced.add_done_callback(then_hooks)
    _catching_up = synced
    return synced


async def sync_now(z2: Zone2, activity_id: int | None = None) -> str | None:
    """Sync Strava now, or fetch one activity again with its streams, and wait for it.
    Returns what went wrong, if anything."""
    if activity_id is not None:
        if not try_claim():
            return _BUSY
        found, err = await asyncio.to_thread(resync_activity, z2, activity_id, True)
        return err or (None if found else f"Strava has no activity {activity_id}.")
    strava = catch_up(z2, timedelta(0))
    if strava is None:
        return _BUSY
    return await strava
