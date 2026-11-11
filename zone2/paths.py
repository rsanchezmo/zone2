"""Where z2 keeps its data: one definition of every path under the data directory.

The defaults sit in the checkout, not the working directory: Docker runs the app
from /app with the data volume at /app/.strava, and locally the data is
<repo>/.strava, so both resolve to the same folder from wherever z2 starts."""

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_DATA_DIR = PROJECT_ROOT / ".strava"
DEFAULT_WORKDIR = PROJECT_ROOT / "zone2_workdir"


@dataclass(frozen=True)
class DataDir:
    root: Path

    @property
    def activities(self) -> Path:
        return self.root / "activities"

    @property
    def streams(self) -> Path:
        return self.root / "streams"

    @property
    def metadata(self) -> Path:
        return self.root / "metadata.json"

    @property
    def token(self) -> Path:
        return self.root / "token.json"

    @property
    def gear(self) -> Path:
        return self.root / "gear.json"

    @property
    def calendar_db(self) -> Path:
        return self.root / "calendar.db"

    @property
    def garmin_tokens(self) -> Path:
        return self.root / "garmin"

    @property
    def matplotlib_config(self) -> Path:
        return self.root / "matplotlib"

    @property
    def xdg_cache(self) -> Path:
        return self.root / "cache"
