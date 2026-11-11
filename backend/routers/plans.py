"""Planned runs: exploration loops over a city's coverage, saved to the planner's list and sent
to Garmin Connect as courses (backend/services/planned_routes.py).

Endpoints (under /api/coverage)
-------------------------------
- POST   /{slug}/plan                — plan a loop (not saved)
- GET    /{slug}/plan/{plan_id}      — a loop planned and not saved yet, while it is held
- GET    /{slug}/plans               — saved loops, with the km of them still new
- POST   /{slug}/plans               — save a planned loop by its plan_id
- DELETE /{slug}/plans/{id}          — delete a saved loop (its Garmin course stays)
- POST   /{slug}/plans/{id}/garmin   — create its Garmin course (once) and send it to a watch
- GET    /{slug}/garmin-courses      — the Garmin courses starting in the city, with their new km
"""
from typing import Any, TypedDict

import aiosqlite
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from backend._serialize import PackedJSONResponse
from backend.db import get_db
from backend.dependencies import get_z2
from backend.services import coverage, planned_routes
from backend.services.planned_routes import MAX_NAME, PlanRequest, SavedRoute
from zone2.core import Zone2
from zone2.map_matching import LoopFeature

router = APIRouter()


@router.post("/{slug}/plan")
def plan_loop(slug: str, payload: PlanRequest) -> LoopFeature:
    """A loop of about distance_km from the start through the via points,
    over streets not run yet (new_share of it where it can) and avoiding the
    given kinds of way, as a GeoJSON Feature with its `length_km`, `new_km`,
    `start` and the `plan_id` to save it by. Another seed draws other
    waypoints."""
    return planned_routes.plan(slug, payload)["feature"]


class HeldPlanView(TypedDict):
    feature: LoopFeature
    request: dict[str, Any]


@router.get("/{slug}/plan/{plan_id}")
def held_plan(slug: str, plan_id: str) -> HeldPlanView | None:
    """The loop planned under `plan_id` with the request it was planned from, so a page can
    show it and plan on from it; null once it isn't held any more (a restart, many plans
    since), which is an answer, not an error."""
    coverage.require_city(slug)
    held = coverage.held_plan(slug, plan_id)
    return None if held is None else {"feature": held["feature"], "request": held["request"]}


@router.get("/{slug}/plans")
async def list_plans(slug: str, db: aiosqlite.Connection = Depends(get_db)) -> list[SavedRoute]:
    """The city's saved loops, newest first, with `new_km_now`: the km of
    their new streets not run since."""
    return await planned_routes.saved_routes(db, slug)


class SaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    plan_id: str
    # Planned again when the plan is no longer held (a restart, many plans since)
    request: PlanRequest


@router.post("/{slug}/plans")
async def save_plan(slug: str, payload: SaveRequest, db: aiosqlite.Connection = Depends(get_db)) -> SavedRoute:
    return await planned_routes.save(db, slug, payload.plan_id, payload.name, payload.request)


@router.delete("/{slug}/plans/{route_id}")
async def delete_plan(slug: str, route_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await planned_routes.delete(db, slug, route_id)
    return {"status": "deleted"}


class GarminSendRequest(BaseModel):
    # None: only create the course in Garmin Connect
    device_id: int | None = None


@router.post("/{slug}/plans/{route_id}/garmin")
async def send_plan_to_garmin(slug: str, route_id: int, payload: GarminSendRequest,
                              db: aiosqlite.Connection = Depends(get_db), z2: Zone2 = Depends(get_z2)) -> SavedRoute:
    """Create the loop's Garmin course (the first time) and queue it for the
    watch, which downloads it on its next sync."""
    return await planned_routes.send_to_garmin(z2, db, slug, route_id, payload.device_id)


@router.get("/{slug}/garmin-courses")
def garmin_courses_in_city(slug: str, z2: Zone2 = Depends(get_z2)) -> Response:
    return PackedJSONResponse(coverage.city_garmin_courses(slug, z2))
