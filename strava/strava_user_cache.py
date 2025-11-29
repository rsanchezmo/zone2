from strava.strava_endpoint import StravaEndpoint
from datetime import datetime, timedelta

class StravaUserCache:
    def __init__(self, strava_endpoint: StravaEndpoint):
        self.strava_endpoint = strava_endpoint

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
    
    def get_athlete_stats(self, max_age_hours: int = 24, force_refresh: bool = False) -> dict:
        """Get athlete stats, using cache if not expired."""
        if force_refresh or self.__is_expired(self._stats_cached_at, max_age_hours):
            self._stats_cache = self.strava_endpoint.get_athlete_stats()
            self._stats_cached_at = datetime.now()

        return self._stats_cache or {}
    
    def get_athlete_zones(self, max_age_hours: int = 24, force_refresh: bool = False) -> dict:
        """Get athlete zones, using cache if not expired."""
        if force_refresh or self.__is_expired(self._zones_cached_at, max_age_hours):
            self._zones_cache = self.strava_endpoint.get_athlete_zones()
            self._zones_cached_at = datetime.now()

        return self._zones_cache or {}
    

    def clear_cache(self):
        """Clear all cached data."""
        self._profile_cache = None
        self._profile_cached_at = None

        self._stats_cache = None
        self._stats_cached_at = None

        self._zones_cache = None
        self._zones_cached_at = None