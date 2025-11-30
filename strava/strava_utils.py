import geopandas as gpd
from shapely.geometry import LineString, Polygon, box
import polyline
import pandas as pd
import json

from strava.constants import BASE_CRS


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
