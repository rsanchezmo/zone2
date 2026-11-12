from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pathlib import Path

from zone2.paths import DEFAULT_DATA_DIR, DEFAULT_WORKDIR, ENV_FILE


class Settings(BaseSettings):
    workdir: Path = DEFAULT_WORKDIR
    # Activities, streams, tokens and calendar.db (zone2.paths.DataDir)
    data_dir: Path = DEFAULT_DATA_DIR
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]
    sync_max_age_hours: int = 12
    # If > 0, the backend runs an incremental sync every N hours. 0 disables
    # the scheduler (default) — manual UI sync still works either way.
    auto_sync_hours: int = 0
    # Garmin auto-sync — independent of Strava. Default 6h: wellness data
    # mostly refreshes once per night, but stress / body battery / steps
    # update through the day, so a few daytime checkpoints are worth it.
    # Each run is skipped while Garmin isn't connected (no sign-in, no .env credentials).
    auto_garmin_sync_hours: int = 6
    log_level: str = "INFO"
    # Optional: pin the iCal feed token via env. If set, wins over the
    # DB-stored token and disables UI rotation (rotate by editing .env).
    calendar_feed_token: str | None = None
    # CARTO basemap key, served to the browser via /api/config. Without it
    # cartocdn stamps every tile with an "API KEY REQUIRED" watermark, so the
    # frontend falls back to keyless OSM tiles when this is unset.
    # Free key (no account needed): https://carto.com/basemaps/apikey
    carto_api_key: str | None = None
    # The agent's model, as a Pydantic AI model string. OpenAI reads
    # OPENAI_API_KEY; a local model runs through Ollama ("ollama:<model>",
    # with OLLAMA_BASE_URL).
    agent_model: str = "openai:gpt-6-luna"
    # Live speech to text for talking to the agent (backend/agent/voice.py)
    agent_transcribe_model: str = "gpt-live-transcribe"

    model_config = {"env_prefix": "STRAVA_WEB_", "extra": "ignore"}


def load_settings() -> Settings:
    """The settings from the environment, with the project's .env loaded into it
    first: Garmin and the agent's model provider read their own keys from there."""
    load_dotenv(ENV_FILE)
    return Settings()


settings = load_settings()
