"""Leak-free backtest of the race predictor: each past race predicted as of the
day before it, calibrated only from the races before it.

    poetry run python scripts/backtest_race_predictions.py [sport_category]
"""
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.races import refresh_race_activities  # noqa: E402
from zone2.core import Zone2  # noqa: E402


def main(sport_category: str) -> None:
    z2 = Zone2(workdir=Path(tempfile.mkdtemp()), auto_sync=False)
    analytics = z2.strava_analytics
    refresh_race_activities(z2)

    residuals = [r for _, r in analytics._compute_race_residuals(sport_category)]
    if not residuals:
        print(f"No {sport_category} races to backtest")
        return
    clamp, min_races = analytics.RACE_CALIBRATION_CLAMP, analytics.RACE_CALIBRATION_MIN_RACES
    calibrated = []
    for i, r in enumerate(residuals):
        prior = residuals[:i]
        factor = float(np.clip(np.median(prior), 1 - clamp, 1 + clamp)) if len(prior) >= min_races else 1.0
        calibrated.append(r / factor)

    raw_mae = np.mean(np.abs(np.array(residuals) - 1)) * 100
    cal_mae = np.mean(np.abs(np.array(calibrated) - 1)) * 100
    bias = (np.median(residuals) - 1) * 100
    print(f"{len(residuals)} races  MAE raw {raw_mae:.2f}%  calibrated {cal_mae:.2f}%  raw median bias {bias:+.2f}%")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "running")
