from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    workdir: Path = Path("./strava_intelligence_workdir")
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]
    sync_max_age_hours: int = 12
    # If > 0, the backend runs an incremental sync every N hours. 0 disables
    # the scheduler (default) — manual UI sync still works either way.
    auto_sync_hours: int = 0
    # Garmin auto-sync — independent of Strava. Default 6h: wellness data
    # mostly refreshes once per night, but stress / body battery / steps
    # update through the day, so a few daytime checkpoints are worth it.
    # Only starts when GARMIN_EMAIL is set; otherwise the loop is skipped.
    auto_garmin_sync_hours: int = 6
    log_level: str = "INFO"
    # Optional: pin the iCal feed token via env. If set, wins over the
    # DB-stored token and disables UI rotation (rotate by editing .env).
    calendar_feed_token: str | None = None

    model_config = {"env_prefix": "STRAVA_WEB_"}


settings = Settings()
