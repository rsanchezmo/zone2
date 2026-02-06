import geopandas as gpd
from shapely.geometry import LineString, Polygon, box
import polyline
import pandas as pd
import json

from strava.constants import BASE_CRS


# Sport category sets for reuse across functions
CYCLING_SPORTS = {'ride', 'virtualride', 'ebikeride', 'handcycle', 'velomobile', 
                  'gravel ride', 'gravelride', 'mountain bike ride', 'mountainbikeride'}
SWIMMING_SPORTS = {'swim', 'openwater swim', 'openwaterswim'}
RUNNING_SPORTS = {'run', 'trailrun', 'trail run', 'virtualrun', 'treadmill'}


def get_sport_category(sport_type: str | None) -> str:
    """
    Determine the sport category from sport type.
    
    Args:
        sport_type: Strava sport type (e.g., 'Run', 'Ride', 'Swim')
    
    Returns:
        Category string: 'cycling', 'swimming', or 'running' (default)
    """
    sport_type = sport_type or ""
    sport_lower = sport_type.lower()
    
    if any(cycle in sport_lower for cycle in CYCLING_SPORTS):
        return 'cycling'
    elif any(swim in sport_lower for swim in SWIMMING_SPORTS):
        return 'swimming'
    else:
        return 'running'


def convert_speed(speed_ms: float, sport_type: str | None = None) -> tuple[float, str]:
    """
    Convert speed from m/s to sport-appropriate unit.
    
    Args:
        speed_ms: Speed in m/s from Strava API
        sport_type: Strava sport type (e.g., 'Run', 'Ride', 'Swim')
    
    Returns:
        Tuple of (converted_value, unit_label):
        - Running sports: (pace in min/km, "min/km")
        - Cycling sports: (speed in km/h, "km/h")
        - Swimming sports: (pace in min/100m, "min/100m")
    """
    if speed_ms <= 0:
        return (0.0, "N/A")
    
    category = get_sport_category(sport_type)
    
    if category == 'swimming':
        # Swimming: pace per 100m (in minutes)
        pace_min_per_100m = (100 / speed_ms) / 60
        return (pace_min_per_100m, "min/100m")
    
    elif category == 'cycling':
        # Cycling: speed in km/h
        speed_kmh = speed_ms * 3.6
        return (speed_kmh, "km/h")
    
    else:
        # Running and other sports: pace per km (in minutes)
        pace_min_per_km = 1000 / (60 * speed_ms)
        return (pace_min_per_km, "min/km")


def format_pace_or_speed(avg_speed: float, sport_type: str | None = None) -> str:
    """
    Format pace or speed based on the sport type.
    
    Args:
        avg_speed: Average speed in m/s from Strava API
        sport_type: Strava sport type (e.g., 'Run', 'Ride', 'Swim', 'TrailRun', etc.)
    
    Returns:
        Formatted string:
        - Running sports: pace in min:sec /km (e.g., "5:30 /km")
        - Cycling sports: speed in km/h (e.g., "25.3 km/h")
        - Swimming sports: pace in min:sec /100m (e.g., "1:45 /100m")
        - Other sports: pace in min:sec /km (default)
    """
    if avg_speed <= 0:
        return "N/A"
    
    category = get_sport_category(sport_type)
    
    if category == 'swimming':
        # Swimming: pace per 100m
        pace_sec_per_100m = 100 / avg_speed  # seconds per 100m
        pace_mins = int(pace_sec_per_100m // 60)
        pace_secs = round(pace_sec_per_100m % 60)
        if pace_secs == 60:
            pace_mins += 1
            pace_secs = 0
        return f"{pace_mins}:{pace_secs:02d} /100m"
    
    elif category == 'cycling':
        # Cycling: speed in km/h
        speed_kmh = avg_speed * 3.6  # m/s to km/h
        return f"{speed_kmh:.1f} km/h"
    
    else:
        # Running and other sports: pace per km (default)
        pace_min_per_km = 1000 / (60 * avg_speed)
        pace_mins = int(pace_min_per_km)
        pace_secs = round((pace_min_per_km % 1) * 60)
        if pace_secs == 60:
            pace_mins += 1
            pace_secs = 0
        return f"{pace_mins}:{pace_secs:02d} /km"


def get_activities_as_gdf(activities: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert a pd.Dataframes with strava activities to a GeoDataFrame with LineString geometries."""
    
    # Drop activities without map data
    activities = activities.dropna(subset=['map'])

    # Parse polylines into LineString geometries
    def _parse_map(map_activity):
        # Handle JSON string from Parquet deserialization
        if isinstance(map_activity, str):
            try:
                map_activity = json.loads(map_activity)
            except json.JSONDecodeError:
                return None
        
        if isinstance(map_activity, dict) and 'summary_polyline' in map_activity and map_activity['summary_polyline'] != "":
            encoded_polyline = map_activity['summary_polyline']
            decoded_points = polyline.decode(encoded_polyline, geojson=True)
            return LineString(decoded_points)
        return None
    
    activities['geometry'] = activities['map'].apply(_parse_map)
    activities = activities.dropna(subset=['geometry'])

    if activities.empty:
        return gpd.GeoDataFrame(geometry=[], crs=BASE_CRS)
    
    return gpd.GeoDataFrame(activities, geometry='geometry', crs=BASE_CRS)  


def get_activities_as_gdf_from_streams(activities: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert activities to a GeoDataFrame using high-resolution GPS streams (lat/lng).

    Falls back to summary_polyline for activities without cached streams.
    """
    activities = activities.copy()

    def _parse_streams(row):
        streams = row.get('streams')
        if streams is not None:
            if isinstance(streams, str):
                try:
                    streams = json.loads(streams)
                except json.JSONDecodeError:
                    streams = None

            if isinstance(streams, list) and len(streams) >= 2:
                coords = [(pt['lng'], pt['lat']) for pt in streams
                          if 'lat' in pt and 'lng' in pt]
                if len(coords) >= 2:
                    return LineString(coords)

        # Fallback to summary polyline
        map_data = row.get('map')
        if map_data is not None:
            if isinstance(map_data, str):
                try:
                    map_data = json.loads(map_data)
                except json.JSONDecodeError:
                    return None
            if isinstance(map_data, dict) and map_data.get('summary_polyline'):
                decoded = polyline.decode(map_data['summary_polyline'], geojson=True)
                return LineString(decoded)
        return None

    activities['geometry'] = activities.apply(_parse_streams, axis=1)
    activities = activities.dropna(subset=['geometry'])

    if activities.empty:
        return gpd.GeoDataFrame(geometry=[], crs=BASE_CRS)

    return gpd.GeoDataFrame(activities, geometry='geometry', crs=BASE_CRS)


def vo2_max(hr_max: float, hr_rest: float) -> float:
    """
    Calculate VO2 Max based on Uth-Sørensen-Overgaard-Pedersen estimation:
        VO2 Max = 15.3 x (HR_max / HR_rest)
    """
    return 15.3 * (hr_max / hr_rest)

def get_region_coordinates(region_name: str) -> dict | None:
    """
    Get the latitude and longitude of a city using OSM Nominatim API.
    """
    import requests

    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'agent'}
    params = {
        'q': region_name,
        'format': 'json',
        'limit': 1
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    if data:
        lat = float(data[0]['lat'])
        lon = float(data[0]['lon'])
        bbox = data[0]['boundingbox']
        min_lat, max_lat = float(bbox[0]), float(bbox[1])
        min_lon, max_lon = float(bbox[2]), float(bbox[3])
        bbox_polygon = box(min_lon, min_lat, max_lon, max_lat)
        return {'lat': lat, 'lon': lon, 'boundingbox': bbox_polygon}
    
    return None
