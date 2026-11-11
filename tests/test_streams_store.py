import numpy as np

from zone2.streams_store import (
    StreamsStore, columnar_to_points, detect_stops, float_column, from_strava_api, grade_adjusted_speeds,
    moving_time, on_grid, sample_gaps, slice_streams, stream_length,
)
from tests.synthetic import steady_stream


def _with_pause(before_s: int, pause_s: int, after_s: int, speed: float = 4.0) -> dict:
    """1 Hz at `speed`, standing still (the watch still recording) for `pause_s` in between."""
    time, distance = list(range(before_s + 1)), [speed * i for i in range(before_s + 1)]
    stop_at = distance[-1]
    time += [before_s + 1 + i for i in range(pause_s)]
    distance += [stop_at] * pause_s
    time += [before_s + 1 + pause_s + i for i in range(after_s)]
    distance += [stop_at + speed * (i + 1) for i in range(after_s)]
    return {"time": time, "distance": distance}


# ── Shape helpers ────────────────────────────────────────────────────────

def test_stream_length_and_slicing():
    streams = {"time": [0, 1, 2, 3], "heartrate": [100, 101, 102, 103]}
    assert stream_length(streams) == 4
    assert stream_length({}) == 0
    assert stream_length({"distance": [0.0, 5.0]}) == 2
    assert slice_streams(streams, 1, 3) == {"time": [1, 2], "heartrate": [101, 102]}


def test_columnar_to_points_splits_latlng_and_drops_gaps():
    streams = {"time": [0, 1, 2], "heartrate": [120, None, 122], "latlng": [[50.0, 10.0], None, [50.1, 10.1]]}
    assert columnar_to_points(streams) == [
        {"time": 0, "heartrate": 120, "lat": 50.0, "lng": 10.0},
        {"time": 1},
        {"time": 2, "heartrate": 122, "lat": 50.1, "lng": 10.1},
    ]


def test_from_strava_api():
    api = {"time": {"data": [0, 1]}, "latlng": {"data": [[50.0, 10.0], [50.1, 10.1]]}, "odd": "not a stream"}
    assert from_strava_api(api) == {"time": [0, 1], "latlng": [[50.0, 10.0], [50.1, 10.1]]}
    assert from_strava_api({}) == {}


def test_float_column():
    streams = {"time": [0, 1, 2], "heartrate": [120, None, 122], "cadence": [80, 81]}
    assert np.array_equal(float_column(streams, "heartrate"), [120, np.nan, 122], equal_nan=True)
    assert float_column(streams, "cadence") is None   # not aligned with the stream
    assert float_column(streams, "watts") is None


def test_on_grid_interpolates_across_missing_samples():
    t = np.array([0.0, 5.0, 10.0])
    assert np.allclose(on_grid(t, np.array([0.0, np.nan, 10.0]), np.array([0.0, 2.5, 10.0])), [0.0, 2.5, 10.0])
    assert np.isnan(on_grid(t, np.array([1.0, np.nan, np.nan]), t)).all()


def test_sample_gaps():
    t = np.array([0.0, 10.0, 20.0])
    gaps = sample_gaps(t, np.array([1.0, np.nan, 3.0]), np.array([0.0, 5.0, 10.0, 20.0]))
    assert gaps.tolist() == [0.0, 5.0, 10.0, 0.0]


# ── Moving time and stops ────────────────────────────────────────────────

def test_moving_time_of_a_steady_run_is_its_elapsed_time():
    assert moving_time(steady_stream(600, 3.0)) == 599


def test_moving_time_drops_a_standstill():
    # 100 s, 60 s standing, 100 s: 260 s elapsed
    assert moving_time(_with_pause(100, 60, 100)) == 200


def test_moving_time_charges_a_stopped_gap_its_distance():
    # A 30 s gap covering 4 m, after running at 4 m/s, is 1 s moving and 29 stopped
    streams = steady_stream(251, 4.0)
    streams["time"] += [280 + i for i in range(251)]
    streams["distance"] += [1004 + 4.0 * i for i in range(251)]
    assert moving_time(streams) == 530 - 29


def test_moving_time_edge_cases():
    walk = steady_stream(300, 1.3)
    assert moving_time(walk) == 299   # walking counts as moving
    # Pool swims sample every few minutes: stops can't be told from slow laps
    sparse = {"time": [0, 120, 240, 360], "distance": [0.0, 50.0, 50.0, 100.0]}
    assert moving_time(sparse) == 360
    assert moving_time({"time": [0, 1, 1, 2], "distance": [0.0, 4.0, 4.0, 8.0]}) == 2
    assert moving_time({"time": [0]}) == 0


def test_detect_stops():
    assert detect_stops(_with_pause(100, 60, 100)) == [{"start_km": 0.4, "start_s": 100, "duration_s": 60}]
    assert detect_stops(_with_pause(100, 5, 100)) == []
    assert len(detect_stops(_with_pause(100, 5, 100), min_duration_s=3)) == 1


# ── Grade-adjusted pace ──────────────────────────────────────────────────

def _on_grade(grade: float, speed: float = 2.0, n: int = 500) -> dict:
    streams = steady_stream(n, speed)
    streams["altitude"] = [grade * d for d in streams["distance"]]
    return streams


def test_grade_adjusted_speed_on_the_flat_is_the_speed():
    assert np.allclose(grade_adjusted_speeds(_on_grade(0.0)), 2.0)
    assert np.allclose(grade_adjusted_speeds(steady_stream(100, 2.0)), 2.0)   # no altitude
    assert grade_adjusted_speeds({"time": [0, 1], "distance": [0.0, 2.0]}) is None


def test_grade_adjusted_speed_on_a_slope():
    # Minetti's cost (J/kg/m) at ±10%, against 3.6 on the flat
    uphill = 155.4e-5 - 30.4e-4 - 43.3e-3 + 46.3e-2 + 1.95 + 3.6
    downhill = -155.4e-5 - 30.4e-4 + 43.3e-3 + 46.3e-2 - 1.95 + 3.6
    assert np.allclose(grade_adjusted_speeds(_on_grade(0.10)), 2.0 * uphill / 3.6)
    assert np.allclose(grade_adjusted_speeds(_on_grade(-0.10)), 2.0 * downhill / 3.6)


def test_grade_adjusted_speed_clips_implausible_grades():
    assert np.allclose(grade_adjusted_speeds(_on_grade(0.9)), grade_adjusted_speeds(_on_grade(0.45)))


# ── StreamsStore ─────────────────────────────────────────────────────────

def _streams(seed: float) -> dict:
    return {"time": [0, 1, 2], "distance": [0.0, seed, 2 * seed]}


def test_store_round_trip_across_years(tmp_path):
    store = StreamsStore(tmp_path)
    store.save({1: _streams(3.0), 2: _streams(4.0), 3: _streams(5.0)}, {1: 2025, 2: 2026, 3: 2026})
    assert store.get(2) == _streams(4.0)
    assert store.get_many([1, 3, 99]) == {1: _streams(3.0), 3: _streams(5.0)}
    assert store.get(99) is None and not store.has(99)

    store.save({2: None}, {2: 2026})   # None deletes
    reopened = StreamsStore(tmp_path)
    assert reopened.all_activity_ids() == {1, 3}
    assert reopened.get(1) == _streams(3.0)


def test_summaries_are_computed_once_and_persisted(tmp_path):
    store = StreamsStore(tmp_path)
    store.save({1: _streams(3.0), 2: _streams(4.0)}, {1: 2026, 2: 2026})
    calls = []

    def total(streams: dict) -> float:
        calls.append(1)
        return streams["distance"][-1]

    assert store.summaries("total:v1", [1, 2, 99], total) == {1: 6.0, 2: 8.0}
    assert store.summaries("total:v1", [1, 2], total) == {1: 6.0, 2: 8.0}
    assert StreamsStore(tmp_path).summaries("total:v1", [1, 2], total) == {1: 6.0, 2: 8.0}
    assert len(calls) == 2


def test_resaving_streams_drops_their_summaries(tmp_path):
    store = StreamsStore(tmp_path)
    store.save({1: _streams(3.0)}, {1: 2026})
    assert store.summaries("total:v1", [1], lambda s: s["distance"][-1]) == {1: 6.0}
    store.save({1: _streams(10.0)}, {1: 2026})
    assert store.summaries("total:v1", [1], lambda s: s["distance"][-1]) == {1: 20.0}


def test_a_summary_read_before_a_save_is_not_kept(tmp_path):
    store = StreamsStore(tmp_path)
    store.save({1: _streams(3.0)}, {1: 2026})

    def total_while_a_sync_lands(streams: dict) -> float:
        store.save({1: _streams(10.0)}, {1: 2026})
        return streams["distance"][-1]

    assert store.summaries("total:v1", [1], total_while_a_sync_lands) == {}
    assert store.summaries("total:v1", [1], lambda s: s["distance"][-1]) == {1: 20.0}
