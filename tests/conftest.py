"""Shared fixtures. Before anything imports backend.config, the session's data directory and
workdir become throwaway temp dirs and the project's .env is swapped for a missing file, so no
test reads the owner's data or credentials; sockets refuse to connect, so no test reaches Strava,
Garmin or a model."""
import os
import shutil
import socket
import tempfile
from pathlib import Path

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="z2-tests-"))
os.environ["STRAVA_WEB_DATA_DIR"] = str(_SESSION_DIR / "data")
os.environ["STRAVA_WEB_WORKDIR"] = str(_SESSION_DIR / "work")
os.environ["STRAVA_WEB_AUTO_SYNC_HOURS"] = "0"
os.environ["STRAVA_WEB_AUTO_GARMIN_SYNC_HOURS"] = "0"
for _name in ("GARMIN_EMAIL", "GARMIN_PASSWORD", "GARMINTOKENS", "OPENAI_API_KEY", "STRAVA_CLIENT_ID",
              "STRAVA_CLIENT_SECRET", "STRAVA_WEB_CALENDAR_FEED_TOKEN", "STRAVA_WEB_AGENT_MODEL"):
    os.environ.pop(_name, None)

import matplotlib  # noqa: E402
import zone2.paths  # noqa: E402

zone2.paths.ENV_FILE = _SESSION_DIR / ".env"
# The app would point matplotlib at the empty session data dir and rebuild its font cache (~10 s)
os.environ.setdefault("MPLCONFIGDIR", matplotlib.get_configdir())

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import date, datetime, time as day_time, timezone  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tests.synthetic import ATHLETE_PROFILE, store_activities  # noqa: E402

if TYPE_CHECKING:
    from zone2.core import Zone2

TODAY = date.today()


def pytest_unconfigure(config: pytest.Config) -> None:
    shutil.rmtree(_SESSION_DIR, ignore_errors=True)


_LOCAL_HOSTS = {None, "localhost", "127.0.0.1", "::1"}


@pytest.fixture(scope="session", autouse=True)
def no_network() -> Iterator[None]:
    real_connect, real_connect_ex, real_getaddrinfo = (socket.socket.connect, socket.socket.connect_ex,
                                                       socket.getaddrinfo)

    def refuse(address: object) -> None:
        raise ConnectionRefusedError(f"tests never reach the network (tried {address!r})")

    def getaddrinfo(host: object, *args: object, **kwargs: object) -> list:
        if host not in _LOCAL_HOSTS:
            refuse(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def connect(self: socket.socket, address: object) -> None:
        if self.family == socket.AF_UNIX:
            return real_connect(self, address)
        refuse(address)

    def connect_ex(self: socket.socket, address: object) -> int:
        if self.family == socket.AF_UNIX:
            return real_connect_ex(self, address)
        refuse(address)
        return 1

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket.socket, "connect", connect)
        mp.setattr(socket.socket, "connect_ex", connect_ex)
        mp.setattr(socket, "getaddrinfo", getaddrinfo)
        yield


def pin_clock(monkeypatch: pytest.MonkeyPatch, z2: object, at: datetime) -> None:
    """Pin the athlete's clock of a Zone2 and its analytics to `at`, in UTC (Garmin's cache keeps
    its own: none of these tests sync Garmin)."""
    from zone2.clock import Clock
    clock = Clock(lambda: timezone.utc, lambda: at)
    for holder in (z2, z2.strava_analytics):
        monkeypatch.setattr(holder, "clock", clock)


def seed_token(data_dir: Path) -> None:
    """A Strava token that is valid for a day, so StravaEndpoint never refreshes it."""
    from zone2.paths import DataDir
    data_dir.mkdir(parents=True, exist_ok=True)
    token = {"access_token": "a", "refresh_token": "r", "expires_at": int(time.time()) + 86_400}
    DataDir(data_dir).token.write_text(json.dumps(token))


@pytest.fixture(scope="session")
def activity_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A data directory holding the synthetic activities (tests.synthetic.store_activities),
    built once; tests copy it."""
    from zone2.activities_cache import StravaActivitiesCache
    from zone2.paths import DataDir

    data = DataDir(tmp_path_factory.mktemp("store") / "data")
    StravaActivitiesCache(data.activities, data.streams, data.metadata).save_activities(store_activities(TODAY))
    seed_token(data.root)
    return data.root


@dataclass
class OfflineApp:
    client: TestClient
    z2: "Zone2"
    data_dir: Path
    today: date


@pytest.fixture
def offline_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, activity_store: Path) -> Iterator[OfflineApp]:
    """The FastAPI app on a copy of the synthetic store, without its lifespan (no startup sync,
    no Garmin login, no background loops): a Zone2 built on the temp data dir is the one
    get_z2 hands out, and every module that holds the calendar database's path points at the
    temp one. Strava's endpoint answers profile and zones from made-up data and refuses the rest.
    The athlete's clock is pinned to noon UTC of the session's day."""
    import backend.db as calendar_db
    from backend import dependencies
    from backend.agent import reviews
    from backend.app import app
    from backend.config import settings
    from backend.routers import activities as activities_router
    from backend.routers import workouts as workouts_router
    from backend.services import garmin_courses, garmin_sync, garmin_workouts, races, sync
    from backend.services.export_cache import clear_export_cache
    from backend.services.gear import clear_gear_cache
    from backend.services.stats_cache import clear_stats_cache
    from zone2.core import Zone2
    from zone2.paths import DataDir

    data_dir, workdir = tmp_path / "data", tmp_path / "work"
    shutil.copytree(activity_store, data_dir)
    monkeypatch.setenv("STRAVA_CLIENT_ID", "0")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "workdir", workdir)
    db_path = DataDir(data_dir).calendar_db
    for module in (calendar_db, races, reviews):
        monkeypatch.setattr(module, "DB_PATH", db_path)
    asyncio.run(calendar_db.init_db())

    z2 = Zone2(workdir=workdir, data_dir=data_dir, auto_sync=False)

    def strava(*args: object, **kwargs: object) -> None:
        raise AssertionError("tests never reach Strava")
    endpoint = z2.strava_endpoint
    for name in ("get_activities", "get_activity_detail", "get_activity_streams", "get_activity_photos", "get_gear"):
        monkeypatch.setattr(endpoint, name, strava)
    monkeypatch.setattr(endpoint, "get_athlete", lambda: dict(ATHLETE_PROFILE))
    monkeypatch.setattr(endpoint, "get_athlete_zones", lambda: {"heart_rate": {"custom_zones": False, "zones": []}})
    pin_clock(monkeypatch, z2, datetime.combine(TODAY, day_time(12), timezone.utc))

    monkeypatch.setattr(dependencies, "_instance", z2)
    monkeypatch.setattr(reviews, "_loop", None)
    monkeypatch.setattr(reviews, "_wake", None)
    monkeypatch.setattr(sync, "_status", sync.SyncStatus())
    monkeypatch.setattr(sync, "_catching_up", None)
    monkeypatch.setattr(garmin_sync, "_status", garmin_sync.GarminSyncStatus())
    monkeypatch.setattr(garmin_sync, "_catching_up", None)
    for clear in (clear_stats_cache, clear_export_cache, clear_gear_cache, garmin_courses.clear_courses_cache,
                  activities_router._polylines_cache.clear, workouts_router._garmin_steps_cache.clear,
                  garmin_workouts.library_listing.clear):
        clear()
    yield OfflineApp(client=TestClient(app), z2=z2, data_dir=data_dir, today=TODAY)
    clear_stats_cache()
