import logging
from pathlib import Path
import pandas as pd
import json
from datetime import datetime, timedelta
from typing import Iterable

from zone2.endpoint import StravaRateLimitError, StravaStreamFetchError
from zone2.streams_store import (
    StreamsStore,
    from_strava_api,
    points_to_columnar,
    stream_length,
)

logger = logging.getLogger(__name__)


def _has_full_photo_list(raw) -> bool:
    """True when the cached photos column holds a real photo list.

    The detail endpoint returns a thumbnail summary dict (primary + count) under
    the same 'photos' key; if that ever lands in the cache it would look like a
    valid string here. Parse it and require a non-empty list to distinguish.
    """
    if not isinstance(raw, str):
        return False
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(parsed, list) and len(parsed) > 0


class StravaActivitiesCache:
    def __init__(self, cache_dir: Path = Path("./.strava")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.activities_dir = self.cache_dir / "activities"
        self.activities_dir.mkdir(parents=True, exist_ok=True)

        self.streams = StreamsStore(self.cache_dir / "streams")

        self.metadata_file = self.cache_dir / "metadata.json"
        self.__load_metadata()

        # In-memory cache (lazy-loaded). Holds activity metadata only —
        # streams live in the separate StreamsStore.
        self._memory_cache: pd.DataFrame | None = None
        self._cache_loaded_at: datetime | None = None

        # Monotonic version bumped whenever the underlying dataset changes.
        # Downstream caches (stats, prepared views) use this as a key component
        # so stale entries self-invalidate without needing an explicit clear.
        self._cache_version: int = 0

        # Prepared view for list/filter hot paths (start_date_local parsed once).
        self._prepared_view: pd.DataFrame | None = None
        self._prepared_view_version: int = -1

    @property
    def cache_version(self) -> int:
        return self._cache_version

    def get_prepared_view(self) -> pd.DataFrame:
        """Return a DataFrame with `start_date_local` parsed once. Rebuilt
        only when the underlying cache changes. Callers MUST NOT mutate it
        (it's the live cache)."""
        if self._prepared_view is not None and self._prepared_view_version == self._cache_version:
            return self._prepared_view
        raw = self._load_to_memory()
        if raw.empty:
            self._prepared_view = raw
        else:
            view = raw.copy()
            view["start_date_local"] = pd.to_datetime(view["start_date_local"])
            self._prepared_view = view
        self._prepared_view_version = self._cache_version
        return self._prepared_view

    # ── streams API ──────────────────────────────────────────────────
    def get_streams(self, activity_id: int) -> dict | None:
        """Columnar streams for one activity, or None if absent.
        Shape: {time: [...], distance: [...], heartrate: [...], ...}."""
        return self.streams.get(int(activity_id))

    def get_streams_bulk(self, activity_ids: Iterable[int]) -> dict[int, dict]:
        """Columnar streams for many activities, keyed by id. Only ids with
        cached streams appear in the result."""
        return self.streams.get_many(activity_ids)

    def has_streams(self, activity_id: int) -> bool:
        return self.streams.has(int(activity_id))

    def __load_metadata(self):
        """Load cache metadata or initialize if missing."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                self.metadata = json.load(f)
                if 'last_sync' in self.metadata and self.metadata['last_sync']:
                    self.metadata['last_sync'] = datetime.fromisoformat(self.metadata['last_sync'])
            # Back-compat: pre-migration metadata used 'monthly_counts'. We
            # ignore stale monthly entries; yearly_counts is rebuilt on next save.
            self.metadata.setdefault('yearly_counts', {})
            self.metadata.pop('monthly_counts', None)
        else:
            self.metadata = {
                'last_sync': None,
                'total_activities': 0,
                'earliest_activity': None,
                'latest_activity': None,
                'yearly_counts': {},
            }

    def _invalidate_memory_cache(self):
        """Invalidate the in-memory cache after data changes."""
        self._memory_cache = None
        self._cache_loaded_at = None
        self._cache_version += 1

    def _load_to_memory(self) -> pd.DataFrame:
        """
        Load all Parquet files into memory once. Streams are NOT loaded here —
        they live in the separate StreamsStore and are fetched lazily per id.
        """
        if self._memory_cache is not None:
            return self._memory_cache

        parquet_files = sorted(self.activities_dir.rglob("*.parquet"))

        if not parquet_files:
            self._memory_cache = pd.DataFrame()
            self._cache_loaded_at = datetime.now()
            return self._memory_cache

        # Load yearly files, skipping the 'streams' column when present
        # (legacy parquets before the StreamsStore migration). Each file's
        # schema may differ, so we drop after read rather than passing a
        # `columns=` filter that would reject when 'streams' isn't in the file.
        dfs = []
        for f in parquet_files:
            try:
                df = pd.read_parquet(f, engine='pyarrow')
            except Exception as e:
                logger.warning("Skipping corrupt parquet file %s: %s", f, e)
                continue
            if 'streams' in df.columns:
                df = df.drop(columns=['streams'])
            dfs.append(df)
        self._memory_cache = pd.concat(dfs, ignore_index=True)
        self._memory_cache['start_date'] = pd.to_datetime(self._memory_cache['start_date_local'])
        self._memory_cache = self._memory_cache.sort_values('start_date')
        self._cache_loaded_at = datetime.now()

        return self._memory_cache

    def __save_metadata(self):
        """Persist cache metadata."""
        meta_copy = self.metadata.copy()

        if meta_copy['last_sync']:
            meta_copy['last_sync'] = meta_copy['last_sync'].isoformat()
        
        with open(self.metadata_file, 'w') as f:
            json.dump(meta_copy, f, indent=2)

    def needs_sync(self, max_age_hours: int = 24) -> bool:
        """Check if cache needs refresh based on last sync time."""
        if self.metadata['last_sync'] is None:
            return True
        age = datetime.now() - self.metadata['last_sync']
        return age > timedelta(hours=max_age_hours)

    def get_last_sync_time(self) -> datetime | None:
        """Return when activity metadata was last successfully synced."""
        return self.metadata.get('last_sync')
    

    def save_activities(self, activities: list[dict]):
        """Save activities to Parquet files, grouped by month.

        If incoming activity dicts carry a 'streams' value (Strava API columnar
        dict, legacy list-of-dicts, or JSON string), it is persisted to the
        separate StreamsStore — never written into the activities parquet."""
        if not activities:
            return

        # Extract streams BEFORE building the DataFrame so we can route them
        # to the StreamsStore and strip them from the parquet payload.
        streams_by_id: dict[int, dict | None] = {}
        activity_year: dict[int, int] = {}
        for act in activities:
            aid = act.get('id')
            if aid is None:
                continue
            aid = int(aid)
            if 'streams' in act:
                raw = act.pop('streams')
                streams_by_id[aid] = _normalize_streams(raw)
            # Year for streams routing (matches activities parquet bucketing).
            sdl = act.get('start_date_local')
            if sdl is not None:
                try:
                    activity_year[aid] = pd.Timestamp(sdl).year
                except Exception:
                    pass

        df = pd.DataFrame(activities)
        df['start_date'] = pd.to_datetime(df['start_date_local'])

        # Group by year (per-year parquets — faster cold load than per-month).
        df['year_bucket'] = df['start_date'].dt.tz_localize(None).dt.year.astype(int)

        def __convert_for_parquet(data):
            """Convert non-parquet-compatible types."""
            if isinstance(data, bool):
                return float(data)
            if isinstance(data, dict):
                return json.dumps(data)
            if isinstance(data, list):
                return json.dumps(data)
            return data

        # Convert incompatible types for Parquet and apply to all columns
        df = df.map(__convert_for_parquet)

        yearly_counts = self.metadata.setdefault('yearly_counts', {})

        for year, group in df.groupby('year_bucket'):
            year_file = self.activities_dir / f"{int(year)}.parquet"
            year_key = str(int(year))

            if year_file.exists():
                existing_df = pd.read_parquet(year_file, engine='pyarrow')
                # Defensive: strip a lingering 'streams' column from pre-migration files.
                if 'streams' in existing_df.columns:
                    existing_df = existing_df.drop(columns=['streams'])
                group = group.drop(columns=['year_bucket'])
                existing_clean = existing_df.dropna(axis=1, how='all')
                group_clean = group.dropna(axis=1, how='all').drop_duplicates(subset=['id'], keep='last')
                # combine_first preserves existing values (photos, detail_fetched)
                # for columns the activity-list response doesn't carry, while the new
                # batch overrides for the columns it does carry (name, distance, etc.).
                existing_indexed = existing_clean.set_index('id')
                group_indexed = group_clean.set_index('id')
                combined = group_indexed.combine_first(existing_indexed).reset_index()
                combined.to_parquet(year_file, index=False, engine='pyarrow')
                yearly_counts[year_key] = len(combined)
                logger.info("Updated %s (%d activities)", year_file.name, len(combined))
            else:
                group = group.drop(columns=['year_bucket'])
                group.to_parquet(year_file, index=False, engine='pyarrow')
                yearly_counts[year_key] = len(group)
                logger.info("Created %s (%d activities)", year_file.name, len(group))

        # Persist any extracted streams. Backfill missing years from the
        # parquet group dates above (rare: incoming activity lacked start_date_local).
        for aid in streams_by_id:
            if aid not in activity_year:
                match = df[df['id'] == aid]
                if not match.empty:
                    activity_year[aid] = int(match['start_date'].iloc[0].year)
        self.streams.save(streams_by_id, activity_year)

        # Update metadata — sum from the yearly_counts dict we just maintained,
        # avoiding a full parquet re-scan on every save.
        self.metadata['last_sync'] = datetime.now()
        self.metadata['total_activities'] = sum(yearly_counts.values())

        if not df.empty:
            batch_earliest = df['start_date'].min()
            batch_latest = df['start_date'].max()
            # Only expand the range, never shrink it
            existing_earliest = datetime.fromisoformat(self.metadata['earliest_activity']) if self.metadata.get('earliest_activity') else None
            existing_latest = datetime.fromisoformat(self.metadata['latest_activity']) if self.metadata.get('latest_activity') else None
            self.metadata['earliest_activity'] = min(batch_earliest, existing_earliest).isoformat() if existing_earliest else batch_earliest.isoformat()
            self.metadata['latest_activity'] = max(batch_latest, existing_latest).isoformat() if existing_latest else batch_latest.isoformat()

        self.__save_metadata()
        self._invalidate_memory_cache()


    def load_activities(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        sports: list[str] | None = None,
        force_reload: bool = False,
    ) -> pd.DataFrame:
        """
        Load cached activities (metadata only — no streams column) with optional filters.

        Streams now live in StreamsStore; use `cache.get_streams(activity_id)` to fetch them.

        Args:
            from_date: Filter activities after this date
            to_date: Filter activities before this date
            sports: Filter by sport types
            force_reload: If True, bypass memory cache and reload from disk
        """
        if force_reload:
            self._invalidate_memory_cache()

        base = self._load_to_memory()
        if base.empty:
            return base.copy() if base is not None else base

        df = base
        if from_date:
            df = df[df['start_date'] >= from_date]
        if to_date:
            df = df[df['start_date'] <= to_date]
        if sports:
            df = df[df["sport_type"].isin(sports)]
        if df is base:
            df = base.copy()
        return df

    def get_last_activity_date(self) -> datetime | None:
        """Get the date of the most recent cached activity."""
        if self.metadata['latest_activity']:
            return datetime.fromisoformat(self.metadata['latest_activity'])
        return None
    
    def get_earliest_activity_date(self) -> datetime | None:
        """Get the date of the earliest cached activity."""
        if self.metadata['earliest_activity']:
            return datetime.fromisoformat(self.metadata['earliest_activity'])
        return None
    
    def count_cached_activities(self) -> int:
        """Count total cached activities.

        Reads from the `yearly_counts` metadata dict (maintained incrementally
        by save_activities). Falls back to a one-off parquet scan and persists
        the result for caches without yearly_counts populated yet.
        """
        yearly_counts = self.metadata.get('yearly_counts')
        if yearly_counts:
            return sum(yearly_counts.values())

        # Legacy / first-run path: rebuild from disk once, then persist.
        parquet_files = list(self.activities_dir.rglob("*.parquet"))
        if not parquet_files:
            return 0
        rebuilt: dict[str, int] = {}
        for f in parquet_files:
            try:
                rebuilt[f.stem] = len(pd.read_parquet(f, engine='pyarrow'))
            except Exception as e:
                logger.warning("Corrupt parquet file %s: %s", f, e)
        self.metadata['yearly_counts'] = rebuilt
        self.metadata['total_activities'] = sum(rebuilt.values())
        self.__save_metadata()
        return self.metadata['total_activities']
    
    def clear_cache(self):
        """Clear all cached activities, streams, and metadata."""
        for file in self.activities_dir.rglob("*.parquet"):
            file.unlink()

        self.streams.clear()

        if self.metadata_file.exists():
            self.metadata_file.unlink()

        self.metadata = {
            'last_sync': None,
            'total_activities': 0,
            'earliest_activity': None,
            'latest_activity': None,
            'yearly_counts': {},
        }

        self.__save_metadata()
        self._invalidate_memory_cache()

    @property
    def activities(self) -> pd.DataFrame:
        """Get all cached activities as a DataFrame."""
        return self.load_activities()

    @property
    def activities_raw(self) -> pd.DataFrame:
        """Get all cached activities without copying or parsing streams.
        WARNING: Do not modify the returned DataFrame — it's the live cache."""
        return self._load_to_memory()

    def get_activity_by_id(self, activity_id: int) -> pd.Series | None:
        """Look up a single activity by ID from the in-memory metadata cache.

        Streams are NOT attached — fetch them separately via get_streams(activity_id)."""
        df = self._load_to_memory()
        if df.empty:
            return None
        match = df[df["id"] == activity_id]
        if match.empty:
            return None
        return match.iloc[0].copy()
    
    # Fields that come from the detail endpoint (not the list/summary endpoint)
    DETAIL_FIELDS = ['description', 'calories', 'splits_metric', 'best_efforts', 'laps', 'gear',
                     'perceived_exertion', 'suffer_score', 'segment_efforts', 'similar_activities', 'device_name']

    def pull_activity_detail(self, activity_id: int, strava_endpoint) -> bool:
        """Fetch detail from Strava API for a single activity and merge into cache.
        Returns True if new data was saved."""
        row = self.get_activity_by_id(activity_id)
        if row is None:
            return False
        # Already has detail?
        if row.get('detail_fetched') == True:
            return False

        detail = strava_endpoint.get_activity_detail(activity_id)

        activity = row.to_dict()
        if detail:
            for field in self.DETAIL_FIELDS:
                val = detail.get(field)
                if val is not None:
                    if isinstance(val, (dict, list)):
                        activity[field] = json.dumps(val)
                    else:
                        activity[field] = val
        activity['detail_fetched'] = True

        self.save_activities([activity])
        return True

    def resync_activity(self, activity_id: int, strava_endpoint, include_streams: bool = False) -> bool:
        """Re-fetch a single activity from Strava and merge updates into the cached row.

        Pulls the detail endpoint (which carries both summary fields like name/description
        and detail-only fields), refetches the full photo list when the activity has any,
        and optionally re-fetches streams. The detail endpoint also returns a 'photos'
        field, but it's a thumbnail summary (primary + count) — caching that would clobber
        the full photo list, so it's dropped before the merge and photos are refreshed via
        the dedicated /photos endpoint instead.

        Returns True if the cache was updated.
        """
        if self.get_activity_by_id(activity_id) is None:
            return False

        detail = strava_endpoint.get_activity_detail(activity_id)
        if not detail:
            return False

        activity = {k: v for k, v in detail.items() if k != 'photos'}
        activity['detail_fetched'] = True

        photo_count = int(detail.get('total_photo_count', 0) or 0)
        if photo_count > 0:
            photos = strava_endpoint.get_activity_photos(activity_id)
            if photos:
                activity['photos'] = json.dumps(photos)

        if include_streams:
            try:
                streams = strava_endpoint.get_activity_streams(activity_id)
                activity['streams'] = streams or {}
            except StravaStreamFetchError as e:
                logger.warning("Skipping streams refresh for activity %s: %s", activity_id, e)

        self.save_activities([activity])
        return True

    def save_activities_df(self, df: pd.DataFrame):
        """Save a DataFrame of activities to the cache."""
        activities = df.to_dict(orient='records')
        self.save_activities(activities)
    
    def get_cache_completeness(self) -> dict:
        """Return completeness stats for streams and photos across all cached activities."""
        df = self._load_to_memory()
        if df.empty:
            return {
                'total': 0,
                'streams': {'complete': 0, 'missing': 0, 'total_expected': 0},
                'photos': {'complete': 0, 'missing': 0, 'total_expected': 0},
                'detail': {'complete': 0, 'missing': 0, 'total_expected': 0},
                'missing_streams_ids': [],
                'missing_photos_ids': [],
                'missing_detail_ids': [],
            }

        total = len(df)

        # Streams: only device-recorded activities (upload_id present) can have streams.
        # Manual entries have no upload_id and will never return stream data.
        streams_ids = self.streams.all_activity_ids()
        has_streams = df['id'].astype('int64').isin(streams_ids)
        expects_streams = df['upload_id'].notna() if 'upload_id' in df.columns else pd.Series([True] * total, index=df.index)
        streams_expected = int(expects_streams.sum())
        streams_complete = int((expects_streams & has_streams).sum())
        streams_missing = streams_expected - streams_complete

        # Photos: only activities with total_photo_count > 0 are expected to have photos
        photo_count_col = df['total_photo_count'].fillna(0).astype(int) if 'total_photo_count' in df.columns else pd.Series([0] * total)
        expects_photos = photo_count_col > 0
        has_photos = df['photos'].apply(_has_full_photo_list) if 'photos' in df.columns else pd.Series([False] * total, index=df.index)
        photos_complete = int((expects_photos & has_photos).sum())
        photos_expected = int(expects_photos.sum())
        photos_missing = photos_expected - photos_complete

        # Detail: check the explicit detail_fetched flag
        has_detail = df['detail_fetched'].eq(True) if 'detail_fetched' in df.columns else pd.Series([False] * total, index=df.index)
        detail_complete = int(has_detail.sum())
        detail_expected = total
        detail_missing = detail_expected - detail_complete

        # IDs of activities missing data (most recent first)
        missing_streams_ids = df.loc[expects_streams & ~has_streams, 'id'].tolist() if streams_missing > 0 else []
        missing_photos_ids = df.loc[expects_photos & ~has_photos, 'id'].tolist() if photos_missing > 0 else []
        missing_detail_ids = df.loc[~has_detail, 'id'].tolist() if detail_missing > 0 else []

        return {
            'total': total,
            'streams': {'complete': streams_complete, 'missing': streams_missing, 'total_expected': streams_expected},
            'photos': {'complete': photos_complete, 'missing': photos_missing, 'total_expected': photos_expected},
            'detail': {'complete': detail_complete, 'missing': detail_missing, 'total_expected': detail_expected},
            'missing_streams_ids': missing_streams_ids,
            'missing_photos_ids': missing_photos_ids,
            'missing_detail_ids': missing_detail_ids,
        }

    def sync_streams(self, strava_endpoint, activity_ids: list[int] | None = None):
        """Sync streams, detail fields (description, calories, splits, best_efforts), and photos.

        Args:
            strava_endpoint: The StravaEndpoint instance to fetch data from
            activity_ids: List of activity IDs to sync. If None, syncs all activities.
        """

        # Check rate limit budget before starting
        try:
            limits = strava_endpoint.get_rate_limits(refresh=True)
            fifteen = limits['fifteen_min']
            daily = limits['daily']
            remaining = min(fifteen['limit'] - fifteen['usage'], daily['limit'] - daily['usage'])
            logger.info(
                "Rate limit: %d/%d (15min), %d/%d (daily) — %d requests available",
                fifteen['usage'], fifteen['limit'], daily['usage'], daily['limit'], remaining,
            )
            if remaining <= 1:
                logger.warning("No rate limit budget available. Try again later.")
                return
        except Exception as e:
            logger.debug("Rate-limit pre-check skipped: %s", e)  # Non-critical

        # Load raw activities (without parsing streams JSON — we only need metadata here)
        self._invalidate_memory_cache()
        df = self._load_to_memory().copy()

        if df.empty:
            logger.info("No activities to sync")
            return

        # Filter to specific activity IDs if provided
        if activity_ids is not None:
            df = df[df['id'].isin(activity_ids)]

        if df.empty:
            logger.info("No matching activities found")
            return

        # Pre-filter: only iterate activities that actually need work (recent first)
        # Skip manual activities (no upload_id) — they have no device data and will never have streams.
        cached_stream_ids = self.streams.all_activity_ids()
        needs_work = []
        for idx, activity in df.sort_values('start_date', ascending=False).iterrows():
            is_manual = pd.isna(activity.get('upload_id'))
            has_streams = int(activity['id']) in cached_stream_ids
            has_photos = _has_full_photo_list(activity.get('photos'))
            has_detail = activity.get('detail_fetched') == True
            photo_count = int(activity.get('total_photo_count', 0) or 0)
            needs_photos = not has_photos and photo_count > 0
            needs_streams = not has_streams and not is_manual
            needs_detail = not has_detail

            if needs_streams or needs_photos or needs_detail:
                needs_work.append((idx, activity, needs_streams, needs_photos, needs_detail, photo_count))

        total = len(df)
        skipped_count = total - len(needs_work)
        logger.info("%d activities need work, %d already complete", len(needs_work), skipped_count)

        synced_count = 0
        updated_activities = []
        BATCH_SIZE = 50  # Save every 50 to avoid losing progress

        rate_limited = False
        try:
            for i, (idx, activity, needs_streams, needs_photos, needs_detail, photo_count) in enumerate(needs_work):
                activity_id = activity['id']
                needs_update = False

                if needs_streams:
                    logger.info("[%d/%d] Fetching streams for activity %s...", i + 1, len(needs_work), activity_id)
                    try:
                        streams = strava_endpoint.get_activity_streams(activity_id)
                        # 200 OK with empty body = legitimately no streams (manual /
                        # indoor activity). Cache as empty dict to skip future retries.
                        activity['streams'] = streams or {}
                        needs_update = True
                        if not streams:
                            logger.info("No streams returned for activity %s", activity_id)
                    except StravaStreamFetchError as e:
                        # Transient (5xx, 404, network). Don't cache; let the next
                        # backfill retry. Continue to detail/photos for this activity.
                        logger.warning("Skipping streams for activity %s: %s — will retry next sync", activity_id, e)

                if needs_detail:
                    logger.info("[%d/%d] Fetching detail for activity %s...", i + 1, len(needs_work), activity_id)
                    detail = strava_endpoint.get_activity_detail(activity_id)
                    if detail:
                        for field in self.DETAIL_FIELDS:
                            val = detail.get(field)
                            if val is not None:
                                if isinstance(val, (dict, list)):
                                    activity[field] = json.dumps(val)
                                else:
                                    activity[field] = val
                    # Mark as fetched even if detail returned nothing, so we don't retry
                    activity['detail_fetched'] = True
                    needs_update = True

                if needs_photos:
                    logger.info("[%d/%d] Fetching photos for activity %s (%d photos)...", i + 1, len(needs_work), activity_id, photo_count)
                    photos = strava_endpoint.get_activity_photos(activity_id)
                    if photos:
                        activity['photos'] = json.dumps(photos)
                        needs_update = True

                if needs_update:
                    updated_activities.append(activity.to_dict())
                    synced_count += 1

                # Save in batches to avoid losing progress on rate limit / crash
                if len(updated_activities) >= BATCH_SIZE:
                    logger.info("Saving batch of %d activities...", len(updated_activities))
                    self.save_activities(updated_activities)
                    updated_activities = []

        except StravaRateLimitError as e:
            rate_limited = True
            logger.warning("Rate limit reached — stopping sync. %s", e)

        # Save remaining (including partial progress on rate limit)
        if updated_activities:
            logger.info(
                "Saving %s batch of %d activities...",
                "partial" if rate_limited else "final", len(updated_activities),
            )
            self.save_activities(updated_activities)

        if rate_limited:
            logger.warning(
                "Synced %d activities before rate limit. Re-run later to continue.",
                synced_count,
            )
        elif synced_count > 0:
            logger.info("Synced %d activities, skipped %d (already had data)", synced_count, skipped_count)
        else:
            logger.info("All %d activities already have the requested data", skipped_count)


def _normalize_streams(raw) -> dict | None:
    """Coerce any of the shapes streams arrive in into the columnar dict
    persisted by StreamsStore. Returns None for absent / empty streams so
    StreamsStore can treat them as a delete on save."""
    if raw is None:
        return None
    # JSON string from legacy parquet
    if isinstance(raw, str):
        if not raw or raw == 'null':
            return None
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not raw:
        return None
    # Strava /streams API: {type: {data: [...]}}
    if isinstance(raw, dict):
        first = next(iter(raw.values()), None)
        if isinstance(first, dict) and 'data' in first:
            return from_strava_api(raw) or None
        # Already columnar (list values aligned to a length)
        if all(isinstance(v, list) for v in raw.values()):
            return raw if stream_length(raw) > 0 else None
    # Legacy list-of-dicts shape
    if isinstance(raw, list):
        cols = points_to_columnar(raw)
        return cols if cols else None
    return None
