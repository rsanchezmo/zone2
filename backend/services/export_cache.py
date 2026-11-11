"""The PNG exports' cache, shared so anything that changes what they draw (a sync, the zones,
the resting HR) can drop it."""

from backend.export_cache import ExportCache

export_cache = ExportCache()


def clear_export_cache() -> None:
    """Drop cached PNG exports after activity data changes."""
    export_cache.invalidate_all()
