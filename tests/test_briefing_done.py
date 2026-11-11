"""Today's briefing calls the day done only when an activity fulfils the planned session, as the
calendar matches them: a walk on a swim day is not the swim. Against a throwaway calendar
database; every row is made up."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import backend.db as calendar_db
from backend.services import briefing
from zone2.activities_cache import StravaActivitiesCache
from zone2.clock import Clock
from tests.synthetic import activities_frame

DAY = "2027-03-01"


class Activities:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.view = activities_frame(rows)

    def get_prepared_view(self):
        return self.view

    days_mask = StravaActivitiesCache.days_mask


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calendar_db, "DB_PATH", tmp_path / "calendar.db")
    asyncio.run(calendar_db.init_db())

    async def zones(z2: Any, db: Any) -> dict[str, Any]:
        return {"zones": []}

    async def resting(z2: Any, db: Any) -> dict[str, Any]:
        return {"value": 50}
    monkeypatch.setattr(briefing, "resolve_hr_zones", zones)
    monkeypatch.setattr(briefing, "resolve_resting_hr", resting)


def suggestion(sports_done: list[str]) -> str:
    rows = [{"id": i, "sport_type": sport, "name": f"Synthetic {i}", "start_date_local": f"{DAY}T0{7 + i}:00:00Z",
             "distance": 2000.0, "moving_time": 1800} for i, sport in enumerate(sports_done)]
    evening = datetime(2027, 3, 1, 19, tzinfo=timezone.utc)
    z2 = SimpleNamespace(
        clock=Clock(lambda: timezone.utc, lambda: evening),
        strava_activities_cache=Activities(rows),
        garmin_cache=SimpleNamespace(get=lambda day, metric: None),
        strava_analytics=SimpleNamespace(get_fitness_form=lambda *args: {"series": []}),
    )

    async def go() -> str:
        async with calendar_db.connect_db() as db:
            await db.execute("INSERT INTO training_sessions (date, title, sport_type) VALUES (?, 'Swim', 'Swim')",
                             (DAY,))
            await db.commit()
            done = [{"sport_type": sport} for sport in sports_done]
            return (await briefing.today_briefing(z2, db, done))["suggestion"]["text"]
    return asyncio.run(go())


def test_a_walk_does_not_fulfil_a_planned_swim():
    assert not suggestion(["Walk"]).startswith("Done for today")


def test_the_planned_swim_does():
    assert suggestion(["Walk", "Swim"]).startswith("Done for today")
