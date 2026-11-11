"""The coach's street-coverage and route tools, loaded with the coverage capability. They go
through the services the Coverage page's endpoints use and answer in small tables: no route's
shape ever reaches the model, a planned loop comes back as its id and numbers."""

import asyncio
import time
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from backend.agent.tools import AgentDeps, toolset
from backend.errors import NotFound, ServiceError, UpstreamUnavailable
from backend.services import coverage as coverage_service
from backend.services import planned_routes
from backend.services.coverage import AreaKind
from backend.services.planned_routes import PlanRequest
from zone2.map_matching import city_slug
from zone2.route_planner import ExplorationPlanner, WayClass

coverage_tools = toolset()

MAX_ROWS = 50
# Areas with less street than this rank by luck: a stub of the city edge run once reads 100%
MIN_AREA_KM = 1.0
# A Garmin course's km in the city is worth showing when this much of it lies outside
CITY_SHARE_SHOWN = 0.8
AvoidableWay = Literal["main_road", "cycleway", "path", "track", "steps"]
LatLonList = list[float]


def _km(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _latlon(lat: float, lon: float) -> LatLonList:
    return [round(lat, 4), round(lon, 4)]


def _city(slug: str) -> str:
    try:
        return coverage_service.require_city(slug)
    except ServiceError as e:
        raise ModelRetry(f"{e.message}; `cities` lists the slugs.") from e


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class CityRow(TypedDict):
    slug: str
    name: str
    km_run: float
    km_total: float
    pct: float
    runs: int
    # [lat, lon] where its runs usually start; absent before any run is matched
    start: NotRequired[LatLonList]


class CityAdding(TypedDict):
    name: str
    stage: NotRequired[str]
    minutes: NotRequired[int]
    failed: NotRequired[str]


class Cities(TypedDict):
    cities: list[CityRow]
    adding: NotRequired[CityAdding]


def _cities() -> Cities:
    rows: list[CityRow] = []
    for c in coverage_service.city_list():
        row: CityRow = {"slug": c["slug"], "name": c["city_name"], "km_run": round(c["traversed_km"], 1),
                        "km_total": round(c["total_network_km"], 1), "pct": round(c["coverage_pct"], 1),
                        "runs": c["num_matched_activities"]}
        if (start := coverage_service.city_coverage(c["slug"]).usual_start()) is not None:
            row["start"] = _latlon(*start)
        rows.append(row)
    out: Cities = {"cities": rows}
    download = coverage_service.add_status()
    if download["running"] and download["city_name"]:
        minutes = int((time.time() - (download["started_at"] or time.time())) // 60)
        out["adding"] = {"name": download["city_name"], "stage": download["progress"] or "starting", "minutes": minutes}
    elif download["error"] and download["city_name"]:
        out["adding"] = {"name": download["city_name"], "failed": download["error"][:200]}
    return out


@coverage_tools.tool
async def cities(ctx: RunContext[AgentDeps]) -> Cities:
    """Every city with a street coverage map: its `slug` (what the other coverage tools take),
    km run of its km of streets and the %, the runs matched there, and `start`, where its runs
    usually start ([lat, lon]). `adding` is a city being added (its stage and minutes so far),
    or the last one that failed."""
    return await asyncio.to_thread(_cities)


class AreaRow(TypedDict):
    # The district's name, or the H3 cell's id
    name: str
    km_run: float
    km_total: float
    pct: float
    centre: NotRequired[LatLonList]
    district: NotRequired[str]


class AreaTable(TypedDict):
    city: str
    by: str
    # Areas ranked (those with under MIN_AREA_KM of streets are left out)
    ranked: int
    rows: list[AreaRow]


@coverage_tools.tool
async def coverage(
    ctx: RunContext[AgentDeps],
    city: str,
    by: Literal["district", "neighbourhood", "hex"] = "district",
    order: Literal["most", "least"] = "most",
    limit: Annotated[int, Field(ge=1, le=MAX_ROWS)] = 10,
) -> AreaTable:
    """The city's coverage per district, neighbourhood or H3 hex (resolution 8, about 0.7 km²
    each): km run, km of streets and % run, the most or least covered first. Areas with under
    1 km of streets are left out. A hex comes with its id as `name`, its centre [lat, lon] and
    the district it lies in.

    Args:
        city: The city's slug, from `cities`.
    """
    _city(city)
    kind = AreaKind(by)
    try:
        areas = await asyncio.to_thread(coverage_service.area_coverage, city, kind)
    except ServiceError as e:
        raise ModelRetry(e.message) from e
    sized = [a for a in areas if a["total_km"] >= MIN_AREA_KM]
    # Equal shares go to the area with more streets: the bigger block to finish, or the bigger feat
    sized.sort(key=lambda a: (a["coverage_pct"] if order == "least" else -a["coverage_pct"], -a["total_km"]))
    rows: list[AreaRow] = []
    for a in sized[:limit]:
        row: AreaRow = {"name": a["name"], "km_run": round(a["covered_km"], 1), "km_total": round(a["total_km"], 1),
                        "pct": round(a["coverage_pct"], 1)}
        if "centre" in a:
            row["centre"] = _latlon(*a["centre"])
        if "district" in a:
            row["district"] = a["district"]
        rows.append(row)
    return {"city": city, "by": kind.value, "ranked": len(sized), "rows": rows}


class SavedRow(TypedDict):
    id: int
    name: str
    km: float
    # Km of its streets not run yet; null when the city's street map changed since it was planned
    new_km: float | None
    on_garmin: bool
    date: str


class CourseRow(TypedDict):
    course_id: int
    name: str
    km: float
    new_km: float | None
    # The km of it on the city's streets, when much of it lies outside
    city_km: NotRequired[float]


class Routes(TypedDict):
    saved: list[SavedRow]
    saved_total: int
    courses: NotRequired[list[CourseRow]]
    garmin: NotRequired[str]


@coverage_tools.tool
async def routes(ctx: RunContext[AgentDeps], city: str,
                 limit: Annotated[int, Field(ge=1, le=MAX_ROWS)] = 10) -> Routes:
    """The athlete's routes in the city, newest first: loops saved from the planner (`id`, for
    send_route and open_page) and their Garmin Connect courses starting there, each with its km
    and `new_km`, the km of streets on it not run yet (null when unknown).

    Args:
        city: The city's slug, from `cities`.
    """
    _city(city)
    saved = await planned_routes.saved_routes(ctx.deps.db, city)
    out: Routes = {
        "saved": [{"id": r["id"], "name": r["name"], "km": round(r["distance_km"], 1), "new_km": _km(r["new_km_now"]),
                   "on_garmin": r["garmin_course_id"] is not None, "date": r["created_at"][:10]} for r in saved[:limit]],
        "saved_total": len(saved),
    }
    z2 = ctx.deps.z2
    if not z2.garmin_client.enabled:
        out["garmin"] = "not connected"
        return out
    try:
        courses = await asyncio.to_thread(coverage_service.garmin_courses_in, city, z2)
    except ServiceError as e:
        out["garmin"] = f"unavailable: {e.message}"
        return out
    # A saved loop sent to Garmin is listed once, as the saved loop
    sent = {r["garmin_course_id"] for r in saved}
    rows: list[CourseRow] = []
    for c in [c for c in courses if c["course_id"] not in sent][:limit]:
        row: CourseRow = {"course_id": c["course_id"], "name": c["name"], "km": round(c["distance_km"], 1),
                          "new_km": _km(c["new_km"])}
        if c["city_km"] is not None and c["city_km"] < CITY_SHARE_SHOWN * c["distance_km"]:
            row["city_km"] = round(c["city_km"], 1)
        rows.append(row)
    out["courses"] = rows
    return out


class PlannedRoute(TypedDict):
    plan_id: str
    km: float
    new_km: float
    # The share of it on streets not run yet, in %
    new_pct: int


@coverage_tools.tool
async def plan_route(
    ctx: RunContext[AgentDeps],
    city: str,
    start: Point,
    distance_km: Annotated[float, Field(ge=1, le=42)],
    new_share: Annotated[float, Field(ge=0, le=1)] = 1.0,
    avoid: list[AvoidableWay] | None = None,
    via: Annotated[list[Point], Field(max_length=ExplorationPlanner.MAX_VIA)] | None = None,
    variant: int = 0,
) -> PlannedRoute | str:
    """Plan a loop, back to its start, over the city's streets, as the Coverage page's planner
    does. It isn't saved: show it with open_page (coverage, plan_id), save it or send it to the
    watch with save_route.

    It needs the city, the start and the distance: ask for whichever the athlete hasn't given.
    For "from home" or another named place, use its coordinates from your notes; with none, ask
    for them (lat/lon, e.g. copied from a map) and offer to `remember` them (topic preferences).
    With no start stated, you may propose the city's usual start from `cities`.

    Args:
        city: The city's slug, from `cities`.
        start: Where the loop starts and ends.
        distance_km: The loop's length.
        new_share: How much of it on streets not run yet, 0 to 1; as much as it can when omitted.
        avoid: Kinds of way kept off wherever there is another way round.
        via: Up to 3 points the loop must pass.
        variant: Another number plans another loop with the same settings.
    """
    _city(city)
    request = PlanRequest(distance_km=distance_km, start=(start.lat, start.lon),
                          via=[(p.lat, p.lon) for p in via or []], new_share=new_share,
                          avoid=[WayClass(w) for w in avoid or []], seed=variant)
    try:
        held = await asyncio.to_thread(planned_routes.plan, city, request)
    except ServiceError as e:
        return (f"No loop: {e.message}. Try another distance, a start on the city's streets, fewer via "
                "points, a lower new_share or fewer ways to avoid.")
    props = held["feature"]["properties"]
    length, new = props["length_km"], props["new_km"]
    return {"plan_id": props["plan_id"], "km": round(length, 1), "new_km": round(new, 1),
            "new_pct": round(100 * new / length) if length else 0}


class RouteResult(TypedDict):
    id: int
    name: str
    km: float
    new_km: float | None
    on_garmin: bool
    # The watch it was sent to, which gets it on its next sync
    sent_to: NotRequired[str]
    note: NotRequired[str]


def _result(route: planned_routes.SavedRoute) -> RouteResult:
    return {"id": route["id"], "name": route["name"], "km": round(route["distance_km"], 1),
            "new_km": _km(route["new_km_now"]), "on_garmin": route["garmin_course_id"] is not None}


async def _send(ctx: RunContext[AgentDeps], city: str, route_id: int) -> RouteResult:
    """Raises the service's error when Garmin can't take it."""
    z2 = ctx.deps.z2
    if not z2.garmin_client.enabled:
        raise UpstreamUnavailable("Garmin Connect isn't connected in z2 (Profile, Garmin)")
    watch = await asyncio.to_thread(planned_routes.primary_watch, z2)
    out = _result(await planned_routes.send_to_garmin(z2, ctx.deps.db, city, route_id,
                                                      watch["device_id"] if watch else None))
    if watch:
        out["sent_to"] = watch["name"]
    else:
        out["note"] = "No watch takes courses: it's in Garmin Connect only."
    return out


@coverage_tools.tool(requires_approval=True)
async def save_route(ctx: RunContext[AgentDeps], city: str, plan_id: str, name: str | None = None,
                     to_watch: bool = False) -> RouteResult:
    """Save a loop from plan_route to the city's routes, when the athlete asks; with `to_watch`,
    also send it to their Garmin watch as a course.

    Args:
        name: Short; "Loop 10.2 km · 7.9 new" when omitted.
        to_watch: Create its Garmin course and send it to their watch, which gets it on its next sync.
    """
    _city(city)
    try:
        route = await planned_routes.save(ctx.deps.db, city, plan_id, name)
    except ServiceError as e:
        raise ModelRetry(f"It wasn't saved: {e.message}") from e
    if not to_watch:
        return _result(route)
    try:
        return await _send(ctx, city, route["id"])
    except ServiceError as e:
        return {**_result(route), "note": f"Saved, but it didn't reach Garmin: {e.message}"}


@coverage_tools.tool(requires_approval=True)
async def send_route(ctx: RunContext[AgentDeps], city: str, route_id: int) -> RouteResult:
    """Send a saved route (from `routes`) to the athlete's Garmin watch as a course, when they
    ask; the watch gets it on its next sync."""
    _city(city)
    try:
        await planned_routes.saved_route(ctx.deps.db, city, route_id)
    except NotFound as e:
        raise ModelRetry(f"{e.message}; `routes` lists them.") from e
    try:
        return await _send(ctx, city, route_id)
    except ServiceError as e:
        raise ModelRetry(f"It didn't reach Garmin: {e.message}") from e


class Suggestion(TypedDict):
    name: str
    area_km2: float


class CityCandidate(TypedDict):
    # What the name resolves to on OpenStreetMap
    place: str
    country: str
    area_km2: NotRequired[float]
    # [lat, lon]
    centre: LatLonList
    added: bool
    point_only: NotRequired[bool]
    suggestion: NotRequired[Suggestion]


@coverage_tools.tool
async def find_city(ctx: RunContext[AgentDeps], name: str) -> CityCandidate:
    """Look a city up on OpenStreetMap before adding it: the place the name resolves to, its
    country and size, and whether it is added already. A bare name can resolve to another place
    of the same name: unless the place is clearly the one meant, confirm it with the athlete
    before add_city, and look up a fuller name ("Springfield, Illinois") when it isn't.
    `point_only` means OSM has the place only as a point, with no area to cover; `suggestion` is
    the area around it that can be added instead.

    Args:
        name: The city, with its region or country when known.
    """
    try:
        found = await asyncio.to_thread(coverage_service.geocode_city, name)
    except ServiceError as e:
        raise ModelRetry(f"Not found: {e.message}") from e
    out: CityCandidate = {"place": found["display_name"], "country": found["display_name"].rsplit(",", 1)[-1].strip(),
                          "centre": _latlon(found["lat"], found["lon"]),
                          "added": city_slug(name) in coverage_service.known_cities()}
    if "area_km2" in found:
        out["area_km2"] = found["area_km2"]
    if found.get("point_only"):
        out["point_only"] = True
        if suggestion := found.get("suggestion"):
            out["suggestion"] = {"name": suggestion["query"], "area_km2": suggestion["area_km2"]}
    return out


@coverage_tools.tool(requires_approval=True)
async def add_city(ctx: RunContext[AgentDeps], name: str) -> str:
    """Add a city's coverage map, once the athlete agreed to the place find_city showed: give the
    name you looked up (or its suggestion's name). It downloads the city's streets from
    OpenStreetMap in the background, a few minutes for a big city; `cities` shows how far it got.
    Its runs are matched at the next sync (sync_now). One city at a time."""
    try:
        slug = coverage_service.claim_city_download(name)
    except ServiceError as e:
        raise ModelRetry(f"It wasn't started: {e.message}") from e
    ctx.deps.schedule(coverage_service.download_city, name)
    return (f"Downloading {name} (slug {slug}) from OpenStreetMap in the background: a few minutes for a big "
            "city. `cities` shows its progress; its runs are matched at the next sync.")
