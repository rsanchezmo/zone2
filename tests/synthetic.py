"""Made-up activities and streams for the tests. The repo is public: never put
real activities, coordinates or names here."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from zone2.analytics import StravaAnalytics

# A five-zone ladder with round bounds, so which zone a bpm lands in is obvious
ZONES = [
    {"min": 0, "max": 120},
    {"min": 120, "max": 140},
    {"min": 140, "max": 160},
    {"min": 160, "max": 180},
    {"min": 180, "max": 200},
]


def stream_from_speeds(speeds: Sequence[float], heartrate: Sequence[float] | None = None) -> dict:
    """A 1 Hz columnar stream at these speeds (m/s), its distance integrated from them."""
    distance, d = [], 0.0
    for v in speeds:
        distance.append(d)
        d += v
    streams: dict[str, list] = {"time": list(range(len(speeds))), "distance": distance,
                                "velocity_smooth": list(speeds)}
    if heartrate is not None:
        streams["heartrate"] = list(heartrate)
    return streams


def steady_stream(seconds: int, speed: float, heartrate: Callable[[int], float] | None = None) -> dict:
    hr = None if heartrate is None else [heartrate(t) for t in range(seconds)]
    return stream_from_speeds([speed] * seconds, hr)


def activities_frame(rows: list[dict]) -> pd.DataFrame:
    """Activities as the prepared view holds them: oldest first, with
    start_date_local parsed as UTC wall-clock time."""
    df = pd.DataFrame(rows)
    df["start_date_local"] = pd.to_datetime(df["start_date_local"], utc=True)
    return df.sort_values("start_date_local", ignore_index=True)


class FakeActivitiesCache:
    """The parts of StravaActivitiesCache that StravaAnalytics reads, in memory."""

    def __init__(self, activities: pd.DataFrame, streams: dict[int, dict] | None = None):
        self.view = activities
        self.streams = streams or {}
        self.cache_version = 0
        self.summary_names: list[str] = []
        # Runs once the next summaries request has read its streams: a sync landing mid-build
        self.after_next_summaries: Callable[[], None] | None = None

    def get_prepared_view(self) -> pd.DataFrame:
        return self.view

    def _load_to_memory(self) -> pd.DataFrame:
        return self.view

    def get_stream_summaries(self, name: str, activity_ids: Iterable[int],
                             compute: Callable[[dict], Any]) -> dict[int, Any]:
        self.summary_names.append(name)
        summaries = {a: compute(self.streams[a]) for a in activity_ids if a in self.streams}
        hook, self.after_next_summaries = self.after_next_summaries, None
        if hook is not None:
            hook()
        return summaries

    def replace(self, activities: pd.DataFrame, streams: dict[int, dict]) -> None:
        """What a sync does: new data under a new version."""
        self.view, self.streams = activities, streams
        self.cache_version += 1


class FakeUserCache:
    """An athlete without Strava custom zones, and no Strava API behind it."""

    def cached_athlete_zones(self) -> None:
        return None

    def get_athlete_zones(self) -> dict:
        raise AssertionError("tests never reach the Strava API")


def make_analytics(rows: list[dict] | None = None,
                   streams: dict[int, dict] | None = None) -> tuple[StravaAnalytics, FakeActivitiesCache]:
    activities = activities_frame(rows) if rows else pd.DataFrame()
    cache = FakeActivitiesCache(activities, streams)
    return StravaAnalytics(cache, FakeUserCache()), cache  # type: ignore[arg-type]


# ── Street grids ─────────────────────────────────────────────────────────

def street_grid(n: int, spacing: float = 100.0, x0: float = 0.0, y0: float = 0.0,
                first_id: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """An n×n grid of straight streets in projected metres, as the planner and the matcher take
    a network: end node ids (node (i, j) is first_id + j·n + i) and LineStrings oriented u -> v
    with a vertex halfway. Rows first, then columns."""
    from shapely.geometry import LineString

    def node(i: int, j: int) -> int:
        return first_id + j * n + i
    u, v, geoms = [], [], []
    for (i, j, di, dj) in [(i, j, 1, 0) for j in range(n) for i in range(n - 1)] + \
                          [(i, j, 0, 1) for i in range(n) for j in range(n - 1)]:
        a = (x0 + spacing * i, y0 + spacing * j)
        b = (x0 + spacing * (i + di), y0 + spacing * (j + dj))
        u.append(node(i, j))
        v.append(node(i + di, j + dj))
        geoms.append(LineString([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), b]))
    return np.asarray(u, dtype=np.int64), np.asarray(v, dtype=np.int64), np.asarray(geoms, dtype=object)


# ── The activity store the API tests stand the app on ────────────────────

ATHLETE_PROFILE = {"id": 1, "firstname": "Test", "lastname": "Athlete",
                   "shoes": [{"id": "g-shoe-1", "name": "Synthetic trainer", "distance": 100000.0, "retired": False}],
                   "bikes": []}
# Open ocean, far from any coast
_ORIGIN = (0.0, -25.0)
SHOE = "g-shoe-1"
RUN_PACE_S_PER_KM = 300
# The recent runs: every third day back from three days ago, oldest id highest
RECENT_RUNS = 28
STREAM_RUN_IDS = (101, 102)


def _polyline(offset: float) -> str:
    import polyline
    lat, lon = _ORIGIN
    return polyline.encode([(lat + offset, lon), (lat + offset + 0.001, lon + 0.001), (lat + offset, lon + 0.002)])


def _activity(activity_id: int, sport_type: str, day: date, km: float, seconds: int, *, hour: int = 8,
              heartrate: float | None = None, elevation: float = 0.0, name: str | None = None,
              gear_id: str | None = None, **extra: Any) -> dict:
    """An activity as Strava's list endpoint returns it, an hour ahead of UTC."""
    return {
        "id": activity_id, "name": name or f"Synthetic {sport_type.lower()} {activity_id}", "sport_type": sport_type,
        "type": sport_type, "distance": km * 1000.0, "moving_time": seconds, "elapsed_time": seconds + 60,
        "total_elevation_gain": elevation, "start_date": f"{day.isoformat()}T{hour - 1:02d}:00:00Z",
        "start_date_local": f"{day.isoformat()}T{hour:02d}:00:00Z", "utc_offset": 3600.0, "timezone": None,
        "average_speed": km * 1000.0 / seconds, "max_speed": km * 1000.0 / seconds * 1.3,
        "average_heartrate": heartrate, "max_heartrate": heartrate + 20 if heartrate else None,
        "gear_id": gear_id, "map": {"summary_polyline": _polyline(activity_id / 10_000)}, **extra,
    }


def _run_stream(km: float, heartrate: float, with_latlng: bool) -> dict:
    seconds = int(km * RUN_PACE_S_PER_KM)
    streams = steady_stream(seconds, 1000 / RUN_PACE_S_PER_KM, lambda t: heartrate + 5 * (t % 60 < 30))
    streams["altitude"] = [10.0] * seconds
    if with_latlng:
        lat, lon = _ORIGIN
        streams["latlng"] = [[lat, lon + d / 111_320] for d in streams["distance"]]
    return streams


def store_activities(today: date) -> list[dict]:
    """A history of made-up activities: a fixed 2024 (four runs, the last in ISO week 1 of 2025,
    and a ride), then runs every third day over the twelve weeks before `today`, a ride, a swim and
    a hike. The two latest runs have streams."""
    rows = [
        _activity(1, "Run", date(2024, 3, 4), 10, 3000, heartrate=145, elevation=50, name="Synthetic morning run",
                  gear_id=SHOE),
        _activity(2, "Run", date(2024, 3, 6), 5, 1500, heartrate=150, elevation=10),
        _activity(3, "Run", date(2024, 6, 10), 21.1, 6600, heartrate=155, elevation=120, name="Synthetic half"),
        _activity(4, "Ride", date(2024, 6, 15), 40, 4800, heartrate=130, elevation=300),
        _activity(5, "Run", date(2024, 12, 30), 8, 2400, heartrate=140),
        _activity(201, "Ride", today - timedelta(days=10), 40, 4800, heartrate=130, elevation=250),
        _activity(202, "Swim", today - timedelta(days=5), 2, 2400, heartrate=125),
        _activity(203, "Hike", today - timedelta(days=20), 8, 9600, heartrate=110, elevation=400),
    ]
    for k in range(1, RECENT_RUNS + 1):
        km = (6, 8, 10, 12)[k % 4]
        heartrate = 140 + 4 * (k % 4)
        activity_id = 100 + k
        extra: dict[str, Any] = {}
        if activity_id in STREAM_RUN_IDS:
            extra["streams"] = _run_stream(km, heartrate, with_latlng=activity_id == STREAM_RUN_IDS[0])
        if activity_id == STREAM_RUN_IDS[0]:
            extra.update(description="Steady", splits_metric=[{"split": 1, "distance": 1000.0, "moving_time": 300}])
        rows.append(_activity(activity_id, "Run", today - timedelta(days=3 * k), km, int(km * RUN_PACE_S_PER_KM),
                              heartrate=heartrate, elevation=30, name="Tempo run" if k % 4 == 3 else "Easy run",
                              gear_id=SHOE if k % 2 == 0 else None, **extra))
    return rows
