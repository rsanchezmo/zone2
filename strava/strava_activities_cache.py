from pathlib import Path
import pandas as pd
import json
from datetime import datetime, timedelta


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


    def __load_metadata(self):
        """Load cache metadata or initialize if missing."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                self.metadata = json.load(f)
                if 'last_sync' in self.metadata:
                    self.metadata['last_sync'] = datetime.fromisoformat(self.metadata['last_sync'])
        else:
            self.metadata = {
                'last_sync': None,
                'total_activities': 0,
                'earliest_activity': None,
                'latest_activity': None,
            }

    def _invalidate_memory_cache(self):
        """Invalidate the in-memory cache after data changes."""
        self._memory_cache = None
        self._cache_loaded_at = None

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
        
        # Load all monthly files
        dfs = [pd.read_parquet(f) for f in parquet_files]
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
        
        for period, group in df.groupby('year_month'):
            year = period.year
            month_file = self.activities_dir / str(year) / f"{period}.parquet"
            month_file.parent.mkdir(parents=True, exist_ok=True)
            
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
                print(f"✓ Updated {month_file.name} ({len(combined)} activities)")
            else:
                # drop year_month column before saving
                group = group.drop(columns=['year_month'])
                group.to_parquet(month_file, index=False)
                print(f"✓ Created {month_file.name} ({len(group)} activities)")
        
        # Update metadata
        self.metadata['last_sync'] = datetime.now()
        self.metadata['total_activities'] = self.count_cached_activities()

        if not df.empty:
            self.metadata['earliest_activity'] = df['start_date'].min().isoformat()
            self.metadata['latest_activity'] = df['start_date'].max().isoformat()

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
        
        # Lazy load: only read from disk on first access
        df = self._load_to_memory().copy()  # Copy to avoid modifying cache
        
        if df.empty:
            return df
        
        # Apply filters on in-memory data (fast)
        if from_date:
            df = df[df['start_date'] >= from_date]
        if to_date:
            df = df[df['start_date'] <= to_date]
        if sports:
            df = df[df["sport_type"].isin(sports)]
        
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
        """Count total cached activities."""
        parquet_files = list(self.activities_dir.rglob("*.parquet"))
        if not parquet_files:
            return 0
        return sum(len(pd.read_parquet(f)) for f in parquet_files)
    
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
        }

        self.__save_metadata()
        self._invalidate_memory_cache()

    @property
    def activities(self) -> pd.DataFrame:
        """Get all cached activities as a DataFrame."""
        return self.load_activities()