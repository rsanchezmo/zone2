import numpy as np
import pandas as pd


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
