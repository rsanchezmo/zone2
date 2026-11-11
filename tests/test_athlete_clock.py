"""The athlete's clock: today and the current week in the athlete's time zone (from their latest
activity), whatever zone the server runs in. Activities are made up."""
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from zone2.activities_cache import StravaActivitiesCache
from zone2.analytics import StravaAnalytics
from zone2.clock import Clock, zone_from_strava
from tests.synthetic import FakeActivitiesCache, FakeUserCache, activities_frame

PARIS = ZoneInfo("Europe/Paris")
# Monday 9 Nov 2026, 00:30 in Paris: still Sunday in UTC
MONDAY_JUST_AFTER_MIDNIGHT = datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)


def test_strava_timezones_name_their_zone():
    assert zone_from_strava("(GMT+01:00) Europe/Paris") == PARIS
    assert zone_from_strava("(GMT-08:00) America/Los_Angeles") == ZoneInfo("America/Los_Angeles")
    assert zone_from_strava("(GMT+01:00) Nowhere/Atlantis") is None
    assert zone_from_strava(None) is None


def test_today_is_the_athletes_not_the_servers():
    clock = Clock(lambda: PARIS, lambda: MONDAY_JUST_AFTER_MIDNIGHT)
    assert clock.today() == date(2026, 11, 9)
    # Labelled UTC like start_date_local, so it compares with activity times directly
    assert clock.now() == datetime(2026, 11, 9, 0, 30, tzinfo=timezone.utc)


def test_the_athletes_zone_is_their_latest_activitys(tmp_path: Path):
    cache = StravaActivitiesCache(tmp_path / "activities", tmp_path / "streams", tmp_path / "metadata.json")
    assert cache.latest_zone() is None
    cache.save_activities([
        {"id": 1, "name": "Synthetic 1", "sport_type": "Run", "distance": 5000.0, "utc_offset": -28800.0,
         "start_date": "2026-10-01T15:00:00Z", "start_date_local": "2026-10-01T08:00:00Z",
         "timezone": "(GMT-08:00) America/Los_Angeles"},
        {"id": 2, "name": "Synthetic 2", "sport_type": "Run", "distance": 5000.0, "utc_offset": 3600.0,
         "start_date": "2026-11-05T07:00:00Z", "start_date_local": "2026-11-05T08:00:00Z",
         "timezone": "(GMT+01:00) Europe/Paris"},
        # A manual entry without a zone doesn't move the athlete
        {"id": 3, "name": "Synthetic 3", "sport_type": "Run", "distance": 5000.0,
         "start_date": "2026-11-06T07:00:00Z", "start_date_local": "2026-11-06T08:00:00Z"},
    ])
    assert cache.latest_zone() == PARIS


def test_the_current_weekly_report_turns_over_at_the_athletes_midnight():
    rows = [
        {"id": 1, "sport_type": "Run", "name": "Sunday long run", "start_date_local": "2026-11-08T10:00:00Z",
         "distance": 15000.0, "moving_time": 4500, "total_elevation_gain": 50.0},
    ]
    cache = FakeActivitiesCache(activities_frame(rows))
    clock = Clock(lambda: PARIS, lambda: MONDAY_JUST_AFTER_MIDNIGHT)
    analytics = StravaAnalytics(cache, FakeUserCache(), clock=clock)  # type: ignore[arg-type]
    report = analytics.get_weekly_report(None, hr_zones=[])
    assert (report["week_start"], report["week_end"]) == ("2026-11-09", "2026-11-15")
    assert report["total_activities"] == 0
