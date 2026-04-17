import time
from threading import Lock
from typing import Any, Hashable


class TTLCache:
    """Small thread-safe TTL + LRU-ish cache. No external deps.

    On `get`, expired entries are dropped lazily. On `put`, when the cache is
    full and the incoming key is new, the entry with the oldest insertion time
    is evicted (O(n); fine at the sizes we use).
    """

    def __init__(self, maxsize: int = 256, ttl_seconds: float = 900.0):
        self._store: dict[Hashable, tuple[float, Any]] = {}
        self._lock = Lock()
        self._maxsize = maxsize
        self._ttl = ttl_seconds

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if (time.monotonic() - ts) > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            if key not in self._store and len(self._store) >= self._maxsize:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
