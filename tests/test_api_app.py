"""The app as a whole over HTTP: health and sync status, syncs started from the API, the coach's
conversation history in pages, unknown /api paths (404, never the SPA), and the real startup and
shutdown against a temp data dir. On the app stood up offline (conftest.offline_app); nothing
reaches Strava, Garmin or a model."""
import asyncio
import logging
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai import ModelRequest, ModelResponse, TextPart, UserPromptPart

import backend.db as calendar_db
from backend import dependencies
from backend.agent import conversations, message_store
from backend.app import _SPAStaticFiles, app
from backend.services import sync
from zone2.endpoint import StravaEndpoint
from tests.conftest import OfflineApp
from tests.synthetic import RECENT_RUNS, STREAM_RUN_IDS, store_activities

ALL = 5 + 3 + RECENT_RUNS


# ── Health and sync ──────────────────────────────────────────────────────

def test_health_and_sync_status(offline_app: OfflineApp):
    api = offline_app.client
    health = api.get("/api/health").json()
    assert (health["status"], health["total_activities"], health["sync_running"]) == ("ok", ALL, False)
    status = api.get("/api/sync/status").json()
    assert (status["syncing"], status["last_error"], status["needs_sync"]) == (False, None, False)
    assert (status["total_activities"], status["athlete_name"]) == (ALL, "Test Athlete")
    assert status["earliest_activity_date"].startswith("2024-03-04")
    assert status["last_activity_date"].startswith((offline_app.today - timedelta(days=3)).isoformat())
    assert api.get("/api/sync/cache-completeness").status_code == 200


def new_run(app: OfflineApp) -> dict[str, Any]:
    return {"id": 999, "name": "Fresh run", "sport_type": "Run", "distance": 5000.0, "moving_time": 1500,
            "start_date": f"{app.today}T06:00:00Z", "start_date_local": f"{app.today}T07:00:00Z"}


def test_a_sync_from_the_api_runs_in_the_slot_and_frees_it(offline_app: OfflineApp, monkeypatch: pytest.MonkeyPatch):
    api, z2 = offline_app.client, offline_app.z2
    calls: list[tuple[bool, bool]] = []

    def strava_sync(full_sync: bool = False, include_streams: bool = False) -> None:
        calls.append((full_sync, include_streams))
        z2.strava_activities_cache.save_activities([new_run(offline_app)])
    monkeypatch.setattr(z2, "sync_activities", strava_sync)
    version = api.get("/api/health").json()["cache_version"]

    assert api.post("/api/sync", params={"full_sync": True}).json() == {"status": "started"}
    assert calls == [(True, False)]
    health = api.get("/api/health").json()
    assert (health["total_activities"], health["sync_running"]) == (ALL + 1, False)
    assert health["cache_version"] > version
    assert api.get("/api/activities", params={"per_page": 1}).json()["items"][0]["id"] == 999

    assert sync.try_claim()
    assert api.post("/api/sync").json() == {"status": "already_running"}
    assert api.post("/api/sync/backfill-streams").json() == {"status": "already_running"}
    assert api.get("/api/health").json()["sync_running"] is True
    assert calls == [(True, False)]


def test_a_failed_sync_shows_in_the_status(offline_app: OfflineApp, monkeypatch: pytest.MonkeyPatch):
    def down(**kwargs: Any) -> None:
        raise RuntimeError("Strava is down")
    monkeypatch.setattr(offline_app.z2, "sync_activities", down)
    assert offline_app.client.post("/api/sync").json() == {"status": "started"}
    status = offline_app.client.get("/api/sync/status").json()
    assert (status["syncing"], status["last_error"]) == (False, "Strava is down")


def test_resyncing_one_activity(offline_app: OfflineApp, monkeypatch: pytest.MonkeyPatch):
    api, endpoint = offline_app.client, offline_app.z2.strava_endpoint
    missing = api.post("/api/sync/activity/999999")
    assert (missing.status_code, missing.json()) == (404, {"detail": "Activity not found or no detail returned"})
    detail = {k: v for k, v in store_activities(offline_app.today)[-RECENT_RUNS].items() if k != "streams"}
    assert detail["id"] == STREAM_RUN_IDS[0]
    monkeypatch.setattr(endpoint, "get_activity_detail", lambda activity_id: {**detail, "name": "Renamed"})
    assert api.post(f"/api/sync/activity/{STREAM_RUN_IDS[0]}").json() == {"status": "success"}
    assert api.get(f"/api/activities/{STREAM_RUN_IDS[0]}").json()["name"] == "Renamed"

    def refused(activity_id: int) -> dict:
        raise RuntimeError("429 Too Many Requests")
    monkeypatch.setattr(endpoint, "get_activity_detail", refused)
    failed = api.post(f"/api/sync/activity/{STREAM_RUN_IDS[0]}")
    assert (failed.status_code, failed.json()) == (502, {"detail": "429 Too Many Requests"})
    assert not sync.status().running


# ── The coach's conversation ─────────────────────────────────────────────

def store_exchanges(app: OfflineApp, conversation_id: str, n: int) -> None:
    """n question-and-answer turns, an hour apart, ending a few hours ago."""
    start = datetime.now(timezone.utc) - timedelta(hours=n + 3)
    messages = []
    for k in range(n):
        at = start + timedelta(hours=k)
        messages += [ModelRequest(parts=[UserPromptPart(f"question {k}", timestamp=at)], timestamp=at),
                     ModelResponse(parts=[TextPart(f"answer {k}")], timestamp=at + timedelta(seconds=5))]

    async def write() -> None:
        async with calendar_db.connect_db() as db:
            await message_store.replace_from(db, conversation_id, None, [conversations.encode(m) for m in messages])
    asyncio.run(write())


def test_the_conversation_history_in_pages(offline_app: OfflineApp):
    api = offline_app.client
    store_exchanges(offline_app, "coach", 5)
    whole = api.get("/api/agent/conversations/coach").json()
    assert set(whole) == {"messages", "pending"} and whole["pending"] == []
    texts = [m["text"] for m in whole["messages"] if m["role"] in ("user", "agent")]
    assert texts == [t for k in range(5) for t in (f"question {k}", f"answer {k}")]

    pages, before = [], None
    while True:
        params = {"turns": 2, **({"before": before} if before else {})}
        page = api.get("/api/agent/conversations/coach", params=params).json()
        pages.insert(0, page["messages"])
        before = page["older"]
        if before is None:
            break
    assert len(pages) == 3
    assert [m for page in pages for m in page] == whole["messages"]


def test_conversation_paging_parameters(offline_app: OfflineApp):
    api = offline_app.client
    empty = api.get("/api/agent/conversations/nobody", params={"turns": 5}).json()
    assert empty == {"messages": [], "pending": [], "older": None}
    for params in ({"turns": 0}, {"turns": 201}, {"before": 0}, {"turns": "all"}):
        assert api.get("/api/agent/conversations/coach", params=params).status_code == 422, params


def test_the_coach_without_a_key_never_calls_a_model(offline_app: OfflineApp):
    api = offline_app.client
    status = api.get("/api/agent/status").json()
    assert (status["available"], status["unread"]) == (False, 0)
    refused = api.post("/api/agent/chat", json={"message": "How was my week?"})
    assert refused.status_code == 503 and refused.json()["detail"].startswith("The coach has no key for")
    assert api.post("/api/agent/approve", json={"conversation_id": "coach", "approvals": {}}).status_code == 503


def test_nothing_reaches_the_network(offline_app: OfflineApp):
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("192.0.2.1", 443), timeout=1)
    with pytest.raises(requests.ConnectionError):
        requests.get("https://www.strava.com/api/v3/athlete", timeout=1)
    # Strava's real client, left unstubbed, fails without a request leaving
    with pytest.raises(requests.ConnectionError):
        StravaEndpoint.get_athlete(offline_app.z2.strava_endpoint)


# ── Unknown paths and the SPA ────────────────────────────────────────────

def test_unknown_api_paths_are_404(offline_app: OfflineApp):
    for path in ("/api/nope", "/api/activities/101/nope", "/api/stats/nope/deeper"):
        response = offline_app.client.get(path)
        assert response.status_code == 404, path
        assert response.headers["content-type"].startswith("application/json")


@pytest.fixture
def spa(tmp_path: Path) -> TestClient:
    """A frontend build served the way the app serves frontend/dist, beside one API route."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>z2</title>")
    (dist / "assets" / "app-1a2b.js").write_text("console.log(1)")
    spa_app = FastAPI()
    spa_app.get("/api/health")(lambda: {"status": "ok"})
    spa_app.mount("/", _SPAStaticFiles(directory=str(dist), html=True), name="frontend")
    return TestClient(spa_app)


def test_the_spa_serves_deep_links_but_not_unknown_api_paths_or_assets(spa: TestClient):
    for path in ("/", "/calendar", "/activities/123"):
        page = spa.get(path)
        assert (page.status_code, page.headers["cache-control"]) == (200, "no-cache"), path
        assert page.text.startswith("<!doctype html>")
    asset = spa.get("/assets/app-1a2b.js")
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert spa.get("/api/health").json() == {"status": "ok"}
    for path in ("/api/nope", "/assets/missing.js"):
        assert spa.get(path).status_code == 404, path


# ── Startup and shutdown ─────────────────────────────────────────────────

def test_startup_warms_the_cache_without_syncing_or_logging_in(offline_app: OfflineApp,
                                                               monkeypatch: pytest.MonkeyPatch):
    fetched: list[Any] = []
    monkeypatch.setattr(StravaEndpoint, "get_activities", lambda self, *a, **k: fetched.append(a) or [])
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        with TestClient(app) as client:
            z2 = dependencies.get_z2()
            assert z2 is not offline_app.z2 and z2.data.root == offline_app.data_dir
            health = client.get("/api/health").json()
            assert (health["cache_loaded"], health["total_activities"], health["sync_running"]) == (True, ALL, False)
            assert client.get("/api/stats/streaks").status_code == 200
    finally:
        root.handlers[:], root.level = handlers, level
    assert fetched == [] and not z2.garmin_client.enabled
    assert not sync.status().running
