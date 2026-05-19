"""One-shot migration to the new cache layout.

Two changes happen here, atomically per year:

1. Streams are extracted from each activities parquet (`streams` column,
   JSON-encoded list-of-dicts) and persisted to a per-year pickled
   StreamsStore in columnar shape under `.strava/streams/{year}.pkl`.

2. The 99 monthly activities parquets at `.strava/activities/{year}/{YYYY-MM}.parquet`
   are consolidated into a single per-year file at
   `.strava/activities/{year}.parquet`. The old monthly files (and the now-empty
   year subdirs) are removed.

Idempotent: rerunning is safe — already-consolidated years are skipped,
already-extracted streams are not re-written. After running, the cache loads
in ~0.5–0.8s on the Pi instead of ~9s.

Run from the project root:

    poetry run python scripts/migrate_streams_to_store.py

Or with a custom cache dir:

    poetry run python scripts/migrate_streams_to_store.py --cache-dir /app/.strava
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

# Add project root to sys.path so we can import strava.* when invoked from anywhere
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strava.streams_store import (  # noqa: E402
    StreamsStore,
    from_strava_api,
    points_to_columnar,
    stream_length,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("migrate_streams")


def _normalize_streams_blob(raw) -> dict | None:
    """Same logic as StravaActivitiesCache._normalize_streams. Duplicated
    here so the migration script has no dependency on the cache class
    (which would create the streams dir on import)."""
    if raw is None:
        return None
    if isinstance(raw, float) and pd.isna(raw):
        return None
    if isinstance(raw, str):
        if not raw or raw == "null":
            return None
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not raw:
        return None
    if isinstance(raw, dict):
        first = next(iter(raw.values()), None)
        if isinstance(first, dict) and "data" in first:
            cols = from_strava_api(raw)
            return cols if cols else None
        if all(isinstance(v, list) for v in raw.values()):
            return raw if stream_length(raw) > 0 else None
    if isinstance(raw, list):
        cols = points_to_columnar(raw)
        return cols if cols else None
    return None


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write df.to_parquet via a tmp path + rename, so a crash mid-write
    can't leave a half-written file at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False, engine='pyarrow')
    os.replace(tmp, path)


def migrate(cache_dir: Path, dry_run: bool = False) -> None:
    activities_dir = cache_dir / "activities"
    streams_dir = cache_dir / "streams"

    # Inputs: every parquet anywhere under .strava/activities, both
    # legacy monthly (under year subdirs) and any existing yearly files.
    all_parquets = sorted(activities_dir.rglob("*.parquet"))
    if not all_parquets:
        logger.info("No parquet files under %s; nothing to do.", activities_dir)
        return

    monthly = [p for p in all_parquets if p.parent != activities_dir]
    already_yearly = [p for p in all_parquets if p.parent == activities_dir]

    logger.info(
        "Found %d parquet file(s): %d monthly to consolidate, %d already yearly.",
        len(all_parquets), len(monthly), len(already_yearly),
    )

    if not dry_run:
        streams_dir.mkdir(parents=True, exist_ok=True)
    store = StreamsStore(streams_dir)

    # Group parquets by year for atomic per-year consolidation.
    by_year: dict[int, list[Path]] = {}
    for pf in all_parquets:
        # year is the parent dir name for monthly files, or the stem for yearly
        if pf.parent == activities_dir:
            year_hint = pf.stem
        else:
            year_hint = pf.parent.name
        try:
            year = int(year_hint)
        except ValueError:
            logger.warning("Skipping parquet at unexpected path: %s", pf)
            continue
        by_year.setdefault(year, []).append(pf)

    t_start = time.perf_counter()
    total_rows = 0
    total_streams_extracted = 0
    years_consolidated = 0

    for year in sorted(by_year):
        sources = by_year[year]
        yearly_target = activities_dir / f"{year}.parquet"

        # Skip if this year already has only the yearly file AND no monthly leftovers.
        if (
            len(sources) == 1
            and sources[0] == yearly_target
            and not any(p for p in sources if p.parent != activities_dir)
        ):
            # Already-consolidated year. Still extract streams (idempotent in store).
            df = pd.read_parquet(yearly_target, engine='pyarrow')
            extracted = _extract_streams_into_store(df, year, store, dry_run=dry_run)
            if extracted and "streams" in df.columns and not dry_run:
                df = df.drop(columns=["streams"])
                _atomic_write_parquet(df, yearly_target)
            total_rows += len(df)
            total_streams_extracted += extracted
            logger.info(
                "year %d: already yearly (rows=%d, streams now=%d)",
                year, len(df), extracted,
            )
            continue

        # Read every source file, drop streams column, concat, dedupe by id.
        dfs: list[pd.DataFrame] = []
        for pf in sources:
            try:
                df = pd.read_parquet(pf, engine='pyarrow')
            except Exception as e:
                logger.warning("Skipping unreadable %s: %s", pf, e)
                continue
            dfs.append(df)
        if not dfs:
            logger.warning("year %d: nothing readable, skipping", year)
            continue

        combined = pd.concat(dfs, ignore_index=True)
        if "id" in combined.columns:
            combined = combined.drop_duplicates(subset=["id"], keep="last")

        extracted = _extract_streams_into_store(combined, year, store, dry_run=dry_run)
        if "streams" in combined.columns:
            combined = combined.drop(columns=["streams"])

        if dry_run:
            logger.info(
                "[dry-run] year %d: would write %s with %d rows, %d streams to store, then delete %d monthly file(s)",
                year, yearly_target.name, len(combined), extracted,
                sum(1 for p in sources if p.parent != activities_dir),
            )
        else:
            _atomic_write_parquet(combined, yearly_target)

            # Delete old monthly files (don't delete the new yearly target
            # if it happened to be in `sources`).
            for pf in sources:
                if pf == yearly_target:
                    continue
                try:
                    pf.unlink()
                except FileNotFoundError:
                    pass

            # Remove empty year subdirs
            year_subdir = activities_dir / str(year)
            if year_subdir.is_dir():
                try:
                    if not any(year_subdir.iterdir()):
                        year_subdir.rmdir()
                except OSError as e:
                    logger.warning("Could not remove %s: %s", year_subdir, e)

            logger.info(
                "year %d: wrote %s (rows=%d, streams=%d) — deleted %d monthly files",
                year, yearly_target.name, len(combined), extracted,
                sum(1 for p in sources if p.parent != activities_dir),
            )
            years_consolidated += 1

        total_rows += len(combined)
        total_streams_extracted += extracted

    dt = time.perf_counter() - t_start
    logger.info(
        "%sDone in %.2fs: %d year(s) consolidated, %d total rows, %d streams persisted.",
        "[dry-run] " if dry_run else "",
        dt, years_consolidated, total_rows, total_streams_extracted,
    )

    store_files = sorted(streams_dir.glob("*.pkl"))
    total_size = sum(f.stat().st_size for f in store_files)
    logger.info(
        "Streams store: %d files, %.1fMB total",
        len(store_files), total_size / 1e6,
    )


def _extract_streams_into_store(
    df: pd.DataFrame,
    year: int,
    store: StreamsStore,
    dry_run: bool,
) -> int:
    """Pull the `streams` column out of df rows, normalize to columnar, and
    save into the store under the given year. Returns the count of streams
    actually persisted."""
    if "streams" not in df.columns or "id" not in df.columns:
        return 0
    streams_by_id: dict[int, dict] = {}
    for idx in range(len(df)):
        aid_val = df["id"].iloc[idx]
        if aid_val is None or pd.isna(aid_val):
            continue
        cols = _normalize_streams_blob(df["streams"].iloc[idx])
        if cols is None:
            continue
        streams_by_id[int(aid_val)] = cols

    if not streams_by_id or dry_run:
        return len(streams_by_id)

    activity_year = {aid: year for aid in streams_by_id}
    store.save(streams_by_id, activity_year)
    return len(streams_by_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir", default=".strava",
        help="Path to the .strava cache directory (default: ./.strava)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't write the store or rewrite parquets, just report what would happen",
    )
    args = parser.parse_args()
    cache_dir = Path(args.cache_dir).resolve()
    if not cache_dir.exists():
        logger.error("cache dir does not exist: %s", cache_dir)
        sys.exit(2)
    migrate(cache_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
