"""Heart-rate drift within a run: how far HR climbs while the grade-adjusted
pace holds (cardiac drift), from the activity's streams."""
from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

from zone2.streams_store import float_column, grade_adjusted_speeds

# Bump whenever heart_rate_drift changes: it names the persisted summaries.
DRIFT_VERSION = 1

STEP_S = 5
# HR takes minutes to settle after the start, and a warm-up isn't the run.
SKIP_START_MIN = 10
SKIP_END_S = 60
MIN_MINUTES = 20
# Slower is walking or standing, where HR follows something other than pace.
MIN_SPEED_MS = 2.0
# Further from its minute's median, an HR sample is a sensor glitch (a dry
# strap, an optical spike).
HR_GLITCH_BPM = 12
# An HR sample further than this from any recorded one is a gap, not data.
HR_GAP_S = 15
# Spread of the 1-minute grade-adjusted pace above which the run isn't steady.
MAX_PACE_CV_PCT = 8.0
# Friel's decoupling bands: under 5% the pace held its heart-rate cost.
DRIFTING_PCT = 5.0
HIGH_PCT = 10.0
SERIES_STEP_S = 30

# Results are persisted, so they hold plain strings rather than enum members,
# and carry the thresholds they were measured with for the UI to quote.
DriftVerdict = Literal["steady", "drifting", "high"]


class NoHeartRate(TypedDict):
    status: Literal["no_heart_rate"]


class TooShort(TypedDict):
    status: Literal["too_short"]
    minutes: int
    min_minutes: int
    skipped_min: int


class Unsteady(TypedDict):
    status: Literal["unsteady"]
    minutes: int
    pace_cv_pct: float
    max_pace_cv_pct: float


class MeasuredDrift(TypedDict):
    status: Literal["measured"]
    verdict: DriftVerdict
    decoupling_pct: float
    drift_bpm_per_10min: float
    rise_bpm: int
    minutes: int
    # First half, second half.
    metres_per_beat: tuple[float, float]
    pace_cv_pct: float
    start_km: float
    half_km: float
    end_km: float
    skipped_min: int
    steady_below_pct: float
    # [km, bpm] every 30 s: the HR the pace alone explains at the start's cost.
    no_drift_hr: NotRequired[list[tuple[float, float]]]


HeartRateDrift = NoHeartRate | TooShort | Unsteady | MeasuredDrift


def _verdict(decoupling_pct: float) -> DriftVerdict:
    if decoupling_pct >= HIGH_PCT:
        return "high"
    if decoupling_pct >= DRIFTING_PCT:
        return "drifting"
    return "steady"


def heart_rate_drift(streams: dict | None, with_series: bool = False) -> HeartRateDrift:
    """How much the run's HR rose at a steady grade-adjusted pace.

    Past the first 10 minutes and before the last one, on moving samples
    without HR glitches:
      decoupling  — drop in metres per heartbeat from the first half to the
                    second (Friel's Pa:HR), so a fade at the same HR counts too
      drift       — bpm per 10 min from HR = a + b·speed + c·time, so the
                    figure holds when the pace changes (surges, a fast finish)
    `with_series` adds `no_drift_hr`, for plotting against the real HR."""
    streams = streams or {}
    hr = float_column(streams, "heartrate")
    if hr is not None:
        hr[hr <= 0] = np.nan
    gap = grade_adjusted_speeds(streams)
    speed = float_column(streams, "velocity_smooth")
    if hr is None or (~np.isnan(hr)).sum() < 2 or gap is None or speed is None:
        return {"status": "no_heart_rate"}
    t = np.asarray(streams["time"], dtype=np.float64)
    dist = float_column(streams, "distance")
    if dist is None:
        dist = np.concatenate([[0.0], np.cumsum(np.nan_to_num(speed[1:]) * np.diff(t))])

    grid = np.arange(t[0], t[-1] + 1e-9, STEP_S)

    def on_grid(values: np.ndarray) -> np.ndarray:
        valid = ~np.isnan(values)
        return np.interp(grid, t[valid], values[valid]) if valid.sum() >= 2 else np.full(len(grid), np.nan)

    g_hr, g_gap, g_speed, g_dist = on_grid(hr), on_grid(gap), on_grid(speed), on_grid(dist)
    hr_t = t[~np.isnan(hr)]
    nearest = np.searchsorted(hr_t, grid).clip(1, len(hr_t) - 1)
    hr_gap = np.minimum(np.abs(grid - hr_t[nearest - 1]), np.abs(hr_t[nearest] - grid))
    glitch = np.abs(g_hr - median_filter(g_hr, size=2 * (60 // STEP_S) + 1, mode="nearest")) > HR_GLITCH_BPM

    moving = g_speed >= MIN_SPEED_MS
    moving_s = np.cumsum(moving) * STEP_S
    keep = (moving & (moving_s > SKIP_START_MIN * 60) & (moving_s <= moving_s[-1] - SKIP_END_S)
            & (hr_gap <= HR_GAP_S) & ~glitch)
    measured_s = int(keep.sum()) * STEP_S
    minutes = round(measured_s / 60)
    if measured_s < MIN_MINUTES * 60:
        return {"status": "too_short", "minutes": minutes, "min_minutes": MIN_MINUTES,
                "skipped_min": SKIP_START_MIN}

    pace, beats, x, km = g_gap[keep], g_hr[keep], moving_s[keep].astype(np.float64), g_dist[keep] / 1000
    one_min = uniform_filter1d(pace, size=60 // STEP_S, mode="nearest")
    pace_cv = float(one_min.std() / one_min.mean()) * 100
    if pace_cv > MAX_PACE_CV_PCT:
        return {"status": "unsteady", "minutes": minutes, "pace_cv_pct": round(pace_cv, 1),
                "max_pace_cv_pct": MAX_PACE_CV_PCT}

    first = x <= (x[0] + x[-1]) / 2
    per_beat = (float(pace[first].mean() * 60 / beats[first].mean()),
                float(pace[~first].mean() * 60 / beats[~first].mean()))
    decoupling = (per_beat[0] - per_beat[1]) / per_beat[0] * 100

    smooth_pace = uniform_filter1d(pace, size=30 // STEP_S, mode="nearest")
    design = np.column_stack([np.ones(len(x)), smooth_pace, (x - x[0]) / 600])
    a, b, c = np.linalg.lstsq(design, beats, rcond=None)[0]

    result: MeasuredDrift = {
        "status": "measured",
        "verdict": _verdict(decoupling),
        "decoupling_pct": round(decoupling, 1),
        "drift_bpm_per_10min": round(float(c), 1),
        "rise_bpm": round(float(c) * (x[-1] - x[0]) / 600),
        "minutes": minutes,
        "metres_per_beat": (round(per_beat[0], 2), round(per_beat[1], 2)),
        "pace_cv_pct": round(pace_cv, 1),
        "start_km": round(float(km[0]), 2),
        "half_km": round(float(km[np.argmax(~first)]), 2),
        "end_km": round(float(km[-1]), 2),
        "skipped_min": SKIP_START_MIN,
        "steady_below_pct": DRIFTING_PCT,
    }
    if with_series:
        every = SERIES_STEP_S // STEP_S
        result["no_drift_hr"] = [
            (round(float(k), 3), round(float(v), 1))
            for k, v in zip(km[::every], (a + b * smooth_pace)[::every])
        ]
    return result
