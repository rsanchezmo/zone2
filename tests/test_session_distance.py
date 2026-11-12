"""A session's planned distance taken from its steps follows them when they change; a distance goal
of its own stays. Against a throwaway calendar database; Garmin is off and every row is made up."""
import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

import backend.db as calendar_db
from backend.services import sessions, workout_library
from backend.services.sessions import NewSession, SessionChanges
from backend.services.workout_library import NewWorkout, WorkoutChanges
from zone2.clock import Clock

INTERVALS = [  # 2 + 6 × 1 + 1.5 = 9.5 km
    {"type": "warmup", "distance_km": 2},
    {"type": "work", "distance_km": 1, "repetitions": 6, "recovery_duration_mins": 1.5},
    {"type": "cooldown", "distance_km": 1.5},
]
LONGER = [  # 2 + 8 × 1 + 7 × 0.2 + 1.5 = 12.9 km
    {"type": "warmup", "distance_km": 2},
    {"type": "work", "distance_km": 1, "repetitions": 8, "recovery_distance_km": 0.2},
    {"type": "cooldown", "distance_km": 1.5},
]
DAY = date.today() + timedelta(days=7)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calendar_db, "DB_PATH", tmp_path / "calendar.db")
    asyncio.run(calendar_db.init_db())


Z2 = SimpleNamespace(garmin_client=SimpleNamespace(configured=False, enabled=False), clock=Clock())


def run[T](work: Callable[[Any], Awaitable[T]]) -> T:
    async def go() -> T:
        async with calendar_db.connect_db() as db:
            return await work(db)
    return asyncio.run(go())


def ignore(*args: Any) -> None:
    pass


async def planned(db: Any, distance_km: float) -> dict[str, Any]:
    """A run as the calendar saves it: the steps' total stands in when there is no distance goal."""
    return await sessions.create(Z2, db, NewSession(date=DAY, title="Intervals", sport_type="Run",
                                                    segments=INTERVALS, planned_distance_km=distance_km), ignore)


def test_new_steps_replace_a_distance_taken_from_the_old_ones():
    async def work(db: Any) -> dict[str, Any]:
        session = await planned(db, 9.5)
        return await sessions.update(Z2, db, session["id"], SessionChanges(segments=LONGER), ignore)
    assert run(work)["planned_distance_km"] == 12.9


def test_a_distance_goal_of_its_own_stays():
    async def work(db: Any) -> dict[str, Any]:
        session = await planned(db, 11.0)
        return await sessions.update(Z2, db, session["id"], SessionChanges(segments=LONGER), ignore)
    assert run(work)["planned_distance_km"] == 11.0


def test_a_saved_workouts_new_steps_carry_their_distance_to_upcoming_sessions():
    async def work(db: Any) -> dict[str, Any]:
        workout = await workout_library.create(Z2, db, NewWorkout(name="Intervals", sport_type="Run",
                                                                  segments=INTERVALS), ignore)
        session = await sessions.create(Z2, db, NewSession(date=DAY, title="Intervals", sport_type="Run",
                                                           workout_template_id=workout["id"],
                                                           planned_distance_km=9.5), ignore)
        await workout_library.update(Z2, db, workout["id"], WorkoutChanges(segments=LONGER), ignore)
        return await sessions.get(db, session["id"])
    assert run(work)["planned_distance_km"] == 12.9
