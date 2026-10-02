import gzip
import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd
from fastapi import Response
from fastapi.encoders import jsonable_encoder
from starlette.datastructures import Headers
from starlette.types import Receive, Scope, Send


def sanitize(val):
    """Convert numpy/pandas types to native Python types for JSON serialization."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def json_bytes(content: Any) -> bytes:
    """`content` rendered exactly as FastAPI's default JSON response would,
    without first walking all of it through jsonable_encoder (slow on large
    payloads): only values json can't encode natively go through it."""
    return json.dumps(
        content, ensure_ascii=False, allow_nan=False, separators=(",", ":"), default=jsonable_encoder,
    ).encode("utf-8")


class PackedJSON:
    """Serialized JSON plus its gzip encoding and ETag, computed once when
    packed (off the event loop) instead of by GZipMiddleware on every request."""
    __slots__ = ("raw", "gzipped", "etag")
    _MIN_GZIP_BYTES = 1024

    def __init__(self, raw: bytes, gzipped: bytes | None = None):
        self.raw = raw
        if gzipped is None and len(raw) >= self._MIN_GZIP_BYTES:
            gzipped = gzip.compress(raw, compresslevel=9)
        self.gzipped = gzipped
        # Weak: the same tag covers the raw and gzipped encodings
        self.etag = f'W/"{hashlib.blake2b(raw, digest_size=16).hexdigest()}"'

    @classmethod
    def from_gzipped(cls, gzipped: bytes) -> "PackedJSON":
        raw = gzip.decompress(gzipped)
        return cls(raw, gzipped if len(raw) >= cls._MIN_GZIP_BYTES else None)

    def to_gzipped(self) -> bytes:
        return self.gzipped if self.gzipped is not None else gzip.compress(self.raw)


class PackedJSONResponse(Response):
    """Serves a PackedJSON, gzipped when the client accepts it, or a 304 when
    the client already holds it: browsers revalidate (no-cache) with the ETag,
    so a revisit costs a round trip instead of the payload. GZipMiddleware
    leaves responses that already carry a Content-Encoding alone."""
    media_type = "application/json"

    def __init__(self, packed: PackedJSON):
        super().__init__(packed.raw, media_type=self.media_type)
        self.packed = packed
        self.headers["etag"] = packed.etag
        self.headers["cache-control"] = "no-cache"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _etag_matches(Headers(scope=scope).get("if-none-match", ""), self.packed.etag):
            await Response(status_code=304, headers={
                "etag": self.packed.etag, "cache-control": "no-cache", "vary": "Accept-Encoding",
            })(scope, receive, send)
            return
        if self.packed.gzipped is not None:
            self.headers["vary"] = "Accept-Encoding"
            if "gzip" in Headers(scope=scope).get("accept-encoding", ""):
                self.body = self.packed.gzipped
                self.headers["content-encoding"] = "gzip"
                self.headers["content-length"] = str(len(self.body))
        await super().__call__(scope, receive, send)


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """Weak comparison: proxies such as Cloudflare may weaken a tag in transit."""
    def bare(tag: str) -> str:
        tag = tag.strip()
        return tag[2:] if tag.startswith("W/") else tag
    return any(bare(t) == bare(etag) or t.strip() == "*" for t in if_none_match.split(",") if t.strip())
