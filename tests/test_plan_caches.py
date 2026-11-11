"""The caches behind the coach's plans and every HR-zone reader: session scores, the race
predictions' history and the resolved zones and resting HR, each keyed by what it is computed
from. Activities, streams and settings are made up; Strava and Garmin are never reached."""
import asyncio
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

import backend.db as calendar_db
from backend import _ttl_cache
from backend._ttl_cache import TTLCache
from backend.scoring import compute_execution_score
from backend.services import stats_cache
from backend.services.resting_hr import resolve_resting_hr
from backend.services.session_scores import score_sessions
from backend.services.zones import resolve_hr_zones, set_setting
from zone2.utils import SportCategory
from tests.synthetic import ZONES, activities_frame, steady_stream

OTHER_ZONES = [{"min": 0, "max": 110}, {"min": 110, "max": 130}, {"min": 130, "max": 150},
               {"min": 150, "max": 170}, {"min": 170, "max": 190}]


@pytest.fixture(autouse=True)
def empty_stats_cache() -> None:
    stats_cache.clear_stats_cache()


# ── Session scores ───────────────────────────────────────────────────────

class Activities:
    """The parts of StravaActivitiesCache scoring reads, counting the streams it loads."""

    def __init__(self, rows: list[dict], streams: dict[int, dict]):
        self.view = activities_frame(rows)
        self.stored = streams
        self.cache_version = 0
        self.loaded: list[list[int]] = []
        self.streams = SimpleNamespace(has=lambda activity_id: activity_id in self.stored)

    def get_prepared_view(self) -> pd.DataFrame:
        return self.view

    def days_mask(self, date_from: str, date_to: str) -> pd.Series:
        sdl = self.view["start_date_local"]
        return (sdl >= pd.Timestamp(date_from, tz="UTC")) & (sdl < pd.Timestamp(date_to, tz="UTC") + pd.Timedelta(days=1))

    def get_streams_bulk(self, ids: list[int]) -> dict[int, dict]:
        self.loaded.append(sorted(ids))
        return {i: self.stored[i] for i in ids if i in self.stored}


def run(activity_id: int, day: str, km: float, hr: float = 150) -> dict[str, Any]:
    return {"id": activity_id, "sport_type": "Run", "start_date_local": f"{day}T08:00:00Z", "distance": km * 1000,
            "moving_time": km * 300, "elapsed_time": km * 300, "average_speed": 1000 / 300, "average_heartrate": hr}


def session(session_id: int, day: str, km: float, zone_pct: float = 80) -> dict[str, Any]:
    return {"id": session_id, "date": day, "title": "Easy", "sport_type": "Run", "planned_distance_km": km,
            "target_hr_zone": 3, "target_zone_pct": zone_pct, "segments": None, "completed": False}


def fresh(z2: SimpleNamespace, sessions: list[dict], zones: list[dict]) -> dict[int, dict | None]:
    """The scores computed from scratch, for comparison."""
    activities: Activities = z2.strava_activities_cache
    loaded = list(activities.loaded)
    stats_cache.clear_stats_cache()
    scores = score_sessions(z2, sessions, "2027-03-01", "2027-03-07", zones)
    activities.loaded = loaded
    return scores


def test_session_scores_load_streams_only_when_what_they_are_computed_from_changes() -> None:
    activities = Activities(
        [run(101, "2027-03-01", 10), run(102, "2027-03-03", 8), run(103, "2027-03-05", 6)],
        {101: steady_stream(3000, 1000 / 300, lambda t: 150), 102: steady_stream(2400, 1000 / 300, lambda t: 130)},
    )
    z2 = SimpleNamespace(strava_activities_cache=activities)
    sessions = [session(1, "2027-03-01", 10), session(2, "2027-03-03", 8), session(3, "2027-03-05", 6),
                session(4, "2027-03-06", 5)]

    def score(these: list[dict] = sessions, zones: list[dict] = ZONES) -> dict[int, dict | None]:
        return score_sessions(z2, these, "2027-03-01", "2027-03-07", zones)

    first = score()
    assert activities.loaded == [[101, 102, 103]] and first[4] is None
    assert first[1] == compute_execution_score(sessions[0], {**run(101, "2027-03-01", 10), "distance_km": 10.0},
                                               ZONES, activities.stored[101])
    assert score() == first and activities.loaded == [[101, 102, 103]]

    retargeted = [session(1, "2027-03-01", 10, zone_pct=50), *sessions[1:]]
    assert score(retargeted) == fresh(z2, retargeted, ZONES)
    assert activities.loaded[-1] == [101]

    assert score(zones=OTHER_ZONES) == fresh(z2, sessions, OTHER_ZONES)
    assert activities.loaded[-1] == [101, 102, 103]

    activities.cache_version += 1
    score()
    assert activities.loaded[-1] == [101, 102, 103]

    # A stream backfill adds 103's streams without a new activities version
    activities.stored[103] = steady_stream(1800, 1000 / 300, lambda t: 170)
    assert score() == fresh(z2, sessions, ZONES)
    assert activities.loaded[-1] == [103]

    # Session 2 is now fulfilled by another activity
    activities.view = activities_frame([run(101, "2027-03-01", 10), run(104, "2027-03-03", 8.1),
                                        run(103, "2027-03-05", 6)])
    scores = score()
    assert scores[2]["matched_activity_id"] == 104 and activities.loaded[-1] == [104]


def test_race_predictions_history_is_computed_once_a_day_per_version(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    def history(sport: SportCategory, weeks: int, step_days: int) -> list[dict]:
        calls.append((sport, weeks, step_days))
        return [{"end_date": "2027-03-01", "predictions": []}]

    z2 = SimpleNamespace(strava_activities_cache=SimpleNamespace(cache_version=0),
                         strava_analytics=SimpleNamespace(get_race_predictions_history=history))
    get = stats_cache.get_race_predictions_history_cached
    assert get(z2, SportCategory.RUNNING, 6, 7) == get(z2, SportCategory.RUNNING, 6, 7)
    assert len(calls) == 1
    get(z2, SportCategory.RUNNING, 7, 7)
    z2.strava_activities_cache.cache_version = 1
    get(z2, SportCategory.RUNNING, 6, 7)
    assert len(calls) == 3


def test_stats_cache_entries_never_expire_but_stay_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr(_ttl_cache, "time", SimpleNamespace(monotonic=lambda: now[0]))
    cache = TTLCache(maxsize=2, ttl_seconds=None)
    cache.set("a", 1)
    cache.set("b", 2)
    now[0] = 10 ** 9
    assert (cache.get("a"), cache.get("b")) == (1, 2)
    cache.set("c", 3)
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == (None, 2, 3)


# ── HR zones and resting HR ──────────────────────────────────────────────

class Analytics:
    """Counts what resolving reads, and on which thread."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.on_loop: list[bool] = []
        self.measured_rhr: float | None = 52.0

    def _read(self, what: str) -> None:
        self.calls.append(what)
        self.on_loop.append(threading.current_thread() is threading.main_thread())

    def get_max_heart_rate(self) -> int:
        self._read("max_hr")
        return 190

    def get_hr_zones(self) -> list[dict]:
        self._read("zones")
        return ZONES

    def _garmin_resting_hr(self) -> float | None:
        self._read("garmin_rhr")
        return self.measured_rhr


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "calendar.db"
    monkeypatch.setattr(calendar_db, "DB_PATH", path)
    asyncio.run(calendar_db.init_db())
    return path


@pytest.fixture
def zones_z2() -> SimpleNamespace:
    strava_zones: list[dict | None] = [None]
    return SimpleNamespace(
        strava_analytics=Analytics(),
        strava_user_cache=SimpleNamespace(cached_athlete_zones=lambda: strava_zones[0], strava_zones=strava_zones),
        strava_activities_cache=SimpleNamespace(cache_version=0),
        garmin_client=SimpleNamespace(email=None),
    )


def resolve(what: Any, z2: SimpleNamespace) -> Any:
    async def go() -> Any:
        async with calendar_db.connect_db() as db:
            return await what(z2, db)
    return asyncio.run(go())


def setting(key: str, value: str) -> None:
    async def go() -> None:
        async with calendar_db.connect_db() as db:
            await set_setting(db, key, value)
    asyncio.run(go())


def test_zones_resolve_once_until_what_they_read_changes(db_path: Path, zones_z2: SimpleNamespace) -> None:
    analytics: Analytics = zones_z2.strava_analytics
    estimated = resolve(resolve_hr_zones, zones_z2)
    assert estimated["source"] == "estimated" and estimated["zones"] == ZONES
    assert resolve(resolve_hr_zones, zones_z2) == estimated
    assert analytics.calls == ["max_hr", "zones"] and not any(analytics.on_loop)

    setting("manual_hr_zones", '[{"min": 0, "max": 110}, {"min": 110, "max": 130}, {"min": 130, "max": 150}, '
                               '{"min": 150, "max": 170}, {"min": 170, "max": 190}]')
    setting("hr_zones_source", "manual")
    manual = resolve(resolve_hr_zones, zones_z2)
    assert manual["source"] == "manual" and manual["zones"] == OTHER_ZONES
    computed = len(analytics.calls)
    assert resolve(resolve_hr_zones, zones_z2) == manual and len(analytics.calls) == computed

    zones_z2.strava_activities_cache.cache_version = 1
    resolve(resolve_hr_zones, zones_z2)
    assert len(analytics.calls) > computed
    computed = len(analytics.calls)

    zones_z2.strava_user_cache.strava_zones[0] = {"heart_rate": {"custom_zones": False, "zones": ZONES}}
    resolve(resolve_hr_zones, zones_z2)
    assert len(analytics.calls) > computed


def test_resting_hr_follows_garmin_data_and_its_settings(db_path: Path, zones_z2: SimpleNamespace) -> None:
    analytics: Analytics = zones_z2.strava_analytics
    with sqlite3.connect(db_path) as c:
        c.execute("INSERT INTO garmin_daily_stats (date, metric, payload, fetched_at) VALUES "
                  "('2027-03-01', 'heart_rates', x'00', '2027-03-01 06:00:00')")
    measured = resolve(resolve_resting_hr, zones_z2)
    assert (measured["value"], measured["source"]) == (52.0, "garmin")
    assert resolve(resolve_resting_hr, zones_z2) == measured
    assert analytics.calls == ["garmin_rhr"] and analytics.on_loop == [False]

    # A Garmin sync brings a new night
    analytics.measured_rhr = 49.0
    with sqlite3.connect(db_path) as c:
        c.execute("INSERT INTO garmin_daily_stats (date, metric, payload, fetched_at) VALUES "
                  "('2027-03-02', 'heart_rates', x'00', '2027-03-02 06:00:00')")
    assert resolve(resolve_resting_hr, zones_z2)["value"] == 49.0

    setting("manual_resting_hr", "47.0")
    setting("resting_hr_source", "manual")
    assert resolve(resolve_resting_hr, zones_z2)["value"] == 47.0
    setting("manual_resting_hr", "46.0")
    assert resolve(resolve_resting_hr, zones_z2)["value"] == 46.0
    assert analytics.calls == ["garmin_rhr", "garmin_rhr"]
