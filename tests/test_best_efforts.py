"""The sliding-window best efforts behind personal records and race predictions."""
import pytest

from zone2.analytics import StravaAnalytics
from tests.synthetic import stream_from_speeds

RUN_MAX_SPEED = StravaAnalytics.MAX_SPEED_MS[StravaAnalytics.RECORD_SPORTS[0]]


def best_efforts(streams: dict, targets: list[int]) -> dict[int, float]:
    return StravaAnalytics._best_effort_times(streams["distance"], streams["time"], targets, RUN_MAX_SPEED)


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


@pytest.mark.xfail(reason="max_speed rejects whole windows by their average speed, so a window taking in part "
                          "of a GPS jump still credits the jumped metres: the 1K comes out at the 7.2 m/s cap "
                          "(138.9 s, a 2:19 /km record) instead of 250 s")
def test_gps_jumps_faster_than_humanly_possible_are_ignored():
    # 500 m in one sample, in a run at 4 m/s
    run = stream_from_speeds([4.0] * 500 + [500.0] + [4.0] * 500)
    assert best_efforts(run, [1000]) == {1000: 250.0}


def test_longer_targets_never_take_less_time():
    run = stream_from_speeds([3.0] * 600 + [5.5] * 200 + [3.5] * 1800 + [4.5] * 900)
    efforts = best_efforts(run, [400, 1000, 5000, 10000])
    times = [efforts[t] for t in sorted(efforts)]
    assert times == sorted(times)
