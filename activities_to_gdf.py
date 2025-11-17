import geopandas as gpd
from shapely.geometry import LineString
import polyline

def get_activities_as_gdf(activities: list[dict]) -> gpd.GeoDataFrame:
    """Convert a list of Strava activities to a GeoDataFrame with LineString geometries."""
    features = []
    for activity in activities:
        if 'map' in activity and 'summary_polyline' in activity['map']:
            encoded_polyline = activity['map']['summary_polyline']
            decoded_points = polyline.decode(encoded_polyline, geojson=True)
            line = LineString(decoded_points)

            feature = {
                'geometry': line,
            }
            feature.update(
                activity
            )
                
            features.append(feature)
    
    if not features:
        return gpd.GeoDataFrame(columns=['geometry'], crs="EPSG:4326")
    
    return gpd.GeoDataFrame(features, crs="EPSG:4326")