"""Sync orchestration with stubs: the one Strava slot and the one Garmin slot, what a sync refreshes
when it changes the activities, errors that free the slot, hooks, and catch-ups that share one run.
Strava, Garmin and the coach's review queue are stand-ins."""
import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

import backend.db as calendar_db
from backend.agent import reviews
from backend.services import garmin_sync, sync
from backend.services.zones import set_setting


class Activities:
    def __init__(self) -> None:
        self.cache_version = 0
        self.last_sync: datetime | None = None
        self.warmed = 0

    def get_last_sync_time(self) -> datetime | None:
        return self.last_sync

    def warm(self) -> None:
        self.warmed += 1


class Strava:
    """A Zone2 whose sync runs `behaviour` (bumping the data version unless told otherwise)."""

    def __init__(self, changes: bool = True, error: Exception | None = None, hold: threading.Event | None = None):
        self.strava_activities_cache = Activities()
        self.strava_analytics = SimpleNamespace(warm_caches=self._warm)
        self.strava_endpoint = SimpleNamespace()
        self.changes, self.error, self.hold = changes, error, hold
        self.syncs: list[tuple[bool, bool]] = []
        self.warmed_stats = 0

    def _warm(self) -> None:
        self.warmed_stats += 1

    def sync_activities(self, full_sync: bool, include_streams: bool) -> None:
        self.syncs.append((full_sync, include_streams))
        if self.hold is not None:
            assert self.hold.wait(5)
        if self.error is not None:
            raise self.error
        self.strava_activities_cache.last_sync = datetime.now()
        if self.changes:
            self.strava_activities_cache.cache_version += 1


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the sync refreshed, in order, with a fresh slot and no hooks but these."""
    seen: list[str] = []
    monkeypatch.setattr(sync, "_status", sync.SyncStatus())
    monkeypatch.setattr(sync, "_catching_up", None)
    monkeypatch.setattr(sync, "_changed_hooks", [lambda: seen.append("changed hook")])
    monkeypatch.setattr(sync, "_synced_hooks", [lambda z2: seen.append(f"synced hook, running={sync.status().running}")])
    monkeypatch.setattr(sync, "clear_stats_cache", lambda: seen.append("stats cleared"))
    monkeypatch.setattr(sync, "clear_gear_cache", lambda: seen.append("gear cleared"))
    monkeypatch.setattr(sync, "refresh_race_activities", lambda z2: seen.append("races refreshed") or False)
    monkeypatch.setattr(reviews, "activity_ids", lambda z2: {1, 2})
    monkeypatch.setattr(reviews, "queue_new", lambda z2, before: seen.append(f"queued new after {sorted(before)}"))
    return seen


# ── Strava ───────────────────────────────────────────────────────────────

def test_one_sync_at_a_time(events: list[str]):
    assert sync.try_claim()
    assert not sync.try_claim()
    assert sync.status().running
    sync.run(Strava(), False, True)
    assert sync.status() == sync.SyncStatus(running=False, last_error=None)
    assert sync.try_claim()


def test_a_sync_that_changes_the_activities_refreshes_what_depends_on_them(events: list[str]):
    z2 = Strava()
    assert sync.try_claim()
    sync.run(z2, True, False)
    assert z2.syncs == [(True, False)]
    assert events == ["stats cleared", "gear cleared", "changed hook", "races refreshed", "queued new after [1, 2]",
                      "synced hook, running=False"]
    assert (z2.strava_activities_cache.warmed, z2.warmed_stats) == (1, 1)


def test_a_new_race_activity_clears_the_stats_again(events: list[str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sync, "refresh_race_activities", lambda z2: events.append("races changed") or True)
    assert sync.try_claim()
    sync.run(Strava(), False, False)
    assert events[:5] == ["stats cleared", "gear cleared", "changed hook", "races changed", "stats cleared"]


def test_a_sync_that_changes_nothing_keeps_the_caches(events: list[str]):
    z2 = Strava(changes=False)
    assert sync.try_claim()
    sync.run(z2, False, True)
    assert events == ["synced hook, running=False"]
    assert (z2.strava_activities_cache.warmed, z2.warmed_stats) == (0, 0)


def test_a_failing_sync_frees_the_slot_and_records_the_error(events: list[str]):
    assert sync.try_claim()
    sync.run(Strava(error=RuntimeError("Strava is down")), False, True)
    assert sync.status() == sync.SyncStatus(running=False, last_error="Strava is down")
    assert events == []
    # The next claim starts clean
    assert sync.try_claim() and sync.status().last_error is None


def test_a_failing_cleanup_is_the_syncs_error(events: list[str], monkeypatch: pytest.MonkeyPatch):
    def broken() -> None:
        raise OSError("disk full")
    monkeypatch.setattr(sync, "_changed_hooks", [broken])
    z2 = Strava()
    assert sync.try_claim()
    sync.run(z2, False, True)
    assert sync.status() == sync.SyncStatus(running=False, last_error="cleanup failed: OSError: disk full")
    assert not any(e.startswith(("synced hook", "queued")) for e in events)
    assert z2.warmed_stats == 0


def test_a_failing_post_sync_hook_leaves_the_others_running(events: list[str], monkeypatch: pytest.MonkeyPatch):
    def broken(z2: Any) -> None:
        raise RuntimeError("coverage failed")
    monkeypatch.setattr(sync, "_synced_hooks", [broken, lambda z2: events.append("second hook")])
    assert sync.try_claim()
    sync.run(Strava(), False, True)
    assert events[-1] == "second hook" and sync.status().last_error is None


def test_backfill_and_resync_release_the_slot(events: list[str]):
    def rate_limited() -> None:
        raise RuntimeError("rate limited")
    z2 = Strava()
    z2.ensure_activities_with_streams = rate_limited
    assert sync.try_claim()
    sync.backfill_streams(z2)
    assert sync.status() == sync.SyncStatus(running=False, last_error="rate limited")

    z2.strava_activities_cache.resync_activity = lambda **kwargs: False
    assert sync.try_claim()
    assert sync.resync_activity(z2, 5, True) == (False, None)
    assert not sync.status().running


def test_concurrent_catch_ups_share_one_run(events: list[str]):
    hold = threading.Event()
    z2 = Strava(hold=hold)
    hook_ran = threading.Event()
    sync._synced_hooks.append(lambda z2: hook_ran.set())

    async def go() -> tuple[Any, Any, Any, str | None]:
        first = sync.catch_up(z2, timedelta(minutes=15))
        second = sync.catch_up(z2, timedelta(minutes=15))
        busy = sync.try_claim()
        hold.set()
        return first, second, busy, await first
    first, second, busy, error = asyncio.run(go())
    assert first is second and error is None and not busy
    assert z2.syncs == [(False, True)]
    assert hook_ran.wait(5)
    assert not sync.status().running
    # Fresh now: nothing to catch up
    assert asyncio.run(_catch_up(z2)) is None


async def _catch_up(z2: Strava, max_age: timedelta = timedelta(minutes=15)) -> Any:
    return sync.catch_up(z2, max_age)


def test_a_catch_up_waits_its_turn(events: list[str]):
    z2 = Strava()
    z2.strava_activities_cache.last_sync = datetime.now() - timedelta(hours=1)
    assert sync.try_claim()
    assert asyncio.run(_catch_up(z2)) is None
    assert z2.syncs == []
    z2.strava_activities_cache.last_sync = datetime.now() - timedelta(minutes=5)
    sync._release(None)
    assert asyncio.run(_catch_up(z2)) is None


def test_sync_now(events: list[str]):
    z2 = Strava()
    z2.strava_activities_cache.resync_activity = lambda **kwargs: False
    assert asyncio.run(sync.sync_now(z2, activity_id=5)) == "Strava has no activity 5."
    assert sync.try_claim()
    assert asyncio.run(sync.sync_now(z2, activity_id=5)) == sync._BUSY
    assert asyncio.run(sync.sync_now(z2)) == sync._BUSY
    sync._release(None)
    assert asyncio.run(sync.sync_now(Strava(error=RuntimeError("Strava is down")))) == "Strava is down"


# ── Garmin ───────────────────────────────────────────────────────────────

class Wellness:
    def __init__(self, error: Exception | None = None, last: datetime | None = None,
                 hold: threading.Event | None = None):
        self.error, self.last, self.hold = error, last, hold
        self.synced: list[int] = []

    def sync_recent(self, days: int) -> int:
        self.synced.append(days)
        if self.hold is not None:
            assert self.hold.wait(5)
        if self.error is not None:
            raise self.error
        return 3 * days

    def sync_full(self) -> dict[str, Any]:
        return {"days": 100}

    def last_sync_at(self) -> datetime | None:
        return self.last


def garmin(wellness: Wellness, enabled: bool = True) -> SimpleNamespace:
    invalidated: list[bool] = []
    return SimpleNamespace(garmin_cache=wellness, garmin_client=SimpleNamespace(enabled=enabled, email="a@example.com"),
                           strava_analytics=SimpleNamespace(invalidate_caches=lambda: invalidated.append(True)),
                           invalidated=invalidated)


@pytest.fixture
def garmin_events(tmp_path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(calendar_db, "DB_PATH", tmp_path / "calendar.db")
    asyncio.run(calendar_db.init_db())
    monkeypatch.setattr(garmin_sync, "_status", garmin_sync.GarminSyncStatus())
    monkeypatch.setattr(garmin_sync, "_catching_up", None)
    monkeypatch.setattr(garmin_sync, "_zones_changed_hooks", [lambda: seen.append("zones hook")])
    monkeypatch.setattr(garmin_sync, "clear_stats_cache", lambda: seen.append("stats cleared"))

    async def reconcile(z2: Any) -> None:
        seen.append("workouts reconciled")
    monkeypatch.setattr(garmin_sync, "reconcile_workouts", reconcile)
    return seen


def zones_moved(monkeypatch: pytest.MonkeyPatch, moved: bool) -> None:
    async def refresh(z2: Any) -> bool:
        return moved
    monkeypatch.setattr(garmin_sync, "refresh_garmin_zones", refresh)


def test_a_garmin_sync_then_reconciles_workouts_and_rebuilds_on_new_zones(garmin_events: list[str],
                                                                          monkeypatch: pytest.MonkeyPatch):
    zones_moved(monkeypatch, True)

    async def use_garmin_zones() -> None:
        async with calendar_db.connect_db() as db:
            await set_setting(db, "hr_zones_source", "garmin")
    asyncio.run(use_garmin_zones())
    z2 = garmin(Wellness())
    assert garmin_sync.try_claim() and not garmin_sync.try_claim()
    asyncio.run(garmin_sync.run(z2, False, days=7))
    assert garmin_sync.status() == garmin_sync.GarminSyncStatus(running=False, last_error=None,
                                                                last_summary={"rows_written": 21})
    assert garmin_events == ["workouts reconciled", "stats cleared", "zones hook"]
    assert z2.invalidated == [True]


def test_new_garmin_zones_not_in_use_rebuild_nothing(garmin_events: list[str], monkeypatch: pytest.MonkeyPatch):
    zones_moved(monkeypatch, True)
    z2 = garmin(Wellness())
    assert garmin_sync.try_claim()
    asyncio.run(garmin_sync.run(z2, True))
    assert garmin_sync.status().last_summary == {"days": 100}
    assert garmin_events == ["workouts reconciled"] and z2.invalidated == []


def test_a_failing_garmin_sync_frees_the_slot_and_keeps_the_last_summary(garmin_events: list[str],
                                                                         monkeypatch: pytest.MonkeyPatch):
    zones_moved(monkeypatch, False)
    assert garmin_sync.try_claim()
    asyncio.run(garmin_sync.run(garmin(Wellness()), False, days=1))
    assert garmin_sync.try_claim()
    asyncio.run(garmin_sync.run(garmin(Wellness(error=ConnectionError("Garmin is down"))), False))
    assert garmin_sync.status() == garmin_sync.GarminSyncStatus(
        running=False, last_error="ConnectionError: Garmin is down", last_summary={"rows_written": 3})


def test_garmin_catch_ups(garmin_events: list[str]):
    async def catch_up(z2: SimpleNamespace) -> Any:
        return await garmin_sync.catch_up(z2, timedelta(minutes=15))
    assert asyncio.run(catch_up(garmin(Wellness(), enabled=False))) is None
    fresh = Wellness(last=datetime.now(UTC) - timedelta(minutes=5))
    assert asyncio.run(catch_up(garmin(fresh))) is None and fresh.synced == []

    hold = threading.Event()
    stale = Wellness(last=datetime.now(UTC) - timedelta(hours=2), hold=hold)
    z2 = garmin(stale)

    async def two() -> tuple[Any, Any]:
        first, second = await catch_up(z2), await catch_up(z2)
        hold.set()
        await first
        return first, second
    first, second = asyncio.run(two())
    assert first is second and stale.synced == [2]
    assert garmin_sync.status().last_summary == {"rows_written": 6}

    assert garmin_sync.try_claim()
    assert asyncio.run(catch_up(garmin(Wellness()))) is None
