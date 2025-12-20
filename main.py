from strava.strava_intelligence import StravaIntelligence
from pathlib import Path
from pprint import pprint


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
    
    strava_year_in_sport = strava_intelligence.get_year_in_sport(year=2025, main_sport='Run', comparison_year=2024)
    
    # get for 2024 
    strava_year_in_sport_2024 = strava_intelligence.get_year_in_sport(year=2024, main_sport='Run', neon_color="#00ffea")

    # get for 2023
    strava_year_in_sport_2023 = strava_intelligence.get_year_in_sport(year=2023, main_sport='Run', neon_color="#ff00f7")

    strava_intelligence.save_geojson_activities()
