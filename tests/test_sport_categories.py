"""The coach's year in sport counts a sport category, like its other tools: every run type is
running, walks and hikes never are. Activities are made up."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.agent import tools
from backend.services.stats_cache import clear_stats_cache
from zone2.clock import Clock
from zone2.utils import SportCategory, format_pace_or_speed
from tests.synthetic import make_analytics


def test_year_stats_counts_every_run_type_and_no_walks():
    rows = [
        {"id": i, "sport_type": sport, "name": f"Synthetic {i}", "start_date_local": f"2025-0{i}-01T08:00:00Z",
         "distance": km * 1000.0, "moving_time": 3000, "total_elevation_gain": 10.0, "average_speed": 3.0}
        for i, (sport, km) in enumerate([("Run", 10), ("TrailRun", 12), ("VirtualRun", 5), ("Walk", 4),
                                         ("Hike", 9), ("Ride", 40)], start=1)
    ]
    analytics, cache = make_analytics(rows)
    noon = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    z2 = SimpleNamespace(strava_activities_cache=cache, strava_analytics=analytics,
                         clock=Clock(lambda: timezone.utc, lambda: noon))
    ctx = SimpleNamespace(deps=SimpleNamespace(z2=z2))
    clear_stats_cache()

    running = asyncio.run(tools.year_stats(ctx, year=2025))["running"]
    assert (running["total_activities"], running["total_distance_km"]) == (3, 27.0)
    walking = asyncio.run(tools.year_stats(ctx, year=2025, sport=SportCategory.WALKING))["walking"]
    assert walking["total_activities"] == 2
    cycling = asyncio.run(tools.year_stats(ctx, year=2025, sport=SportCategory.CYCLING))["cycling"]
    assert cycling["fastest_activity_pace"] == "10.8 km/h"


def test_a_category_formats_in_its_own_unit():
    assert format_pace_or_speed(10.0, SportCategory.CYCLING) == format_pace_or_speed(10.0, "Ride")
    assert format_pace_or_speed(1.0, SportCategory.SWIMMING) == format_pace_or_speed(1.0, "Swim")
