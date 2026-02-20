from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    workdir: Path = Path("./strava_intelligence_workdir")
    cors_origins: list[str] = ["http://localhost:5173"]
    sync_max_age_hours: int = 12

    model_config = {"env_prefix": "STRAVA_WEB_"}


settings = Settings()
