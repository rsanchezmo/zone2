"""Signing in to Garmin from the app: the email and password reach Garmin once and only its tokens
are kept, a code Garmin asks for finishes the sign-in (and a wrong one can be retried), Garmin's
refusals read as such, and a sign-out forgets the tokens. garminconnect's Garmin is a fake."""
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services import garmin_sync
from tests.conftest import OfflineApp
from zone2.garmin_client import GarminClient

EMAIL, PASSWORD = "athlete@example.com", "synthetic-password"


@dataclass
class Account:
    """The Garmin account the fake signs in to."""
    code: str | None = None
    rate_limited: bool = False


def fake_garmin(monkeypatch: pytest.MonkeyPatch, account: Account) -> None:
    import garminconnect
    from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError

    class Session:
        token: str | None = None

        def dump(self, path: str) -> None:
            Path(path).write_text(json.dumps({"di_token": self.token}))

    class Garmin:
        def __init__(self, email: str | None = None, password: str | None = None, **options: object) -> None:
            self.email, self.password, self.client, self.display_name = email, password, Session(), None

        def login(self, tokenstore: str | None = None) -> tuple[str | None, None]:
            stored = Path(tokenstore or "") / "garmin_tokens.json"
            if tokenstore and stored.exists() and json.loads(stored.read_text())["di_token"] == "granted":
                self.display_name = "synthetic"
                return None, None
            if not self.email:
                raise GarminConnectAuthenticationError("Username and password are required")
            if account.rate_limited:
                raise GarminConnectTooManyRequestsError("All login strategies rate limited (429)")
            if (self.email, self.password) != (EMAIL, PASSWORD):
                raise GarminConnectAuthenticationError("Invalid credentials")
            if account.code:
                return "needs_mfa", None
            self.client.token = "granted"
            return None, None

        def resume_login(self, state: object, code: str) -> tuple[None, None]:
            if code != account.code:
                raise GarminConnectAuthenticationError("Widget MFA failed: Enter code")
            self.client.token = "granted"
            return None, None

    monkeypatch.setattr(garminconnect, "Garmin", Garmin)


@pytest.fixture
def syncs(offline_app: OfflineApp, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """The Garmin syncs a sign-in starts (whether each was full)."""
    started: list[bool] = []

    async def run(z2: object, full: bool) -> None:
        started.append(full)
    monkeypatch.setattr(garmin_sync, "run", run)
    return started


def sign_in(app: OfflineApp, password: str = PASSWORD) -> tuple[int, dict]:
    response = app.client.post("/api/garmin/sign-in", json={"email": EMAIL, "password": password})
    return response.status_code, response.json()


def enter(app: OfflineApp, code: str) -> tuple[int, dict]:
    response = app.client.post("/api/garmin/sign-in/code", json={"code": code})
    return response.status_code, response.json()


def test_a_sign_in_keeps_garmins_tokens_and_never_the_password(offline_app: OfflineApp, syncs: list[bool],
                                                               monkeypatch: pytest.MonkeyPatch):
    fake_garmin(monkeypatch, Account())
    client = offline_app.z2.garmin_client
    assert offline_app.client.get("/api/garmin/status").json()["configured"] is False

    assert sign_in(offline_app) == (200, {"needs_code": False})
    assert PASSWORD not in client.tokens_file.read_text()
    status = offline_app.client.get("/api/garmin/status").json()
    assert (status["configured"], status["enabled"], status["from_env"]) == (True, True, False)
    assert syncs == [False]

    # After a restart the tokens alone sign in
    assert GarminClient(None, None, client.token_dir).ensure_logged_in()


def test_a_code_garmin_asks_for_finishes_the_sign_in(offline_app: OfflineApp, syncs: list[bool],
                                                     monkeypatch: pytest.MonkeyPatch):
    fake_garmin(monkeypatch, Account(code="246810"))
    assert sign_in(offline_app) == (200, {"needs_code": True})
    assert not offline_app.z2.garmin_client.configured and syncs == []

    refused = enter(offline_app, "000000")
    assert refused == (400, {"detail": "Garmin didn't accept that code."})
    assert enter(offline_app, " 246810 ") == (200, {"needs_code": False})
    assert offline_app.z2.garmin_client.enabled and syncs == [False]
    assert enter(offline_app, "246810")[1]["detail"].startswith("That sign-in expired")


def test_garmins_refusals_read_as_such(offline_app: OfflineApp, syncs: list[bool], monkeypatch: pytest.MonkeyPatch):
    account = Account()
    fake_garmin(monkeypatch, account)
    assert sign_in(offline_app, password="wrong") == (400, {"detail": "Garmin didn't accept that email and password."})
    assert sign_in(offline_app, password="")[0] == 400
    account.rate_limited = True
    status, body = sign_in(offline_app)
    assert status == 503 and "limiting sign-ins" in body["detail"]
    assert not offline_app.z2.garmin_client.configured and syncs == []


def test_signing_out_forgets_the_tokens_unless_garmin_is_set_in_env(offline_app: OfflineApp, syncs: list[bool],
                                                                     monkeypatch: pytest.MonkeyPatch):
    fake_garmin(monkeypatch, Account())
    sign_in(offline_app)
    client = offline_app.z2.garmin_client
    assert offline_app.client.post("/api/garmin/sign-out").status_code == 200
    assert not client.tokens_file.exists() and not client.configured and not client.enabled

    monkeypatch.setattr(client, "email", EMAIL)
    monkeypatch.setattr(client, "password", PASSWORD)
    assert offline_app.client.post("/api/garmin/sign-out").status_code == 409


def test_the_coach_is_told_while_garmin_is_not_connected(offline_app: OfflineApp, syncs: list[bool],
                                                          monkeypatch: pytest.MonkeyPatch):
    from backend.agent.agent import _garmin_connection

    ctx = SimpleNamespace(deps=SimpleNamespace(z2=offline_app.z2))
    assert "Garmin Connect isn't connected" in _garmin_connection(ctx)
    fake_garmin(monkeypatch, Account())
    sign_in(offline_app)
    assert _garmin_connection(ctx) is None
