import hashlib
import time
from io import BytesIO
from threading import Lock


class ExportCache:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 50):
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds
        self._max_entries = max_entries

    def _make_key(self, endpoint: str, params: dict) -> str:
        raw = f"{endpoint}:{sorted(params.items())}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, endpoint: str, params: dict) -> BytesIO | None:
        key = self._make_key(endpoint, params)
        with self._lock:
            entry = self._cache.get(key)
            if entry and (time.time() - entry[0]) < self._ttl:
                buf = BytesIO(entry[1])
                buf.seek(0)
                return buf
            elif entry:
                del self._cache[key]
        return None

    def put(self, endpoint: str, params: dict, buf: BytesIO) -> None:
        key = self._make_key(endpoint, params)
        data = buf.getvalue()
        with self._lock:
            if len(self._cache) >= self._max_entries and key not in self._cache:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest_key]
            self._cache[key] = (time.time(), data)

    def invalidate_all(self) -> None:
        with self._lock:
            self._cache.clear()
