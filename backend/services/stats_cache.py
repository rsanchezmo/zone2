"""The stats endpoints' response cache, shared so anything that changes what they report
(a sync, the zones, the race calendar) can drop it, from a router or the agent."""

from backend._ttl_cache import TTLCache

# Keys are tuples (endpoint, *params, cache_version) so entries self-invalidate when the
# underlying activities dataset changes.
stats_cache = TTLCache(maxsize=256, ttl_seconds=900)


def clear_stats_cache() -> None:
    """Drop cached reports now (TTL and cache_version also handle this lazily; this just
    reclaims memory sooner, and covers changes the activities version doesn't see)."""
    stats_cache.clear()
