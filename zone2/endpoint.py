from datetime import datetime
from enum import Enum, auto
import logging
import os
import threading
import time
from dotenv import load_dotenv
from pydantic import BaseModel
import requests
import webbrowser
from pathlib import Path
import json

logger = logging.getLogger(__name__)

load_dotenv()


class StravaRateLimitError(Exception):
    """Raised when Strava API rate limit is reached (HTTP 429 or usage >= limit)."""
    def __init__(self, message: str = "Strava API rate limit reached", usage: dict | None = None):
        super().__init__(message)
        self.usage = usage


class StravaStreamFetchError(Exception):
    """Raised when a stream fetch fails for a non-rate-limit reason (5xx, 404,
    network). Distinct from a 200 OK with empty body, which is a valid 'no
    streams' result and is cached as such."""


class RateGuard(Enum):
    """How a request treats Strava's rate limits."""
    RECORD = auto()    # only record usage: profile reads must not fail a sync
    ON_429 = auto()    # pre-flight budget check, raise only when Strava refuses
    AT_LIMIT = auto()  # pre-flight budget check, raise on 429 or once a window is used up


class StravaTokenData(BaseModel):
    """Pydantic model for Strava OAuth tokens"""
    access_token: str
    refresh_token: str
    expires_at: int
    token_type: str = "Bearer"
    
    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if token is expired (with optional buffer)"""
        return datetime.now().timestamp() >= (self.expires_at - buffer_seconds)
    
    @classmethod
    def from_file(cls, filepath: Path) -> "StravaTokenData":
        """Load token data from a JSON file"""
        
        with open(filepath, 'r') as f:
            data = json.load(f)

        return cls(**data)
    
    def to_file(self, filepath: Path):
        """Save token data to a JSON file"""

        # check if the filepath has an extension
        if filepath.suffix != '.json':
            filepath = filepath / "token.json"

        with open(filepath, 'w') as f:
            json.dump(self.model_dump(), f, indent=2)

        print(f"✓ Token saved to {filepath}")

class StravaEndpoint:

    # Strava moves the API to a new host on 2027-06-01; confirm it in the official
    # docs before changing this, since every request sends the Bearer token here.
    __API_BASE = 'https://www.strava.com/api/v3'
    __OAUTH_TOKEN_URL = 'https://www.strava.com/oauth/token'
    __OAUTH_AUTHORIZE_URL = 'https://www.strava.com/oauth/authorize'
    __TOKEN_FILENAME = 'token.json'
    __REQUEST_TIMEOUT = (5, 30)

    def __init__(self, cache_dir: Path = Path("./.strava")):
        self.__STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
        self.__STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
        self.__session = requests.Session()
        self.__token_data = None
        # Guards against two threads refreshing with the same refresh_token
        # (Strava rotates refresh_tokens, so the second request would 400).
        self.__token_lock = threading.Lock()

        # Rate-limit usage cache, updated from X-RateLimit-Usage response
        # headers. Used as a pre-flight guard so we don't fire a request that
        # we already know will 429.
        self._last_usage_fifteen: int = 0
        self._last_usage_daily: int = 0
        self._last_usage_at: float = 0.0  # time.monotonic(); 0 = unknown

        self.__cache_dir = cache_dir
        self.__cache_dir.mkdir(parents=True, exist_ok=True)

        if self.__STRAVA_CLIENT_ID is None:
            raise ValueError("STRAVA_CLIENT_ID not found in environment variables.")
        if self.__STRAVA_CLIENT_SECRET is None:
            raise ValueError("STRAVA_CLIENT_SECRET not found in environment variables.")
        
        # Get the access token 
        self.__authenticate()

    def __get_initial_token(self) -> StravaTokenData:
        """Obtain initial OAuth token via user authorization flow."""
        if (self.__cache_dir / StravaEndpoint.__TOKEN_FILENAME).exists():
            return StravaTokenData.from_file(self.__cache_dir / StravaEndpoint.__TOKEN_FILENAME)

        # Request all necessary scopes for full API access
        scopes = [
            'read',              # Public data access
            'read_all',          # Private routes, segments, events
            'profile:read_all',  # Full profile access (required for zones)
            'activity:read_all', # All activities including private
        ]

        auth_url = (
            f"{StravaEndpoint.__OAUTH_AUTHORIZE_URL}?"
            f"client_id={self.__STRAVA_CLIENT_ID}&"
            f"response_type=code&"
            f"redirect_uri=http://localhost/exchange_token&"
            f"scope={','.join(scopes)}"
        )
        webbrowser.open(auth_url)
        authorization_code = input("Enter the authorization code from the URL: ")
        
        response = self.__session.post(
            StravaEndpoint.__OAUTH_TOKEN_URL,
            data={
                'client_id': self.__STRAVA_CLIENT_ID,
                'client_secret': self.__STRAVA_CLIENT_SECRET,
                'code': authorization_code,
                'grant_type': 'authorization_code'
            },
            timeout=self.__REQUEST_TIMEOUT,
        )
        
        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.json()}")
        
        token_data = response.json()
        
        token = StravaTokenData(**token_data)

        token.to_file(self.__cache_dir / StravaEndpoint.__TOKEN_FILENAME)

        return token
    
    def __refresh_token(self) -> StravaTokenData:
        """Refresh OAuth token using the refresh token."""
        response = self.__session.post(
            StravaEndpoint.__OAUTH_TOKEN_URL,
            data={
                'client_id': self.__STRAVA_CLIENT_ID,
                'client_secret': self.__STRAVA_CLIENT_SECRET,
                'grant_type': 'refresh_token',
                'refresh_token': self.__token_data.refresh_token
            },
            timeout=self.__REQUEST_TIMEOUT,
        )
        
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.json()}")
        
        token_data = response.json()
        
        token = StravaTokenData(**token_data)

        token.to_file(self.__cache_dir / StravaEndpoint.__TOKEN_FILENAME)

        return token
    
    def __get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary. Thread-safe:
        concurrent callers serialize on __token_lock and only the first
        refresh actually hits Strava; the rest see the already-refreshed
        token on the re-check inside the lock."""
        if not self.__token_data.is_expired():
            return self.__token_data.access_token
        with self.__token_lock:
            if self.__token_data.is_expired():
                self.__token_data = self.__refresh_token()
            return self.__token_data.access_token

    def __authenticate(self):
        self.__token_data = self.__get_initial_token()

        if self.__token_data.is_expired():
            with self.__token_lock:
                if self.__token_data.is_expired():
                    self.__token_data = self.__refresh_token()

    def __get_headers(self) -> dict[str, str]:
        access_token = self.__get_valid_token()
        return {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

    # Rate-limit cache is considered fresh for 15 minutes (Strava's 15min
    # window length). Older cached values are treated as unknown — we let
    # the request through and refresh the cache from its response.
    _RATE_LIMIT_CACHE_TTL_SECONDS = 900

    def usage_is_fresh(self) -> bool:
        """Whether the cached usage comes from a response recent enough to trust."""
        return self._last_usage_at != 0.0 and (time.monotonic() - self._last_usage_at) <= self._RATE_LIMIT_CACHE_TTL_SECONDS

    def _ensure_rate_limit_budget(self) -> None:
        """Raise StravaRateLimitError if cached usage says we're already at
        or over a limit and the cache is fresh enough to trust. No-op when
        usage is unknown or stale."""
        if not self.usage_is_fresh():
            return
        if self._last_usage_fifteen >= self.FIFTEEN_MIN_LIMIT:
            raise StravaRateLimitError(
                f"Pre-flight: 15min rate limit already reached "
                f"({self._last_usage_fifteen}/{self.FIFTEEN_MIN_LIMIT})",
                usage={'fifteen_min': self._last_usage_fifteen, 'daily': self._last_usage_daily},
            )
        if self._last_usage_daily >= self.DAILY_LIMIT:
            raise StravaRateLimitError(
                f"Pre-flight: daily rate limit already reached "
                f"({self._last_usage_daily}/{self.DAILY_LIMIT})",
                usage={'fifteen_min': self._last_usage_fifteen, 'daily': self._last_usage_daily},
            )

    def _update_rate_limit_cache(self, response: requests.Response) -> tuple[int, int] | None:
        """Update cached usage from Strava response headers."""
        usage_header = response.headers.get('X-RateLimit-Usage', '')
        if usage_header:
            usage_parts = usage_header.split(',')
            if len(usage_parts) >= 2:
                try:
                    self._last_usage_fifteen = int(usage_parts[0])
                    self._last_usage_daily = int(usage_parts[1])
                    self._last_usage_at = time.monotonic()
                    return self._last_usage_fifteen, self._last_usage_daily
                except ValueError:
                    logger.debug("Unparseable X-RateLimit-Usage header: %s", usage_header)
        return None

    def __get(self, path: str, params: dict | None = None, guard: RateGuard = RateGuard.AT_LIMIT) -> requests.Response:
        """GET an API path with a valid token, recording the usage headers."""
        if guard is not RateGuard.RECORD:
            self._ensure_rate_limit_budget()
        response = self.__session.get(
            f"{StravaEndpoint.__API_BASE}{path}",
            headers=self.__get_headers(),
            params=params,
            timeout=self.__REQUEST_TIMEOUT,
        )
        if guard is RateGuard.AT_LIMIT:
            self._check_rate_limit(response)
            return response
        self._update_rate_limit_cache(response)
        if guard is RateGuard.ON_429 and response.status_code == 429:
            raise StravaRateLimitError("Strava API returned 429 Too Many Requests")
        return response

    def _check_rate_limit(self, response: requests.Response):
        """Update cached usage from the response headers, then raise if the
        response indicates the limit was reached."""
        usage = self._update_rate_limit_cache(response)
        if response.status_code == 429:
            raise StravaRateLimitError("Strava API returned 429 Too Many Requests")
        if usage:
            fifteen_usage, daily_usage = usage
            if fifteen_usage >= self.FIFTEEN_MIN_LIMIT or daily_usage >= self.DAILY_LIMIT:
                raise StravaRateLimitError(
                    f"Rate limit reached (15min: {fifteen_usage}/{self.FIFTEEN_MIN_LIMIT}, daily: {daily_usage}/{self.DAILY_LIMIT})",
                    usage={'fifteen_min': fifteen_usage, 'daily': daily_usage},
                )
    

    def __fetch_activities(self, page: int, per_page: int, from_date: datetime | None = None, to_date: datetime | None = None) -> list[dict]:
        activities = []
        while True:
            params = {
                "page": page,
                'per_page': per_page
            }

            logger.info("Fetching #%d activities from page %d...", per_page, page)

            if from_date:
                params['after'] = int(from_date.timestamp())
            if to_date:
                params['before'] = int(to_date.timestamp())

            response = self.__get('/athlete/activities', params, RateGuard.ON_429)
            if response.status_code != 200:
                logger.error("Failed to fetch activities: %s", response.text)
                return activities
            
            page_activities = response.json()

            if not page_activities:
                break

            activities.extend(page_activities)

            if len(page_activities) < per_page:
                break

            page += 1

        return activities

    def get_activities(self, from_date: datetime | None = None, to_date: datetime | None = None) -> list[dict]:
        """Summary activities from the Strava API (streams are fetched per activity, see get_activity_streams)."""
        return self.__fetch_activities(page=1, per_page=200, from_date=from_date, to_date=to_date)
    
    def get_athlete(self) -> dict:
        """Fetch athlete information from Strava API."""
        response = self.__get('/athlete', guard=RateGuard.RECORD)
        if response.status_code != 200:
            logger.error("Failed to fetch athlete info: %s", response.text)
            return {}

        return response.json()

    # Strava headers report 200/2000 but actually enforce 100/1000 for non-partner apps
    FIFTEEN_MIN_LIMIT = 100
    DAILY_LIMIT = 1000

    def get_rate_limits(self, refresh: bool = False) -> dict:
        """Return cached Strava API rate-limit status.

        When refresh=True, performs one /athlete request to seed/update the
        cache. The web UI should usually leave this False so status polling does
        not spend Strava quota.
        """
        if refresh:
            response = self.__get('/athlete', guard=RateGuard.RECORD)
            if response.status_code != 200:
                logger.error("Failed to refresh rate limits: %s", response.text)
        known = self._last_usage_at != 0.0
        return {
            'fifteen_min': {'limit': self.FIFTEEN_MIN_LIMIT, 'usage': self._last_usage_fifteen},
            'daily': {'limit': self.DAILY_LIMIT, 'usage': self._last_usage_daily},
            'known': known,
        }

    def get_athlete_zones(self) -> dict:
        """
        Get the authenticated athlete's heart rate and power zones.
        Returns zones configuration for heart rate and power.
        
        Endpoint: GET /athlete/zones
        """
        response = self.__get('/athlete/zones', guard=RateGuard.RECORD)
        if response.status_code != 200:
            logger.error("Failed to fetch athlete zones: %s", response.text)
            return {}
        
        return response.json()

    def get_activity_detail(self, activity_id: int | str) -> dict | None:
        """
        Fetch detailed info for a single activity (includes description, gear, etc.).
        """
        response = self.__get(f'/activities/{activity_id}')
        if response.status_code != 200:
            logger.error("Failed to fetch detail for activity %s: %s", activity_id, response.text)
            return None
        return response.json()

    def get_gear(self, gear_id: str) -> dict | None:
        """
        Fetch detailed info for a single gear item. Unlike /athlete, this also
        works for retired gear, which Strava omits from the profile response.
        """
        response = self.__get(f'/gear/{gear_id}')
        if response.status_code != 200:
            logger.error("Failed to fetch gear %s: %s", gear_id, response.text)
            return None
        return response.json()

    def get_activity_photos(self, activity_id: int | str, size: int = 600) -> list[dict]:
        """
        Fetch photos for a single activity.
        Returns a list of photo objects with URLs.
        """
        response = self.__get(f'/activities/{activity_id}/photos', {'photo_sources': 'true', 'size': size})
        if response.status_code != 200:
            logger.error("Failed to fetch photos for activity %s: %s", activity_id, response.text)
            return []
        return response.json()

    def get_activity_streams(self, activity_id: int | str) -> dict:
        """
        Fetch streams for a single activity.

        Returns a columnar dict like
            {time: [...], distance: [...], heartrate: [...], latlng: [[lat, lng], ...], ...}
        with all lists aligned. Empty dict when the activity has no streams.
        """
        from zone2.streams_store import from_strava_api

        response = self.__get(f'/activities/{activity_id}/streams', {
            'keys': 'time,latlng,altitude,velocity_smooth,heartrate,cadence,watts,distance',
            'key_by_type': 'true',
            'resolution': 'medium',
        })
        if response.status_code != 200:
            logger.error("Failed to fetch streams for activity %s: %s", activity_id, response.text)
            raise StravaStreamFetchError(
                f"streams fetch returned HTTP {response.status_code} for activity {activity_id}"
            )

        return from_strava_api(response.json())
    