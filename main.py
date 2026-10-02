from zone2.core import Zone2
from pathlib import Path


if __name__ == "__main__":

    workdir = Path("./zone2_workdir")
    z2 = Zone2(workdir=workdir, sync_max_age_hours=3)

    # # get the heatmap in amsterdam
    z2.strava_visualizer.thunderstorm_heatmap(
        location="Amsterdam, Netherlands",
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
