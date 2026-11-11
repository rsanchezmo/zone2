"""Races, goals, planned sessions and saved workouts: one write path per entity, shared by the
API and the agent's tools, against a throwaway calendar database. Garmin and the race
analytics are stubbed; every row is made up."""
import asyncio
from collections.abc import Awaitable, Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_ai import ModelRetry

import backend.db as calendar_db
from backend.agent import tools
from backend.app import app
from backend.dependencies import get_z2
from backend.errors import Conflict, Invalid, NotFound, UpstreamFailed, UpstreamUnavailable
from backend.services import garmin_courses, garmin_workouts, goals, races, sessions, sync, workout_library
from backend.services.coverage import sync_all_cities
from backend.services.export_cache import clear_export_cache
from backend.services.goals import GoalChanges, NewGoal
from backend.services.races import NewRace, RaceChanges
from backend.services.sessions import NewSession, SessionChanges
from backend.services.workout_library import NewWorkout, WorkoutChanges
from zone2.garmin_client import GarminUnavailable

INTERVALS = [
    {"type": "warmup", "distance_km": 2, "duration_mins": None, "repetitions": 1},
    {"type": "work", "distance_km": 1, "repetitions": 5, "target_pace_min": 3.9, "target_pace_max": 4.0,
     "recovery_duration_mins": 2, "recovery_distance_km": None},
    {"type": "cooldown", "distance_km": 2, "repetitions": 1},
]
RACE = {"name": "Harbour 10K", "date": "2027-03-07", "sport_type": "Run", "distance_km": 10, "target_pace": 4.0,
        "description": None, "location": "Harbour", "url": None}
GOAL = {"year": 2027, "sport_type": "Run", "metric": "distance_km", "period": "weekly", "target_value": 30}
SESSION = {"date": "2027-03-01", "title": "5×1 km", "sport_type": "Run", "planned_distance_km": 9.0,
           "target_hr_zone": 4, "target_zone_pct": 80, "segments": INTERVALS, "workout_template_id": None}
WORKOUT = {"name": "5×1 km", "sport_type": "Run", "segments": INTERVALS}
IGNORED = ("id", "created_at", "workout_template_id")


class Garmin:
    """Stands in for the Garmin pushes a write queues, recording which ones."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def schedule(self, fn: Callable[..., Any], *args: Any) -> None:
        self.calls.append(fn.__name__)


@pytest.fixture
def z2() -> SimpleNamespace:
    return SimpleNamespace(garmin_client=SimpleNamespace(email=None, enabled=False))


@pytest.fixture
def race_refreshes(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    def refresh(z2: object) -> bool:
        calls.append(z2)
        return False
    monkeypatch.setattr(races, "refresh_race_activities", refresh)
    return calls


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The Garmin pushes the API's background tasks ran, by name."""
    ran: list[str] = []
    for name in ("sync_library", "sync_session", "forget_session", "delete_copy"):
        async def push(*args: Any, name: str = name) -> None:
            ran.append(name)
        push.__name__ = name
        monkeypatch.setattr(garmin_workouts, name, push)
    return ran


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch: pytest.MonkeyPatch, race_refreshes: list[object], pushes: list[str]) -> None:
    monkeypatch.setattr(calendar_db, "DB_PATH", tmp_path / "calendar.db")
    asyncio.run(calendar_db.init_db())


@pytest.fixture
def api(z2: SimpleNamespace) -> Iterator[TestClient]:
    app.dependency_overrides[get_z2] = lambda: z2
    yield TestClient(app)
    app.dependency_overrides.clear()


def run[T](work: Callable[[Any], Awaitable[T]]) -> T:
    async def go() -> T:
        async with calendar_db.connect_db() as db:
            return await work(db)
    return asyncio.run(go())


def agent_ctx(z2: SimpleNamespace, db: Any, garmin: Garmin) -> SimpleNamespace:
    return SimpleNamespace(deps=tools.AgentDeps(z2=z2, db=db, schedule=garmin.schedule))


def same_row(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return {k: v for k, v in a.items() if k not in IGNORED} == {k: v for k, v in b.items() if k not in IGNORED}


# ── Races ────────────────────────────────────────────────────────────────

def test_race_round_trip(z2: SimpleNamespace, race_refreshes: list[object]) -> None:
    async def work(db: Any) -> None:
        created = await races.create(z2, db, NewRace.model_validate(RACE))
        assert created["date"] == "2027-03-07" and created["target_pace"] == 4.0
        moved = await races.update(z2, db, created["id"], RaceChanges(date="2027-03-14"))
        assert moved["date"] == "2027-03-14" and moved["name"] == "Harbour 10K"
        assert await races.upcoming(db) == [moved]
        assert await races.races_between(db, "2027-03-01", "2027-03-10") == []
        assert (await races.delete(z2, db, created["id"]))["id"] == created["id"]
        with pytest.raises(NotFound, match="Race event not found"):
            await races.get(db, created["id"])
    run(work)
    assert len(race_refreshes) == 3


def test_race_validation(z2: SimpleNamespace) -> None:
    with pytest.raises(ValidationError):
        NewRace.model_validate({**RACE, "date": "2027-13-07"})
    with pytest.raises(ValidationError):
        NewRace.model_validate({**RACE, "target_pace": 0})
    assert NewRace(name="Club 5K", date="2027-05-01").sport_type == "Run"

    async def work(db: Any) -> None:
        # A swim's pace is per 100 m and a ride's is km/h: only a run's is held to min/km
        await races.create(z2, db, NewRace.model_validate({**RACE, "sport_type": "Swim", "target_pace": 2.0}))
        ride = await races.create(z2, db, NewRace.model_validate({**RACE, "sport_type": "Ride", "target_pace": 28}))
        with pytest.raises(Invalid, match="minutes per km"):
            await races.create(z2, db, NewRace.model_validate({**RACE, "target_pace": 30}))
        run_race = await races.create(z2, db, NewRace.model_validate(RACE))
        with pytest.raises(Invalid):
            await races.update(z2, db, run_race["id"], RaceChanges(target_pace=1.5))
        assert (await races.update(z2, db, ride["id"], RaceChanges(target_pace=32)))["target_pace"] == 32
        with pytest.raises(Invalid, match="No fields to update"):
            await races.update(z2, db, run_race["id"], RaceChanges())
        with pytest.raises(NotFound, match="Race event not found"):
            await races.update(z2, db, 999, RaceChanges(name="x"))
        with pytest.raises(NotFound):
            await races.delete(z2, db, 999)
    run(work)


# ── Goals ────────────────────────────────────────────────────────────────

def test_goal_round_trip() -> None:
    async def work(db: Any) -> None:
        created = await goals.create(db, NewGoal.model_validate(GOAL))
        changed = await goals.update(db, created["id"], GoalChanges(period="monthly", target_value=120))
        assert (changed["period"], changed["target_value"], changed["metric"]) == ("monthly", 120.0, "distance_km")
        assert await goals.goals_of(db, 2027) == [changed]
        assert await goals.goals_of(db, 2026) == []
        await goals.delete(db, created["id"])
        assert await goals.goals_of(db) == []
        with pytest.raises(NotFound, match="Goal not found"):
            await goals.delete(db, created["id"])
        with pytest.raises(NotFound, match="Goal not found"):
            await goals.update(db, created["id"], GoalChanges(target_value=5))
        with pytest.raises(Invalid, match="No fields to update"):
            await goals.update(db, created["id"], GoalChanges())
    run(work)


@pytest.mark.parametrize("change", [{"metric": "km"}, {"period": "daily"}, {"target_value": 0}, {"target_value": -3}])
def test_goal_validation(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NewGoal.model_validate({**GOAL, **change})
    with pytest.raises(ValidationError):
        GoalChanges.model_validate(change)


# ── Planned sessions ─────────────────────────────────────────────────────

def test_session_round_trip(z2: SimpleNamespace) -> None:
    garmin = Garmin()

    async def work(db: Any) -> None:
        created = await sessions.create(z2, db, NewSession.model_validate(SESSION), garmin.schedule)
        # Steps keep the fields they set; a session built from steps is saved to the library
        assert created["segments"][0] == {"type": "warmup", "distance_km": 2.0, "repetitions": 1}
        assert created["segments"][1]["recovery_duration_mins"] == 2.0
        saved = await workout_library.get(db, created["workout_template_id"])
        assert saved["segments"] == created["segments"]
        moved = await sessions.update(z2, db, created["id"], SessionChanges(date="2027-03-02"), garmin.schedule)
        assert moved["date"] == "2027-03-02" and moved["workout_template_id"] == saved["id"]
        done = await sessions.update(z2, db, created["id"], SessionChanges(completed=True), garmin.schedule)
        assert done["completed"] is True
        cleared = await sessions.update(z2, db, created["id"], SessionChanges(segments=None), garmin.schedule)
        assert cleared["segments"] is None and cleared["workout_template_id"] is None
        assert (await sessions.delete(z2, db, created["id"], garmin.schedule))["title"] == "5×1 km"
        with pytest.raises(NotFound, match="Session not found"):
            await sessions.get(db, created["id"])
        with pytest.raises(NotFound, match="Session not found"):
            await sessions.delete(z2, db, created["id"], garmin.schedule)
        with pytest.raises(NotFound, match="Session not found"):
            await sessions.update(z2, db, created["id"], SessionChanges(title="x"), garmin.schedule)
        with pytest.raises(Invalid, match="No fields to update"):
            await sessions.update(z2, db, created["id"], SessionChanges(), garmin.schedule)
        empty = await sessions.create(z2, db, NewSession.model_validate({**SESSION, "segments": []}), garmin.schedule)
        assert empty["segments"] is None
    run(work)
    assert garmin.calls == ["sync_library", "forget_session"]


@pytest.mark.parametrize("change", [
    {"date": "tomorrow"}, {"planned_intensity": "brutal"}, {"target_hr_zone": 6}, {"target_zone_pct": 0},
    {"target_zone_pct": 101}, {"target_avg_pace": 0}, {"segments": [{"type": "sprint"}]},
    {"segments": [{"type": "work", "target_hr_zone": 0}]},
])
def test_session_validation(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NewSession.model_validate({**SESSION, **change})
    with pytest.raises(ValidationError):
        SessionChanges.model_validate(change)


def test_session_paces_by_sport(z2: SimpleNamespace) -> None:
    garmin = Garmin()

    async def work(db: Any) -> None:
        ride = await sessions.create(z2, db, NewSession(date="2027-03-02", title="Ride", sport_type="Ride",
                                                        target_avg_pace=28, target_pace_min=25), garmin.schedule)
        await sessions.create(z2, db, NewSession(date="2027-03-03", title="Swim", sport_type="Swim",
                                                 target_avg_pace=1.9), garmin.schedule)
        with pytest.raises(Invalid, match="minutes per km"):
            await sessions.create(z2, db, NewSession(date="2027-03-04", title="Run", sport_type="Run",
                                                     target_avg_pace=30), garmin.schedule)
        steps = [{"type": "work", "distance_km": 1, "target_pace_min": 1.0}]
        with pytest.raises(Invalid):
            await sessions.create(z2, db, NewSession.model_validate({**SESSION, "segments": steps}), garmin.schedule)
        # A change without the sport is checked against the session's own
        with pytest.raises(Invalid):
            await sessions.update(z2, db, ride["id"], SessionChanges(sport_type="Run", target_avg_pace=28),
                                  garmin.schedule)
        kept = await sessions.update(z2, db, ride["id"], SessionChanges(target_avg_pace=30), garmin.schedule)
        assert kept["target_avg_pace"] == 30
    run(work)


# ── Saved workouts ───────────────────────────────────────────────────────

def test_workout_round_trip(z2: SimpleNamespace) -> None:
    garmin = Garmin()

    async def work(db: Any) -> None:
        created = await workout_library.create(z2, db, NewWorkout.model_validate(WORKOUT), garmin.schedule)
        planned = await sessions.create(z2, db, NewSession.model_validate(SESSION), garmin.schedule)
        assert planned["workout_template_id"] == created["id"]
        renamed = await workout_library.update(z2, db, created["id"], WorkoutChanges(name="Fives"), garmin.schedule)
        assert renamed["name"] == "Fives" and renamed["segments"] == created["segments"]
        assert [t["name"] for t in await workout_library.library(z2, db)] == ["Fives"]
        assert (await workout_library.library(z2, db))[0]["uses"] == 1
        deleted = await workout_library.delete(z2, db, created["id"], garmin.schedule)
        assert deleted["name"] == "Fives"
        assert (await sessions.get(db, planned["id"]))["workout_template_id"] is None
        with pytest.raises(NotFound, match="Template not found"):
            await workout_library.get(db, created["id"])
        with pytest.raises(NotFound, match="Template not found"):
            await workout_library.delete(z2, db, created["id"], garmin.schedule)
        with pytest.raises(NotFound, match="Template not found"):
            await workout_library.update(z2, db, created["id"], WorkoutChanges(name="x"), garmin.schedule)
    run(work)
    assert garmin.calls == ["sync_library", "sync_library"]


def test_workout_conflicts_and_validation(z2: SimpleNamespace) -> None:
    garmin = Garmin()
    with pytest.raises(ValidationError):
        NewWorkout.model_validate({**WORKOUT, "segments": [{"type": "sprint"}]})
    with pytest.raises(ValidationError):
        NewWorkout.model_validate({"name": "No steps", "sport_type": "Run"})

    async def work(db: Any) -> None:
        first = await workout_library.create(z2, db, NewWorkout.model_validate(WORKOUT), garmin.schedule)
        with pytest.raises(Conflict, match="Same steps as “5×1 km”"):
            await workout_library.create(z2, db, NewWorkout.model_validate({**WORKOUT, "name": "Again"}),
                                         garmin.schedule)
        other = await workout_library.create(z2, db, NewWorkout(name="Long", sport_type="Run",
                                                                segments=[{"type": "work", "distance_km": 16}]),
                                             garmin.schedule)
        with pytest.raises(Conflict):
            await workout_library.update(z2, db, other["id"], WorkoutChanges.model_validate({"segments": INTERVALS}),
                                         garmin.schedule)
        # The same steps for another sport are another workout
        swim = await workout_library.create(z2, db, NewWorkout.model_validate({**WORKOUT, "sport_type": "Swim"}),
                                            garmin.schedule)
        assert swim["id"] != first["id"]
        with pytest.raises(Invalid, match="minutes per km"):
            await workout_library.create(z2, db, NewWorkout(name="Fast", sport_type="Run", segments=[
                {"type": "work", "distance_km": 1, "target_pace_max": 20}]), garmin.schedule)
    run(work)


# ── The API and the agent write the same rows ────────────────────────────

def test_api_and_agent_write_the_same_race(api: TestClient, z2: SimpleNamespace,
                                           race_refreshes: list[object]) -> None:
    by_api = api.post("/api/races/", json=RACE)
    assert by_api.status_code == 201

    async def work(db: Any) -> dict[str, Any]:
        await tools.add_race(agent_ctx(z2, db, Garmin()), NewRace.model_validate(RACE), "asked")
        return (await races.races_between(db))[-1]
    assert same_row(by_api.json(), run(work))
    assert len(race_refreshes) == 2


def test_api_and_agent_write_the_same_goal(api: TestClient, z2: SimpleNamespace) -> None:
    by_api = api.post("/api/goals/", json=GOAL)
    assert by_api.status_code == 201

    async def work(db: Any) -> dict[str, Any]:
        return await tools.set_goal(agent_ctx(z2, db, Garmin()), NewGoal.model_validate(GOAL), "asked")
    assert same_row(by_api.json(), run(work))


def test_api_and_agent_write_the_same_session(api: TestClient, z2: SimpleNamespace, pushes: list[str]) -> None:
    by_api = api.post("/api/calendar/sessions", json=SESSION)
    assert by_api.status_code == 201
    garmin = Garmin()

    async def work(db: Any) -> dict[str, Any]:
        created = await tools.add_session(agent_ctx(z2, db, garmin), NewSession.model_validate(SESSION), "asked")
        return await sessions.get(db, created["id"])
    by_agent = run(work)
    assert same_row(by_api.json(), by_agent)
    # Both link to the one saved workout with these steps, saved (and pushed) once
    assert by_agent["workout_template_id"] == by_api.json()["workout_template_id"]
    assert pushes == ["sync_library"] and garmin.calls == []


def test_api_and_agent_write_the_same_workout(api: TestClient, z2: SimpleNamespace, pushes: list[str]) -> None:
    by_api = api.post("/api/workouts", json=WORKOUT)
    assert by_api.status_code == 201
    assert api.delete(f"/api/workouts/{by_api.json()['id']}").status_code == 204
    garmin = Garmin()

    async def work(db: Any) -> dict[str, Any]:
        created = await tools.save_workout(agent_ctx(z2, db, garmin), NewWorkout.model_validate(WORKOUT), "asked")
        return await workout_library.get(db, created["id"])
    assert same_row(by_api.json(), run(work))
    assert pushes == ["sync_library"] and garmin.calls == ["sync_library"]


def test_api_and_agent_change_and_remove_alike(api: TestClient, z2: SimpleNamespace) -> None:
    first = api.post("/api/calendar/sessions", json={**SESSION, "segments": None}).json()
    second = api.post("/api/calendar/sessions", json={**SESSION, "segments": None}).json()
    change = {"date": "2027-03-09", "target_avg_pace": 4.5, "planned_intensity": "easy"}
    by_api = api.put(f"/api/calendar/sessions/{first['id']}", json=change)
    assert by_api.status_code == 200

    async def work(db: Any) -> dict[str, Any]:
        ctx = agent_ctx(z2, db, Garmin())
        await tools.change_session(ctx, second["id"], SessionChanges.model_validate(change), "asked")
        changed = await sessions.get(db, second["id"])
        assert await tools.remove_session(ctx, second["id"], "asked") == f"Session {second['id']} removed."
        return changed
    assert same_row(by_api.json(), run(work))
    assert api.delete(f"/api/calendar/sessions/{first['id']}").status_code == 204


# ── Errors as each side sees them ────────────────────────────────────────

def test_api_statuses_and_messages(api: TestClient) -> None:
    assert api.put("/api/races/999", json={"name": "x"}).json() == {"detail": "Race event not found"}
    assert api.put("/api/races/999", json={"name": "x"}).status_code == 404
    assert api.delete("/api/goals/999").json() == {"detail": "Goal not found"}
    assert api.put("/api/calendar/sessions/999", json={"title": "x"}).status_code == 404
    assert api.delete("/api/workouts/999").json() == {"detail": "Template not found"}
    goal = api.post("/api/goals/", json=GOAL).json()
    empty = api.put(f"/api/goals/{goal['id']}", json={})
    assert (empty.status_code, empty.json()) == (400, {"detail": "No fields to update"})
    assert api.post("/api/workouts", json=WORKOUT).status_code == 201
    duplicate = api.post("/api/workouts", json={**WORKOUT, "name": "Again"})
    assert (duplicate.status_code, duplicate.json()) == (409, {"detail": "Same steps as “5×1 km”"})
    pace = api.post("/api/races/", json={**RACE, "target_pace": 30})
    assert pace.status_code == 400 and "minutes per km" in pace.json()["detail"]
    assert api.post("/api/goals/", json={**GOAL, "metric": "km"}).status_code == 422
    unknown = api.get("/api/coverage/no-such-city/districts")
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "No coverage map for 'no-such-city'"})


def test_garmin_failures_reach_the_api_as_before(api: TestClient, z2: SimpleNamespace) -> None:
    def offline() -> list[dict[str, Any]]:
        raise GarminUnavailable("Garmin isn't signed in")

    def broken() -> list[dict[str, Any]]:
        raise RuntimeError("boom")
    garmin_courses.clear_courses_cache()
    z2.garmin_client = SimpleNamespace(course_devices=offline)
    with pytest.raises(UpstreamUnavailable):
        garmin_courses.course_devices(z2)
    assert api.get("/api/garmin/devices").status_code == 503
    z2.garmin_client = SimpleNamespace(course_devices=broken)
    with pytest.raises(UpstreamFailed, match="Garmin Connect failed: boom"):
        garmin_courses.course_devices(z2)
    response = api.get("/api/garmin/devices")
    assert (response.status_code, response.json()) == (502, {"detail": "Garmin Connect failed: boom"})


def test_agent_tools_retry_on_service_errors(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        ctx = agent_ctx(z2, db, Garmin())
        with pytest.raises(ModelRetry, match="There is no goal 999"):
            await tools.change_goal(ctx, 999, GoalChanges(target_value=5), "asked")
        with pytest.raises(ModelRetry, match="There is no race 999"):
            await tools.change_race(ctx, 999, RaceChanges(name="x"), "asked")
        with pytest.raises(ModelRetry, match="There is no session 999"):
            await tools.remove_session(ctx, 999, "asked")
        with pytest.raises(ModelRetry, match="There is no saved workout 999"):
            await tools.remove_workout(ctx, 999, "asked")
        await tools.save_workout(ctx, NewWorkout.model_validate(WORKOUT), "asked")
        with pytest.raises(ModelRetry, match="Same steps as"):
            await tools.save_workout(ctx, NewWorkout.model_validate({**WORKOUT, "name": "Again"}), "asked")
        with pytest.raises(ModelRetry, match="minutes per km"):
            await tools.add_race(ctx, NewRace.model_validate({**RACE, "target_pace": 30}), "asked")
    run(work)


def test_sync_hooks_register_once() -> None:
    sync.register_hooks()
    sync.register_hooks()
    assert sync._changed_hooks.count(clear_export_cache) == 1
    assert sync._synced_hooks.count(sync_all_cities) == 1
