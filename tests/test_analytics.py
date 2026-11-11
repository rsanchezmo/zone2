"""StravaAnalytics over an in-memory activities cache: records, race predictions,
weekly reports, training load, and the caches keyed by the activities' version."""
from datetime import datetime

import numpy as np
import pytest

from zone2.analytics import WeeklyReportFeatures as W
from zone2.utils import SportCategory
from tests.synthetic import ZONES, make_analytics, steady_stream


def activity(activity_id: int, sport_type: str, start: str, distance: float = 0.0, moving_time: int = 0,
             **extra) -> dict:
    return {"id": activity_id, "name": f"Activity {activity_id}", "sport_type": sport_type,
            "start_date_local": start, "distance": distance, "moving_time": moving_time,
            "total_elevation_gain": 0.0, "average_heartrate": None, "max_heartrate": 190, "workout_type": None,
            **extra}


def records_world() -> tuple[list[dict], dict[int, dict]]:
    rows = [
        activity(1, "Run", "2026-03-01T08:00:00Z", 8000, 2000),
        activity(2, "Run", "2026-04-01T08:00:00Z", 5500, 1100),
        # A walk faster than either run must not count as one
        activity(3, "Walk", "2026-04-02T08:00:00Z", 1800, 300),
        activity(4, "Ride", "2026-04-03T08:00:00Z", 21000, 2100),
    ]
    streams = {1: steady_stream(2001, 4.0), 2: steady_stream(1101, 5.0), 3: steady_stream(301, 6.0),
               4: steady_stream(2101, 10.0)}
    return rows, streams


def by_label(records: list[dict]) -> dict[str, tuple[float, int]]:
    return {r["label"]: (round(r["time_s"], 1), r["activity_id"]) for r in records}


# ── Personal records ─────────────────────────────────────────────────────

def test_personal_records_take_the_fastest_effort_per_sport():
    analytics, _ = make_analytics(*records_world())
    records = analytics.get_personal_records()
    assert by_label(records[SportCategory.RUNNING]) == {"400m": (80.0, 2), "1K": (200.0, 2), "5K": (1000.0, 2)}
    assert by_label(records[SportCategory.CYCLING]) == {"10K": (1000.0, 4), "20K": (2000.0, 4)}
    assert SportCategory.SWIMMING not in records


def test_a_tied_record_goes_to_the_earliest_activity():
    rows = [activity(6, "Run", "2026-05-02T08:00:00Z"), activity(5, "Run", "2026-05-01T08:00:00Z")]
    analytics, _ = make_analytics(rows, {5: steady_stream(301, 4.0), 6: steady_stream(301, 4.0)})
    assert {r["activity_id"] for r in analytics.get_personal_records()[SportCategory.RUNNING]} == {5}


def test_a_race_is_a_maximal_effort_at_its_own_distance_only():
    rows = [activity(7, "Run", "2026-06-07T09:00:00Z", 10000, 2500, workout_type=1),
            activity(8, "Run", "2026-06-14T09:00:00Z", 5000, 1250)]
    analytics, _ = make_analytics(rows, {7: steady_stream(2501, 4.0), 8: steady_stream(1251, 4.0)})

    def races() -> set[tuple[int, int]]:
        bests = analytics._get_per_activity_bests_df(SportCategory.RUNNING)
        flagged = bests[bests["is_race"]]
        return set(zip(flagged["activity_id"], flagged["distance_m"]))

    assert races() == {(7, 10000)}
    # A race from the race calendar, not flagged on Strava
    analytics.set_race_activity_ids(frozenset({8}))
    assert races() == {(7, 10000), (8, 5000)}


def test_recent_bests_keep_the_top_three_close_to_the_fastest_in_the_window():
    one_k_times = {"2026-10-01": 200, "2026-09-01": 210, "2026-08-01": 245, "2026-07-01": 260,
                   "2025-06-01": 190}   # the fastest is too old
    rows, streams = [], {}
    for i, (day, seconds) in enumerate(one_k_times.items()):
        rows.append(activity(i, "Run", f"{day}T08:00:00Z"))
        streams[i] = steady_stream(int(seconds * 1.05), 1000 / seconds)
    analytics, _ = make_analytics(rows, streams)
    recent = analytics._recent_best_efforts_list(SportCategory.RUNNING, end_date=datetime(2026, 11, 1))
    # 245 s is over 120% of the fastest 200 s, and 260 s isn't in the top three
    assert [(round(b["time_s"]), b["is_top1"]) for b in recent if b["distance_m"] == 1000] == [
        (200, True), (210, False),
    ]


# ── Caches keyed by the activities' version ──────────────────────────────

def best_effort_builds(cache) -> int:
    return sum(name.startswith("best_efforts") for name in cache.summary_names)


def test_best_efforts_are_built_once_per_cache_version():
    analytics, cache = make_analytics(*records_world())
    analytics.get_personal_records()
    analytics.get_personal_records()
    assert best_effort_builds(cache) == 3   # once per record sport
    cache.replace(cache.view, cache.streams)
    analytics.get_personal_records()
    assert best_effort_builds(cache) == 6


def test_changing_the_races_rebuilds():
    analytics, cache = make_analytics(*records_world())
    analytics.get_personal_records()
    assert analytics.set_race_activity_ids(frozenset({1})) is True
    assert analytics.set_race_activity_ids(frozenset({1})) is False
    analytics.get_personal_records()
    assert best_effort_builds(cache) == 6


def test_a_build_overtaken_by_a_sync_is_not_served_after_it():
    rows, streams = records_world()
    analytics, cache = make_analytics(rows, streams)
    cache.after_next_summaries = lambda: cache.replace(cache.view, {**streams, 2: steady_stream(1101, 5.5)})
    analytics.get_personal_records()   # built from the streams before the sync
    one_k = by_label(analytics.get_personal_records()[SportCategory.RUNNING])["1K"]
    assert one_k == (round(1000 / 5.5, 1), 2)


# ── HR zones ─────────────────────────────────────────────────────────────

def test_zones_estimated_from_max_heart_rate():
    analytics, _ = make_analytics([activity(1, "Run", "2026-01-01T08:00:00Z", max_heartrate=190)])
    assert [(z["min"], z["max"]) for z in analytics.get_hr_zones()] == [
        (0, 114), (114, 133), (133, 152), (152, 171), (171, 190),
    ]


def test_default_zone_bounds_are_exact_percentages():
    analytics, _ = make_analytics()
    assert [z["max"] for z in analytics._build_default_zones(180)] == [108, 126, 144, 162, 180]


# ── Race predictions ─────────────────────────────────────────────────────

def predictions_world() -> tuple[list[dict], dict[int, dict]]:
    """A 5K, a 10K and a half marathon race in the last weeks, one at a steady 4 m/s."""
    rows = [activity(41, "Run", "2026-10-04T09:00:00Z", 5100, 1275, workout_type=1),
            activity(42, "Run", "2026-10-11T09:00:00Z", 10100, 2525, workout_type=1),
            activity(43, "Run", "2026-10-18T09:00:00Z", 21200, 5300, workout_type=1)]
    streams = {41: steady_stream(1276, 4.0), 42: steady_stream(2526, 4.0), 43: steady_stream(5301, 4.0)}
    return rows, streams


def test_race_predictions_are_cached_per_day_and_rebuilt_on_new_races():
    analytics, _ = make_analytics(*predictions_world())
    result = analytics.get_race_predictions(SportCategory.RUNNING)
    assert result is analytics.get_race_predictions(SportCategory.RUNNING)
    assert result["data_quality"]["total_activities"] == 3
    assert result["race_day_calibration"]["n_races"] == 2   # the first race has nothing before it
    assert analytics.set_race_activity_ids(frozenset({41}))
    assert analytics.get_race_predictions(SportCategory.RUNNING) is not result


def test_each_race_is_calibrated_against_its_prediction_from_the_day_before():
    analytics, _ = make_analytics(*predictions_world())
    residuals = analytics._compute_race_residuals(SportCategory.RUNNING)
    # The first race has no efforts before it
    assert [str(day.date()) for day, _ in residuals] == ["2026-10-11", "2026-10-18"]
    assert analytics._compute_race_residuals(SportCategory.RUNNING) is residuals


# ── Weekly report and training load ──────────────────────────────────────

def test_weekly_report_covers_monday_to_sunday():
    rows = [
        activity(20, "Run", "2026-11-01T23:30:00Z", 5000, 1500),   # the Sunday before
        activity(21, "Run", "2026-11-02T07:00:00Z", 10000, 3000),
        activity(22, "Ride", "2026-11-05T18:00:00Z", 30000, 3600),
        activity(23, "Run", "2026-11-08T23:30:00Z", 5000, 1500),
        activity(24, "Run", "2026-11-09T06:00:00Z", 8000, 2400),   # the Monday after
    ]
    streams = {21: {"time": list(range(100)), "heartrate": [130] * 50 + [150] * 50}}
    analytics, _ = make_analytics(rows, streams)

    report = analytics.get_weekly_report("2026-11-05", hr_zones=ZONES)
    assert (report[W.WEEK_START], report[W.WEEK_END]) == ("2026-11-02", "2026-11-08")
    assert report[W.TOTAL_ACTIVITIES] == 3
    assert report[W.TOTAL_DISTANCE_KM] == 45.0
    assert report[W.TOTAL_TIME_HOURS] == 2.25
    assert report[W.ACTIVITIES_PER_DAY] == {0: 1, 1: 0, 2: 0, 3: 1, 4: 0, 5: 0, 6: 1}
    assert report[W.DISTANCE_PER_SPORT_KM] == {"Run": 15.0, "Ride": 30.0}
    assert report[W.HR_ZONE_DISTRIBUTION] == {1: 0.0, 2: 50.0, 3: 50.0, 4: 0.0, 5: 0.0}
    assert report[W.LONGEST_ACTIVITY_KM] == 30.0

    # A week cut at Wednesday, to compare with one still running
    partial = analytics.get_weekly_report("2026-11-02", cutoff_date="2026-11-04", hr_zones=ZONES)
    assert (partial[W.WEEK_END], partial[W.TOTAL_ACTIVITIES], partial[W.TOTAL_DISTANCE_KM]) == ("2026-11-04", 1, 10.0)


def test_daily_training_load():
    rows = [
        # An hour halfway between resting (50) and max HR (190), without streams
        activity(30, "Run", "2026-10-10T08:00:00Z", 10000, 3600, average_heartrate=120),
        # Half an hour all in Z2, from its HR stream
        activity(31, "Run", "2026-10-10T18:00:00Z", 6000, 1800, average_heartrate=130),
    ]
    analytics, _ = make_analytics(rows, {31: {"time": list(range(1800)), "heartrate": [130] * 1800}})
    [day] = analytics.get_daily_training_load(hr_rest=50, hr_zones=ZONES)
    assert day["date"] == "2026-10-10"
    banister = round(60 * 0.5 * 0.64 * np.exp(1.92 * 0.5), 1)
    assert {a["trimp_method"]: a["trimp"] for a in day["activities"]} == {"banister": banister,
                                                                         "zone_weighted": 30 * 1.1}
    assert day["trimp"] == pytest.approx(banister + 33.0)
