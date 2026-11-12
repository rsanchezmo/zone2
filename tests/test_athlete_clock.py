"""The athlete's clock: today and the current week in the athlete's time zone (from their latest
activity), whatever zone the server runs in, and every day the app counts from it. Activities,
sessions and races are made up, in a throwaway calendar database."""
import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.db as calendar_db
from backend.agent import reviews
from backend.app import app
from backend.dependencies import get_z2
from backend.routers import coverage as coverage_router
from backend.services import coach_log, coverage, garmin_workouts, races, workout_library
from backend.services.workout_library import WorkoutChanges
from zone2.activities_cache import StravaActivitiesCache
from zone2.analytics import StravaAnalytics
from zone2.clock import Clock, zone_from_strava
from zone2.garmin_cache import GarminDailyStatsCache
from tests.synthetic import FakeActivitiesCache, FakeUserCache, activities_frame

PARIS = ZoneInfo("Europe/Paris")
# Monday 9 Nov 2026, 00:30 in Paris: still Sunday in UTC
MONDAY_JUST_AFTER_MIDNIGHT = datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)
# Sunday 7 Mar 2027, 00:30 in Paris: still Saturday on a server in UTC
SUNDAY_AFTER_MIDNIGHT = Clock(lambda: ZoneInfo("Europe/Paris"), lambda: datetime(2027, 3, 6, 23, 30, tzinfo=timezone.utc))
SATURDAY, SUNDAY = "2027-03-06", "2027-03-07"
STEPS = [{"type": "work", "distance_km": 1, "repetitions": 5, "recovery_duration_mins": 2}]


def test_strava_timezones_name_their_zone():
    assert zone_from_strava("(GMT+01:00) Europe/Paris") == PARIS
    assert zone_from_strava("(GMT-08:00) America/Los_Angeles") == ZoneInfo("America/Los_Angeles")
    assert zone_from_strava("(GMT+01:00) Nowhere/Atlantis") is None
    assert zone_from_strava(None) is None


def test_today_is_the_athletes_not_the_servers():
    clock = Clock(lambda: PARIS, lambda: MONDAY_JUST_AFTER_MIDNIGHT)
    assert clock.today() == date(2026, 11, 9)
    # Labelled UTC like start_date_local, so it compares with activity times directly
    assert clock.now() == datetime(2026, 11, 9, 0, 30, tzinfo=timezone.utc)


def test_the_athletes_zone_is_their_latest_activitys(tmp_path: Path):
    cache = StravaActivitiesCache(tmp_path / "activities", tmp_path / "streams", tmp_path / "metadata.json")
    assert cache.latest_zone() is None
    cache.save_activities([
        {"id": 1, "name": "Synthetic 1", "sport_type": "Run", "distance": 5000.0, "utc_offset": -28800.0,
         "start_date": "2026-10-01T15:00:00Z", "start_date_local": "2026-10-01T08:00:00Z",
         "timezone": "(GMT-08:00) America/Los_Angeles"},
        {"id": 2, "name": "Synthetic 2", "sport_type": "Run", "distance": 5000.0, "utc_offset": 3600.0,
         "start_date": "2026-11-05T07:00:00Z", "start_date_local": "2026-11-05T08:00:00Z",
         "timezone": "(GMT+01:00) Europe/Paris"},
        # A manual entry without a zone doesn't move the athlete
        {"id": 3, "name": "Synthetic 3", "sport_type": "Run", "distance": 5000.0,
         "start_date": "2026-11-06T07:00:00Z", "start_date_local": "2026-11-06T08:00:00Z"},
    ])
    assert cache.latest_zone() == PARIS


def test_the_current_weekly_report_turns_over_at_the_athletes_midnight():
    rows = [
        {"id": 1, "sport_type": "Run", "name": "Sunday long run", "start_date_local": "2026-11-08T10:00:00Z",
         "distance": 15000.0, "moving_time": 4500, "total_elevation_gain": 50.0},
    ]
    cache = FakeActivitiesCache(activities_frame(rows))
    clock = Clock(lambda: PARIS, lambda: MONDAY_JUST_AFTER_MIDNIGHT)
    analytics = StravaAnalytics(cache, FakeUserCache(), clock=clock)  # type: ignore[arg-type]
    report = analytics.get_weekly_report(None, hr_zones=[])
    assert (report["week_start"], report["week_end"]) == ("2026-11-09", "2026-11-15")
    assert report["total_activities"] == 0


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "calendar.db"
    for module in (calendar_db, reviews):
        monkeypatch.setattr(module, "DB_PATH", db_path)
    asyncio.run(calendar_db.init_db())
    return db_path


def run[T](work: Callable[[Any], Awaitable[T]]) -> T:
    async def go() -> T:
        async with calendar_db.connect_db() as db:
            return await work(db)
    return asyncio.run(go())


def athlete(**parts: Any) -> SimpleNamespace:
    return SimpleNamespace(**{"clock": SUNDAY_AFTER_MIDNIGHT,
                              "garmin_client": SimpleNamespace(configured=True), **parts})


async def plan_runs(db: Any, days: tuple[str, ...]) -> list[int]:
    """A saved run workout and a session planned from it on each day: ids of the sessions."""
    cur = await db.execute("INSERT INTO workout_templates (name, sport_type, segments) VALUES ('5×1 km', 'Run', ?)",
                           (json.dumps(STEPS),))
    ids = []
    for day in days:
        ids.append((await db.execute(
            "INSERT INTO training_sessions (date, title, sport_type, segments, workout_template_id) "
            "VALUES (?, '5×1 km', 'Run', ?, ?)", (day, json.dumps(STEPS), cur.lastrowid))).lastrowid)
    await db.commit()
    return ids


def test_a_race_is_upcoming_until_the_athletes_day_is_over(database: Path):
    async def work(db: Any) -> list[str]:
        await db.executemany("INSERT INTO race_events (name, date, sport_type) VALUES ('Synthetic', ?, 'Run')",
                             [(SATURDAY,), (SUNDAY,)])
        await db.commit()
        return [r["date"] for r in await races.upcoming(athlete(), db)]
    assert run(work) == [SUNDAY]


def test_the_watch_gets_the_sessions_from_the_athletes_today(database: Path):
    async def work(db: Any) -> tuple[list[bool], list[str | None]]:
        ids = await plan_runs(db, (SATURDAY, SUNDAY))
        sessions = [dict(await (await db.execute("SELECT * FROM training_sessions WHERE id = ?", (i,))).fetchone())
                    for i in ids]
        marked = [await garmin_workouts.mark_pending(athlete(), db, s) for s in sessions]
        await db.execute("UPDATE training_sessions SET garmin_sync_state = NULL")
        await garmin_workouts.mark_due_pending(athlete(), db)
        states = [r[0] for r in await (await db.execute(
            "SELECT garmin_sync_state FROM training_sessions ORDER BY date")).fetchall()]
        return marked, states
    assert run(work) == ([False, True], [None, "pending"])


def test_a_deleted_session_of_the_athletes_yesterday_keeps_its_garmin_entry(database: Path):
    removed: list[int] = []
    z2 = athlete(garmin_client=SimpleNamespace(configured=True, unschedule_workout=removed.append))

    async def work(db: Any) -> int:
        (session_id,) = await plan_runs(db, (SATURDAY,))
        await db.execute("INSERT INTO garmin_workout_schedules (schedule_id, workout_id, date, session_id) "
                         "VALUES (7, 70, ?, ?)", (SATURDAY, session_id))
        await db.commit()
        return session_id
    asyncio.run(garmin_workouts.forget_session(z2, run(work)))
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT schedule_id, session_id FROM garmin_workout_schedules").fetchall() == [(7, None)]
    assert removed == []


def test_new_steps_reach_the_sessions_from_the_athletes_today(database: Path):
    longer = [{**STEPS[0], "repetitions": 6}]

    async def work(db: Any) -> list[int]:
        await plan_runs(db, (SATURDAY, SUNDAY))
        await workout_library.update(athlete(garmin_client=SimpleNamespace(configured=False)), db, 1,
                                     WorkoutChanges(segments=longer), lambda *args: None)
        rows = await (await db.execute("SELECT segments FROM training_sessions ORDER BY date")).fetchall()
        return [json.loads(r[0])[0]["repetitions"] for r in rows]
    assert run(work) == [5, 6]


def test_the_coachs_log_dates_an_entry_on_the_athletes_day(database: Path):
    async def work(db: Any) -> str:
        return (await coach_log.add(athlete(), db, kind=coach_log.Kind.CHANGE, title="Moved a session"))["date"]
    assert run(work) == SUNDAY


def test_a_sync_reviews_the_athletes_last_two_days(database: Path):
    rows = [{"id": i, "sport_type": "Run", "start_date_local": f"{day}T08:00:00Z"}
            for i, day in ((1, "2027-03-04"), (2, "2027-03-05"))]
    reviews.queue_new(athlete(strava_activities_cache=FakeActivitiesCache(activities_frame(rows))), set())
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT activity_id FROM agent_reviews").fetchall() == [(2,)]


def test_the_calendar_feed_spans_from_the_athletes_today(database: Path):
    async def work(db: Any) -> None:
        await db.executemany("INSERT INTO training_sessions (date, title, sport_type) VALUES (?, 'Easy', 'Run')",
                             [("2027-01-05",), ("2027-01-06",)])
        await db.commit()
    run(work)
    app.dependency_overrides[get_z2] = lambda: athlete()
    try:
        api = TestClient(app)
        token = api.get("/api/calendar/feed-url").json()["token"]
        feed = api.get("/api/calendar.ics", params={"token": token}).text
    finally:
        app.dependency_overrides.clear()
    # 60 days back from the athlete's Sunday
    assert "DTSTART;VALUE=DATE:20270106" in feed and "DTSTART;VALUE=DATE:20270105" not in feed


def test_the_coverage_timeline_runs_to_the_athletes_month(monkeypatch: pytest.MonkeyPatch):
    # The cache's start_date is the local wall time; the second run is 1 April, 00:30 in Paris
    rows = pd.DataFrame({"id": [1, 2], "start_date": ["2027-03-10T08:00:00Z", "2027-04-01T00:30:00Z"]})
    # 00:45 in Paris, still 31 March on a server in UTC
    april = Clock(lambda: ZoneInfo("Europe/Paris"), lambda: datetime(2027, 3, 31, 22, 45, tzinfo=timezone.utc))
    z2 = SimpleNamespace(clock=april, strava_activities_cache=SimpleNamespace(activities_raw=rows))
    monkeypatch.setattr(coverage_router, "_new_streets",
                        lambda slug, z2: pd.DataFrame({"activity_id": [1, 2], "new_m": [1000.0, 500.0]}))
    monkeypatch.setattr(coverage, "state_version", lambda slug: ())
    monkeypatch.setattr(coverage, "cached_json", lambda key, version, build: build())
    months = coverage_router.coverage_timeline("gridtown", z2)["months"]
    assert [(m["month"], m["new_km"], m["runs"]) for m in months] == [("2027-03", 1.0, 1), ("2027-04", 0.5, 1)]


def test_garmin_days_are_the_athletes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = GarminDailyStatsCache(SimpleNamespace(enabled=True), tmp_path / "calendar.db")  # type: ignore[arg-type]
    synced: list[tuple[date, Any]] = []
    monkeypatch.setattr(cache, "clock", SUNDAY_AFTER_MIDNIGHT)
    monkeypatch.setattr(cache, "sync_day", lambda d, refresh_intraday: synced.append((d, refresh_intraday)) or 0)
    monkeypatch.setattr(cache, "sync_range_metrics", lambda start, end: synced.append((start, end)) or 0)
    cache.sync_recent(days=2)
    saturday, sunday = date.fromisoformat(SATURDAY), date.fromisoformat(SUNDAY)
    assert synced == [(saturday, True), (sunday, True), (saturday, sunday)]
