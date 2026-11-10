"""The coach's own reviews of new activities. A sync queues each new activity; a worker reviews
the ones that fulfil a planned session, one coach turn each, as a message in the chat the athlete
reads later, and any change it proposes waits for their yes. The robot shows how many are unread."""

import asyncio
import logging
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

import aiosqlite
import pandas as pd

from backend.agent import preferences
from backend.db import DB_PATH, connect_db
from backend.services import session_scores
from backend.services import sessions as planned_sessions
from backend.services.zones import get_setting, set_setting
from zone2.core import Zone2

logger = logging.getLogger(__name__)

# A sync reviews what it brings in from this far back, so a first or full sync doesn't
# review the whole history
REVIEW_WINDOW = timedelta(days=2)
# The worker also looks at the queue this often, should a wake-up be missed
FALLBACK_S = 600
SEEN_KEY = "agent_seen_at"


class ReviewStatus(StrEnum):
    QUEUED = "queued"
    DONE = "done"
    SKIPPED = "skipped"  # no planned session for it, or no key for the coach's model
    FAILED = "failed"


_loop: asyncio.AbstractEventLoop | None = None
_wake: asyncio.Event | None = None


def activity_ids(z2: Zone2) -> set[int]:
    activities = z2.strava_activities_cache.activities
    return set() if activities.empty else {int(i) for i in activities["id"]}


def queue(ids: Iterable[int], again: bool = False) -> None:
    """Queue activities for review, from any thread; each is reviewed once unless `again`."""
    rows = [(int(i),) for i in ids]
    if not rows:
        return
    upsert = ("ON CONFLICT(activity_id) DO UPDATE SET status = 'queued', queued_at = datetime('now'), done_at = NULL"
              if again else "ON CONFLICT(activity_id) DO NOTHING")
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        db.executemany(f"INSERT INTO agent_reviews (activity_id) VALUES (?) {upsert}", rows)
    if _loop is not None and _wake is not None:
        _loop.call_soon_threadsafe(_wake.set)


def queue_new(z2: Zone2, before: set[int]) -> None:
    """Queue what a sync brought in from the last REVIEW_WINDOW: the ids not in `before`."""
    view = z2.strava_activities_cache.get_prepared_view()
    if view.empty:
        return
    recent = view[view["start_date_local"].dt.date >= date.today() - REVIEW_WINDOW]
    queue(i for i in (int(x) for x in recent["id"]) if i not in before)


async def _planned_session(z2: Zone2, db: aiosqlite.Connection, activity_id: int) -> dict | None:
    """The planned session the activity fulfils, if any."""
    row = z2.strava_activities_cache.get_activity_by_id(activity_id)
    if row is None:
        return None
    day = pd.Timestamp(row["start_date_local"]).date().isoformat()
    sessions = await planned_sessions.between(db, day, day)
    if not sessions:
        return None
    matches = session_scores.session_matches(sessions, session_scores.activities_by_day(z2, day, day))
    return next((s for s, a in matches if a.get("id") == activity_id), None)


async def _set(db: aiosqlite.Connection, activity_id: int, status: ReviewStatus) -> None:
    await db.execute("UPDATE agent_reviews SET status = ?, done_at = datetime('now') WHERE activity_id = ?",
                     (status, activity_id))
    await db.commit()


async def _review(z2: Zone2, activity_id: int) -> None:
    async with connect_db() as db:
        session = await _planned_session(z2, db, activity_id)
        if session is None or not preferences.has_key(await preferences.model(db)):
            await _set(db, activity_id, ReviewStatus.SKIPPED)
            return
    status = ReviewStatus.DONE
    try:
        from backend.agent import chat  # Pydantic AI loads with the first review, not at startup
        await chat.review(z2, activity_id, session)
    except Exception:
        logger.exception("The coach's review of activity %s failed", activity_id)
        status = ReviewStatus.FAILED
    async with connect_db() as db:
        await _set(db, activity_id, status)


async def worker(z2: Zone2) -> None:
    """Review queued activities as they come, until cancelled."""
    global _loop, _wake
    _loop, _wake = asyncio.get_running_loop(), asyncio.Event()
    _wake.set()  # whatever a restart left queued
    while True:
        try:
            await asyncio.wait_for(_wake.wait(), timeout=FALLBACK_S)
        except TimeoutError:
            pass
        _wake.clear()
        async with connect_db() as db:
            rows = await (await db.execute(
                "SELECT activity_id FROM agent_reviews WHERE status = ? ORDER BY queued_at", (ReviewStatus.QUEUED,),
            )).fetchall()
        for (activity_id,) in rows:
            await _review(z2, activity_id)


async def unread(db: aiosqlite.Connection) -> int:
    """Reviews written since the athlete last opened the chat."""
    seen = await get_setting(db, SEEN_KEY) or ""
    row = await (await db.execute(
        "SELECT COUNT(*) FROM agent_reviews WHERE status = ? AND done_at > ?", (ReviewStatus.DONE, seen),
    )).fetchone()
    return row[0]


async def mark_seen(db: aiosqlite.Connection) -> None:
    await set_setting(db, SEEN_KEY, datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"))
