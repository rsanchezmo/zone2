"""Connecting Strava from the app: the app runs before any account is connected, Strava's consent
page comes back to the callback that keeps the token, and a sign-in that didn't complete, or a
token Strava stopped accepting, leaves it to connect again. Strava's token endpoint is stubbed."""
import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from backend.services import strava_auth
from backend.services import sync as strava_sync
from tests.conftest import OfflineApp
from zone2.endpoint import StravaEndpoint, StravaNotConnected
from zone2.paths import DataDir
from zone2.user_cache import StravaUserCache

GRANTED = "read,activity:read_all,profile:read_all"
TOKEN = {"access_token": "fresh", "refresh_token": "next", "expires_at": int(time.time()) + 21_600,
         "token_type": "Bearer", "athlete": {"id": 7, "firstname": "Synthetic"}}


class _Answer:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code, self._payload, self.text = status_code, payload, json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def strava_answers(monkeypatch: pytest.MonkeyPatch, status_code: int, payload: dict) -> list[dict]:
    """Strava's token endpoint answering every POST with `payload`; returns what was posted."""
    posted: list[dict] = []

    def post(self: requests.Session, url: str, data: dict, **kwargs: object) -> _Answer:
        posted.append({"url": url, **data})
        return _Answer(status_code, payload)
    monkeypatch.setattr(requests.Session, "post", post)
    return posted


@pytest.fixture
def unconnected(offline_app: OfflineApp, monkeypatch: pytest.MonkeyPatch) -> OfflineApp:
    """The offline app without a Strava token, on the real client: with no token it never sends a
    request."""
    DataDir(offline_app.data_dir).token.unlink()
    for name in ("get_activities", "get_activity_detail", "get_activity_streams", "get_activity_photos", "get_gear",
                 "get_athlete", "get_athlete_zones"):
        monkeypatch.delattr(offline_app.z2.strava_endpoint, name)
    monkeypatch.setattr(strava_auth, "_pending", {})
    return offline_app


def connect_url(app: OfflineApp, return_to: str = "/calendar?view=week") -> dict[str, str]:
    response = app.client.post("/api/athlete/strava/connect",
                               json={"origin": "http://localhost:5173", "return_to": return_to})
    assert response.status_code == 200
    url = urlsplit(response.json()["url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "www.strava.com", "/oauth/authorize")
    return {k: v[0] for k, v in parse_qs(url.query).items()}


def come_back(app: OfflineApp, **query: str) -> str:
    """Where the callback sends the browser after Strava's consent page."""
    response = app.client.get("/api/athlete/strava/callback", params=query, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def error_of(location: str) -> str:
    return parse_qs(urlsplit(location).query)["strava_error"][0]


def test_the_app_runs_before_strava_is_connected(unconnected: OfflineApp):
    api, z2 = unconnected.client, unconnected.z2
    status = api.get("/api/sync/status").json()
    assert (status["connected"], status["athlete_name"]) == (False, None)
    assert api.get("/api/athlete/profile").status_code == 200
    refused = api.get("/api/athlete/rate-limits", params={"refresh": True})
    assert refused.status_code == 503 and refused.json()["detail"] == str(StravaNotConnected())

    assert api.post("/api/sync").json() == {"status": "started"}
    assert strava_sync.status().last_error == str(StravaNotConnected())
    assert asyncio.run(strava_sync.sync_now(z2)) == str(StravaNotConnected())


# What the pages read on a fresh install
FIRST_RUN_READS = (
    "/api/sync/status", "/api/sync/cache-completeness", "/api/athlete/profile", "/api/athlete/zones",
    "/api/calendar/briefing", "/api/activities?page=1&per_page=20", "/api/activities/polylines",
    "/api/activities/years", "/api/gear", "/api/stats/streaks", "/api/stats/personal-records",
    "/api/stats/sport-totals", "/api/stats/fitness?days=180", "/api/stats/weekly-report",
    "/api/stats/weekly-totals?weeks=12&sport_type=Run", "/api/stats/relative-effort/weekly?sport_type=Run",
    "/api/stats/year-in-sport?year=2026&main_sport=Run&comparison_year=2025",
    "/api/stats/cumulative-distance?year=2026&main_sport=Run&comparison_year=2025",
    "/api/stats/race-predictions?sport_category=running",
    "/api/stats/race-predictions/history?sport_category=running&weeks=52",
)


def test_a_fresh_install_reads_without_activities(unconnected: OfflineApp):
    cache = unconnected.z2.strava_activities_cache
    for year_file in cache.activities_dir.glob("*.parquet"):
        year_file.unlink()
    cache._invalidate_memory_cache()
    failed = {path: r.status_code for path in FIRST_RUN_READS if (r := unconnected.client.get(path)).status_code != 200}
    assert failed == {}


def test_strava_consent_page_comes_back_connected(unconnected: OfflineApp, monkeypatch: pytest.MonkeyPatch):
    api = unconnected.client
    query = connect_url(unconnected)
    assert query["redirect_uri"] == "http://localhost:5173/api/athlete/strava/callback"
    assert (query["client_id"], query["response_type"]) == ("0", "code")
    assert set(query["scope"].split(",")) == set(GRANTED.split(","))

    posted = strava_answers(monkeypatch, 200, TOKEN)
    assert come_back(unconnected, state=query["state"], code="the-code", scope=GRANTED) == \
        "/calendar?view=week&strava=connected"
    assert (posted[0]["code"], posted[0]["grant_type"]) == ("the-code", "authorization_code")
    assert json.loads(DataDir(unconnected.data_dir).token.read_text())["access_token"] == "fresh"
    assert api.get("/api/sync/status").json()["connected"] is True

    # Each state brings one sign-in back
    assert "expired" in error_of(come_back(unconnected, state=query["state"], code="the-code", scope=GRANTED))


@pytest.mark.parametrize("answer, outcome", [
    ({"error": "access_denied", "scope": ""}, "cancelled"),
    ({"code": "c", "scope": "read,activity:read_all"}, "leave both boxes ticked"),
])
def test_a_sign_in_that_did_not_complete_leaves_strava_unconnected(unconnected: OfflineApp, answer: dict,
                                                                    outcome: str):
    query = connect_url(unconnected, return_to="/records")
    location = come_back(unconnected, state=query["state"], **answer)
    assert urlsplit(location).path == "/records" and outcome in error_of(location)
    assert not DataDir(unconnected.data_dir).token.exists()


def test_strava_refusing_the_code_or_an_unknown_state_is_an_error(unconnected: OfflineApp,
                                                                  monkeypatch: pytest.MonkeyPatch):
    strava_answers(monkeypatch, 400, {"message": "Bad Request"})
    query = connect_url(unconnected)
    assert "refused the sign-in" in error_of(come_back(unconnected, state=query["state"], code="c", scope=GRANTED))
    assert "expired" in error_of(come_back(unconnected, state="forged", code="c", scope=GRANTED))
    assert not unconnected.z2.strava_endpoint.connected


def test_the_callback_only_returns_to_the_app(unconnected: OfflineApp):
    query = connect_url(unconnected, return_to="//elsewhere.example/page")
    assert come_back(unconnected, state=query["state"], error="access_denied").startswith("/?strava_error=")
    refused = unconnected.client.post("/api/athlete/strava/connect", json={"origin": "javascript:alert(1)"})
    assert refused.status_code == 400


def test_the_coach_is_told_while_strava_is_not_connected(offline_app: OfflineApp):
    from pydantic_ai import ModelMessage, ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    import backend.db as calendar_db
    from backend.agent.agent import build_agent
    from backend.agent.tools import AgentDeps

    told: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        told.append(info.instructions or "")
        return ModelResponse(parts=[TextPart("ok")])
    agent = build_agent(FunctionModel(respond, model_name="stub"))

    async def ask() -> None:
        async with calendar_db.connect_db() as db:
            await agent.run("How was my week?", deps=AgentDeps(z2=offline_app.z2, db=db, schedule=lambda *a: None))

    asyncio.run(ask())
    DataDir(offline_app.data_dir).token.unlink()
    asyncio.run(ask())
    held = offline_app.z2.strava_activities_cache.count_cached_activities()
    assert "Strava isn't connected" not in told[0]
    assert "Strava isn't connected" in told[1] and f"the {held} activities synced before" in told[1]


def test_a_token_strava_stops_accepting_asks_to_connect_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "0")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"access_token": "old", "refresh_token": "revoked", "expires_at": 0}))
    endpoint = StravaEndpoint(token_file)
    assert endpoint.connected

    strava_answers(monkeypatch, 400, {"errors": [{"resource": "RefreshToken", "code": "invalid"}]})
    with pytest.raises(StravaNotConnected):
        endpoint.get_athlete()
    assert not endpoint.connected
    assert StravaUserCache(endpoint, tmp_path / "gear.json").get_athlete_profile() == {}

    strava_answers(monkeypatch, 200, TOKEN)
    endpoint.connect("new-code")
    assert endpoint.connected
