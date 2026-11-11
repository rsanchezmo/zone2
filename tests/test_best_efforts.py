"""The sliding-window best efforts behind personal records and race predictions."""
import math

import pytest

from zone2.analytics import StravaAnalytics
from zone2.utils import SportCategory
from tests.synthetic import stream_from_speeds

RUN_MAX_SPEED = StravaAnalytics.MAX_SPEED_MS[SportCategory.RUNNING]
RIDE_MAX_SPEED = StravaAnalytics.MAX_SPEED_MS[SportCategory.CYCLING]
SWIM_MAX_SPEED = StravaAnalytics.MAX_SPEED_MS[SportCategory.SWIMMING]


def best_efforts(streams: dict, targets: list[int], max_speed: float = RUN_MAX_SPEED) -> dict[int, float]:
    return StravaAnalytics._best_effort_times(streams["distance"], streams["time"], targets, max_speed)


def test_steady_run():
    run = stream_from_speeds([4.0] * 1301)   # 5.2 km at 4:10 /km
    assert best_efforts(run, [400, 1000, 5000]) == {400: 100.0, 1000: 250.0, 5000: 1250.0}


def test_sparse_samples_are_interpolated_not_charged_whole():
    # A sample every 10 s, 40 m apart: the 1000 m mark falls between two
    sparse = {"time": [10 * i for i in range(81)], "distance": [40.0 * i for i in range(81)]}
    assert best_efforts(sparse, [1000]) == {1000: 250.0}


def test_fastest_stretch_inside_a_slower_run():
    run = stream_from_speeds([3.0] * 300 + [5.0] * 300 + [3.0] * 300)
    assert best_efforts(run, [1000])[1000] == pytest.approx(200.0)


def test_distances_longer_than_the_activity_are_absent():
    assert best_efforts(stream_from_speeds([4.0] * 200), [400, 1000, 5000]) == {400: 100.0}


def test_rests_between_reps_are_not_stitched_out():
    # 400 m, 2 min standing, 400 m: the best 800 m includes the rest
    reps = stream_from_speeds([5.0] * 80 + [0.0] * 120 + [5.0] * 81)
    assert best_efforts(reps, [400, 800]) == {400: 80.0, 800: 280.0}


def test_gps_jumps_faster_than_humanly_possible_are_ignored():
    # 500 m in one sample, in a run at 4 m/s
    run = stream_from_speeds([4.0] * 500 + [500.0] + [4.0] * 500)
    assert best_efforts(run, [1000]) == {1000: 250.0}


def test_a_jump_between_sparse_samples_is_ignored():
    # A sample every 5 s, 20 m apart, one of them 300 m too far
    steps = [20.0] * 120
    steps[60] += 300.0
    sparse = {"time": [5 * i for i in range(121)], "distance": [sum(steps[:i]) for i in range(121)]}
    assert best_efforts(sparse, [1000]) == {1000: 250.0}


def test_a_jump_ahead_then_a_stall_until_the_runner_catches_up_credits_nothing():
    run = stream_from_speeds([4.0] * 300 + [500.0] + [0.0] * 125 + [4.0] * 300)
    efforts = best_efforts(run, [1000, 2000])
    assert efforts[1000] == 250.0
    # Every 2K takes in the stall: never faster than the runner went
    assert efforts[2000] >= 2000 / 4.0


def test_a_pool_length_credited_after_the_rest_is_ignored():
    # Swimming at 1 m/s, the watch counts the last length only after 30 s at the wall
    swim = stream_from_speeds([1.0] * 150 + [0.0] * 30 + [25.0] + [1.0] * 150)
    assert best_efforts(swim, [100], SWIM_MAX_SPEED) == {100: 100.0}


def test_the_drive_home_after_a_forgotten_stop_is_not_a_run():
    run = stream_from_speeds([4.0] * 300 + [12.0] * 600)
    assert best_efforts(run, [1000, 5000]) == {1000: 250.0}


def test_whole_second_timestamps_leave_a_fast_effort_untouched():
    # A sample every 1.5 s at 6 m/s, stamped to the second: every other one reads 9 m/s
    times = [math.floor(1.5 * i + 0.5) for i in range(301)]
    reps = {"time": times, "distance": [9.0 * i for i in range(301)]}
    efforts = best_efforts(reps, [400, 1000])
    assert efforts == best_efforts(reps, [400, 1000], max_speed=math.inf)
    assert efforts[1000] == pytest.approx(1000 / 6.0, abs=1.0)


def test_a_signal_gap_counts_at_its_average_speed():
    # 60 s without samples in a tunnel, 240 m further on: 4 m/s as everywhere else
    times = list(range(200)) + list(range(260, 460))
    tunnel = {"time": times, "distance": [4.0 * t for t in times]}
    assert best_efforts(tunnel, [1000]) == {1000: 250.0}


def test_a_pause_without_samples_is_charged_to_the_effort():
    # 400 m, paused for 120 s, 400 m
    times = list(range(81)) + list(range(200, 281))
    distance = [5.0 * t for t in range(81)] + [400.0 + 5.0 * (t - 200) for t in range(200, 281)]
    assert best_efforts({"time": times, "distance": distance}, [400, 800]) == {400: 80.0, 800: 280.0}


def test_an_indoor_run_without_distance_has_no_efforts():
    assert best_efforts({"time": list(range(1800)), "distance": [0.0] * 1800}, [400, 1000]) == {}


def test_each_sport_has_its_own_cap():
    ride = stream_from_speeds([15.0] * 1400)
    assert best_efforts(ride, [10000], RIDE_MAX_SPEED) == {10000: pytest.approx(10000 / 15.0)}
    # 54 km/h never happened on foot
    assert best_efforts(ride, [1000]) == {}


def test_longer_targets_never_take_less_time():
    run = stream_from_speeds([3.0] * 600 + [5.5] * 200 + [3.5] * 1800 + [4.5] * 900)
    efforts = best_efforts(run, [400, 1000, 5000, 10000])
    times = [efforts[t] for t in sorted(efforts)]
    assert times == sorted(times)
