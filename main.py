# Importing the settings loads the project's .env
from backend.config import settings
from zone2.core import Zone2


if __name__ == "__main__":

    z2 = Zone2(workdir=settings.workdir, data_dir=settings.data_dir, sync_max_age_hours=3)

    # # get the heatmap of a city
    z2.strava_visualizer.thunderstorm_heatmap(
        location="Paris, France",
        sport_types=["Run"],
        show_title=False,
    )


    weekly_data = z2.get_weekly_report()
    # z2.get_weekly_report('2026-02-11')

    strava_year_in_sport = z2.get_year_in_sport(
        year=2026,
        main_sport='Run',
        comparison_year=2025,
        neon_color="#de0606",
        comparison_neon_color="#91ffe9",
    )
    
    # z2.save_gpkg_activities()
