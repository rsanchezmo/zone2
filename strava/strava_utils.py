import geopandas as gpd
from shapely.geometry import LineString, Polygon, box
import polyline
import pandas as pd
import json

from strava.constants import BASE_CRS


# Sport category sets for reuse across functions (lowercase for matching)
CYCLING_SPORTS = {
    'ride', 'virtualride', 'ebikeride', 'handcycle', 'velomobile',
    'gravelride', 'mountainbikeride', 'emountainbikeride', 'rollerski',
}
SWIMMING_SPORTS = {'swim'}
RUNNING_SPORTS = {'run', 'trailrun', 'virtualrun', 'walk', 'hike', 'snowshoe'}
WATER_SPORTS = {'canoeing', 'standuppaddling', 'kayaking', 'surfing', 'kitesurf', 'rowing', 'windsurf', 'sail'}
SPEED_SPORTS = {
    'squash', 'tennis', 'pickleball', 'racquetball', 'badminton', 'tabletennis', 'padel',
    'weighttraining', 'workout', 'yoga', 'pilates', 'crossfit', 'highintensityintervaltraining',
    'elliptical', 'stairstepper', 'dance', 'rockclimbing', 'alpineski', 'backcountryski',
    'nordicski', 'snowboard', 'iceskate', 'inlineskate', 'skateboard',
    'soccer', 'basketball', 'volleyball', 'cricket', 'golf',
}


def get_sport_category(sport_type: str | None) -> str:
    """
    Determine the sport category from sport type.

    Args:
        sport_type: Strava sport type (e.g., 'Run', 'Ride', 'Swim')

    Returns:
        Category string: 'cycling', 'swimming', 'water', 'speed', or 'running' (default)
    """
    sport_type = sport_type or ""
    sport_lower = sport_type.lower().replace(' ', '')

    if sport_lower in CYCLING_SPORTS:
        return 'cycling'
    elif sport_lower in SWIMMING_SPORTS:
        return 'swimming'
    elif sport_lower in WATER_SPORTS:
        return 'water'
    elif sport_lower in SPEED_SPORTS:
        return 'speed'
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

    elif category in ('cycling', 'water', 'speed'):
        # Cycling, water & speed sports: speed in km/h
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
    
    elif category in ('cycling', 'water', 'speed'):
        # Cycling, water & speed sports: speed in km/h
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

    # Parse polylines into LineString geometries. The `map` column may arrive
    # as either a dict (already-decoded view from analytics) or a JSON string
    # (raw from parquet via cache.load_activities). Handle both.
    def _parse_map(map_activity):
        if isinstance(map_activity, str):
            try:
                map_activity = json.loads(map_activity)
            except (json.JSONDecodeError, TypeError):
                return None
        if isinstance(map_activity, dict) and map_activity.get('summary_polyline'):
            decoded_points = polyline.decode(map_activity['summary_polyline'], geojson=True)
            return LineString(decoded_points)
        return None

    activities['geometry'] = activities['map'].apply(_parse_map)
    activities = activities.dropna(subset=['geometry'])

    if activities.empty:
        return gpd.GeoDataFrame(geometry=[], crs=BASE_CRS)

    return gpd.GeoDataFrame(activities, geometry='geometry', crs=BASE_CRS)


def get_activities_as_gdf_from_streams(activities: pd.DataFrame, streams_store=None) -> gpd.GeoDataFrame:
    """Convert activities to a GeoDataFrame using high-resolution GPS streams (lat/lng).

    Falls back to summary_polyline for activities without cached streams.
    `streams_store` is a StreamsStore (typically `cache.streams`). If omitted,
    only summary polylines are used.
    """
    activities = activities.copy()

    streams_map = {}
    if streams_store is not None and 'id' in activities.columns:
        streams_map = streams_store.get_many(activities['id'].astype('int64').tolist())

    def _parse_streams(row):
        aid = int(row['id']) if row.get('id') is not None else None
        streams = streams_map.get(aid) if aid is not None else None
        if isinstance(streams, dict):
            latlng = streams.get('latlng')
            if latlng and len(latlng) >= 2:
                coords = [(ll[1], ll[0]) for ll in latlng
                          if ll is not None and len(ll) == 2 and ll[0] is not None and ll[1] is not None]
                if len(coords) >= 2:
                    return LineString(coords)

        # Fallback to summary polyline
        map_data = row.get('map')
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


# ── Advanced analytics helpers ─────────────────────────────────────

import math
import numpy as np


def vdot_from_time_distance(time_s: float, distance_m: float) -> float | None:
    """Compute Jack Daniels VDOT from race time and distance.

    Uses the closed-form approximation from Daniels' Running Formula.
    Returns None for invalid inputs or efforts shorter than 3 minutes.
    """
    if time_s <= 0 or distance_m <= 0 or time_s < 180:
        return None
    t = time_s / 60.0  # minutes
    v = distance_m / t  # m/min
    # Oxygen cost
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v * v
    # Fraction of VO2max sustained
    pct_vo2max = 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)
    if pct_vo2max <= 0:
        return None
    vdot = vo2 / pct_vo2max
    if vdot <= 0:
        return None
    return round(vdot, 2)


def predicted_time_from_vdot(vdot: float, distance_m: float) -> float | None:
    """Predict race time (seconds) for a distance given a VDOT value.

    Uses bisection search to invert vdot_from_time_distance.
    VDOT decreases as time increases (slower effort = lower VDOT).
    Returns None if no convergence.
    """
    if vdot <= 0 or distance_m <= 0:
        return None
    # Estimate a reasonable search range based on speed
    # VDOT 30 ~ 3.5 m/s running, VDOT 85 ~ 6.5 m/s
    lo = max(180.0, distance_m / 7.0)    # fastest plausible
    hi = min(86400.0, distance_m / 0.5)  # slowest plausible
    if lo >= hi:
        lo, hi = 180.0, 86400.0

    for _ in range(100):
        mid = (lo + hi) / 2.0
        est = vdot_from_time_distance(mid, distance_m)
        if est is None:
            # Formula invalid here — narrow from both sides toward the valid region
            est_lo = vdot_from_time_distance(lo, distance_m)
            if est_lo is None:
                lo = lo + (hi - lo) * 0.1
            else:
                hi = mid
            continue
        if est > vdot:
            lo = mid  # too fast, need more time
        else:
            hi = mid  # too slow, need less time
        if hi - lo < 0.5:
            break
    result = (lo + hi) / 2.0
    check = vdot_from_time_distance(result, distance_m)
    if check is None or abs(check - vdot) > 1.0:
        return None
    return round(result, 1)


def riegel_predict(t1_s: float, d1_m: float, d2_m: float, exponent: float = 1.06) -> float:
    """Predict race time using Riegel's formula: t2 = t1 * (d2/d1)^exponent."""
    return t1_s * (d2_m / d1_m) ** exponent


def fit_riegel_exponent(prs: list[dict]) -> float | None:
    """Fit a personalized Riegel exponent from personal records.

    Each PR dict must have 'distance_m' and 'time_s' keys.
    Returns None if fewer than 3 PRs.
    """
    if len(prs) < 3:
        return None
    distances = np.array([pr['distance_m'] for pr in prs])
    times = np.array([pr['time_s'] for pr in prs])
    # log(t) = exponent * log(d) + c
    coeffs = np.polyfit(np.log(distances), np.log(times), 1)
    exponent = float(coeffs[0])
    # Sanity check: exponent should be roughly 1.0-1.2
    if exponent < 0.8 or exponent > 1.5:
        return None
    return round(exponent, 4)


def compute_trimp_banister(duration_min: float, avg_hr: float, hr_rest: float, hr_max: float, gender: str = 'male') -> float:
    """Compute Banister TRIMP from average HR and duration.

    Uses gender-specific exponential weighting.
    """
    if hr_max <= hr_rest or avg_hr < hr_rest:
        return 0.0
    delta = (avg_hr - hr_rest) / (hr_max - hr_rest)
    delta = max(0.0, min(delta, 1.0))
    if gender == 'female':
        return duration_min * delta * 0.86 * math.exp(1.67 * delta)
    return duration_min * delta * 0.64 * math.exp(1.92 * delta)


def compute_trimp_zone_weighted(time_in_zones_min: list[float], zone_weights: list[float] | None = None) -> float:
    """Compute zone-weighted TRIMP using Lucia's weights.

    Args:
        time_in_zones_min: Time spent in each zone (5 zones expected).
        zone_weights: Optional custom weights per zone.
    """
    if zone_weights is None:
        zone_weights = [1.0, 1.1, 1.5, 2.2, 4.5]
    return sum(t * w for t, w in zip(time_in_zones_min, zone_weights))


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
