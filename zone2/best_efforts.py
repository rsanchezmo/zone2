"""Best efforts: each activity's fastest stretch at the standard distances of
its sport, from its streams, and the queries over them behind personal records
and the race predictions' recent bests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

import numpy as np
import pandas as pd

from zone2.utils import SportCategory, df_rows

# Bump whenever best_effort_times changes: it names the persisted summaries.
BEST_EFFORTS_VERSION = 2

Distances = tuple[tuple[int, str], ...]

RUNNING_DISTANCES: Distances = (
    (400, "400m"),
    (1000, "1K"),
    (5000, "5K"),
    (10000, "10K"),
    (15000, "15K"),
    (20000, "20K"),
    (21097, "Half Marathon"),
    (42195, "Marathon"),
)
CYCLING_DISTANCES: Distances = (
    (10000, "10K"),
    (20000, "20K"),
    (40000, "40K"),
    (100000, "100K"),
    (160000, "100 mi"),
)
SWIMMING_DISTANCES: Distances = (
    (100, "100m"),
    (200, "200m"),
    (400, "400m"),
    (800, "800m"),
    (1500, "1500m"),
    (1900, "1900m"),   # Half Ironman swim leg
    (3000, "3000m"),
    (3800, "3800m"),   # Ironman swim leg
)
SPORT_DISTANCES: dict[SportCategory, Distances] = {
    SportCategory.RUNNING: RUNNING_DISTANCES,
    SportCategory.CYCLING: CYCLING_DISTANCES,
    SportCategory.SWIMMING: SWIMMING_DISTANCES,
}
# The sports with standard distances: records and predictions
RECORD_SPORTS: tuple[SportCategory, ...] = (SportCategory.RUNNING, SportCategory.CYCLING, SportCategory.SWIMMING)

# Fastest plausible speed per sport (m/s); metres gained faster are bad data.
# Running: 2:20/km, about the 800m world record pace
# Cycling: 75 km/h, a pro sprint
# Swimming: 0:50/100m, the 100m freestyle world record
MAX_SPEED_MS: dict[SportCategory, float] = {
    SportCategory.RUNNING: 7.2,
    SportCategory.CYCLING: 21.0,
    SportCategory.SWIMMING: 2.0,
}

# A recent best slower than this multiple of its distance's fastest in the
# window is an easy-run "best" that only ranked top-K, not race-quality evidence.
RECENT_BEST_MAX_MULT = 1.20

BESTS_COLUMNS = ["activity_id", "activity_name", "date", "distance_m", "time_s", "is_race", "avg_hr"]


class PersonalRecord(TypedDict):
    distance_m: int
    label: str
    time_s: float
    activity_id: int
    activity_name: str
    date: str


class BestEffort(TypedDict):
    distance_m: int
    time_s: float
    activity_id: int
    activity_name: str
    date: str
    # The fastest at its distance in the window
    is_top1: bool
    # A race's effort at the race's own distance
    is_race: bool
    avg_hr: float | None


@dataclass(frozen=True, eq=False)
class RankedBests:
    """The per-activity bests as arrays ordered by distance, then time, then
    activity order (the earliest wins a tie), for fast window queries."""
    distance_m: np.ndarray
    time_s: np.ndarray
    date_ns: np.ndarray
    date: np.ndarray
    activity_id: np.ndarray
    activity_name: np.ndarray
    is_race: np.ndarray
    avg_hr: np.ndarray


def sport_distances(sport_category: SportCategory) -> Distances:
    return SPORT_DISTANCES.get(sport_category, ())


def summary_name(sport_category: SportCategory) -> str:
    """The name the per-activity best efforts of a sport persist under: it
    changes with anything that changes their values."""
    targets = [t for t, _ in sport_distances(sport_category)]
    return f"best_efforts:v{BEST_EFFORTS_VERSION}:{sport_category}:{MAX_SPEED_MS[sport_category]}:{targets}"


def stream_best_efforts(streams: dict, sport_category: SportCategory) -> dict[int, float]:
    """{target_m: best_time_s} at the sport's standard distances for one
    activity's streams, empty without distance and time samples."""
    dist_col = streams.get("distance")
    time_col = streams.get("time")
    if not dist_col or not time_col or len(dist_col) < 2:
        return {}
    targets = [t for t, _ in sport_distances(sport_category)]
    return best_effort_times(dist_col, time_col, targets, MAX_SPEED_MS[sport_category])


def best_effort_times(dist_col: list, time_col: list, targets: list[int], max_speed: float) -> dict[int, float]:
    """Sliding-window best effort per target distance for one activity's
    streams. Returns {target_m: best_time_s}.

    Efforts are continuous elapsed time. Excluding stops would stitch
    separate interval reps (6×400 with standing rests) into a fake 1K,
    and streams can't tell a rest from a traffic light.

    The window end is linearly interpolated between the two samples
    bracketing the exact target distance instead of charging the full gap
    to the effort: GPS samples can be many metres apart.

    Metres gained faster than `max_speed` are dropped before the search
    (`plausible_distance`), so no window can credit any part of them.
    """
    distances = np.asarray(dist_col, dtype=np.float64)
    times = np.asarray(time_col, dtype=np.float64)
    n = len(distances)
    if n < 2:
        return {}
    distances = plausible_distance(distances, times, max_speed)

    out: dict[int, float] = {}
    total_d = distances[-1]
    for target_m in targets:
        if total_d < target_m:
            continue
        thresholds = distances + target_m
        right = np.searchsorted(distances, thresholds, side="left")
        valid = right < n
        left_idx = np.nonzero(valid)[0]
        if len(left_idx) == 0:
            continue
        right_idx = right[valid]
        # searchsorted(side="left") guarantees right > left and
        # distances[right-1] < threshold <= distances[right]: interpolate
        # the crossing time inside that bracket.
        prev_idx = right_idx - 1
        seg = distances[right_idx] - distances[prev_idx]
        seg_safe = np.where(seg > 0, seg, 1.0)
        frac = np.where(seg > 0, (thresholds[left_idx] - distances[prev_idx]) / seg_safe, 1.0)
        frac = np.clip(frac, 0.0, 1.0)
        cross_t = times[prev_idx] + frac * (times[right_idx] - times[prev_idx])
        elapsed = cross_t - times[left_idx]
        ok = elapsed > 0
        if not np.any(ok):
            continue
        out[int(target_m)] = float(elapsed[ok].min())
    return out


def plausible_distance(distances: np.ndarray, times: np.ndarray, max_speed: float) -> np.ndarray:
    """The cumulative distance without the metres gained faster than
    `max_speed`: GPS jumps, a watch crediting pool lengths after a rest,
    the drive home after a forgotten stop. The time they took stays.

    Timestamps are whole seconds, so a stretch can read up to a second
    shorter than it took: consecutive over-speed samples are only dropped
    when they beat the cap even granted that second.
    """
    steps = np.diff(distances)
    gaps = np.diff(times)
    fast = steps > max_speed * gaps
    if not fast.any():
        return distances
    stretch = np.cumsum(np.r_[True, fast[1:] != fast[:-1]]) - 1
    stretch_m = np.bincount(stretch, weights=steps)
    stretch_s = np.bincount(stretch, weights=gaps)
    impossible = fast & (stretch_m[stretch] > max_speed * (stretch_s[stretch] + 1))
    return distances - np.r_[0.0, np.cumsum(np.where(impossible, steps, 0.0))]


def per_activity_bests(activities: pd.DataFrame, efforts_by_id: dict[int, dict[int, float]],
                       race_ids: set[int]) -> pd.DataFrame:
    """One row per best effort of each of `activities` (one sport's) found in
    `efforts_by_id`: columns BESTS_COLUMNS, `date` as a UTC pd.Timestamp,
    `is_race` set on a race's effort at the race's own distance."""
    rows: list[dict] = []
    for row in df_rows(activities, "id", "name", "start_date_local", "average_heartrate"):
        efforts = efforts_by_id.get(int(row.get("id"))) if row.get("id") is not None else None
        if not efforts:
            continue

        activity_id = row.get("id")
        activity_name = row.get("name", "")
        act_date = row.get("start_date_local")
        # A race is a maximal effort at its own distance only: its splits at
        # shorter distances were paced for the whole race.
        race_distance = max(efforts) if activity_id in race_ids else None
        avg_hr = row.get("average_heartrate")
        avg_hr = float(avg_hr) if avg_hr is not None and not pd.isna(avg_hr) else None

        for target_m, best_time in efforts.items():
            rows.append({
                "activity_id": activity_id,
                "activity_name": activity_name,
                "date": act_date,
                "distance_m": target_m,
                "time_s": best_time,
                "is_race": target_m == race_distance,
                "avg_hr": avg_hr,
            })

    df = pd.DataFrame(rows, columns=BESTS_COLUMNS)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    return df


def personal_records(bests: pd.DataFrame, distances: Distances) -> list[PersonalRecord]:
    """The fastest of `bests` at each of `distances` (the earliest wins a tie)."""
    records: list[PersonalRecord] = []
    for target_m, label in distances:
        at_distance = bests[bests["distance_m"] == target_m]
        if at_distance.empty:
            continue
        r = at_distance.loc[at_distance["time_s"].idxmin()]
        records.append({
            "distance_m": target_m,
            "label": label,
            "time_s": float(r["time_s"]),
            "activity_id": int(r["activity_id"]),
            "activity_name": r["activity_name"],
            "date": str(r["date"]),
        })
    return records


def rank_bests(bests: pd.DataFrame) -> RankedBests:
    order = np.lexsort((np.arange(len(bests)), bests["time_s"].to_numpy(dtype=np.float64),
                        bests["distance_m"].to_numpy(dtype=np.int64)))
    ranked = bests.iloc[order]
    return RankedBests(
        distance_m=ranked["distance_m"].to_numpy(dtype=np.int64),
        time_s=ranked["time_s"].to_numpy(dtype=np.float64),
        date_ns=ranked["date"].to_numpy(dtype="datetime64[ns]").view(np.int64),
        date=np.array([str(d) for d in ranked["date"]], dtype=object),
        activity_id=ranked["activity_id"].to_numpy(),
        activity_name=ranked["activity_name"].to_numpy(dtype=object),
        is_race=ranked["is_race"].to_numpy(),
        avg_hr=ranked["avg_hr"].to_numpy(dtype=object),
    )


def recent_best_efforts(ranked: RankedBests, end: datetime | pd.Timestamp, within_days: int,
                        top_k: int = 3) -> list[BestEffort]:
    """The top-K fastest efforts per distance in the `within_days` up to
    `end` (naive is UTC), less those slower than RECENT_BEST_MAX_MULT of
    the distance's fastest.

    Several anchors per distance rather than its single best keep the
    predictions from cliffing: when the fastest effort ages past the window,
    only 1/K of the distance's weight changes hands.
    """
    if not len(ranked.time_s):
        return []

    ts = pd.Timestamp(end)
    end_ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
    start_ts = end_ts - pd.Timedelta(days=within_days)

    in_window = np.nonzero((ranked.date_ns >= start_ts.value) & (ranked.date_ns <= end_ts.value))[0]
    if not len(in_window):
        return []
    # Rows are ranked fastest-first within each distance, so the top-K of
    # a distance are its first K rows inside the window.
    dist = ranked.distance_m[in_window]
    first = np.r_[True, dist[1:] != dist[:-1]]
    pos = np.arange(len(in_window))
    rank = pos - np.maximum.accumulate(np.where(first, pos, 0))

    result: list[BestEffort] = []
    best_time = 0.0
    for i, r in zip(in_window[rank < top_k].tolist(), rank[rank < top_k].tolist()):
        time_s = float(ranked.time_s[i])
        if r == 0:
            best_time = time_s
        elif time_s > best_time * RECENT_BEST_MAX_MULT:
            continue
        avg_hr = ranked.avg_hr[i]
        result.append({
            "distance_m": int(ranked.distance_m[i]),
            "time_s": time_s,
            "activity_id": int(ranked.activity_id[i]),
            "activity_name": ranked.activity_name[i],
            "date": ranked.date[i],
            "is_top1": r == 0,
            "is_race": bool(ranked.is_race[i]),
            "avg_hr": float(avg_hr) if not pd.isna(avg_hr) else None,
        })
    return result
