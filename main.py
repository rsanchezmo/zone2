from strava.strava_intelligence import StravaIntelligence
from pathlib import Path


if __name__ == "__main__":

    strava_intelligence = StravaIntelligence(workdir=Path("./strava_intelligence_workdir"))


    strava_intelligence.strava_visualizer.thunderstorm_heatmap(
        sport_types=['Run'], location="paris", radius_km=20.0, add_basemap=False, show_title=False
    )
    strava_intelligence.strava_visualizer.activity_clock(
        sport_types=['Run'], show_title=False
    )

    strava_intelligence.strava_visualizer.hud_dashboard(
        sport_types=['Run']
    )   

    strava_intelligence.strava_visualizer.plot_efficiency_factor(
        sport_types=['Run']
    )

    strava_intelligence.strava_visualizer.plot_performance_frontier(
        sport_types=['Run']
    )

    strava_intelligence.strava_visualizer.activity_bubble_map(
        sport_types=['Run'], region="europe")

    strava_intelligence.save_geojson_activities()
