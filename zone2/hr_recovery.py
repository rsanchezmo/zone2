"""Heart-rate recovery in an interval session: how far HR falls from each rep's
peak in the 30 and 60 s after the rep ends, from the activity's streams."""
from __future__ import annotations

from typing import Literal, TypedDict

import numpy as np

from zone2.streams_store import float_column, grade_adjusted_speeds, on_grid, sample_gaps

# Bump whenever heart_rate_recovery changes: it names the persisted summaries.
HR_RECOVERY_VERSION = 1

# One-second grid, so the 30 and 60 s marks land on a sample.
STEP_S = 1
# Further than this from any recorded sample is a pause or dropout, not data.
MAX_SAMPLE_GAP_S = 15
# Slower than this is walking or standing, which drops HR faster than a jog.
JOG_SPEED_MS = 1.7
# The jogged pace must split into two groups explaining this share of its
# variance (Otsu's separability) at this speed ratio. Interval sessions score
# above 0.8; steady runs, traffic lights and all, stay under 0.7.
MIN_SEPARABILITY = 0.78
MIN_SPEED_RATIO = 1.25
# Shorter surges are strides, not reps.
MIN_REP_S = 40
# A dip this short (a turn, a crossing) doesn't end a rep; recoveries run longer.
MERGE_GAP_S = 20
MIN_REPS = 2
# HR lags pace: it peaks around the end of the rep, up to some 15 s after.
PEAK_BEFORE_S = 20
PEAK_AFTER_S = 15
DROP_AFTER_S = (30, 60)


class NoHeartRate(TypedDict):
    status: Literal["no_heart_rate"]


class NoReps(TypedDict):
    status: Literal["no_reps"]
    reps: int
    min_reps: int


class RepRecovery(TypedDict):
    start_km: float
    end_km: float
    duration_s: int
    speed_ms: float
    peak_km: float
    # None where the HR around the rep's end wasn't recorded.
    peak_hr: int | None
    # None when the next rep started first, or HR wasn't recorded then.
    drop_30: int | None
    drop_60: int | None
    # Seconds from the rep's end to the next one; None after the last rep.
    recovery_s: int | None
    jogged: bool


class MeasuredRecovery(TypedDict):
    status: Literal["measured"]
    reps: list[RepRecovery]
    drop_30_mean: float | None
    drop_60_mean: float | None
    jog_speed_ms: float


HeartRateRecovery = NoHeartRate | NoReps | MeasuredRecovery


def _split(values: np.ndarray) -> tuple[float, float, float, float]:
    """Otsu's threshold over speeds: the cut leaving two groups with the most
    variance between them. Returns (threshold, slow mean, fast mean, the share
    of the variance the split explains)."""
    v = np.sort(values)
    n = len(v)
    below = np.arange(1, n)
    total = np.cumsum(v)
    slow = total[:-1] / below
    fast = (total[-1] - total[:-1]) / (n - below)
    between = below * (n - below) / n ** 2 * (fast - slow) ** 2
    i = int(np.argmax(between))
    separability = float(between[i] / v.var()) if v.var() > 0 else 0.0
    return float((v[i] + v[i + 1]) / 2), float(slow[i]), float(fast[i]), separability


def _rep_spans(pace: np.ndarray, threshold: float, jogging: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) grid indices of the fast stretches long enough, and once
    merged across dips still fast enough on average, to be reps."""
    fast = jogging & (pace >= threshold)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], fast.astype(np.int8), [0]])))
    spans: list[tuple[int, int]] = []
    for start, end in zip(edges[::2], edges[1::2]):
        if spans and start - spans[-1][1] < MERGE_GAP_S // STEP_S:
            spans[-1] = (spans[-1][0], int(end))
        else:
            spans.append((int(start), int(end)))
    return [(s, e) for s, e in spans if (e - s) * STEP_S >= MIN_REP_S and pace[s:e].mean() >= threshold]


def heart_rate_recovery(streams: dict | None) -> HeartRateRecovery:
    """Each rep's peak HR and how far it fell 30 and 60 s later.

    Reps are the stretches where the grade-adjusted pace is in the faster of
    the two groups the run's jogged pace splits into; a run with no clear fast
    group (a steady or progression run) has none. The drops count from the
    rep's end, against the highest HR around it, since HR lags pace."""
    streams = streams or {}
    hr = float_column(streams, "heartrate")
    if hr is not None:
        hr[hr <= 0] = np.nan
    gap = grade_adjusted_speeds(streams)
    speed = float_column(streams, "velocity_smooth")
    if hr is None or (~np.isnan(hr)).sum() < 2 or gap is None or speed is None or (~np.isnan(speed)).sum() < 2:
        return {"status": "no_heart_rate"}
    t = np.asarray(streams["time"], dtype=np.float64)
    dist = float_column(streams, "distance")
    if dist is None:
        dist = np.concatenate([[0.0], np.cumsum(np.nan_to_num(speed[1:]) * np.diff(t))])

    grid = np.arange(t[0], t[-1] + 1e-9, STEP_S)
    recorded = sample_gaps(t, speed, grid) <= MAX_SAMPLE_GAP_S
    g_speed = np.where(recorded, on_grid(t, speed, grid), 0.0)
    g_gap = np.where(recorded, on_grid(t, gap, grid), 0.0)
    g_hr = np.where(sample_gaps(t, hr, grid) <= MAX_SAMPLE_GAP_S, on_grid(t, hr, grid), np.nan)
    g_dist = on_grid(t, dist, grid)

    jogging = g_speed >= JOG_SPEED_MS
    if jogging.sum() < 2:
        return {"status": "no_reps", "reps": 0, "min_reps": MIN_REPS}
    threshold, slow, fast, separability = _split(g_gap[jogging])
    structured = separability >= MIN_SEPARABILITY and fast >= slow * MIN_SPEED_RATIO
    spans = _rep_spans(g_gap, threshold, jogging) if structured else []
    if len(spans) < MIN_REPS:
        return {"status": "no_reps", "reps": len(spans), "min_reps": MIN_REPS}

    reps: list[RepRecovery] = []
    for i, (start, end) in enumerate(spans):
        next_start = spans[i + 1][0] if i + 1 < len(spans) else len(grid)
        lo, hi = max(start, end - PEAK_BEFORE_S // STEP_S), min(end + PEAK_AFTER_S // STEP_S, next_start)
        window = g_hr[lo:hi]
        peak = lo + int(np.nanargmax(window)) if not np.isnan(window).all() else end - 1
        peak_hr = None if np.isnan(g_hr[peak]) else float(g_hr[peak])

        def drop(after_s: int) -> int | None:
            j = end + after_s // STEP_S
            if peak_hr is None or j >= next_start or np.isnan(g_hr[j]):
                return None
            return round(peak_hr - float(g_hr[j]))

        after = g_speed[end:min(end + DROP_AFTER_S[-1] // STEP_S, next_start)]
        reps.append({
            "start_km": round(float(g_dist[start]) / 1000, 3),
            "end_km": round(float(g_dist[end - 1]) / 1000, 3),
            "duration_s": (end - start) * STEP_S,
            "speed_ms": round(float(g_speed[start:end].mean()), 2),
            "peak_km": round(float(g_dist[peak]) / 1000, 3),
            "peak_hr": None if peak_hr is None else round(peak_hr),
            "drop_30": drop(DROP_AFTER_S[0]),
            "drop_60": drop(DROP_AFTER_S[1]),
            "recovery_s": (next_start - end) * STEP_S if i + 1 < len(spans) else None,
            "jogged": bool(len(after) and after.mean() >= JOG_SPEED_MS),
        })

    def mean_drop(key: Literal["drop_30", "drop_60"]) -> float | None:
        drops = [r[key] for r in reps if r[key] is not None]
        return round(float(np.mean(drops)), 1) if drops else None

    return {
        "status": "measured",
        "reps": reps,
        "drop_30_mean": mean_drop("drop_30"),
        "drop_60_mean": mean_drop("drop_60"),
        "jog_speed_ms": JOG_SPEED_MS,
    }
