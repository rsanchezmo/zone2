"""The race-prediction engine as pure functions over made-up best efforts."""
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from zone2.best_efforts import BESTS_COLUMNS, BestEffort, rank_bests
from zone2.race_predictions import (
    Calibration, RaceResult, apply_calibration, compute_predictions, fit_fade, predict_races, prediction_history,
    race_calibration, race_distance, race_residuals, race_results, training_paces, weighted_quantile,
)
from zone2.utils import FadeVerdict, SportCategory, predicted_time_from_vdot, vdot_from_time_distance

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def effort(distance_m: int, time_s: float, date: str = "2026-11-01T12:00:00+00:00", **extra) -> BestEffort:
    return {"distance_m": distance_m, "time_s": time_s, "activity_id": distance_m, "activity_name": "Run",
            "date": date, "is_top1": True, "is_race": False, "avg_hr": None, **extra}


def on_riegel_curve(distance_m: int, exponent: float, **extra) -> BestEffort:
    """An effort on a Riegel curve through a 20:00 5K."""
    return effort(distance_m, 1200 * (distance_m / 5000) ** exponent, date="2026-10-01", **extra)


def predicted(core_predictions: list, distance_m: int) -> dict:
    return next(p for p in core_predictions if p["distance_m"] == distance_m)


# ── Fade ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("exponent, verdict", [
    (1.02, FadeVerdict.HOLDS_PACE), (1.06, FadeVerdict.TYPICAL), (1.10, FadeVerdict.FADES),
])
def test_fade_verdict(exponent, verdict):
    fade = fit_fade([on_riegel_curve(d, exponent) for d in (5000, 10000, 21097)], [1.0] * 3)
    assert (fade["exponent"], fade["stderr"], fade["verdict"]) == (exponent, 0.0, verdict)


def test_fade_ignores_efforts_under_three_minutes():
    efforts = [on_riegel_curve(d, 1.06) for d in (5000, 10000, 21097)] + [{**on_riegel_curve(400, 1.06), "time_s": 60.0}]
    assert fit_fade(efforts, [1.0] * 4)["exponent"] == 1.06


def test_fade_needs_three_weighted_distances_spanning_double():
    assert fit_fade([on_riegel_curve(d, 1.06) for d in (5000, 10000)], [1.0] * 2) is None
    assert fit_fade([on_riegel_curve(d, 1.06) for d in (5000, 6000, 8000)], [1.0] * 3) is None
    assert fit_fade([on_riegel_curve(d, 1.06) for d in (5000, 10000, 21097)], [0.0] * 3) is None


def test_each_distance_weighs_once_however_many_efforts_it_has():
    efforts = ([on_riegel_curve(5000, 1.06, activity_id=i) for i in range(4)]
               + [on_riegel_curve(d, 1.06) for d in (10000, 21097)])
    shares: dict[int, float] = {}
    for anchor in fit_fade(efforts, [1.0] * 6)["anchors"]:
        shares[anchor["distance_m"]] = shares.get(anchor["distance_m"], 0.0) + anchor["weight_share"]
    assert shares == pytest.approx({5000: 1 / 3, 10000: 1 / 3, 21097: 1 / 3}, abs=0.002)


# ── Predictions ──────────────────────────────────────────────────────────

DANIELS_VDOT_50 = {5000: 19 * 60 + 57, 10000: 41 * 60 + 21, 21097: 3600 + 31 * 60 + 35, 42195: 3 * 3600 + 10 * 60 + 49}


def test_predictions_for_a_runner_on_daniels_vdot_50_table():
    recent = [effort(d, float(DANIELS_VDOT_50[d]), date="2026-10-25T09:00:00+00:00", is_race=True)
              for d in (5000, 10000, 21097)]
    core = compute_predictions(recent, SportCategory.RUNNING, NOW, hr_max=190)
    assert core["athlete_vdot"] == pytest.approx(50, abs=0.2)
    for distance_m, time_s in DANIELS_VDOT_50.items():
        assert predicted(core["predictions"], distance_m)["predicted_time_s"] == pytest.approx(time_s, rel=0.02)
    times = [p["predicted_time_s"] for p in core["predictions"]]
    assert times == sorted(times)
    # The raw band can miss the central by a little; calibration, even without
    # races to learn from, widens it to hold it
    apply_calibration(core["predictions"], {"factor": 1.0, "band_low_mult": None, "band_high_mult": None,
                                            "n_races": 0})
    for p in core["predictions"]:
        assert p["predicted_time_low_s"] <= p["predicted_time_s"] <= p["predicted_time_high_s"]


def test_no_recent_efforts_predict_nothing():
    core = compute_predictions([], SportCategory.RUNNING, NOW, hr_max=190)
    assert {p["predicted_time_s"] for p in core["predictions"]} == {None}
    assert core["athlete_vdot"] is None and core["fade"] is None


def test_one_effort_projects_by_riegel_at_the_typical_exponent():
    core = compute_predictions([effort(10000, 1000.0)], SportCategory.CYCLING, NOW, hr_max=0)
    ten, twenty, forty = (predicted(core["predictions"], d) for d in (10000, 20000, 40000))
    assert (ten["source"], ten["pr_time_s"], ten["predicted_time_s"]) == ("personal_record", 1000.0, 1000.0)
    assert twenty["source"] == "predicted"
    assert twenty["predicted_time_s"] == round(1000 * 2 ** 1.06, 1)
    assert forty["predicted_time_s"] == round(1000 * 4 ** 1.06, 1)
    # One sample: no spread to make a band of
    assert twenty["predicted_time_low_s"] == twenty["predicted_time_high_s"] == twenty["predicted_time_s"]
    assert twenty["models"] == {"riegel": round(1000 * 2 ** 1.06, 1)}
    assert (core["athlete_vdot"], core["fitted_exponent"], core["fade"]) == (None, None, None)


def ten_k_central(training: BestEffort, hr_max: float = 200) -> float:
    """The 10K central from a 1000 s race and a 1100 s training 10K."""
    race = effort(10000, 1000.0, is_race=True)
    core = compute_predictions([race, training], SportCategory.CYCLING, NOW, hr_max=hr_max)
    return predicted(core["predictions"], 10000)["predicted_time_s"]


def test_anchors_weigh_by_race_intensity_and_age():
    # A race counts 1.5 times an effort without HR
    assert ten_k_central(effort(10000, 1100.0, is_top1=False)) == 1040.0
    # 70% of max HR is half way from the 55% floor to full weight at 85%
    assert ten_k_central(effort(10000, 1100.0, is_top1=False, avg_hr=140.0)) == pytest.approx(1025.0, abs=0.05)
    # Easier than that weighs the 0.4 floor
    assert ten_k_central(effort(10000, 1100.0, is_top1=False, avg_hr=100.0)) == round((1500 + 1100 * 0.4) / 1.9, 1)
    # 90 days old: half the weight
    old = effort(10000, 1100.0, date="2026-08-03T12:00:00+00:00", is_top1=False)
    w = math.exp(-0.693)
    assert ten_k_central(old) == pytest.approx((1500 + 1100 * w) / (1.5 + w), abs=0.05)


def test_vdot_takes_seventy_percent_of_a_running_central():
    core = compute_predictions([effort(5000, 1200.0)], SportCategory.RUNNING, NOW, hr_max=0)
    five_k = predicted(core["predictions"], 5000)
    vdot_time = predicted_time_from_vdot(vdot_from_time_distance(1200.0, 5000), 5000)
    assert five_k["models"] == {"riegel": 1200.0, "vdot": vdot_time}
    assert five_k["predicted_time_s"] == pytest.approx(0.3 * 1200.0 + 0.7 * vdot_time, abs=0.05)
    assert core["athlete_vdot"] == vdot_from_time_distance(1200.0, 5000)


def test_weighted_quantile():
    values = [3.0, 1.0, 4.0, 1.5, 9.0, 2.6]
    for q in (0.25, 0.5, 0.75):
        expected = np.percentile(values, q * 100, method="hazen")
        assert weighted_quantile(values, [1.0] * len(values), q) == pytest.approx(expected)
    assert weighted_quantile([1.0, 2.0, 3.0], [1, 1, 4], 0.5) > weighted_quantile([1.0, 2.0, 3.0], [1, 1, 1], 0.5)
    assert weighted_quantile([], [], 0.5) == 0.0


# ── Races and calibration ────────────────────────────────────────────────

def test_a_race_counts_as_the_standard_distance_its_gps_reaches():
    assert race_distance(16300, SportCategory.RUNNING) == 15000   # a 10-mile race
    assert race_distance(10050, SportCategory.RUNNING) == 10000
    assert race_distance(21300, SportCategory.RUNNING) == 21097
    assert race_distance(11500, SportCategory.RUNNING) is None    # 15% over the 10K
    assert race_distance(9900, SportCategory.RUNNING) is None     # short of the 10K
    assert race_distance(10000, SportCategory.WALKING) is None


def best(activity_id: int, day: str, distance_m: int, time_s: float, is_race: bool = False) -> dict:
    return {"activity_id": activity_id, "activity_name": "Ride", "date": pd.Timestamp(day, tz="UTC"),
            "distance_m": distance_m, "time_s": time_s, "is_race": is_race, "avg_hr": None}


def test_race_results_take_each_races_own_effort_at_its_distance():
    races = pd.DataFrame({"id": [7, 8, 9], "distance": [10400.0, 30000.0, 20100.0],
                          "start_date_local": pd.to_datetime(["2026-06-01", "2026-07-01", "2026-08-01"], utc=True)})
    bests = pd.DataFrame([best(7, "2026-06-01", 10000, 950.0), best(9, "2026-08-01", 10000, 940.0)],
                         columns=BESTS_COLUMNS)
    # 30 km isn't a standard distance; race 9's 20K effort is missing
    assert race_results(races, bests, SportCategory.CYCLING) == [
        RaceResult(pd.Timestamp("2026-06-01", tz="UTC"), 10000, 950.0),
    ]


def test_each_race_is_predicted_from_the_efforts_before_it():
    ranked = rank_bests(pd.DataFrame([best(1, "2026-05-01", 10000, 1000.0),
                                      best(2, "2026-06-01T09:00", 10000, 950.0, is_race=True),
                                      best(3, "2025-01-01T09:00", 10000, 900.0, is_race=True)],
                                     columns=BESTS_COLUMNS))
    races = [RaceResult(pd.Timestamp("2026-06-01T09:00", tz="UTC"), 10000, 950.0),
             RaceResult(pd.Timestamp("2025-01-01T09:00", tz="UTC"), 10000, 900.0)]
    # The 2025 race has nothing in the year before it, and the June one doesn't see itself
    assert race_residuals(races, ranked, SportCategory.CYCLING, hr_max=0) == [
        (pd.Timestamp("2026-06-01T09:00", tz="UTC"), 0.95),
    ]


def calibration(residuals: list[tuple[str, float]], reference: str = "2026-11-01") -> Calibration:
    return race_calibration([(pd.Timestamp(day, tz="UTC"), ratio) for day, ratio in residuals],
                            pd.Timestamp(reference, tz="UTC"))


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
    # A naive reference date is UTC
    assert race_calibration([(pd.Timestamp("2026-05-01", tz="UTC"), 0.97)], datetime(2026, 11, 1))["n_races"] == 1


def test_apply_calibration():
    unbanded = [{"predicted_time_s": 1000.0, "predicted_time_low_s": 980.0, "predicted_time_high_s": 1030.0},
                {"predicted_time_s": None}]
    apply_calibration(unbanded, {"factor": 0.98, "band_low_mult": None, "band_high_mult": None, "n_races": 0})
    assert unbanded == [{"predicted_time_s": 980.0, "predicted_time_low_s": 960.4, "predicted_time_high_s": 1009.4},
                        {"predicted_time_s": None}]
    banded = [{"predicted_time_s": 1000.0, "predicted_time_low_s": 990.0, "predicted_time_high_s": 1010.0}]
    apply_calibration(banded, {"factor": 0.98, "band_low_mult": 0.97, "band_high_mult": 1.01, "n_races": 3})
    assert banded == [{"predicted_time_s": 980.0, "predicted_time_low_s": 970.0, "predicted_time_high_s": 1010.0}]


def test_training_paces_come_from_the_predicted_5k_to_half():
    predictions = [{"distance_m": d, "predicted_time_s": float(t)} for d, t in DANIELS_VDOT_50.items()]
    paces = training_paces(predictions)
    vdots = [vdot_from_time_distance(DANIELS_VDOT_50[d], d) for d in (5000, 10000, 21097)]
    assert paces["vdot"] == round(sum(vdots) / 3, 1)
    assert [p["zone"] for p in paces["paces"]] == ["E", "M", "T", "I", "R"]
    assert training_paces([{"distance_m": 42195, "predicted_time_s": 11449.0}]) is None


# ── Assembled predictions and their history ──────────────────────────────

def ranked_runs(*rows: tuple[int, str, int, float]):
    return rank_bests(pd.DataFrame(
        [{**best(i, day, d, t), "activity_name": "Run"} for i, day, d, t in rows], columns=BESTS_COLUMNS,
    ))


def test_predictions_warn_about_thin_inputs_and_extrapolation():
    ranked = ranked_runs((1, "2026-10-20", 5000, 1200.0))
    garmin = {"date": "2026-10-31", "time5K": 1190, "time10K": None, "timeHalfMarathon": None, "timeMarathon": None}
    result = predict_races(ranked, [], SportCategory.RUNNING, NOW, hr_max=0, garmin=garmin, total_activities=42)
    assert result["confidence"] == "low"
    assert result["data_quality"] == {
        "total_activities": 42, "prs_available": 1, "recent_prs": 1, "sufficient": False, "window_days": 365,
        "warnings": [
            "Only 1 distinct recent best effort(s) in the last 52 weeks — personalized Riegel not fit; "
            "predictions extrapolated from limited inputs",
            "10K, 15K, 20K, Half Marathon, Marathon prediction extrapolates well beyond the longest recent "
            "effort (5.0 km) — treat with caution",
        ],
    }
    assert result["race_day_calibration"] == {"factor": 1.0, "n_races": 0, "band_low_mult": None,
                                              "band_high_mult": None}
    assert predicted(result["predictions"], 5000)["garmin_time_s"] == 1190.0
    assert "garmin_time_s" not in predicted(result["predictions"], 10000)
    assert result["training_paces"] is not None and result["fade"] is None


def test_cycling_predictions_say_what_they_lack():
    result = predict_races(ranked_runs(), [], SportCategory.CYCLING, NOW, hr_max=0, garmin=None, total_activities=0)
    assert result["confidence"] == "low"
    assert result["data_quality"]["warnings"] == [
        "No cycling efforts in the last 52 weeks — predictions unavailable",
        "Cycling predictions use a time/distance Riegel model — for power-based athletes a critical-power "
        "curve would be more accurate",
    ]
    assert result["training_paces"] is None


def test_history_starts_at_the_first_step_with_enough_distances_then_leaves_gaps():
    ranked = ranked_runs((1, "2026-10-14T08:00", 5000, 1200.0), (2, "2026-10-15T08:00", 10000, 2500.0),
                         (3, "2026-10-16T08:00", 21097, 5600.0))
    history = prediction_history(ranked, [], SportCategory.RUNNING, NOW, hr_max=0, weeks=4, step_days=7,
                                 window_days=10)
    assert [(p["end_date"], p["n_inputs"]) for p in history] == [
        ("2026-10-18", 3), ("2026-10-25", 1), ("2026-11-01", 0),
    ]
    assert all(p["predicted_time_s"] for p in history[0]["predictions"])
    for gap in history[1:]:
        assert gap["athlete_vdot"] is None
        assert {p["predicted_time_s"] for p in gap["predictions"]} == {None}
    assert prediction_history(ranked, [], SportCategory.WALKING, NOW, 0, 4, 7, 10) == []
