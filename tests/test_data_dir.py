"""Where z2 keeps its data: every store under the data directory it is given, the defaults in
the checkout whatever the working directory, and the settings' environment variables."""
import json
import os
import time
from pathlib import Path

import pytest

import telegram_bot
from backend.config import Settings, load_settings
from zone2.core import Zone2
from zone2.paths import DEFAULT_DATA_DIR, DEFAULT_WORKDIR, PROJECT_ROOT, DataDir

_SETTINGS_ENV = ("STRAVA_WEB_DATA_DIR", "STRAVA_WEB_WORKDIR")


@pytest.fixture
def offline_strava(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials that never reach Strava (the token below is valid), Garmin switched off."""
    monkeypatch.setenv("STRAVA_CLIENT_ID", "0")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    for name in ("GARMIN_EMAIL", "GARMIN_PASSWORD", "GARMINTOKENS"):
        monkeypatch.delenv(name, raising=False)


def _seed_token(data_dir: Path) -> None:
    data_dir.mkdir(parents=True)
    token = {"access_token": "a", "refresh_token": "r", "expires_at": int(time.time()) + 86_400}
    DataDir(data_dir).token.write_text(json.dumps(token))


def test_every_store_lives_in_the_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline_strava: None):
    cwd, data_dir = tmp_path / "cwd", tmp_path / "data"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    _seed_token(data_dir)

    z2 = Zone2(workdir=tmp_path / "work", data_dir=data_dir, auto_sync=False)
    z2.strava_activities_cache.save_activities([{
        "id": 1, "name": "Synthetic run", "sport_type": "Run", "distance": 5000.0,
        "start_date": "2024-06-01T07:00:00Z", "start_date_local": "2024-06-01T09:00:00Z", "utc_offset": 7200.0,
    }])

    data = DataDir(data_dir)
    assert z2.data == data
    assert z2.strava_activities_cache.activities_dir == data.activities
    assert (data.activities / "2024.parquet").exists()
    assert z2.strava_activities_cache.streams.store_dir == data.streams
    assert data.metadata.exists()
    assert z2.strava_user_cache._gear_file == data.gear
    assert z2.garmin_client.token_dir == data.garmin_tokens
    assert data.calendar_db.exists()
    assert list(cwd.iterdir()) == []


def test_garmintokens_still_points_the_garmin_token_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           offline_strava: None):
    _seed_token(tmp_path / "data")
    monkeypatch.setenv("GARMINTOKENS", str(tmp_path / "tokens"))
    z2 = Zone2(workdir=tmp_path / "work", data_dir=tmp_path / "data", auto_sync=False)
    assert z2.garmin_client.token_dir == tmp_path / "tokens"


def test_defaults_are_in_the_checkout_whatever_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for name in _SETTINGS_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    assert (PROJECT_ROOT / "pyproject.toml").exists()
    assert DEFAULT_DATA_DIR == PROJECT_ROOT / ".strava"
    assert DEFAULT_WORKDIR == PROJECT_ROOT / "zone2_workdir"
    settings = Settings()
    assert settings.data_dir == DEFAULT_DATA_DIR
    assert settings.workdir == DEFAULT_WORKDIR
    assert DataDir(settings.data_dir).calendar_db == PROJECT_ROOT / ".strava" / "calendar.db"


def test_settings_take_the_data_dir_and_workdir_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STRAVA_WEB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STRAVA_WEB_WORKDIR", str(tmp_path / "work"))
    settings = Settings()
    assert settings.data_dir == tmp_path / "data"
    assert settings.workdir == tmp_path / "work"


def test_settings_load_the_projects_env_file_without_overriding_the_environment(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"STRAVA_WEB_DATA_DIR={tmp_path / 'from-file'}\nSTRAVA_WEB_WORKDIR=ignored\n"
                        "GARMIN_EMAIL=athlete@example.com\n")
    monkeypatch.setattr("backend.config.ENV_FILE", env_file)
    monkeypatch.delenv("STRAVA_WEB_DATA_DIR", raising=False)
    monkeypatch.delenv("GARMIN_EMAIL", raising=False)
    monkeypatch.setenv("STRAVA_WEB_WORKDIR", str(tmp_path / "from-env"))
    monkeypatch.chdir(tmp_path.parent)

    settings = load_settings()
    assert settings.data_dir == tmp_path / "from-file"
    assert settings.workdir == tmp_path / "from-env"
    # Loaded for the libraries that read their keys from the environment themselves
    assert os.environ["GARMIN_EMAIL"] == "athlete@example.com"


def test_the_telegram_bot_takes_the_apps_workdir_unless_its_own_is_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("STRAVA_WORKDIR", raising=False)
    assert telegram_bot.bot_workdir(tmp_path / "app") == tmp_path / "app"
    monkeypatch.setenv("STRAVA_WORKDIR", str(tmp_path / "bot"))
    assert telegram_bot.bot_workdir(tmp_path / "app") == tmp_path / "bot"
