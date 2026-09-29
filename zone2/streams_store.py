"""Per-year pickled store for activity streams in columnar form.

Streams are stored separately from the activities Parquet because:
- Streams JSON dominates parquet read time (~5s for 99 files / 1300 activities on a Pi).
- Parsing JSON at every cold load adds another ~4.5s.
- Parsed list-of-dicts in RAM is 4× the JSON byte size; columnar lists are ~2×.

Shape of a single activity's streams:
    {
        "time":             [int, ...],
        "distance":         [float, ...],
        "altitude":         [float | None, ...],
        "velocity_smooth":  [float | None, ...],
        "heartrate":        [int | None, ...],
        "cadence":          [int | None, ...],
        "power":            [int | None, ...],
        "latlng":           [[float, float], ...],
    }

All lists are aligned to the same length. Missing keys mean that channel
wasn't recorded for that activity (e.g. swims have no GPS).
"""

from __future__ import annotations

from collections import OrderedDict
import logging
import os
import pickle
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable

import numpy as np

logger = logging.getLogger(__name__)


# Loaded year-file LRU cap. A year is up to ~8 MB pickled and several times
# that resident; history-wide stats read per-activity summaries instead of
# streams, so only single-activity views and summary builds load years.
_MAX_LOADED_YEARS = 2

_INDEX_FILE = "index.pkl"
_SUMMARIES_FILE = "summaries.pkl"


class StreamsStore:
    def __init__(self, store_dir: Path):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        # Request threads, syncs and summary builds share the store.
        self._lock = RLock()
        # year -> {activity_id: columnar_streams}
        self._loaded: "OrderedDict[int, dict[int, dict]]" = OrderedDict()
        # activity_id -> year, persisted as year -> (file mtime, ids) so a
        # lookup never has to open every pickle to find one id.
        self._index: dict[int, int] | None = None
        self._index_years: dict[int, tuple[int, list[int]]] = {}
        # summary name -> {activity_id: value}
        self._summaries: dict[str, dict[int, Any]] | None = None

    # ── public API ────────────────────────────────────────────────────

    def get(self, activity_id: int) -> dict | None:
        with self._lock:
            year = self._year_for(activity_id)
            if year is None:
                return None
            return self._load_year(year).get(int(activity_id))

    def get_many(self, activity_ids: Iterable[int]) -> dict[int, dict]:
        with self._lock:
            out: dict[int, dict] = {}
            # Group by year to load each year-pickle at most once
            by_year: dict[int, list[int]] = {}
            for aid in activity_ids:
                year = self._year_for(int(aid))
                if year is None:
                    continue
                by_year.setdefault(year, []).append(int(aid))
            for year, ids in by_year.items():
                year_map = self._load_year(year)
                for aid in ids:
                    streams = year_map.get(aid)
                    if streams is not None:
                        out[aid] = streams
            return out

    def has(self, activity_id: int) -> bool:
        with self._lock:
            return self._year_for(int(activity_id)) is not None

    def summaries(self, name: str, activity_ids: Iterable[int],
                  compute: Callable[[dict], Any]) -> dict[int, Any]:
        """Per-activity values derived from streams by `compute`, persisted
        under `name` and computed only for activities not summarized yet, so
        history-wide stats never reload every year of streams. `name` must
        change whenever `compute` does. Activities without streams are absent."""
        with self._lock:
            table = self._load_summaries().setdefault(name, {})
            ids = [int(a) for a in activity_ids]
            missing = [a for a in ids if a not in table and self._year_for(a) is not None]
            if missing:
                for aid, streams in self.get_many(missing).items():
                    table[aid] = compute(streams)
                self._write_atomic(self.store_dir / _SUMMARIES_FILE, self._summaries)
            return {a: table[a] for a in ids if a in table}

    def save(self, streams_by_id: dict[int, dict | None], activity_year: dict[int, int]):
        """Persist a batch of streams, grouped by their activity year.

        `streams_by_id` may include None values (e.g. activity has no streams);
        those entries are removed from the store. `activity_year` must contain
        an int year for every id in `streams_by_id`.
        """
        if not streams_by_id:
            return

        by_year: dict[int, dict[int, dict | None]] = {}
        for aid, streams in streams_by_id.items():
            year = activity_year.get(aid)
            if year is None:
                logger.warning("Skipping streams save for activity %s: no year", aid)
                continue
            by_year.setdefault(year, {})[aid] = streams

        with self._lock:
            self._ensure_index()
            # Drop stale summaries before the streams change on disk: a crash
            # in between only costs recomputing them from the old streams.
            summaries = self._load_summaries()
            stale = [t for t in summaries.values() if any(aid in t for aid in streams_by_id)]
            for table in stale:
                for aid in streams_by_id:
                    table.pop(aid, None)
            if stale:
                self._write_atomic(self.store_dir / _SUMMARIES_FILE, summaries)

            for year, updates in by_year.items():
                existing = self._load_year(year, missing_ok=True) if self._year_file(year).exists() else {}
                # Apply updates: None means delete
                for aid, streams in updates.items():
                    if streams is None:
                        existing.pop(aid, None)
                    else:
                        existing[aid] = streams
                self._write_atomic(self._year_file(year), existing)
                # Refresh cached copy and index
                self._loaded[year] = existing
                self._loaded.move_to_end(year)
                self._trim_lru()
                for aid, streams in updates.items():
                    if streams is None:
                        self._index.pop(aid, None)
                    else:
                        self._index[aid] = year
                self._index_years[year] = (self._year_file(year).stat().st_mtime_ns, list(existing))
            self._write_atomic(self.store_dir / _INDEX_FILE, self._index_years)

    def all_activity_ids(self) -> set[int]:
        """Set of every activity id that has streams in the store."""
        with self._lock:
            self._ensure_index()
            return set(self._index.keys())

    def clear(self):
        with self._lock:
            for f in self.store_dir.glob("*.pkl"):
                f.unlink()
            self._loaded.clear()
            self._index = None
            self._index_years = {}
            self._summaries = None

    # ── internals ─────────────────────────────────────────────────────

    def _year_file(self, year: int) -> Path:
        return self.store_dir / f"{year}.pkl"

    def _ensure_index(self):
        """Build the id -> year index from the persisted one, reopening only
        the year files that changed since it was written."""
        if self._index is not None:
            return
        saved: dict[int, tuple[int, list[int]]] = self._read_pickle(self.store_dir / _INDEX_FILE) or {}
        years: dict[int, tuple[int, list[int]]] = {}
        for f in sorted(self.store_dir.glob("*.pkl")):
            try:
                year = int(f.stem)
            except ValueError:
                continue
            mtime = f.stat().st_mtime_ns
            entry = saved.get(year)
            if entry is None or entry[0] != mtime:
                try:
                    entry = (mtime, list(self._load_year(year)))
                except Exception as e:
                    logger.warning("Skipping corrupt streams file %s: %s", f, e)
                    continue
            years[year] = entry
        if years != saved:
            self._write_atomic(self.store_dir / _INDEX_FILE, years)
        self._index_years = years
        self._index = {aid: year for year, (_, ids) in years.items() for aid in ids}

    def _year_for(self, activity_id: int) -> int | None:
        self._ensure_index()
        return self._index.get(int(activity_id))

    def _load_summaries(self) -> dict[str, dict[int, Any]]:
        if self._summaries is None:
            self._summaries = self._read_pickle(self.store_dir / _SUMMARIES_FILE) or {}
        return self._summaries

    def _load_year(self, year: int, missing_ok: bool = False) -> dict[int, dict]:
        cached = self._loaded.get(year)
        if cached is not None:
            self._loaded.move_to_end(year)
            return cached
        path = self._year_file(year)
        if not path.exists():
            if missing_ok:
                empty: dict[int, dict] = {}
                self._loaded[year] = empty
                self._trim_lru()
                return empty
            raise FileNotFoundError(path)
        with open(path, "rb") as f:
            data = pickle.load(f)
        # Defensive: ensure ids are ints (older test scaffolds may use strings)
        data = {int(k): v for k, v in data.items()}
        self._loaded[year] = data
        self._trim_lru()
        return data

    @staticmethod
    def _read_pickle(path: Path) -> Any | None:
        if not path.exists():
            return None
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning("Ignoring unreadable %s: %s", path, e)
            return None

    @staticmethod
    def _write_atomic(path: Path, obj: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Temp file in the same dir, then rename
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".pkl.tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _trim_lru(self):
        while len(self._loaded) > _MAX_LOADED_YEARS:
            self._loaded.popitem(last=False)


# ── columnar/list-of-dicts conversion helpers ─────────────────────────

# Strava native stream keys (from /streams endpoint). 'latlng' is paired.
STREAM_KEYS = ("time", "distance", "altitude", "velocity_smooth",
               "heartrate", "cadence", "watts", "moving", "temp", "latlng")


def points_to_columnar(points: list[dict]) -> dict:
    """Convert a list-of-dicts (legacy in-memory shape, or API input) to
    columnar. Used during migration and at API ingestion boundaries."""
    if not points:
        return {}
    # Collect keys across all points to be tolerant of missing fields
    keys: set[str] = set()
    for p in points:
        keys.update(p.keys())
    # Special-case lat/lng → latlng
    has_lat_lng = "lat" in keys and "lng" in keys
    keys.discard("lat")
    keys.discard("lng")

    cols: dict[str, list] = {k: [p.get(k) for p in points] for k in keys}
    if has_lat_lng:
        cols["latlng"] = [
            [p.get("lat"), p.get("lng")] if p.get("lat") is not None or p.get("lng") is not None else None
            for p in points
        ]
    return cols


def columnar_to_points(streams: dict) -> list[dict]:
    """Convert columnar dict-of-lists to list-of-dicts. Used at the API edge
    so the wire format the frontend expects stays unchanged."""
    if not streams:
        return []
    n = stream_length(streams)
    keys = [k for k in streams.keys() if k != "latlng"]
    has_latlng = "latlng" in streams
    out: list[dict] = []
    for i in range(n):
        p: dict = {}
        for k in keys:
            arr = streams[k]
            if i < len(arr):
                v = arr[i]
                if v is not None:
                    p[k] = v
        if has_latlng and i < len(streams["latlng"]):
            ll = streams["latlng"][i]
            if ll is not None and len(ll) == 2 and ll[0] is not None and ll[1] is not None:
                p["lat"] = ll[0]
                p["lng"] = ll[1]
        out.append(p)
    return out


def stream_length(streams: dict) -> int:
    """Number of samples in a columnar stream. Empty dict returns 0."""
    if not streams:
        return 0
    # Prefer 'time' (always present from Strava); fall back to first column
    arr = streams.get("time")
    if arr is None:
        arr = next(iter(streams.values()), None)
    return len(arr) if arr is not None else 0


def slice_streams(streams: dict, start: int, end: int) -> dict:
    """Return a columnar streams dict sliced to [start, end). Cheap — list
    slicing in Python is O(end-start) and references shared data."""
    if not streams:
        return {}
    return {k: v[start:end] for k, v in streams.items()}


# Below this implied speed a sample gap counts as stopped (traffic light,
# auto-pause). Walking is ~1.3 m/s, so walked recoveries still count as moving.
STOPPED_SPEED_MS = 0.5
# Sparser streams (pool swims log a sample every few minutes) mix movement and
# rest inside one gap, so stops can't be told apart from slow movement.
MAX_MEDIAN_GAP_S = 60


def _gap_times(streams: dict) -> tuple[np.ndarray, np.ndarray]:
    """Per sample gap: (elapsed seconds, seconds spent stopped).

    A stopped gap still carries the distance covered before halting, so it's
    charged that distance at the pace of the last moving gap rather than
    zero, which would credit free distance."""
    times = np.asarray(streams.get("time") or [], dtype=np.float64)
    n = len(times)
    if n < 2:
        return np.zeros(0), np.zeros(0)
    gaps = np.diff(times)
    elapsed = np.where(gaps > 0, gaps, 0.0)
    stopped_s = np.zeros(n - 1)

    dist_col = streams.get("distance")
    if dist_col is not None and len(dist_col) == n and np.median(gaps) <= MAX_MEDIAN_GAP_S:
        steps = np.diff(np.asarray(dist_col, dtype=np.float64))
        stopped = (gaps > 0) & (steps < STOPPED_SPEED_MS * gaps)
        speeds = np.divide(steps, gaps, out=np.zeros_like(steps), where=gaps > 0)
        last_moving = np.maximum.accumulate(np.where(stopped, 0, np.arange(n - 1)))
        ref_speed = np.where(stopped[last_moving], 0.0, speeds[last_moving])
        charged = np.divide(np.maximum(steps, 0.0), ref_speed,
                            out=elapsed.copy(), where=ref_speed > 0)
        stopped_s = np.where(stopped, elapsed - np.minimum(elapsed, charged), 0.0)

    return elapsed, stopped_s


def moving_time(streams: dict) -> float:
    """Seconds spent moving across a columnar stream, with Strava's
    moving_time semantics: time spent stopped doesn't count."""
    elapsed, stopped_s = _gap_times(streams)
    return float(elapsed.sum() - stopped_s.sum())


def detect_stops(streams: dict, min_duration_s: float = 10) -> list[dict]:
    """Stops long enough to matter, as `{start_km, start_s, duration_s}`.
    Consecutive stopped gaps (a watch still recording while standing) form
    one stop; `start_s` is elapsed time from the start of the stream."""
    _, stopped_s = _gap_times(streams)
    times = streams.get("time") or []
    dists = streams.get("distance") or []
    stops: list[dict] = []
    i = 0
    while i < len(stopped_s):
        if stopped_s[i] <= 0:
            i += 1
            continue
        j = i
        while j + 1 < len(stopped_s) and stopped_s[j + 1] > 0:
            j += 1
        duration = float(stopped_s[i:j + 1].sum())
        if duration >= min_duration_s:
            stops.append({
                "start_km": round((dists[i] or 0) / 1000, 3),
                "start_s": round(times[i] - times[0]),
                "duration_s": round(duration),
            })
        i = j + 1
    return stops


def from_strava_api(api_streams: dict) -> dict:
    """Convert Strava's /streams response (`{type: {data: [...]}}`) to our
    columnar shape. `latlng` stays as list of [lat, lng] pairs."""
    if not api_streams:
        return {}
    out: dict[str, list] = {}
    for key, payload in api_streams.items():
        data = payload.get("data") if isinstance(payload, dict) else None
        if data is None:
            continue
        out[key] = list(data)
    return out
