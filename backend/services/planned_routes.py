"""Planned runs: exploration loops over a city's coverage (zone2/route_planner.py), the ones saved
to the planner's list, and their Garmin Connect courses. The Coverage page's planner and the
coach's tools both go through here."""

import asyncio
import hashlib
import json
from typing import TypedDict

import aiosqlite
from pydantic import BaseModel, Field

from backend.errors import Invalid, NotFound
from backend.services import coverage
from backend.services.garmin_courses import clear_courses_cache, course_devices, garmin_call
from zone2.core import Zone2
from zone2.route_planner import ExplorationPlanner, UnreachablePoint, WayClass
from zone2.utils import gpx_track

EXPIRED = "That loop isn't kept any more (z2 restarted, or many loops were planned since): plan it again."
MAX_NAME = 80


class PlanRequest(BaseModel):
    distance_km: float = Field(ge=1, le=42)
    # [lat, lon]; where the city's runs usually start when omitted
    start: tuple[float, float] | None = None
    via: list[tuple[float, float]] = Field(default_factory=list, max_length=ExplorationPlanner.MAX_VIA)
    new_share: float = Field(1.0, ge=0, le=1)
    avoid: list[WayClass] = Field(default_factory=list)
    seed: int = 0


class SavedRoute(TypedDict):
    id: int
    name: str
    distance_km: float
    # When planned
    new_km: float
    # Of those, the km not run since; None when the city's street map changed since it was planned
    new_km_now: float | None
    garmin_course_id: int | None
    created_at: str
    # [lon, lat] in running order
    coordinates: list[list[float]]


class GarminDevice(TypedDict):
    device_id: int
    name: str
    primary: bool


def plan(slug: str, request: PlanRequest) -> coverage.HeldPlan:
    """Plan a loop and hold it for saving, under the plan_id in its feature's properties.
    Invalid when there is no loop."""
    coverage.require_city(slug)
    city = coverage.city_coverage(slug)
    start = request.start or city.usual_start()
    if start is None:
        raise Invalid("Pick a start point: no run matched here yet")
    try:
        planned = coverage.get_matcher(slug).plan_loop(tuple(start), request.distance_km * 1000,
                                                       via_latlon=request.via, new_share=request.new_share,
                                                       avoid=frozenset(request.avoid), seed=request.seed)
    except UnreachablePoint as e:
        raise Invalid(f"Point {int(e.args[0]) + 1} can't be reached on foot from the start") from e
    if planned is None:
        raise Invalid("No loop of that distance through these points")
    feature, new_ways = planned
    key = f"{slug}|{request.model_dump_json()}|{city.state_version()}"
    plan_id = hashlib.sha1(key.encode()).hexdigest()[:16]
    feature["properties"].update(start=list(start), plan_id=plan_id)
    held: coverage.HeldPlan = {"slug": slug, "feature": feature, "new_ways": new_ways, "network": city.network_stamp(),
                               "request": {**request.model_dump(mode="json"), "start": list(start)}}
    coverage.hold_plan(plan_id, held)
    return held


def held(slug: str, plan_id: str) -> coverage.HeldPlan:
    """The city's loop planned under `plan_id`; NotFound once it isn't held any more."""
    plan_held = coverage.held_plan(slug, plan_id)
    if plan_held is None:
        raise NotFound(EXPIRED)
    return plan_held


def _route(row: aiosqlite.Row, new_km_now: float | None) -> SavedRoute:
    return {
        "id": row["id"],
        "name": row["name"],
        "distance_km": row["distance_km"],
        "new_km": row["new_km"],
        "new_km_now": new_km_now,
        "garmin_course_id": row["garmin_course_id"],
        "created_at": row["created_at"],
        "coordinates": json.loads(row["coordinates"]),
    }


def _new_km_now(slug: str, rows: list[aiosqlite.Row]) -> list[float | None]:
    city = coverage.city_coverage(slug)
    return [city.new_km_now(json.loads(r["new_ways"]), r["network"]) for r in rows]


async def _row(db: aiosqlite.Connection, slug: str, route_id: int) -> aiosqlite.Row:
    cursor = await db.execute("SELECT * FROM planned_routes WHERE id = ? AND slug = ?", (route_id, slug))
    row = await cursor.fetchone()
    if row is None:
        raise NotFound(f"There is no saved route {route_id} in {slug}")
    return row


async def _with_new_km_now(slug: str, rows: list[aiosqlite.Row]) -> list[SavedRoute]:
    new_now = await asyncio.to_thread(_new_km_now, slug, rows)
    return [_route(r, n) for r, n in zip(rows, new_now)]


async def saved_routes(db: aiosqlite.Connection, slug: str) -> list[SavedRoute]:
    """The city's saved loops, newest first, with the km of their new streets not run since."""
    cursor = await db.execute("SELECT * FROM planned_routes WHERE slug = ? ORDER BY id DESC", (slug,))
    return await _with_new_km_now(slug, list(await cursor.fetchall()))


async def saved_route(db: aiosqlite.Connection, slug: str, route_id: int) -> SavedRoute:
    (route,) = await _with_new_km_now(slug, [await _row(db, slug, route_id)])
    return route


def default_name(length_km: float, new_km: float) -> str:
    return f"Loop {length_km:.1f} km · {new_km:.1f} new"


async def save(db: aiosqlite.Connection, slug: str, plan_id: str, name: str | None = None,
               request: PlanRequest | None = None) -> SavedRoute:
    """Save the loop planned under `plan_id`. When it isn't held any more, `request` plans it
    again; without one, NotFound."""
    plan_held = coverage.held_plan(slug, plan_id)
    if plan_held is None:
        if request is None:
            raise NotFound(EXPIRED)
        plan_held = await asyncio.to_thread(plan, slug, request)
    props = plan_held["feature"]["properties"]
    name = (name or "").strip()[:MAX_NAME] or default_name(props["length_km"], props["new_km"])
    cursor = await db.execute(
        """INSERT INTO planned_routes (slug, name, distance_km, new_km, coordinates, new_ways, network, request)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (slug, name, props["length_km"], props["new_km"], json.dumps(plan_held["feature"]["geometry"]["coordinates"]),
         json.dumps(plan_held["new_ways"]), plan_held["network"], json.dumps(plan_held["request"])),
    )
    await db.commit()
    return _route(await _row(db, slug, cursor.lastrowid), props["new_km"])


async def delete(db: aiosqlite.Connection, slug: str, route_id: int) -> None:
    """Delete a saved loop; its Garmin course stays."""
    await _row(db, slug, route_id)
    await db.execute("DELETE FROM planned_routes WHERE id = ?", (route_id,))
    await db.commit()


def primary_watch(z2: Zone2) -> GarminDevice | None:
    """The watch courses go to: the primary training device, else the first that takes courses."""
    devices = course_devices(z2)
    if not devices:
        return None
    first = devices[0]
    return {"device_id": first["device_id"], "name": first["name"], "primary": first["primary"]}


async def send_to_garmin(z2: Zone2, db: aiosqlite.Connection, slug: str, route_id: int,
                         device_id: int | None) -> SavedRoute:
    """Create the loop's Garmin course (the first time) and, with a device, queue it for that
    watch, which downloads it on its next sync."""
    row = await _row(db, slug, route_id)
    garmin = z2.garmin_client
    course_id = row["garmin_course_id"]
    if course_id is None:
        gpx = gpx_track(row["name"], json.loads(row["coordinates"]))
        course = await asyncio.to_thread(garmin_call, garmin.create_course, row["name"], gpx)
        course_id = course["courseId"]
        # Kept before sending, so a failed send doesn't create the course twice
        await db.execute("UPDATE planned_routes SET garmin_course_id = ? WHERE id = ?", (course_id, route_id))
        await db.commit()
        clear_courses_cache()
    if device_id is not None:
        await asyncio.to_thread(garmin_call, garmin.send_course, course_id, device_id)
    return await saved_route(db, slug, route_id)
