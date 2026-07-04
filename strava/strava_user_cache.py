import json
import logging
from pathlib import Path

from strava.strava_endpoint import StravaEndpoint
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class StravaUserCache:
    def __init__(self, strava_endpoint: StravaEndpoint, cache_dir: Path = Path("./.strava")):
        self.strava_endpoint = strava_endpoint
        self._gear_file = cache_dir / "gear.json"
        self._gear_cache: dict[str, dict] | None = None

        self._profile_cache = None
        self._profile_cached_at = None

        self._stats_cache = None
        self._stats_cached_at = None

        self._zones_cache = None
        self._zones_cached_at = None

    def __is_expired(self, cached_at: datetime | None, max_age_hours: int = 24) -> bool:
        if cached_at is None:
            return True
        
        return (datetime.now() - cached_at) > timedelta(hours=max_age_hours)
    
    def get_athlete_profile(self, max_age_hours: int = 24, force_refresh: bool = False) -> dict:
        """Get athlete profile, using cache if not expired."""
        if force_refresh or self.__is_expired(self._profile_cached_at, max_age_hours):
            self._profile_cache = self.strava_endpoint.get_athlete()
            self._profile_cached_at = datetime.now()

        return self._profile_cache or {}
    
    def get_athlete_stats(self, athlete_id: int | str | None = None, max_age_hours: int = 24, force_refresh: bool = False) -> dict:
        """Get athlete stats, using cache if not expired."""
        if force_refresh or self.__is_expired(self._stats_cached_at, max_age_hours):
            self._stats_cache = self.strava_endpoint.get_athlete_stats(athlete_id=athlete_id)
            self._stats_cached_at = datetime.now()

        return self._stats_cache or {}
    
    def get_athlete_zones(self, max_age_hours: int = 24, force_refresh: bool = False) -> dict:
        """Get athlete zones, using cache if not expired."""
        if force_refresh or self.__is_expired(self._zones_cached_at, max_age_hours):
            self._zones_cache = self.strava_endpoint.get_athlete_zones()
            self._zones_cached_at = datetime.now()

        return self._zones_cache or {}
    

    def get_gear_details(self, gear_ids: list[str]) -> dict[str, dict]:
        """Get gear details by id, fetching and persisting unknown ones.

        Used for retired gear, which Strava omits from the /athlete profile.
        Retired gear no longer accumulates distance, so entries are cached
        forever in gear.json (delete the file to force a re-fetch).
        """
        if self._gear_cache is None:
            self._gear_cache = self.__load_gear_file()

        missing = [gid for gid in gear_ids if gid not in self._gear_cache]
        fetched_any = False
        for gid in missing:
            gear = self.strava_endpoint.get_gear(gid)
            if gear:
                self._gear_cache[gid] = gear
                fetched_any = True
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

    def clear_cache(self):
        """Clear all cached data."""
        self._profile_cache = None
        self._profile_cached_at = None

        self._stats_cache = None
        self._stats_cached_at = None

        self._zones_cache = None
        self._zones_cached_at = None