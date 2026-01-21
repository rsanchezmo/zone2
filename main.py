from strava.strava_intelligence import StravaIntelligence
from pathlib import Path


if __name__ == "__main__":

    strava_intelligence = StravaIntelligence(workdir=Path("./strava_intelligence_workdir"))
    # strava_intelligence.ensure_activities_with_streams()

    strava_intelligence.plot_last_activity(sport_type='Run')

    strava_intelligence.strava_visualizer.thunderstorm_heatmap(
        sport_types=['Run'], location="paris", radius_km=20.0, add_basemap=False, show_title=False
    )

    # strava_intelligence.strava_visualizer.thunderstorm_heatmap(
    #     sport_types=['Run'], location="paris", radius_km=20.0, add_basemap=False, show_title=False
    # )

    # strava_intelligence.strava_visualizer.activity_clock(
    #     sport_types=['Run'], show_title=False
    # )

    # strava_intelligence.strava_visualizer.hud_dashboard(
    #     sport_type='Run'
    # )   

    # strava_intelligence.strava_visualizer.activity_bubble_map(
    #     sport_types=['Run'], region="europe")

    weekly_data = strava_intelligence.get_weekly_report()
    weekly_data = strava_intelligence.get_weekly_report(week_start_date="2026-01-14")
    
    strava_year_in_sport = strava_intelligence.get_year_in_sport(year=2026, 
                                                                 main_sport='Run', 
                                                                 comparison_year=2025, 
                                                                 neon_color="#de0606", 
                                                                 comparison_neon_color="#91ffe9")
    
    strava_intelligence.save_geojson_activities()
