"""Made-up activities and streams for the tests. The repo is public: never put
real activities, coordinates or names here."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

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
