"""Execution scoring of planned sessions against what was done."""
import pytest

from backend.scoring import (
    _avg_speed_from_points, _compute_hr_zone_pct, _score_distance, _score_pace, compute_execution_score,
    has_targets, match_activity, slice_streams_by_segments,
)
from tests.synthetic import ZONES, stream_from_speeds


def test_match_activity_picks_the_closest_of_the_same_sport():
    acts = [{"id": 1, "sport_type": "Run", "distance_km": 5.0, "moving_time": 1500},
            {"id": 2, "sport_type": "Run", "distance_km": 12.0, "moving_time": 3600},
            {"id": 3, "sport_type": "Ride", "distance_km": 10.0, "moving_time": 1200}]
    assert match_activity({"sport_type": "Run", "planned_distance_km": 10}, acts)["id"] == 2
    assert match_activity({"sport_type": "Run", "planned_duration_mins": 30}, acts)["id"] == 1
    assert match_activity({"sport_type": "Ride"}, acts)["id"] == 3
    assert match_activity({"sport_type": "Swim"}, acts) is None


def test_a_session_is_done_by_any_type_of_its_sport():
    trail = {"id": 1, "sport_type": "TrailRun", "distance_km": 12.0}
    treadmill = {"id": 2, "sport_type": "VirtualRun", "distance_km": 8.0}
    gravel = {"id": 3, "sport_type": "GravelRide", "distance_km": 40.0}
    assert match_activity({"sport_type": "Run"}, [trail])["id"] == 1
    assert match_activity({"sport_type": "Run", "planned_distance_km": 8}, [trail, treadmill])["id"] == 2
    assert match_activity({"sport_type": "Ride"}, [trail, gravel])["id"] == 3


def test_the_planned_type_wins_over_another_of_its_sport():
    road = {"id": 1, "sport_type": "Run", "distance_km": 10.0}
    treadmill = {"id": 2, "sport_type": "VirtualRun", "distance_km": 10.0}
    assert match_activity({"sport_type": "VirtualRun"}, [road, treadmill])["id"] == 2
    assert match_activity({"sport_type": "Run", "planned_distance_km": 9.9}, [treadmill, road])["id"] == 1


def test_a_sport_is_not_done_by_another():
    assert match_activity({"sport_type": "Run"}, [{"id": 1, "sport_type": "Walk"}, {"id": 2, "sport_type": "Hike"}]) is None
    assert match_activity({"sport_type": "Walk"}, [{"id": 1, "sport_type": "Run"}]) is None
    # Gym and racket sports share a category for display only: each is its own sport
    assert match_activity({"sport_type": "WeightTraining"}, [{"id": 1, "sport_type": "Workout"}]) is None
    assert match_activity({"sport_type": "Squash"}, [{"id": 1, "sport_type": "Padel"}]) is None
    assert match_activity({"sport_type": "Kayaking"}, [{"id": 1, "sport_type": "Rowing"}]) is None
    assert match_activity({"sport_type": "Football"}, [{"id": 1, "sport_type": "Golf"}]) is None


def test_score_distance():
    cases = [(10, 10), (10, 9), (10, 11), (10, 35), (0, 5)]
    assert [_score_distance(target, actual)["score"] for target, actual in cases] == [100, 90, 90, 0, 0]


def test_score_pace_against_a_range():
    # Inside the range, either way round
    assert _score_pace(4.0, 4.5, 4.2, "min/km")["score"] == 100
    assert _score_pace(4.5, 4.0, 4.2, "min/km")["score"] == 100
    # 5% off a pace bound costs twice as much as 5% off a speed bound
    assert _score_pace(4.0, 4.5, 4.725, "min/km")["score"] == 90
    assert _score_pace(30.0, 35.0, 36.75, "km/h")["score"] == 95
    # One-sided target, and none
    assert _score_pace(None, 5.0, 4.0, "min/km")["score"] == 100
    assert _score_pace(None, None, 4.0, "min/km")["score"] == 0


def test_hr_zone_share_counts_edges_once_and_skips_missing_samples():
    streams = {"heartrate": [130, 140, 150, 159, 160, 0, None]}
    assert _compute_hr_zone_pct(streams, 3, ZONES) == 60.0   # 140, 150, 159 of five valid
    assert _compute_hr_zone_pct(streams, 6, ZONES) is None
    assert _compute_hr_zone_pct({"heartrate": [0, None]}, 2, ZONES) is None


def test_average_speed_excludes_stops():
    rep = stream_from_speeds([4.0] * 100 + [0.0] * 60 + [4.0] * 101)
    assert _avg_speed_from_points(rep) == pytest.approx(4.0)


def test_unsegmented_score_averages_its_targets():
    session = {"sport_type": "Run", "planned_distance_km": 10, "planned_duration_mins": 50, "target_avg_pace": 5.0}
    activity = {"id": 7, "sport_type": "Run", "distance_km": 9.5, "moving_time": 3000, "average_speed": 1000 / 300}
    result = compute_execution_score(session, activity)
    assert {k: m["score"] for k, m in result["metrics"].items()} == {"distance": 95, "duration": 100, "avg_pace": 100}
    assert result["overall_score"] == 98
    assert result["matched_activity_id"] == 7


def test_unsegmented_ride_pace_is_scored_as_speed():
    session = {"sport_type": "Ride", "target_pace_min": 30, "target_pace_max": 35}
    result = compute_execution_score(session, {"id": 1, "sport_type": "Ride", "average_speed": 9.0})
    assert result["metrics"]["pace"] == {"target_min": 30, "target_max": 35, "actual": 32.4, "score": 100,
                                         "unit": "km/h"}


def test_sequential_segments_slice_by_distance():
    run = stream_from_speeds([4.0] * 1251)   # 5 km
    segments = [{"type": "warmup", "distance_km": 1}, {"type": "work", "distance_km": 3}, {"type": "cooldown"}]
    slices = slice_streams_by_segments(run, segments)
    covered = [s["points"]["distance"][-1] - s["points"]["distance"][0] for s in slices]
    assert [s["segment_idx"] for s in slices] == [0, 1, 2]
    assert covered[:2] == pytest.approx([1000, 3000])
    # The open cool-down takes the rest
    assert slices[-1]["points"]["distance"][-1] == 5000


INTERVALS = [
    {"type": "warmup", "distance_km": 1.0},
    {"type": "work", "distance_km": 0.4, "repetitions": 4, "recovery_duration_mins": 1.5,
     "target_pace_min": 3.25, "target_pace_max": 3.4},
    {"type": "cooldown", "distance_km": 1.2},
]


def intervals_run() -> dict:
    """1 km warm-up, 4 × (400 m at 5 m/s, 90 s jog), 1.2 km cool-down."""
    speeds = [3.0] * 334 + ([5.0] * 80 + [2.5] * 90) * 3 + [5.0] * 80 + [3.0] * 400
    return stream_from_speeds(speeds, [130] * len(speeds))


def test_interval_reps_are_found_by_speed():
    slices = slice_streams_by_segments(intervals_run(), INTERVALS)
    work = [s for s in slices if s["segment_idx"] == 1 and not s["is_recovery"]]
    recoveries = [s for s in slices if s["is_recovery"]]
    assert [s["rep"] for s in work] == [1, 2, 3, 4]
    assert len(recoveries) == 3
    for s in work:
        assert s["points"]["distance"][-1] - s["points"]["distance"][0] == pytest.approx(400, rel=0.02)


def test_a_well_executed_interval_session_scores_full_marks():
    result = compute_execution_score({"sport_type": "Run", "segments": INTERVALS}, {"id": 1}, ZONES, intervals_run())
    assert result["mode"] == "segmented"
    assert result["overall_score"] == 100
    paces = [s["actual_pace"] for s in result["segment_scores"] if s["type"] == "work"]
    assert paces == pytest.approx([1000 / 300] * 4, abs=0.01)   # 3:20 /km


def test_has_targets():
    assert not has_targets({"sport_type": "Run"})
    assert has_targets({"sport_type": "Run", "target_hr_zone": 2})
    assert has_targets({"sport_type": "Run", "segments": [{"type": "work"}]})
