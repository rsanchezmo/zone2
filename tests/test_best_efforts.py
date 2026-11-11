"""The sliding-window best efforts behind personal records and race predictions,
and the per-activity table and window queries over them."""
import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from zone2.best_efforts import (
    BESTS_COLUMNS, MAX_SPEED_MS, best_effort_times, per_activity_bests, personal_records, rank_bests,
    recent_best_efforts, sport_distances, stream_best_efforts, summary_name,
)
from zone2.utils import SportCategory
from tests.synthetic import activities_frame, stream_from_speeds

RUN_MAX_SPEED = MAX_SPEED_MS[SportCategory.RUNNING]
RIDE_MAX_SPEED = MAX_SPEED_MS[SportCategory.CYCLING]
SWIM_MAX_SPEED = MAX_SPEED_MS[SportCategory.SWIMMING]


def best_efforts(streams: dict, targets: list[int], max_speed: float = RUN_MAX_SPEED) -> dict[int, float]:
    return best_effort_times(streams["distance"], streams["time"], targets, max_speed)


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


# ── Persisted summaries ──────────────────────────────────────────────────

def test_summary_names_stay_put_while_the_values_mean_the_same():
    # Renaming would recompute every activity's persisted best efforts
    assert summary_name(SportCategory.RUNNING) == "best_efforts:v2:running:7.2:[400, 1000, 5000, 10000, 15000, 20000, 21097, 42195]"
    assert summary_name(SportCategory.CYCLING) == "best_efforts:v2:cycling:21.0:[10000, 20000, 40000, 100000, 160000]"
    assert summary_name(SportCategory.SWIMMING) == "best_efforts:v2:swimming:2.0:[100, 200, 400, 800, 1500, 1900, 3000, 3800]"


def test_stream_best_efforts_at_the_sports_own_distances():
    swim = stream_from_speeds([1.0] * 450)
    assert stream_best_efforts(swim, SportCategory.SWIMMING) == {100: 100.0, 200: 200.0, 400: 400.0}
    # 1 m/s is a walk on foot, but nothing at a run's 400 m is above its cap either
    assert stream_best_efforts(swim, SportCategory.RUNNING) == {400: 400.0}
    assert stream_best_efforts({"time": list(range(450))}, SportCategory.SWIMMING) == {}
    assert sport_distances(SportCategory.WALKING) == ()


# ── The per-activity table and its queries ───────────────────────────────

def best(activity_id: int, day: str, distance_m: int, time_s: float, is_race: bool = False,
         avg_hr: float | None = None) -> dict:
    return {"activity_id": activity_id, "activity_name": f"Run {activity_id}", "date": pd.Timestamp(day, tz="UTC"),
            "distance_m": distance_m, "time_s": time_s, "is_race": is_race, "avg_hr": avg_hr}


def bests_frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=BESTS_COLUMNS)


def test_per_activity_bests_mark_a_race_at_its_own_distance_only():
    activities = activities_frame([
        {"id": 1, "name": "Race", "start_date_local": "2026-06-07T09:00:00Z", "average_heartrate": 172.0},
        {"id": 2, "name": "Easy", "start_date_local": "2026-06-08T09:00:00Z", "average_heartrate": np.nan},
        {"id": 3, "name": "No streams", "start_date_local": "2026-06-09T09:00:00Z", "average_heartrate": 140.0},
    ])
    efforts = {1: {400: 80.0, 1000: 210.0, 5000: 1100.0}, 2: {400: 95.0}}
    bests = per_activity_bests(activities, efforts, race_ids={1})
    assert list(bests.columns) == BESTS_COLUMNS
    assert list(zip(bests["activity_id"], bests["distance_m"], bests["is_race"])) == [
        (1, 400, False), (1, 1000, False), (1, 5000, True), (2, 400, False),
    ]
    assert bests["avg_hr"].iloc[0] == 172.0 and pd.isna(bests["avg_hr"].iloc[3])
    assert bests["date"].iloc[0] == pd.Timestamp("2026-06-07T09:00:00Z")


def test_personal_records_take_the_fastest_and_the_earliest_on_a_tie():
    bests = bests_frame(best(1, "2026-05-01", 1000, 210.0), best(2, "2026-05-02", 1000, 200.0),
                        best(3, "2026-05-03", 1000, 200.0), best(3, "2026-05-03", 5000, 1100.0))
    records = personal_records(bests, sport_distances(SportCategory.RUNNING))
    assert [(r["label"], r["time_s"], r["activity_id"]) for r in records] == [("1K", 200.0, 2), ("5K", 1100.0, 3)]
    assert records[0]["date"] == "2026-05-02 00:00:00+00:00"


def test_ranked_bests_order_by_distance_then_time_then_activity_order():
    ranked = rank_bests(bests_frame(best(1, "2026-05-01", 5000, 1100.0), best(2, "2026-05-02", 1000, 205.0),
                                    best(3, "2026-05-03", 1000, 200.0), best(4, "2026-05-04", 1000, 205.0)))
    assert ranked.distance_m.tolist() == [1000, 1000, 1000, 5000]
    assert ranked.activity_id.tolist() == [3, 2, 4, 1]
    assert ranked.date_ns[0] == pd.Timestamp("2026-05-03", tz="UTC").value


def test_recent_bests_keep_the_top_k_close_enough_to_the_fastest():
    ranked = rank_bests(bests_frame(
        best(1, "2026-10-01", 1000, 200.0),
        best(2, "2026-09-01", 1000, 230.0),
        best(3, "2026-08-01", 1000, 250.0),    # over 120% of 200 s
        best(4, "2025-01-01", 1000, 180.0),    # out of the window
        best(5, "2026-10-15", 5000, 1100.0, is_race=True, avg_hr=171.0),
        best(6, "2026-10-20", 5000, 1400.0),   # over 120% of 1100 s
    ))
    recent = recent_best_efforts(ranked, datetime(2026, 11, 1), within_days=365)
    assert [(b["distance_m"], b["time_s"], b["activity_id"], b["is_top1"]) for b in recent] == [
        (1000, 200.0, 1, True), (1000, 230.0, 2, False), (5000, 1100.0, 5, True),
    ]
    assert (recent[2]["is_race"], recent[2]["avg_hr"], recent[0]["avg_hr"]) == (True, 171.0, None)
    assert [b["activity_id"] for b in recent_best_efforts(ranked, datetime(2026, 11, 1), 365, top_k=1)] == [1, 5]


def test_recent_bests_window_holds_both_ends():
    ranked = rank_bests(bests_frame(best(1, "2025-11-01", 1000, 200.0), best(2, "2026-11-01", 5000, 1100.0)))
    assert [b["activity_id"] for b in recent_best_efforts(ranked, pd.Timestamp("2026-11-01", tz="UTC"), 365)] == [1, 2]
    assert [b["activity_id"] for b in recent_best_efforts(ranked, datetime(2026, 10, 31), 364)] == [1]
    assert [b["activity_id"] for b in recent_best_efforts(ranked, datetime(2026, 10, 31), 363)] == []
    assert recent_best_efforts(rank_bests(bests_frame()), datetime(2026, 11, 1), 365) == []
