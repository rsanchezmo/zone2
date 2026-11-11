import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable, Hashable

from backend._serialize import PackedJSON, PackedJSONResponse, json_bytes


class TTLCache:
    """Small thread-safe cache whose entries expire after `ttl_seconds` (never
    with None, for keys that fully determine their values). No external deps.

    On `get`, expired entries are dropped lazily. On `set`, when the cache is
    full and the incoming key is new, the entry set longest ago is evicted.
    """

    def __init__(self, maxsize: int = 256, ttl_seconds: float | None = 900.0):
        self._store: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = Lock()
        self._maxsize = maxsize
        self._ttl = ttl_seconds

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if self._ttl is not None and (time.monotonic() - ts) > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            if key not in self._store and len(self._store) >= self._maxsize:
                self._store.popitem(last=False)
            self._store[key] = (time.monotonic(), value)
            self._store.move_to_end(key)

    def json_response(self, key: Hashable, build: Callable[[], Any]) -> PackedJSONResponse:
        """JSON response for `key`, serializing (and gzipping) `build()` only on
        a miss: hits serve the stored bytes without encoding anything again."""
        packed = self.get(key)
        if packed is None:
            packed = PackedJSON(json_bytes(build()))
            self.set(key, packed)
        return PackedJSONResponse(packed)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
