import json
import logging
from pathlib import Path

from zone2.endpoint import StravaEndpoint
from datetime import datetime, timedelta
from typing import Callable

logger = logging.getLogger(__name__)


class StravaUserCache:
    # A failed fetch is retried after this instead of being cached for the full max age
    RETRY_AFTER_FAILURE = timedelta(minutes=10)
    # Strava gear lookups that failed are not retried for this long
    GEAR_RETRY_AFTER_FAILURE = timedelta(hours=24)

    def __init__(self, strava_endpoint: StravaEndpoint, cache_dir: Path = Path("./.strava")):
        self.strava_endpoint = strava_endpoint
        self._gear_file = cache_dir / "gear.json"
        self._gear_cache: dict[str, dict] | None = None
        self._gear_failed_at: dict[str, datetime] = {}
        # name -> (last good value, when it expires)
        self._cached: dict[str, tuple[dict, datetime]] = {}

    def __get(self, name: str, fetch: Callable[[], dict], max_age_hours: int, force_refresh: bool) -> dict:
        """fetch()'s last good result, refetched once it is max_age_hours old.
        A failed fetch ({}) keeps the last good value and is retried after
        RETRY_AFTER_FAILURE."""
        value, expires_at = self._cached.get(name, ({}, datetime.min))
        if force_refresh or datetime.now() >= expires_at:
            fresh = fetch()
            if fresh:
                value, expires_at = fresh, datetime.now() + timedelta(hours=max_age_hours)
            else:
                expires_at = datetime.now() + self.RETRY_AFTER_FAILURE
            self._cached[name] = (value, expires_at)
        return value

    def get_athlete_profile(self, max_age_hours: int = 24, force_refresh: bool = False) -> dict:
        return self.__get('profile', self.strava_endpoint.get_athlete, max_age_hours, force_refresh)

    def get_athlete_zones(self, max_age_hours: int = 24, force_refresh: bool = False) -> dict:
        return self.__get('zones', self.strava_endpoint.get_athlete_zones, max_age_hours, force_refresh)

    def cached_athlete_zones(self) -> dict | None:
        """The athlete zones if already fetched, without calling Strava."""
        cached = self._cached.get('zones')
        return cached[0] if cached and cached[0] else None

    def get_gear_details(self, gear_ids: list[str]) -> dict[str, dict]:
        """Get gear details by id, fetching and persisting unknown ones.

        Used for retired gear, which Strava omits from the /athlete profile.
        Retired gear no longer accumulates distance, so entries are cached
        forever in gear.json (delete the file to force a re-fetch).
        """
        if self._gear_cache is None:
            self._gear_cache = self.__load_gear_file()

        now = datetime.now()
        missing = [gid for gid in gear_ids if gid not in self._gear_cache
                   and now - self._gear_failed_at.get(gid, datetime.min) >= self.GEAR_RETRY_AFTER_FAILURE]
        fetched_any = False
        for gid in missing:
            gear = self.strava_endpoint.get_gear(gid)
            if gear:
                self._gear_cache[gid] = gear
                fetched_any = True
            else:
                self._gear_failed_at[gid] = now
        if fetched_any:
            self.__save_gear_file()

        return {gid: self._gear_cache[gid] for gid in gear_ids if gid in self._gear_cache}

    def __load_gear_file(self) -> dict[str, dict]:
        if not self._gear_file.exists():
            return {}
        try:
            return json.loads(self._gear_file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read gear cache %s, starting fresh", self._gear_file)
            return {}

    def __save_gear_file(self):
        try:
            self._gear_file.write_text(json.dumps(self._gear_cache, indent=2))
        except OSError:
            logger.warning("Could not write gear cache %s", self._gear_file)
