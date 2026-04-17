import logging
from pathlib import Path
import pandas as pd
import json
from datetime import datetime, timedelta

from strava.strava_endpoint import StravaRateLimitError

logger = logging.getLogger(__name__)


class StravaActivitiesCache:
    def __init__(self, cache_dir: Path = Path("./.strava")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.activities_dir = self.cache_dir / "activities"
        self.activities_dir.mkdir(parents=True, exist_ok=True)

        self.metadata_file = self.cache_dir / "metadata.json"
        self.__load_metadata()

        # In-memory cache (lazy-loaded)
        self._memory_cache: pd.DataFrame | None = None
        self._cache_loaded_at: datetime | None = None

        # Monotonic version bumped whenever the underlying dataset changes.
        # Downstream caches (stats, prepared views) use this as a key component
        # so stale entries self-invalidate without needing an explicit clear.
        self._cache_version: int = 0

        # Prepared view for list/filter hot paths (start_date_local parsed once).
        self._prepared_view: pd.DataFrame | None = None
        self._prepared_view_version: int = -1

        # Prepared view with streams JSON parsed once — used by load_activities
        # so downstream callers don't repeatedly re-parse the same JSON strings.
        self._streams_view: pd.DataFrame | None = None
        self._streams_view_version: int = -1

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

    def _get_streams_view(self) -> pd.DataFrame:
        """Return the memory cache with the 'streams' column parsed from JSON
        once, memoized by cache_version. Internal — use load_activities()."""
        if self._streams_view is not None and self._streams_view_version == self._cache_version:
            return self._streams_view
        raw = self._load_to_memory()
        if raw.empty or 'streams' not in raw.columns:
            self._streams_view = raw
        else:
            view = raw.copy()
            view['streams'] = view['streams'].apply(
                lambda x: json.loads(x) if isinstance(x, str) else (None if pd.isna(x) else x)
            )
            self._streams_view = view
        self._streams_view_version = self._cache_version
        return self._streams_view

    def __load_metadata(self):
        """Load cache metadata or initialize if missing."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                self.metadata = json.load(f)
                if 'last_sync' in self.metadata and self.metadata['last_sync']:
                    self.metadata['last_sync'] = datetime.fromisoformat(self.metadata['last_sync'])
            # Back-compat: older metadata files don't have monthly_counts
            self.metadata.setdefault('monthly_counts', {})
        else:
            self.metadata = {
                'last_sync': None,
                'total_activities': 0,
                'earliest_activity': None,
                'latest_activity': None,
                'monthly_counts': {},
            }

    def _invalidate_memory_cache(self):
        """Invalidate the in-memory cache after data changes."""
        self._memory_cache = None
        self._cache_loaded_at = None
        self._cache_version += 1

    def _load_to_memory(self) -> pd.DataFrame:
        """
        Load all Parquet files into memory once.
        This is the 'lazy loading' pattern - only loads when needed.
        """
        if self._memory_cache is not None:
            return self._memory_cache
        
        parquet_files = sorted(self.activities_dir.rglob("*.parquet"))
        
        if not parquet_files:
            self._memory_cache = pd.DataFrame()
            self._cache_loaded_at = datetime.now()
            return self._memory_cache
        
        # Load all monthly files, skipping corrupt ones
        dfs = []
        for f in parquet_files:
            try:
                dfs.append(pd.read_parquet(f))
            except Exception as e:
                logger.warning("Skipping corrupt parquet file %s: %s", f, e)
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
    

    def save_activities(self, activities: list[dict]):
        """Save activities to Parquet files, grouped by month."""
        if not activities:
            return
        
        df = pd.DataFrame(activities)
        df['start_date'] = pd.to_datetime(df['start_date_local'])
        
        # Group by year-month
        df['year_month'] = df['start_date'].dt.tz_localize(None).dt.to_period('M')

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
        
        monthly_counts = self.metadata.setdefault('monthly_counts', {})

        for period, group in df.groupby('year_month'):
            year = period.year
            month_file = self.activities_dir / str(year) / f"{period}.parquet"
            month_file.parent.mkdir(parents=True, exist_ok=True)
            period_key = str(period)

            # Merge with existing data if file exists
            if month_file.exists():
                existing_df = pd.read_parquet(month_file)
                # drop year_month column before saving
                group = group.drop(columns=['year_month'])
                # Drop all-NA columns before concat to avoid dtype issues
                existing_clean = existing_df.dropna(axis=1, how='all')
                group_clean = group.dropna(axis=1, how='all')
                combined = pd.concat([existing_clean, group_clean], ignore_index=True)
                # deduplicate by activity ID
                combined = combined.drop_duplicates(subset=['id'], keep='last')
                combined.to_parquet(month_file, index=False)
                monthly_counts[period_key] = len(combined)
                logger.info("Updated %s (%d activities)", month_file.name, len(combined))
            else:
                # drop year_month column before saving
                group = group.drop(columns=['year_month'])
                group.to_parquet(month_file, index=False)
                monthly_counts[period_key] = len(group)
                logger.info("Created %s (%d activities)", month_file.name, len(group))

        # Update metadata — sum from the monthly_counts dict we just maintained,
        # avoiding a full parquet re-scan on every save.
        self.metadata['last_sync'] = datetime.now()
        self.metadata['total_activities'] = sum(monthly_counts.values())

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
        Load cached activities with optional filters.
        Uses in-memory cache to avoid repeated disk reads.
        
        Args:
            from_date: Filter activities after this date
            to_date: Filter activities before this date
            sports: Filter by sport types
            force_reload: If True, bypass memory cache and reload from disk
        """
        # Force reload from disk if requested
        if force_reload:
            self._invalidate_memory_cache()

        # Use the streams-parsed view — streams JSON is decoded once and
        # cached across calls (invalidated by cache_version). Filtering below
        # produces a fresh DataFrame per call, so callers can freely mutate.
        base = self._get_streams_view()

        if base.empty:
            return base.copy() if base is not None else base

        df = base
        if from_date:
            df = df[df['start_date'] >= from_date]
        if to_date:
            df = df[df['start_date'] <= to_date]
        if sports:
            df = df[df["sport_type"].isin(sports)]
        # Boolean-mask indexing returns a copy, so callers get a safe df
        # when any filter was applied. Otherwise, copy to preserve the
        # prior contract of returning a mutable df.
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

        Reads from the `monthly_counts` metadata dict (maintained incrementally
        by save_activities). Falls back to a one-off parquet scan and persists
        the result for legacy caches that predate monthly_counts.
        """
        monthly_counts = self.metadata.get('monthly_counts')
        if monthly_counts:
            return sum(monthly_counts.values())

        # Legacy path: rebuild monthly_counts from disk once, then persist.
        parquet_files = list(self.activities_dir.rglob("*.parquet"))
        if not parquet_files:
            return 0
        rebuilt: dict[str, int] = {}
        for f in parquet_files:
            try:
                rebuilt[f.stem] = len(pd.read_parquet(f))
            except Exception as e:
                logger.warning("Corrupt parquet file %s: %s", f, e)
        self.metadata['monthly_counts'] = rebuilt
        self.metadata['total_activities'] = sum(rebuilt.values())
        self.__save_metadata()
        return self.metadata['total_activities']
    
    def clear_cache(self):
        """Clear all cached activities and metadata."""
        for file in self.activities_dir.rglob("*.parquet"):
            file.unlink()

        if self.metadata_file.exists():
            self.metadata_file.unlink()
            
        self.metadata = {
            'last_sync': None,
            'total_activities': 0,
            'earliest_activity': None,
            'latest_activity': None,
            'monthly_counts': {},
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
        """Look up a single activity by ID from memory cache.
        Parses streams JSON only for the matched row."""
        df = self._load_to_memory()
        if df.empty:
            return None
        match = df[df["id"] == activity_id]
        if match.empty:
            return None
        row = match.iloc[0].copy()
        # Parse streams JSON for this single row
        if "streams" in row.index and row["streams"] is not None and isinstance(row["streams"], str):
            try:
                row["streams"] = json.loads(row["streams"])
            except (json.JSONDecodeError, TypeError):
                row["streams"] = None
        return row
    
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
        has_streams = df['streams'].notna() if 'streams' in df.columns else pd.Series([False] * total, index=df.index)
        expects_streams = df['upload_id'].notna() if 'upload_id' in df.columns else pd.Series([True] * total, index=df.index)
        streams_expected = int(expects_streams.sum())
        streams_complete = int((expects_streams & has_streams).sum())
        streams_missing = streams_expected - streams_complete

        # Photos: only activities with total_photo_count > 0 are expected to have photos
        photo_count_col = df['total_photo_count'].fillna(0).astype(int) if 'total_photo_count' in df.columns else pd.Series([0] * total)
        expects_photos = photo_count_col > 0
        has_photos = df['photos'].notna() if 'photos' in df.columns else pd.Series([False] * total)
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
            limits = strava_endpoint.get_rate_limits()
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
        needs_work = []
        for idx, activity in df.sort_values('start_date', ascending=False).iterrows():
            is_manual = pd.isna(activity.get('upload_id'))
            has_streams = 'streams' in activity and isinstance(activity.get('streams'), str)
            has_photos = 'photos' in activity and isinstance(activity.get('photos'), str)
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
                    streams = strava_endpoint.get_activity_streams(activity_id)
                    # Save even empty results as '[]' so we don't retry next time
                    activity['streams'] = json.dumps(streams)
                    needs_update = True
                    if not streams:
                        logger.info("No streams returned for activity %s", activity_id)

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