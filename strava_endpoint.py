from datetime import datetime
import os
from dotenv import load_dotenv
from pydantic import BaseModel
import requests
import webbrowser
from pathlib import Path
import json

load_dotenv()

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

    __ACTIVITIES_URL = 'https://www.strava.com/api/v3/athlete/activities'
    __ATHLETE_URL = 'https://www.strava.com/api/v3/athlete'
    __ATHLETES_URL = 'https://www.strava.com/api/v3/athletes'
    __OAUTH_TOKEN_URL = 'https://www.strava.com/oauth/token'
    __OAUTH_AUTHORIZE_URL = 'https://www.strava.com/oauth/authorize'
    __TOKEN_FILENAME = 'token.json'

    def __init__(self, cache_dir: Path = Path("./.strava")):
        self.__STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
        self.__STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
        self.__token_data = None

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

        auth_url = (
            f"{StravaEndpoint.__OAUTH_AUTHORIZE_URL}?"
            f"client_id={self.__STRAVA_CLIENT_ID}&"
            f"response_type=code&"
            f"redirect_uri=http://localhost/exchange_token&"
            f"scope=activity:read_all"
        )
        webbrowser.open(auth_url)
        authorization_code = input("Enter the authorization code from the URL: ")
        
        response = requests.post(
            StravaEndpoint.__OAUTH_TOKEN_URL,
            data={
                'client_id': self.__STRAVA_CLIENT_ID,
                'client_secret': self.__STRAVA_CLIENT_SECRET,
                'code': authorization_code,
                'grant_type': 'authorization_code'
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.json()}")
        
        token_data = response.json()
        
        token = StravaTokenData(**token_data)

        token.to_file(self.__cache_dir / StravaEndpoint.__TOKEN_FILENAME)

        return token
    
    def __refresh_token(self) -> StravaTokenData:
        """Refresh OAuth token using the refresh token."""
        response = requests.post(
            StravaEndpoint.__OAUTH_TOKEN_URL,
            data={
                'client_id': self.__STRAVA_CLIENT_ID,
                'client_secret': self.__STRAVA_CLIENT_SECRET,
                'grant_type': 'refresh_token',
                'refresh_token': self.__token_data.refresh_token
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.json()}")
        
        token_data = response.json()
        
        token = StravaTokenData(**token_data)

        token.to_file(self.__cache_dir / StravaEndpoint.__TOKEN_FILENAME)

        return token
    
    def __get_valid_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self.__token_data.is_expired():
            self.__token_data = self.__refresh_token()
        return self.__token_data.access_token

    def __authenticate(self):
        self.__token_data = self.__get_initial_token()

        if self.__token_data.is_expired():
            self.__token_data = self.__refresh_token()

    def __get_headers(self) -> dict[str, str]:
        access_token = self.__get_valid_token()
        return {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
    

    def __fetch_activities(self, page: int, per_page: int, from_date: datetime | None = None, to_date: datetime | None = None) -> list[dict]:
        headers = self.__get_headers()

        activities = []
        while True:
        
            params = {
                "page": page,
                'per_page': per_page
            }

            print(f"Fetching #{per_page} activities from page {page}...")
            
            if from_date:
                params['after'] = int(from_date.timestamp())
            if to_date:
                params['before'] = int(to_date.timestamp())
            
            response = requests.get(StravaEndpoint.__ACTIVITIES_URL, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"Failed to fetch activities: {response.json()}")
                return activities
            
            page_activities = response.json()

            if not page_activities:
                break

            activities.extend(page_activities)
            page += 1

        return activities

    def get_activities(self, from_date: datetime | None = None, to_date: datetime | None = None, sports: list[str] | None = None) -> list[dict]:
        """Fetch activities from Strava API."""

        activities = self.__fetch_activities(page=1, per_page=200, from_date=from_date, to_date=to_date)

        # Filter by sports if provided
        if sports:
            activities = [activity for activity in activities if activity.get('type') in sports]
        
        return activities

    def get_athlete(self) -> dict:
        """Fetch athlete information from Strava API."""
        headers = self.__get_headers()
        
        response = requests.get(StravaEndpoint.__ATHLETE_URL, headers=headers)
        
        if response.status_code != 200:
            raise Exception(f"Failed to fetch athlete info: {response.json()}")
        
        return response.json()
    

    def get_athlete_stats(self) -> dict:
        """Fetch athlete stats from Strava API, Only includes data from activities set to Everyone visibilty."""
        headers = self.__get_headers()
        
        response = requests.get(f"{StravaEndpoint.__ATHLETES_URL}/{self.__STRAVA_CLIENT_ID}/stats", headers=headers)

        if response.status_code != 200:
            if response.reason == "Forbidden":
                return {}
        
            raise Exception(f"Failed to fetch athlete stats: {response.json()}")
        return response.json()