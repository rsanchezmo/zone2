import numpy as np
import pytest

from zone2.hr_recovery import _split, heart_rate_recovery
from tests.synthetic import stream_from_speeds, steady_stream


def interval_session(recovery_speed: float = 2.5) -> dict:
    """10 min easy, then 5 × (2 min at 5 m/s, 2 min recovery), then 5 min easy.
    HR climbs 150 → 175 over each rep and falls 0.4 bpm/s after it."""
    speeds, hr = [2.5] * 600, [140.0] * 600
    for rep in range(5):
        speeds += [5.0] * 120
        hr += [150 + 25 * i / 119 for i in range(120)]
        last = rep == 4
        speeds += [2.5 if last else recovery_speed] * (300 if last else 120)
        hr += [max(145.0, 175 - 0.4 * i) for i in range(300 if last else 120)]
    return stream_from_speeds(speeds, hr)


def test_otsu_split():
    assert _split(np.array([3.0] * 50 + [5.0] * 50)) == (4.0, 3.0, 5.0, 1.0)
    assert _split(np.array([3.0] * 10))[3] == 0.0


def test_reps_and_their_heart_rate_drops():
    result = heart_rate_recovery(interval_session())
    assert result["status"] == "measured"
    reps = result["reps"]
    assert len(reps) == 5
    for rep in reps:
        assert rep["duration_s"] == 120
        assert rep["speed_ms"] == pytest.approx(5.0)
        assert rep["peak_hr"] == 175
        assert (rep["drop_30"], rep["drop_60"]) == (12, 24)
        assert rep["jogged"]
    assert [r["recovery_s"] for r in reps] == [120, 120, 120, 120, None]
    assert reps[0]["start_km"] == pytest.approx(1.5)
    assert (result["drop_30_mean"], result["drop_60_mean"]) == (12.0, 24.0)


def test_walked_recoveries_are_flagged():
    reps = heart_rate_recovery(interval_session(recovery_speed=1.0))["reps"]
    assert [r["jogged"] for r in reps] == [False, False, False, False, True]


def test_a_steady_run_has_no_reps():
    assert heart_rate_recovery(steady_stream(2400, 3.0, heartrate=lambda t: 150)) == {
        "status": "no_reps", "reps": 0, "min_reps": 2,
    }


def test_without_heart_rate():
    assert heart_rate_recovery(None) == {"status": "no_heart_rate"}
    assert heart_rate_recovery(steady_stream(600, 3.0)) == {"status": "no_heart_rate"}
