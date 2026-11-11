"""The coach's tools over the entity services: sessions planned from a saved workout, target paces
in each sport's own unit, sport filters, and the writes waiting for a yes, against a throwaway
calendar database. Garmin is stubbed; every row is made up."""
import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_ai import ModelRetry, ModelResponse, ToolCallPart

import backend.db as calendar_db
from backend.agent import chat, conversations, message_store, tools
from backend.services import races, sessions, training, workout_library
from backend.services.races import NewRace, RaceChanges
from backend.services.sessions import NewSession, SessionChanges
from backend.services.workout_library import NewWorkout, WorkoutChanges
from tests.synthetic import activities_frame
from tests.test_agent_conversations import exchange, prompt
from zone2.utils import SportCategory

RUN_STEPS = [
    {"type": "warmup", "distance_km": 2},
    {"type": "work", "distance_km": 1, "repetitions": 6, "recovery_duration_mins": 1.5,
     "target_pace_min": 4.0, "target_pace_max": 4.5},
    {"type": "cooldown", "distance_km": 1.5},
]
RIDE_STEPS = [{"type": "work", "duration_mins": 20, "repetitions": 3, "recovery_duration_mins": 5,
               "target_pace_min": 28, "target_pace_max": 32}]
SWIM_STEPS = [{"type": "work", "distance_km": 0.1, "repetitions": 10, "recovery_duration_mins": 0.5,
               "target_pace_min": 1.75, "target_pace_max": 2.0}]
DAY = date(2027, 3, 1)


class Garmin:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def schedule(self, fn: Callable[..., Any], *args: Any) -> None:
        self.calls.append(fn.__name__)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calendar_db, "DB_PATH", tmp_path / "calendar.db")
    monkeypatch.setattr(races, "refresh_race_activities", lambda z2: False)
    asyncio.run(calendar_db.init_db())


@pytest.fixture
def z2() -> SimpleNamespace:
    return SimpleNamespace(garmin_client=SimpleNamespace(email=None, enabled=False))


def run[T](work: Callable[[Any], Awaitable[T]]) -> T:
    async def go() -> T:
        async with calendar_db.connect_db() as db:
            return await work(db)
    return asyncio.run(go())


def ctx(z2: SimpleNamespace, db: Any) -> SimpleNamespace:
    return SimpleNamespace(deps=tools.AgentDeps(z2=z2, db=db, schedule=Garmin().schedule))


async def save(z2: SimpleNamespace, db: Any, name: str, sport_type: str, steps: list[dict[str, Any]]) -> dict:
    return await workout_library.create(z2, db, NewWorkout(name=name, sport_type=sport_type, segments=steps),
                                        Garmin().schedule)


# ── A session planned from a saved workout ──────────────────────────────

def test_adding_a_session_from_a_saved_workout_takes_its_steps_and_keeps_the_link(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        workout = await save(z2, db, "6×1 km", "Run", RUN_STEPS)
        shown = await tools.add_session(ctx(z2, db), NewSession(date=DAY, title="6×1 km", sport_type="Run",
                                                                workout_template_id=workout["id"]), "asked")
        stored = await sessions.get(db, shown["id"])
        assert stored["workout_template_id"] == workout["id"]
        assert stored["segments"] == workout["segments"]
        assert [t["uses"] for t in await workout_library.library(z2, db)] == [1]
    run(work)


def test_changing_a_session_to_a_saved_workout_takes_its_steps_and_leaves_the_rest(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        workout = await save(z2, db, "6×1 km", "Run", RUN_STEPS)
        easy = await sessions.create(z2, db, NewSession(date=DAY, title="Thursday", sport_type="Run",
                                                        planned_distance_km=11, planned_intensity="hard",
                                                        description="On the track"), Garmin().schedule)
        await tools.change_session(ctx(z2, db), easy["id"], SessionChanges(workout_template_id=workout["id"]), "asked")
        changed = await sessions.get(db, easy["id"])
        assert (changed["workout_template_id"], changed["segments"]) == (workout["id"], workout["segments"])
        assert (changed["date"], changed["title"], changed["planned_distance_km"], changed["description"]) == (
            "2027-03-01", "Thursday", 11.0, "On the track")

        # Later partial changes keep the steps and the link
        await tools.change_session(ctx(z2, db), easy["id"], SessionChanges(date=DAY + timedelta(days=1)), "asked")
        await tools.change_session(ctx(z2, db), easy["id"], SessionChanges(target_hr_zone=4), "asked")
        kept = await sessions.get(db, easy["id"])
        assert (kept["workout_template_id"], kept["segments"]) == (workout["id"], workout["segments"])
        assert (kept["date"], kept["target_hr_zone"], kept["planned_distance_km"]) == ("2027-03-02", 4, 11.0)
    run(work)


def test_naming_the_workout_a_past_session_follows_keeps_its_own_steps(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        workout = await save(z2, db, "6×1 km", "Run", RUN_STEPS)
        past = await sessions.create(z2, db, NewSession(date=date.today() - timedelta(days=3), title="6×1 km",
                                                        sport_type="Run", workout_template_id=workout["id"]),
                                     Garmin().schedule)
        longer = [*RUN_STEPS[:1], {**RUN_STEPS[1], "repetitions": 8}, *RUN_STEPS[2:]]
        await workout_library.update(z2, db, workout["id"], WorkoutChanges.model_validate({"segments": longer}),
                                     Garmin().schedule)
        await tools.change_session(ctx(z2, db), past["id"],
                                   SessionChanges(completed=True, workout_template_id=workout["id"]), "asked")
        done = await sessions.get(db, past["id"])
        assert (done["completed"], done["workout_template_id"]) == (True, workout["id"])
        assert done["segments"][1]["repetitions"] == 6
    run(work)


def test_a_session_changes_sport_for_a_saved_workout_only_when_told(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        workout = await save(z2, db, "Swim sets", "Swim", SWIM_STEPS)
        ride = await sessions.create(z2, db, NewSession(date=DAY, title="Ride", sport_type="Ride", target_avg_pace=28),
                                     Garmin().schedule)
        with pytest.raises(ModelRetry, match="Swim workout and the session a Ride"):
            await tools.change_session(ctx(z2, db), ride["id"], SessionChanges(workout_template_id=workout["id"]),
                                       "asked")
        assert (await sessions.get(db, ride["id"]))["workout_template_id"] is None
        changed = await sessions.update(z2, db, ride["id"], SessionChanges(
            sport_type="Swim", target_avg_pace=1.9, workout_template_id=workout["id"]), Garmin().schedule)
        assert (changed["sport_type"], changed["workout_template_id"]) == ("Swim", workout["id"])
        assert changed["segments"] == workout["segments"]
    run(work)


def test_steps_given_with_a_saved_workout_follow_the_calendars_rule(z2: SimpleNamespace) -> None:
    """As when the calendar plans from the library and the steps are then edited: the same steps
    keep the link, other steps link to the saved workout with those steps or save a new one."""
    async def work(db: Any) -> None:
        workout = await save(z2, db, "6×1 km", "Run", RUN_STEPS)
        same = await sessions.create(z2, db, NewSession.model_validate({
            "date": DAY, "title": "6×1 km", "sport_type": "Run", "segments": RUN_STEPS,
            "workout_template_id": workout["id"]}), Garmin().schedule)
        assert same["workout_template_id"] == workout["id"]
        edited = [*RUN_STEPS[:1], {**RUN_STEPS[1], "repetitions": 8}, *RUN_STEPS[2:]]
        other = await sessions.create(z2, db, NewSession.model_validate({
            "date": DAY, "title": "8×1 km", "sport_type": "Run", "segments": edited,
            "workout_template_id": workout["id"]}), Garmin().schedule)
        assert other["workout_template_id"] not in (None, workout["id"])
        assert (await workout_library.get(db, other["workout_template_id"]))["segments"][1]["repetitions"] == 8
    run(work)


def test_a_saved_workout_of_another_sport_or_none_is_refused(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        ride = await save(z2, db, "3×20 min", "Ride", RIDE_STEPS)
        with pytest.raises(ModelRetry, match="Ride"):
            await tools.add_session(ctx(z2, db), NewSession(date=DAY, title="Run", sport_type="Run",
                                                            workout_template_id=ride["id"]), "asked")
        with pytest.raises(ModelRetry, match="no saved workout 999"):
            await tools.add_session(ctx(z2, db), NewSession(date=DAY, title="Run", sport_type="Run",
                                                            workout_template_id=999), "asked")
        assert await sessions.between(db) == []
    run(work)


# ── Target paces in each sport's unit ───────────────────────────────────

def test_session_targets_read_in_each_sports_unit(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> list[dict[str, Any]]:
        garmin = Garmin()
        for sport_type, avg, steps in (("Run", 4.5, RUN_STEPS), ("Ride", 28.5, RIDE_STEPS), ("Swim", 1.75, SWIM_STEPS)):
            await sessions.create(z2, db, NewSession.model_validate({
                "date": DAY, "title": sport_type, "sport_type": sport_type, "target_avg_pace": avg,
                "segments": steps}), garmin.schedule)
        return await tools.planned_sessions_between(ctx(z2, db), DAY, DAY)
    run_session, ride, swim = run(work)
    assert run_session["target_avg_pace"] == "4:30 /km"
    assert (run_session["segments"][1]["target_pace_min"], run_session["segments"][1]["target_pace_max"]) == (
        "4:00 /km", "4:30 /km")
    assert ride["target_avg_pace"] == "28.5 km/h"
    assert (ride["segments"][0]["target_pace_min"], ride["segments"][0]["target_pace_max"]) == ("28 km/h", "32 km/h")
    assert swim["target_avg_pace"] == "1:45 /100m"
    assert swim["segments"][0]["target_pace_max"] == "2:00 /100m"


def test_written_targets_come_back_in_their_sports_unit(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        c = ctx(z2, db)
        added = await tools.add_session(c, NewSession(date=DAY, title="Ride", sport_type="Ride", target_pace_min=27,
                                                      target_pace_max=30), "asked")
        assert (added["target_pace_min"], added["target_pace_max"]) == ("27 km/h", "30 km/h")
        changed = await tools.change_session(c, added["id"], SessionChanges(target_avg_pace=29), "asked")
        assert (changed["target_avg_pace"], changed["target_pace_min"]) == ("29 km/h", "27 km/h")
        race = await tools.add_race(c, NewRace(name="Lake swim", date=DAY, sport_type="Swim", target_pace=1.9), "asked")
        assert race["target_pace"] == "1:54 /100m"
        moved = await tools.change_race(c, race["id"], RaceChanges(target_pace=1.8), "asked")
        assert moved["target_pace"] == "1:48 /100m"
        await tools.add_race(c, NewRace(name="Gran fondo", date=DAY, sport_type="Ride", target_pace=31), "asked")
        await tools.add_race(c, NewRace(name="Harbour 10K", date=DAY, sport_type="Run", target_pace=4.0), "asked")
        assert [r["target_pace"] for r in await tools.races(c)] == ["1:48 /100m", "31 km/h", "4:00 /km"]
        saved = await tools.save_workout(c, NewWorkout(name="3×20 min", sport_type="Ride", segments=RIDE_STEPS), "asked")
        assert saved["segments"][0]["target_pace_min"] == "28 km/h"
        assert (await tools.saved_workouts(c))[0]["segments"][0]["target_pace_max"] == "32 km/h"
    run(work)


def test_pace_descriptions_name_each_sports_unit() -> None:
    """The model reads the unit from the field's description: each pace field states every
    sport's, or points to the field beside it that does."""
    for model in (NewSession, SessionChanges, NewRace, RaceChanges, NewWorkout):
        schema = model.model_json_schema()
        step = schema.get("$defs", {}).get("Step", {}).get("properties", {})
        fields = {**schema["properties"], **{f"step.{k}": v for k, v in step.items()}}
        units = [v["description"] for k, v in fields.items()
                 if k.endswith(("target_avg_pace", "target_pace", "target_pace_min"))]
        assert units, model
        for text in units:
            assert "same unit" in text or all(unit in text for unit in (
                "decimal minutes per km for runs", "km/h for rides", "decimal minutes per 100 m for swims")), text


def test_a_change_of_sport_never_keeps_targets_in_the_old_unit(z2: SimpleNamespace) -> None:
    async def work(db: Any) -> None:
        c = ctx(z2, db)
        run_session = await sessions.create(z2, db, NewSession.model_validate({
            "date": DAY, "title": "Run", "sport_type": "Run", "target_avg_pace": 4.5, "segments": RUN_STEPS}),
            Garmin().schedule)
        with pytest.raises(ModelRetry, match="in min/km and a Ride's are in km/h"):
            await tools.change_session(c, run_session["id"], SessionChanges(sport_type="Ride"), "asked")
        # The steps' paces count too
        with pytest.raises(ModelRetry, match="km/h"):
            await tools.change_session(c, run_session["id"], SessionChanges(sport_type="Ride", target_avg_pace=28),
                                       "asked")
        assert (await sessions.get(db, run_session["id"]))["sport_type"] == "Run"
        trail = await tools.change_session(c, run_session["id"], SessionChanges(sport_type="TrailRun"), "asked")
        assert trail["target_avg_pace"] == "4:30 /km"
        ride = await tools.change_session(c, run_session["id"], SessionChanges.model_validate(
            {"sport_type": "Ride", "target_avg_pace": 28, "segments": RIDE_STEPS}), "asked")
        assert (ride["target_avg_pace"], ride["segments"][0]["target_pace_min"]) == ("28 km/h", "28 km/h")
        rest = await sessions.create(z2, db, NewSession(date=DAY, title="Rest", sport_type="Rest"), Garmin().schedule)
        assert (await tools.change_session(c, rest["id"], SessionChanges(sport_type="Swim"), "asked"))["sport_type"] == "Swim"

        race = await tools.add_race(c, NewRace(name="Harbour 10K", date=DAY, target_pace=4.0), "asked")
        with pytest.raises(ModelRetry, match="give them in km/h too"):
            await tools.change_race(c, race["id"], RaceChanges(sport_type="Ride"), "asked")
        assert (await tools.change_race(c, race["id"], RaceChanges(sport_type="Ride", target_pace=30), "asked"))[
            "target_pace"] == "30 km/h"

        # The run's steps were saved to the library with it
        with pytest.raises(ModelRetry, match="in min/km and a Swim's are in min/100m"):
            await tools.change_workout(c, run_session["workout_template_id"], WorkoutChanges(sport_type="Swim"),
                                       "asked")
    run(work)


def test_activities_read_in_each_sports_unit() -> None:
    row = {"id": 1, "start_date_local": "2027-03-01T08:00:00Z", "name": "x", "distance": 10000.0,
           "moving_time": 2400, "average_speed": 0.0}
    view = activities_frame([
        {**row, "id": 1, "sport_type": "Run", "average_speed": 1000 / 270},
        {**row, "id": 2, "sport_type": "Ride", "average_speed": 28 / 3.6},
        {**row, "id": 3, "sport_type": "Swim", "average_speed": 100 / 105},
    ])
    assert [tools._activity(r, frozenset())["pace"] for _, r in view.iterrows()] == [
        "4:30 /km", "28.0 km/h", "1:45 /100m"]


# ── Sport filters ───────────────────────────────────────────────────────

def test_weekly_volume_counts_runs_by_category_and_never_walks(monkeypatch: pytest.MonkeyPatch) -> None:
    class Today(date):
        @classmethod
        def today(cls) -> date:
            return date(2027, 3, 3)
    monkeypatch.setattr(training, "date", Today)
    view = activities_frame([
        {"id": i, "sport_type": sport, "start_date_local": "2027-03-01T08:00:00Z", "distance": km * 1000.0}
        for i, (sport, km) in enumerate([("Run", 10), ("TrailRun", 12), ("Walk", 5), ("Hike", 8), ("Ride", 30)])
    ])
    z2 = SimpleNamespace(strava_activities_cache=SimpleNamespace(get_prepared_view=lambda: view))
    c = SimpleNamespace(deps=SimpleNamespace(z2=z2))
    assert asyncio.run(tools.weekly_volume(c, weeks=1, sport=SportCategory.RUNNING)) == [
        {"week_start": "2027-03-01", "km": 22.0, "activities": 2}]
    assert asyncio.run(tools.weekly_volume(c, weeks=1, sport=SportCategory.WALKING))[0]["km"] == 13.0
    assert asyncio.run(tools.weekly_volume(c, weeks=1))[0]["km"] == 65.0


def test_workout_history_shows_the_sessions_sport_only(z2: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    past = date.today() - timedelta(days=7)
    view = activities_frame([
        {"id": 1, "sport_type": "TrailRun", "start_date_local": f"{past}T08:00:00Z", "distance": 9000.0,
         "moving_time": 2400, "average_speed": 3.75, "name": "Intervals"},
        {"id": 2, "sport_type": "Walk", "start_date_local": f"{past}T18:00:00Z", "distance": 3000.0,
         "moving_time": 2400, "average_speed": 1.25, "name": "Evening walk"},
    ])
    z2.strava_activities_cache = SimpleNamespace(get_prepared_view=lambda: view)
    z2.strava_analytics = SimpleNamespace(race_activity_ids=frozenset())

    async def work(db: Any) -> list[dict[str, Any]]:
        workout = await save(z2, db, "6×1 km", "Run", RUN_STEPS)
        await sessions.create(z2, db, NewSession(date=past, title="6×1 km", sport_type="Run",
                                                 workout_template_id=workout["id"]), Garmin().schedule)
        return await tools.workout_history(ctx(z2, db), workout_template_id=workout["id"])
    [session] = run(work)
    assert [a["id"] for a in session["activities"]] == [1]


# ── The terminal's approvals ────────────────────────────────────────────

def test_the_tail_holds_every_write_waiting_for_a_yes() -> None:
    """`approve` in the terminal reads only the conversation's tail: enough for the writes waiting."""
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    waiting = ModelResponse(parts=[ToolCallPart("add_session", {"session": {}}, tool_call_id="w1"),
                                   ToolCallPart("remove_session", {"session_id": 1}, tool_call_id="w2")],
                            timestamp=start + timedelta(hours=2))
    history = [m for n in range(30) for m in exchange(n, start + timedelta(minutes=n))]
    history += [prompt("move friday", start + timedelta(hours=2)), waiting]

    async def work(db: Any) -> tuple[list[str], list[str]]:
        await message_store.replace_from(db, "cli-1", None, [conversations.encode(m) for m in history])
        whole = chat.pending_calls(await conversations.load(db, "cli-1"))
        tail = chat.pending_calls(await conversations.tail(db, "cli-1"))
        return [c.tool_call_id for c in whole], [c.tool_call_id for c in tail]
    whole, tail = run(work)
    assert tail == whole == ["w1", "w2"]
