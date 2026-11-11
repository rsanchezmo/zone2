"""The write API over HTTP: planned sessions and their scores, goals, races, saved workouts and
the athlete's zone settings, with the validation errors and the domain-error statuses, on the app
stood up offline over the synthetic store (conftest.offline_app). Garmin is not configured, so
its pushes are no-ops."""
import asyncio
from datetime import date, timedelta
from typing import Any

import pytest

from backend.app import HTTP_STATUS, service_error
from backend.errors import Conflict, Invalid, NotFound, ServiceError, UpstreamFailed, UpstreamUnavailable
from tests.conftest import OfflineApp
from tests.synthetic import STREAM_RUN_IDS, store_activities

STEPS = [{"type": "warmup", "distance_km": 2}, {"type": "work", "distance_km": 1, "repetitions": 4,
                                                 "target_pace_min": 3.9, "target_pace_max": 4.1},
         {"type": "cooldown", "distance_km": 2}]
MANUAL_ZONES = [{"min": 0, "max": 125}, {"min": 125, "max": 140}, {"min": 140, "max": 155},
                {"min": 155, "max": 170}, {"min": 170, "max": 190}]


def day(app: OfflineApp, days_ago: int) -> str:
    return (app.today - timedelta(days=days_ago)).isoformat()


def session(on: str, **fields: Any) -> dict[str, Any]:
    return {"date": on, "title": "Steady 10", "sport_type": "Run", "planned_distance_km": 10, **fields}


# ── Planned sessions ─────────────────────────────────────────────────────

def test_session_crud(offline_app: OfflineApp):
    api = offline_app.client
    on = day(offline_app, 6)
    created = api.post("/api/calendar/sessions", json=session(on, target_hr_zone=3))
    assert created.status_code == 201
    sid = created.json()["id"]
    [listed] = api.get("/api/calendar/sessions", params={"date_from": on, "date_to": on}).json()
    assert listed == {**created.json(), "plan_name": None}
    later = {"date_from": day(offline_app, 5), "date_to": day(offline_app, 0)}
    assert api.get("/api/calendar/sessions", params=later).json() == []

    changed = api.put(f"/api/calendar/sessions/{sid}", json={"title": "Long", "planned_distance_km": 16})
    assert (changed.status_code, changed.json()["title"], changed.json()["planned_distance_km"]) == (200, "Long", 16.0)
    assert api.put(f"/api/calendar/sessions/{sid}", json={"target_hr_zone": 6}).status_code == 422
    assert api.put(f"/api/calendar/sessions/{sid}", json={}).json() == {"detail": "No fields to update"}

    assert api.delete(f"/api/calendar/sessions/{sid}").status_code == 204
    assert api.get("/api/calendar/sessions").json() == []
    gone = api.delete(f"/api/calendar/sessions/{sid}")
    assert (gone.status_code, gone.json()) == (404, {"detail": "Session not found"})


@pytest.mark.parametrize("change", [{"date": "2026-02-30"}, {"sport_type": None}, {"planned_intensity": "max"},
                                    {"segments": [{"type": "sprint"}]}, {"title": None}])
def test_session_validation(offline_app: OfflineApp, change: dict[str, Any]):
    response = offline_app.client.post("/api/calendar/sessions", json={**session(day(offline_app, 1)), **change})
    assert response.status_code == 422


def test_sessions_are_scored_against_the_activity_that_fulfils_them(offline_app: OfflineApp):
    api = offline_app.client
    run_day, rest_day = day(offline_app, 6), day(offline_app, 7)
    sid = api.post("/api/calendar/sessions", json=session(run_day, target_hr_zone=3)).json()["id"]
    api.post("/api/calendar/sessions", json=session(rest_day, title="Missed"))

    by_activity = api.get(f"/api/calendar/sessions/score-by-activity/{STREAM_RUN_IDS[1]}").json()
    assert by_activity["session"]["id"] == sid
    score = by_activity["score"]
    assert score["matched_activity_id"] == STREAM_RUN_IDS[1]
    assert score["metrics"]["distance"] == {"target": 10.0, "actual": 10.0, "score": 100, "unit": "km"}
    assert 0 <= score["overall_score"] <= 100

    scores = api.get("/api/calendar/sessions/scores", params={"date_from": rest_day, "date_to": run_day}).json()
    assert scores[str(sid)] == score
    assert api.get("/api/calendar/sessions/scores", params={"date_from": run_day}).status_code == 422
    # An activity no session plans, and one that doesn't exist
    assert api.get(f"/api/calendar/sessions/score-by-activity/{STREAM_RUN_IDS[0]}").json() is None
    assert api.get("/api/calendar/sessions/score-by-activity/999999").json() is None

    done = api.get("/api/calendar/sessions/accomplishment").json()
    assert (done["total_planned"], done["total_completed"], done["rate"]) == (2, 1, 50.0)
    assert (done["recent_planned"], done["recent_rate"]) == (2, 50.0)


def test_watch_workouts_need_garmin(offline_app: OfflineApp):
    api = offline_app.client
    assert api.get("/api/calendar/watch-workouts").json() == {"available": False, "enabled": False}
    assert api.put("/api/calendar/watch-workouts", json={"enabled": True}).json() == {"available": False,
                                                                                      "enabled": False}


# ── Goals ────────────────────────────────────────────────────────────────

def test_goal_crud_and_progress(offline_app: OfflineApp):
    api = offline_app.client
    ref = offline_app.today - timedelta(days=6)
    goal = {"year": ref.year, "sport_type": "Run", "metric": "distance_km", "period": "weekly", "target_value": 30}
    created = api.post("/api/goals/", json=goal)
    assert created.status_code == 201
    gid = created.json()["id"]
    assert [g["id"] for g in api.get("/api/goals/", params={"year": ref.year}).json()] == [gid]
    assert api.get("/api/goals/", params={"year": ref.year - 5}).json() == []

    monday = ref - timedelta(days=ref.weekday())
    week_km = sum(a["distance"] for a in store_activities(offline_app.today) if a["sport_type"] == "Run"
                  and monday <= date.fromisoformat(a["start_date_local"][:10]) <= monday + timedelta(days=6)) / 1000
    [progress] = api.get("/api/goals/progress", params={"week_start": ref.isoformat()}).json()["goals"]
    assert (progress["period_start"], progress["current_value"]) == (monday.isoformat(), week_km)
    assert progress["percentage"] == pytest.approx(min(100.0, 100 * week_km / 30), abs=0.1)
    assert api.get("/api/goals/progress", params={"week_start": "soon"}).status_code == 422

    assert api.put(f"/api/goals/{gid}", json={"target_value": 40}).json()["target_value"] == 40.0
    assert api.put(f"/api/goals/{gid}", json={"period": "daily"}).status_code == 422
    empty = api.put(f"/api/goals/{gid}", json={})
    assert (empty.status_code, empty.json()) == (400, {"detail": "No fields to update"})
    assert api.delete(f"/api/goals/{gid}").status_code == 204
    gone = api.put(f"/api/goals/{gid}", json={"target_value": 5})
    assert (gone.status_code, gone.json()) == (404, {"detail": "Goal not found"})


# ── Races ────────────────────────────────────────────────────────────────

def test_race_crud_points_the_analytics_at_the_race(offline_app: OfflineApp):
    api = offline_app.client
    analytics = offline_app.z2.strava_analytics
    race = {"name": "Harbour 8K", "date": day(offline_app, 3), "sport_type": "Run", "distance_km": 8}
    created = api.post("/api/races/", json=race)
    assert created.status_code == 201
    rid = created.json()["id"]
    assert analytics.race_activity_ids == frozenset({STREAM_RUN_IDS[0]})

    future = api.post("/api/races/", json={**race, "name": "Next 10K", "date": day(offline_app, -30)}).json()
    assert [r["id"] for r in api.get("/api/races/upcoming").json()] == [future["id"]]
    assert [r["id"] for r in api.get("/api/races/").json()] == [rid, future["id"]]

    # Moved to a day without a run, it is no race of any activity
    assert api.put(f"/api/races/{rid}", json={"date": day(offline_app, 1)}).status_code == 200
    assert analytics.race_activity_ids == frozenset()
    assert api.delete(f"/api/races/{rid}").status_code == 204
    gone = api.delete(f"/api/races/{rid}")
    assert (gone.status_code, gone.json()) == (404, {"detail": "Race event not found"})


def test_race_validation(offline_app: OfflineApp):
    api = offline_app.client
    race = {"name": "Club 5K", "date": day(offline_app, -10), "sport_type": "Run", "distance_km": 5}
    pace = api.post("/api/races/", json={**race, "target_pace": 30})
    assert pace.status_code == 400 and "minutes per km" in pace.json()["detail"]
    assert api.post("/api/races/", json={**race, "date": "2027-13-07"}).status_code == 422
    assert api.post("/api/races/", json={**race, "target_pace": 0}).status_code == 422
    assert api.post("/api/races/", json={"date": race["date"]}).status_code == 422
    assert api.get("/api/races/").json() == []


# ── Saved workouts ───────────────────────────────────────────────────────

def test_workout_crud(offline_app: OfflineApp):
    api = offline_app.client
    created = api.post("/api/workouts", json={"name": "4×1 km", "sport_type": "Run", "segments": STEPS})
    assert created.status_code == 201
    wid = created.json()["id"]
    listed = api.get("/api/workouts").json()
    assert [(w["id"], w["uses"]) for w in listed] == [(wid, 0)]

    planned = api.post("/api/calendar/sessions", json=session(day(offline_app, -2), segments=STEPS)).json()
    assert planned["workout_template_id"] == wid
    assert api.get("/api/workouts").json()[0]["uses"] == 1

    duplicate = api.post("/api/workouts", json={"name": "Again", "sport_type": "Run", "segments": STEPS})
    assert (duplicate.status_code, duplicate.json()) == (409, {"detail": "Same steps as “4×1 km”"})
    assert api.put(f"/api/workouts/{wid}", json={"name": "Fours"}).json()["name"] == "Fours"
    assert api.post("/api/workouts", json={"name": "No steps", "sport_type": "Run"}).status_code == 422
    assert api.delete(f"/api/workouts/{wid}").status_code == 204
    assert api.get("/api/calendar/sessions").json()[0]["workout_template_id"] is None
    gone = api.delete(f"/api/workouts/{wid}")
    assert (gone.status_code, gone.json()) == (404, {"detail": "Template not found"})
    # Garmin's own library is empty without Garmin
    assert api.get("/api/workouts/garmin").json() == []


# ── Zones and resting HR ─────────────────────────────────────────────────

def test_manual_zones_are_validated_saved_and_used_by_the_reports(offline_app: OfflineApp):
    api = offline_app.client
    assert api.get("/api/athlete/zones-settings").json() == {"source": "estimated", "manual_zones": None,
                                                              "garmin_available": False}
    estimated = api.get("/api/athlete/zones").json()["heart_rate"]
    assert (estimated["source"], len(estimated["zones"])) == ("estimated", 5)

    gap = [*MANUAL_ZONES[:2], {"min": 141, "max": 155}, *MANUAL_ZONES[3:]]
    for zones, message in [(MANUAL_ZONES[:4], "exactly 5"), (gap, "Zone 3 min (141) must equal zone 2 max (140)"),
                           ([{"min": 0, "max": 0}, *MANUAL_ZONES[1:]], "Zone 1: max (0) must be greater than min (0)")]:
        response = api.put("/api/athlete/zones-settings", json={"source": "manual", "manual_zones": zones})
        assert response.status_code == 400 and message in response.json()["detail"]
    assert api.put("/api/athlete/zones-settings", json={"source": "polar"}).status_code == 422
    assert api.put("/api/athlete/zones-settings",
                   json={"source": "manual", "manual_zones": [{"min": 0, "max": 300}] * 5}).status_code == 422

    week = (offline_app.today - timedelta(days=6)).isoformat()
    before = api.get("/api/stats/weekly-report", params={"week_start": week}).json()["current"]["hr_zone_ranges"]
    saved = api.put("/api/athlete/zones-settings", json={"source": "manual", "manual_zones": MANUAL_ZONES})
    assert saved.json() == {"source": "manual"}
    zones = api.get("/api/athlete/zones").json()["heart_rate"]
    assert (zones["zones"], zones["source"], zones["max_hr"]) == (MANUAL_ZONES, "manual", 190)
    after = api.get("/api/stats/weekly-report", params={"week_start": week}).json()["current"]["hr_zone_ranges"]
    assert after != before and after["2"] == [125, 140]


def test_garmin_zones_fall_back_without_garmin(offline_app: OfflineApp):
    api = offline_app.client
    assert api.put("/api/athlete/zones-settings", json={"source": "garmin"}).status_code == 200
    zones = api.get("/api/athlete/zones").json()["heart_rate"]
    assert (zones["source"], zones["requested_source"], zones["fallback_reason"]) == (
        "estimated", "garmin", "Garmin isn't connected")


def test_resting_hr_settings(offline_app: OfflineApp):
    api = offline_app.client
    assert api.put("/api/athlete/resting-hr-settings", json={"source": "manual", "manual_resting_hr": 10}).status_code == 422
    assert api.put("/api/athlete/resting-hr-settings", json={"source": "manual", "manual_resting_hr": 48}).status_code == 200
    assert api.get("/api/athlete/resting-hr-settings").json() == {"source": "manual", "manual_resting_hr": 48.0}
    resting = api.get("/api/athlete/resting-hr").json()
    assert (resting["value"], resting["source"], resting["fallback_reason"]) == (48.0, "manual", None)


# ── Domain errors as HTTP statuses ───────────────────────────────────────

class MissingRoute(NotFound):
    pass


@pytest.mark.parametrize("error, status", [
    (NotFound("x"), 404), (Invalid("x"), 400), (Conflict("x"), 409), (UpstreamUnavailable("x"), 503),
    (UpstreamFailed("x"), 502), (MissingRoute("x"), 404), (ServiceError("x"), 500),
])
def test_each_service_error_maps_to_its_status(error: ServiceError, status: int):
    response = asyncio.run(service_error(None, error))  # type: ignore[arg-type]
    assert (response.status_code, response.body) == (status, b'{"detail":"x"}')


def test_every_service_error_has_a_status():
    assert set(HTTP_STATUS) == {cls for cls in ServiceError.__subclasses__()}
