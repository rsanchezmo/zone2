from strava.strava_intelligence import StravaIntelligence
from strava.strava_map_matching import StravaMapMatcher
from pathlib import Path

from strava.strava_utils import get_activities_as_gdf, get_activities_as_gdf_from_streams


if __name__ == "__main__":

    workdir = Path("./strava_intelligence_workdir")
    strava_intelligence = StravaIntelligence(workdir=workdir, sync_max_age_hours=3)

    # # get the heatmap of a city
    strava_intelligence.strava_visualizer.thunderstorm_heatmap(
        location="Paris, France",
        sport_types=["Run"],
        show_title=False,
    )


    # # --- Map matching ---
    # strava_map_matcher = StravaMapMatcher(
    #     city_name="Paris, France",
    #     workdir=workdir,
    #     force_reload=False,
    # )
    
    # activities_gdf = get_activities_as_gdf_from_streams(
    #     strava_intelligence.strava_activities_cache.activities
    # )
    
    # # get a dataframe with the activity id == 1234567890
    # # activities_gdf = activities_gdf[activities_gdf["id"] == 1234567890]

    # # filter activities for only runs
    # activities_gdf = activities_gdf[activities_gdf["type"] == "Run"]

    # matched_gdf, match_details = strava_map_matcher.match(activities_gdf)
    
    # # Save matched routes (real OSM edge geometries)
    # if not matched_gdf.empty:
    #     matched_gdf.to_file(
    #         strava_map_matcher.workdir / "matched_activities.gpkg", driver="GPKG"
    #     )
    
    # # Inspect per-activity matching details
    # # create the dir 
    # (workdir / 'city').mkdir(parents=True, exist_ok=True)
    # for activity_id, result in match_details.items():
    #     print(f"\nActivity {activity_id} — quality: {result.quality}")
    #     result.plot(save_path=workdir / 'city' / f"map_match_{activity_id}.png")

    # # --- Coverage analysis ---
    # strava_map_matcher.plot_coverage(
    #     match_details,
    #     save_path=workdir / "osm_maps" / "coverage.png",
    # )

    weekly_data = strava_intelligence.get_weekly_report()
    # strava_intelligence.get_weekly_report('2026-02-11')

    strava_year_in_sport = strava_intelligence.get_year_in_sport(
        year=2026,
        main_sport='Run',
        comparison_year=2025,
        neon_color="#de0606",
        comparison_neon_color="#91ffe9",
    )
    
    # strava_intelligence.save_gpkg_activities()
