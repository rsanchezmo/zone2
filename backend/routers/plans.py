"""Planned runs: exploration loops over a city's coverage (see
zone2/route_planner.py), saved to the planner's list and sent to Garmin
Connect as courses.

Endpoints (under /api/coverage)
-------------------------------
- POST   /{slug}/plan                — plan a loop (not saved)
- GET    /{slug}/plans               — saved loops, with the km of them still new
- POST   /{slug}/plans               — save a planned loop by its plan_id
- DELETE /{slug}/plans/{id}          — delete a saved loop (its Garmin course stays)
- POST   /{slug}/plans/{id}/garmin   — create its Garmin course (once) and send it to a watch
- GET    /{slug}/garmin-courses      — the Garmin courses starting in the city, with their new km
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from threading import Lock

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.db import get_db
from backend.dependencies import get_z2
from backend.routers.coverage import (
    _LAYERS_FORMAT, _cached_json, _get_matcher, _osm_dir, _read_stats_cache, _state_version,
)
from backend.routers.garmin import clear_courses_cache, course_line, course_list
from zone2.core import Zone2
from zone2.garmin_client import GarminUnavailable
from zone2.map_matching import StravaMapMatcher
from zone2.route_planner import ExplorationPlanner, UnreachablePoint, WayClass
from zone2.utils import gpx_track

router = APIRouter()
logger = logging.getLogger(__name__)


class PlanRequest(BaseModel):
    distance_km: float = Field(ge=1, le=42)
    # [lat, lon]; where the city's runs usually start when omitted
    start: tuple[float, float] | None = None
    via: list[tuple[float, float]] = Field(default_factory=list, max_length=ExplorationPlanner.MAX_VIA)
    new_share: float = Field(1.0, ge=0, le=1)
    avoid: list[WayClass] = Field(default_factory=list)
    seed: int = 0


# Recent plans by plan_id, so saving one stores exactly the loop on screen
_MAX_RECENT_PLANS = 32
_recent_plans: OrderedDict[str, dict] = OrderedDict()
_recent_lock = Lock()


def _plan(slug: str, request: PlanRequest) -> dict:
    """Plan a loop and hold it for saving: {slug, feature, new_ways, network,
    request}. Raises 422 when there is no loop."""
    osm_dir = _osm_dir()
    start = request.start or StravaMapMatcher.usual_start_of(osm_dir, slug)
    if start is None:
        raise HTTPException(status_code=422, detail="Pick a start point: no run matched here yet")
    try:
        planned = _get_matcher(slug).plan_loop(tuple(start), request.distance_km * 1000, via_latlon=request.via,
                                               new_share=request.new_share, avoid=frozenset(request.avoid),
                                               seed=request.seed)
    except UnreachablePoint as e:
        raise HTTPException(status_code=422, detail=str(e))
    if planned is None:
        raise HTTPException(status_code=422, detail="No loop of that distance through these points")
    feature, new_ways = planned
    key = f"{slug}|{request.model_dump_json()}|{StravaMapMatcher.state_version_of(osm_dir, slug)}"
    plan_id = hashlib.sha1(key.encode()).hexdigest()[:16]
    feature["properties"].update(start=list(start), plan_id=plan_id)
    plan = {"slug": slug, "feature": feature, "new_ways": new_ways,
            "network": StravaMapMatcher.network_stamp_of(osm_dir, slug),
            "request": {**request.model_dump(mode="json"), "start": list(start)}}
    with _recent_lock:
        _recent_plans[plan_id] = plan
        _recent_plans.move_to_end(plan_id)
        while len(_recent_plans) > _MAX_RECENT_PLANS:
            _recent_plans.popitem(last=False)
    return plan


@router.post("/{slug}/plan")
def plan_loop(slug: str, payload: PlanRequest):
    """A loop of about distance_km from the start through the via points,
    over streets not run yet (new_share of it where it can) and avoiding the
    given kinds of way, as a GeoJSON Feature with its `length_km`, `new_km`,
    `start` and the `plan_id` to save it by. Another seed draws other
    waypoints."""
    return _plan(slug, payload)["feature"]


def _route(row: aiosqlite.Row, new_km_now: float | None) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "distance_km": row["distance_km"],
        "new_km": row["new_km"],
        # None when the city's street map changed since it was planned
        "new_km_now": new_km_now,
        "garmin_course_id": row["garmin_course_id"],
        "created_at": row["created_at"],
        "coordinates": json.loads(row["coordinates"]),
    }


def _new_km_now(slug: str, rows: list[aiosqlite.Row]) -> list[float | None]:
    return [StravaMapMatcher.new_km_now(_osm_dir(), slug, json.loads(r["new_ways"]), r["network"]) for r in rows]


async def _fetch_route(db: aiosqlite.Connection, slug: str, route_id: int) -> aiosqlite.Row:
    cursor = await db.execute("SELECT * FROM planned_routes WHERE id = ? AND slug = ?", (route_id, slug))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return row


@router.get("/{slug}/plans")
async def list_plans(slug: str, db: aiosqlite.Connection = Depends(get_db)):
    """The city's saved loops, newest first, with `new_km_now`: the km of
    their new streets not run since."""
    cursor = await db.execute("SELECT * FROM planned_routes WHERE slug = ? ORDER BY id DESC", (slug,))
    rows = await cursor.fetchall()
    new_now = await run_in_threadpool(_new_km_now, slug, rows)
    return [_route(r, n) for r, n in zip(rows, new_now)]


class SaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    plan_id: str
    # Planned again when the plan is no longer held (a restart, many plans since)
    request: PlanRequest


@router.post("/{slug}/plans")
async def save_plan(slug: str, payload: SaveRequest, db: aiosqlite.Connection = Depends(get_db)):
    with _recent_lock:
        plan = _recent_plans.get(payload.plan_id)
    if plan is None or plan["slug"] != slug:
        plan = await run_in_threadpool(_plan, slug, payload.request)
    props = plan["feature"]["properties"]
    cursor = await db.execute(
        """INSERT INTO planned_routes (slug, name, distance_km, new_km, coordinates, new_ways, network, request)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (slug, payload.name.strip(), props["length_km"], props["new_km"],
         json.dumps(plan["feature"]["geometry"]["coordinates"]), json.dumps(plan["new_ways"]),
         plan["network"], json.dumps(plan["request"])),
    )
    await db.commit()
    row = await _fetch_route(db, slug, cursor.lastrowid)
    return _route(row, props["new_km"])


@router.delete("/{slug}/plans/{route_id}")
async def delete_plan(slug: str, route_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await _fetch_route(db, slug, route_id)
    await db.execute("DELETE FROM planned_routes WHERE id = ?", (route_id,))
    await db.commit()
    return {"status": "deleted"}


class GarminSendRequest(BaseModel):
    # None: only create the course in Garmin Connect
    device_id: int | None = None


def _garmin_call(fn, *args):
    try:
        return fn(*args)
    except GarminUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.warning("Garmin course call %s failed: %s: %s", fn.__name__, type(e).__name__, e)
        raise HTTPException(status_code=502, detail=f"Garmin Connect refused it: {e}")


@router.post("/{slug}/plans/{route_id}/garmin")
async def send_plan_to_garmin(slug: str, route_id: int, payload: GarminSendRequest,
                              db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)):
    """Create the loop's Garmin course (the first time) and queue it for the
    watch, which downloads it on its next sync."""
    row = await _fetch_route(db, slug, route_id)
    garmin = z2.garmin_client
    course_id = row["garmin_course_id"]
    if course_id is None:
        gpx = gpx_track(row["name"], json.loads(row["coordinates"]))
        course = await run_in_threadpool(_garmin_call, garmin.create_course, row["name"], gpx)
        course_id = course["courseId"]
        # Kept before sending, so a failed send doesn't create the course twice
        await db.execute("UPDATE planned_routes SET garmin_course_id = ? WHERE id = ?", (course_id, route_id))
        await db.commit()
        clear_courses_cache()
    if payload.device_id is not None:
        await run_in_threadpool(_garmin_call, garmin.send_course, course_id, payload.device_id)
    row = await _fetch_route(db, slug, route_id)
    (new_now,) = await run_in_threadpool(_new_km_now, slug, [row])
    return _route(row, new_now)


# Part of the Garmin courses' cache version: bump when their fields change
_COURSES_FORMAT = 2


def city_garmin_courses(slug: str, z2: Zone2):
    """The Garmin courses starting in the city, each with `city_km`, the km of
    streets of its part in the city, and `new_km`, those not run yet (both
    null when it doesn't match here). Kept until the coverage or the courses
    change; warmed after syncs."""
    south, west, north, east = (_read_stats_cache(slug) or {}).get("bbox") or _get_matcher(slug).city_bbox()
    courses = [c for c in course_list(z2)
               if c["start"][0] is not None and south <= c["start"][0] <= north and west <= c["start"][1] <= east]

    def build():
        matcher = _get_matcher(slug)
        out = []
        for c in courses:
            line = course_line(z2, c["course_id"])["coordinates"]
            new_km, city_km = matcher.new_km_along([(lat, lon) for lon, lat in line]) or (None, None)
            out.append({**c, "new_km": new_km, "city_km": city_km})
        return out
    version = _state_version(slug) + (_LAYERS_FORMAT, _COURSES_FORMAT,
                                      tuple((c["course_id"], c["name"], c["distance_km"]) for c in courses))
    return _cached_json(("garmin-courses", slug), version, build)


@router.get("/{slug}/garmin-courses")
def garmin_courses_in_city(slug: str, z2: Zone2 = Depends(get_z2)):
    return city_garmin_courses(slug, z2)
