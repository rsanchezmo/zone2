"""StravaAnalytics over an in-memory activities cache: records, race predictions,
weekly reports, training load, and the caches keyed by the activities' version."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from zone2.analytics import StravaAnalytics, WeeklyReportFeatures as W, _weighted_quantile
from zone2.utils import FadeVerdict, SportCategory
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

def effort(distance_m: int, exponent: float, **extra) -> dict:
    """An effort on a Riegel curve through a 20:00 5K."""
    return {"distance_m": distance_m, "time_s": 1200 * (distance_m / 5000) ** exponent, "date": "2026-10-01",
            "activity_id": distance_m, "activity_name": "Run", "is_race": False, **extra}


@pytest.mark.parametrize("exponent, verdict", [
    (1.02, FadeVerdict.HOLDS_PACE), (1.06, FadeVerdict.TYPICAL), (1.10, FadeVerdict.FADES),
])
def test_fade_verdict(exponent, verdict):
    analytics, _ = make_analytics()
    fade = analytics._fit_fade([effort(d, exponent) for d in (5000, 10000, 21097)], [1.0] * 3)
    assert (fade["exponent"], fade["stderr"], fade["verdict"]) == (exponent, 0.0, verdict)


def test_fade_ignores_efforts_under_three_minutes():
    analytics, _ = make_analytics()
    efforts = [effort(d, 1.06) for d in (5000, 10000, 21097)] + [{**effort(400, 1.06), "time_s": 60.0}]
    assert analytics._fit_fade(efforts, [1.0] * 4)["exponent"] == 1.06


def test_fade_needs_three_weighted_distances_spanning_double():
    analytics, _ = make_analytics()
    assert analytics._fit_fade([effort(d, 1.06) for d in (5000, 10000)], [1.0] * 2) is None
    assert analytics._fit_fade([effort(d, 1.06) for d in (5000, 6000, 8000)], [1.0] * 3) is None
    assert analytics._fit_fade([effort(d, 1.06) for d in (5000, 10000, 21097)], [0.0] * 3) is None


def test_each_distance_weighs_once_however_many_efforts_it_has():
    analytics, _ = make_analytics()
    efforts = [effort(5000, 1.06, activity_id=i) for i in range(4)] + [effort(d, 1.06) for d in (10000, 21097)]
    shares: dict[int, float] = {}
    for anchor in analytics._fit_fade(efforts, [1.0] * 6)["anchors"]:
        shares[anchor["distance_m"]] = shares.get(anchor["distance_m"], 0.0) + anchor["weight_share"]
    assert shares == pytest.approx({5000: 1 / 3, 10000: 1 / 3, 21097: 1 / 3}, abs=0.002)


DANIELS_VDOT_50 = {5000: 19 * 60 + 57, 10000: 41 * 60 + 21, 21097: 3600 + 31 * 60 + 35, 42195: 3 * 3600 + 10 * 60 + 49}


def test_predictions_for_a_runner_on_daniels_vdot_50_table():
    analytics, _ = make_analytics([activity(1, "Run", "2026-01-01T08:00:00Z")])
    recent = [{"distance_m": d, "time_s": float(DANIELS_VDOT_50[d]), "date": "2026-10-25T09:00:00+00:00",
               "activity_id": d, "activity_name": "Race", "is_race": True, "is_top1": True, "avg_hr": None}
              for d in (5000, 10000, 21097)]
    core = analytics._compute_predictions(recent, SportCategory.RUNNING,
                                          reference_date=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert core["athlete_vdot"] == pytest.approx(50, abs=0.2)
    predicted = {p["distance_m"]: p for p in core["predictions"]}
    for distance_m, time_s in DANIELS_VDOT_50.items():
        assert predicted[distance_m]["predicted_time_s"] == pytest.approx(time_s, rel=0.02)
    times = [p["predicted_time_s"] for p in core["predictions"]]
    assert times == sorted(times)
    # The raw band can miss the central by a little; calibration, even without
    # races to learn from, widens it to hold it
    StravaAnalytics._apply_calibration(core["predictions"], {"factor": 1.0, "band_low_mult": None,
                                                             "band_high_mult": None})
    for p in core["predictions"]:
        assert p["predicted_time_low_s"] <= p["predicted_time_s"] <= p["predicted_time_high_s"]


def test_no_recent_efforts_predict_nothing():
    analytics, _ = make_analytics([activity(1, "Run", "2026-01-01T08:00:00Z")])
    core = analytics._compute_predictions([], SportCategory.RUNNING)
    assert {p["predicted_time_s"] for p in core["predictions"]} == {None}
    assert core["athlete_vdot"] is None and core["fade"] is None


def calibration(residuals: list[tuple[str, float]], reference: str = "2026-11-01") -> dict:
    analytics, _ = make_analytics()
    analytics._compute_race_residuals = lambda sport_category: [
        (pd.Timestamp(day, tz="UTC"), ratio) for day, ratio in residuals
    ]
    return analytics._race_calibration(SportCategory.RUNNING, pd.Timestamp(reference, tz="UTC"))


def test_calibration_needs_three_races():
    assert calibration([("2026-05-01", 0.97), ("2026-06-01", 0.98)]) == {
        "factor": 1.0, "band_low_mult": None, "band_high_mult": None, "n_races": 2,
    }


def test_calibration_is_the_median_race_residual_clamped():
    cal = calibration([("2026-05-01", 0.97), ("2026-06-01", 0.98), ("2026-07-01", 0.99)])
    assert (cal["factor"], cal["band_low_mult"], cal["band_high_mult"]) == pytest.approx((0.98, 0.975, 0.985))
    cal = calibration([("2026-05-01", 0.90), ("2026-06-01", 0.91), ("2026-07-01", 0.92)])
    # The band still holds the clamped factor
    assert (cal["factor"], cal["band_low_mult"], cal["band_high_mult"]) == pytest.approx((0.95, 0.905, 0.95))


def test_calibration_learns_only_from_earlier_races():
    cal = calibration([("2026-05-01", 0.97), ("2026-06-01", 0.98), ("2026-11-01", 0.90), ("2026-11-20", 0.90)])
    assert (cal["n_races"], cal["factor"]) == (2, 1.0)


def test_apply_calibration():
    unbanded = [{"predicted_time_s": 1000.0, "predicted_time_low_s": 980.0, "predicted_time_high_s": 1030.0},
                {"predicted_time_s": None}]
    StravaAnalytics._apply_calibration(unbanded, {"factor": 0.98, "band_low_mult": None, "band_high_mult": None})
    assert unbanded == [{"predicted_time_s": 980.0, "predicted_time_low_s": 960.4, "predicted_time_high_s": 1009.4},
                        {"predicted_time_s": None}]
    banded = [{"predicted_time_s": 1000.0, "predicted_time_low_s": 990.0, "predicted_time_high_s": 1010.0}]
    StravaAnalytics._apply_calibration(banded, {"factor": 0.98, "band_low_mult": 0.97, "band_high_mult": 1.01})
    assert banded == [{"predicted_time_s": 980.0, "predicted_time_low_s": 970.0, "predicted_time_high_s": 1010.0}]


def test_weighted_quantile():
    values = [3.0, 1.0, 4.0, 1.5, 9.0, 2.6]
    for q in (0.25, 0.5, 0.75):
        expected = np.percentile(values, q * 100, method="hazen")
        assert _weighted_quantile(values, [1.0] * len(values), q) == pytest.approx(expected)
    assert _weighted_quantile([1.0, 2.0, 3.0], [1, 1, 4], 0.5) > _weighted_quantile([1.0, 2.0, 3.0], [1, 1, 1], 0.5)
    assert _weighted_quantile([], [], 0.5) == 0.0


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
