"""The user's Garmin Connect courses and the watches that take them. Live Garmin calls, cached
briefly: courses change only through Connect or the planner (which clears this), a course's line
never."""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from backend._ttl_cache import TTLCache
from zone2.core import Zone2
from zone2.garmin_client import GarminUnavailable

logger = logging.getLogger(__name__)

_courses_cache = TTLCache(maxsize=64, ttl_seconds=300)
_course_points_cache = TTLCache(maxsize=64, ttl_seconds=24 * 3600)


def clear_courses_cache() -> None:
    _courses_cache.clear()


def _live[T](fn: Callable[..., T], *args: Any) -> T:
    try:
        return fn(*args)
    except GarminUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.warning("Garmin %s failed: %s: %s", fn.__name__, type(e).__name__, e)
        raise HTTPException(status_code=502, detail=f"Garmin Connect failed: {e}")


def course_list(z2: Zone2) -> list[dict[str, Any]]:
    """The user's Garmin courses, newest first."""
    cached = _courses_cache.get("courses")
    if cached is None:
        cached = [
            {"course_id": c["courseId"], "name": c["courseName"],
             "distance_km": round((c.get("distanceInMeters") or 0) / 1000, 2),
             "start": [c.get("startLatitude"), c.get("startLongitude")],
             "sport": (c.get("activityType") or {}).get("typeKey"),
             "created_at": c.get("createdDateFormatted")}
            for c in sorted(_live(z2.garmin_client.list_courses), key=lambda c: c.get("createdDate") or 0, reverse=True)
        ]
        _courses_cache.set("courses", cached)
    return cached


def course_line(z2: Zone2, course_id: int) -> dict[str, Any]:
    """The course's line as [lon, lat] coordinates."""
    cached = _course_points_cache.get(course_id)
    if cached is None:
        points = _live(z2.garmin_client.course_points, course_id)
        cached = {"coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in points]}
        _course_points_cache.set(course_id, cached)
    return cached


def course_devices(z2: Zone2) -> list[dict[str, Any]]:
    """Watches that take courses, the primary training device first."""
    cached = _courses_cache.get("devices")
    if cached is None:
        cached = sorted(_live(z2.garmin_client.course_devices), key=lambda d: not d["primary"])
        _courses_cache.set("devices", cached)
    return cached
