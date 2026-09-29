import json
from typing import Any

import numpy as np
import pandas as pd
from fastapi.encoders import jsonable_encoder


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
