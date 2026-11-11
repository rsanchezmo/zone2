import pytest

from zone2.drift import DRIFTING_PCT, HIGH_PCT, _verdict, heart_rate_drift
from tests.synthetic import stream_from_speeds, steady_stream


def test_without_heart_rate():
    assert heart_rate_drift(None) == {"status": "no_heart_rate"}
    assert heart_rate_drift(steady_stream(3600, 3.0)) == {"status": "no_heart_rate"}


def test_too_short_once_the_warm_up_is_skipped():
    # 15 minutes, less the first 10 and the last one
    result = heart_rate_drift(steady_stream(15 * 60, 3.0, heartrate=lambda t: 140))
    assert result == {"status": "too_short", "minutes": 4, "min_minutes": 20, "skipped_min": 10}


def test_steady_heart_rate_at_steady_pace():
    result = heart_rate_drift(steady_stream(3600, 3.0, heartrate=lambda t: 140))
    assert result["status"] == "measured"
    assert result["verdict"] == "steady"
    assert result["decoupling_pct"] == 0.0
    assert result["drift_bpm_per_10min"] == 0.0
    assert result["minutes"] == 49
    assert result["start_km"] == pytest.approx(1.8)   # 10 min at 3 m/s


def test_heart_rate_climbing_at_steady_pace():
    # +0.5 bpm a minute: 5 bpm per 10 min. Measured from minute 10 to 59, the
    # halves average about 151 and 163 bpm, so ~7.5% fewer metres per beat.
    result = heart_rate_drift(steady_stream(3600, 3.0, heartrate=lambda t: 140 + 0.5 * t / 60), with_series=True)
    assert result["drift_bpm_per_10min"] == pytest.approx(5.0, abs=0.1)
    assert result["decoupling_pct"] == pytest.approx(7.5, abs=0.2)
    assert result["verdict"] == "drifting"
    # Without drift, HR would have held its level at minute 10 all along
    assert {round(hr) for _, hr in result["no_drift_hr"]} == {145}


def test_changing_pace_is_unsteady():
    run = stream_from_speeds([2.5 if (t // 120) % 2 else 4.5 for t in range(3600)], [140] * 3600)
    result = heart_rate_drift(run)
    assert result["status"] == "unsteady"
    assert result["pace_cv_pct"] > result["max_pace_cv_pct"]


def test_verdict_bands():
    assert _verdict(DRIFTING_PCT - 0.1) == "steady"
    assert _verdict(DRIFTING_PCT) == "drifting"
    assert _verdict(HIGH_PCT) == "high"
