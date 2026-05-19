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
from typing import Iterable

logger = logging.getLogger(__name__)


# Loaded year-file LRU cap. Each year holds streams for ~150 activities at
# ~75 KB columnar (~30 MB serialized / ~200 MB resident). Keeping a few
# years hot is fine on a Pi.
_MAX_LOADED_YEARS = 4


class StreamsStore:
    def __init__(self, store_dir: Path):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        # year -> {activity_id: columnar_streams}
        self._loaded: "OrderedDict[int, dict[int, dict]]" = OrderedDict()
        # Index of which year each activity_id lives in, built from filenames
        # on first lookup. Avoids opening every pickle just to find one id.
        self._index: dict[int, int] | None = None

    # ── public API ────────────────────────────────────────────────────

    def get(self, activity_id: int) -> dict | None:
        year = self._year_for(activity_id)
        if year is None:
            return None
        return self._load_year(year).get(int(activity_id))

    def get_many(self, activity_ids: Iterable[int]) -> dict[int, dict]:
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
        return self._year_for(int(activity_id)) is not None

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

        for year, updates in by_year.items():
            existing = self._load_year(year, missing_ok=True) if self._year_file(year).exists() else {}
            # Apply updates: None means delete
            for aid, streams in updates.items():
                if streams is None:
                    existing.pop(aid, None)
                else:
                    existing[aid] = streams
            self._write_year(year, existing)
            # Refresh cached copy and index
            self._loaded[year] = existing
            self._loaded.move_to_end(year)
            self._trim_lru()
            if self._index is not None:
                # Patch the year index for the changed ids
                for aid, streams in updates.items():
                    if streams is None:
                        self._index.pop(aid, None)
                    else:
                        self._index[aid] = year

    def all_activity_ids(self) -> set[int]:
        """Set of every activity id that has streams in the store."""
        self._ensure_index()
        return set(self._index.keys()) if self._index else set()

    def clear(self):
        for f in self.store_dir.glob("*.pkl"):
            f.unlink()
        self._loaded.clear()
        self._index = None

    # ── internals ─────────────────────────────────────────────────────

    def _year_file(self, year: int) -> Path:
        return self.store_dir / f"{year}.pkl"

    def _ensure_index(self):
        if self._index is not None:
            return
        index: dict[int, int] = {}
        for f in sorted(self.store_dir.glob("*.pkl")):
            try:
                year = int(f.stem)
            except ValueError:
                continue
            try:
                year_map = self._load_year(year)
            except Exception as e:
                logger.warning("Skipping corrupt streams file %s: %s", f, e)
                continue
            for aid in year_map.keys():
                index[int(aid)] = year
        self._index = index

    def _year_for(self, activity_id: int) -> int | None:
        self._ensure_index()
        return self._index.get(int(activity_id)) if self._index else None

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

    def _write_year(self, year: int, year_map: dict[int, dict]):
        path = self._year_file(year)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file in same dir, then rename
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{year}.", suffix=".pkl.tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(year_map, f, protocol=pickle.HIGHEST_PROTOCOL)
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
