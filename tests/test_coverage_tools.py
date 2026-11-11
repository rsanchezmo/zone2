"""The coach's street-coverage and route tools on the synthetic city (tests.synthetic.write_grid_city):
small tables with no route's shape in them, the same service path as the Coverage page's
endpoints, held loops the page can show, and the writes waiting for a yes. Garmin, the geocoder
and the OSM download are stubbed; every place and run is made up."""
import asyncio
import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ModelRetry
from shapely.geometry import box

import backend.db as calendar_db
from backend.agent import chat
from backend.agent import coverage as coverage_tools
from backend.agent import tools
from backend.agent.__main__ import _scripted
from backend.agent.agent import ON_DEMAND, build_agent
from backend.services import coverage, planned_routes
from tests.conftest import OfflineApp
from tests.synthetic import GRID_CITY, grid_latlon

START = dict(zip(("lat", "lon"), grid_latlon(0, 0)))
GRID_CENTRE = dict(zip(("lat", "lon"), grid_latlon(5.5, 5.5)))


class Schedule:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __call__(self, fn: Callable[..., Any], *args: Any) -> None:
        self.calls.append((fn.__name__, args))


def run[T](app: OfflineApp, work: Callable[[SimpleNamespace], Awaitable[T]], schedule: Schedule | None = None) -> T:
    """`work` with a tool context over the offline app and its calendar database."""
    async def go() -> T:
        async with calendar_db.connect_db() as db:
            deps = tools.AgentDeps(z2=app.z2, db=db, schedule=schedule or Schedule())
            return await work(SimpleNamespace(deps=deps))
    return asyncio.run(go())


def shapeless(output: Any) -> None:
    """No line, polygon or coordinate list anywhere in a tool's output."""
    text = json.dumps(output)
    for key in ("coordinates", "geometry", "bbox", "new_ways"):
        assert f'"{key}"' not in text
    assert len(text) < 2500


def plan(app: OfflineApp, slug: str, km: float = 3, **kwargs: Any) -> dict:
    return run(app, lambda ctx: coverage_tools.plan_route(ctx, slug, coverage_tools.Point(**START), km, **kwargs))


# ── Reading ──────────────────────────────────────────────────────────────

def test_cities_lists_each_city_with_its_numbers_and_usual_start(offline_app: OfflineApp, coverage_city: str):
    out = run(offline_app, coverage_tools.cities)
    shapeless(out)
    [city] = out["cities"]
    assert (city["slug"], city["name"], city["runs"]) == (coverage_city, GRID_CITY, 2)
    assert city["km_total"] == pytest.approx(26.4, abs=0.1)
    assert city["km_run"] == pytest.approx(2.2, abs=0.1)
    assert city["pct"] == pytest.approx(100 * city["km_run"] / city["km_total"], abs=0.5)
    # Both runs start at the south-west corner, to about 10 m
    assert city["start"] == pytest.approx([START["lat"], START["lon"]], abs=2e-4)
    assert "adding" not in out


@pytest.mark.parametrize("order", ["most", "least"])
def test_coverage_by_hex_ranks_cells_with_their_centre_and_district(offline_app: OfflineApp, coverage_city: str,
                                                                     order: str):
    out = run(offline_app, lambda ctx: coverage_tools.coverage(ctx, coverage_city, by="hex", order=order, limit=2))
    shapeless(out)
    assert (out["city"], out["by"]) == (coverage_city, "hex")
    assert 0 < len(out["rows"]) <= 2 <= out["ranked"]
    pcts = [r["pct"] for r in out["rows"]]
    assert pcts == sorted(pcts, reverse=order == "most")
    for row in out["rows"]:
        assert row["name"].startswith("88") and row["km_total"] >= coverage_tools.MIN_AREA_KM
        assert row["district"] in {"West", "East"}
        assert len(row["centre"]) == 2 and abs(row["centre"][0] - GRID_CENTRE["lat"]) < 0.02


def test_coverage_by_district_reads_the_pages_layer_without_loading_the_city(offline_app: OfflineApp,
                                                                              coverage_city: str):
    page = offline_app.client.get(f"/api/coverage/{coverage_city}/districts", params={"admin_level": 9, "geometry": True})
    assert page.status_code == 200 and all("geometry" in d for d in page.json())
    coverage._matchers.clear()
    out = run(offline_app, lambda ctx: coverage_tools.coverage(ctx, coverage_city))
    assert not coverage._matchers
    shapeless(out)
    assert {r["name"] for r in out["rows"]} == {"West", "East"} and out["ranked"] == 2
    assert {r["name"]: r["pct"] for r in out["rows"]} == {d["name"]: round(d["coverage_pct"], 1) for d in page.json()}


def test_an_unknown_city_asks_for_a_slug_from_cities(offline_app: OfflineApp, coverage_city: str):
    with pytest.raises(ModelRetry, match="cities"):
        run(offline_app, lambda ctx: coverage_tools.coverage(ctx, "atlantis"))


# ── Planning, and the page showing a held loop ───────────────────────────

def test_a_planned_loop_comes_back_as_its_id_and_numbers_and_the_page_can_show_it(offline_app: OfflineApp,
                                                                                    coverage_city: str):
    out = plan(offline_app, coverage_city, 3, new_share=0.8, avoid=["steps"])
    assert set(out) == {"plan_id", "km", "new_km", "new_pct"}
    assert out["km"] == pytest.approx(3, rel=0.25) and 0 < out["new_km"] <= out["km"]
    assert abs(out["new_pct"] - 100 * out["new_km"] / out["km"]) < 2

    held = offline_app.client.get(f"/api/coverage/{coverage_city}/plan/{out['plan_id']}")
    assert held.status_code == 200
    feature, request = held.json()["feature"], held.json()["request"]
    assert feature["properties"]["plan_id"] == out["plan_id"]
    assert feature["properties"]["length_km"] == pytest.approx(out["km"], abs=0.05)
    assert len(feature["geometry"]["coordinates"]) > 2
    assert request == {"distance_km": 3.0, "start": [START["lat"], START["lon"]], "via": [], "new_share": 0.8,
                       "avoid": ["steps"], "seed": 0}
    # The page plans the same request to the same loop
    again = offline_app.client.post(f"/api/coverage/{coverage_city}/plan", json=request).json()
    assert again["properties"]["plan_id"] == out["plan_id"]


def test_a_loop_no_longer_held_is_an_answer_for_the_page_and_a_retry_for_the_coach(offline_app: OfflineApp,
                                                                                    coverage_city: str):
    gone = offline_app.client.get(f"/api/coverage/{coverage_city}/plan/0123456789abcdef")
    assert gone.status_code == 200 and gone.json() is None
    with pytest.raises(ModelRetry, match="plan it again"):
        run(offline_app, lambda ctx: coverage_tools.save_route(ctx, coverage_city, "0123456789abcdef"))


def test_no_loop_is_said_plainly_with_what_to_change(offline_app: OfflineApp, coverage_city: str):
    far = coverage_tools.Point(lat=START["lat"] + 1, lon=START["lon"])
    out = run(offline_app, lambda ctx: coverage_tools.plan_route(ctx, coverage_city, far, 3))
    assert isinstance(out, str) and out.startswith("No loop") and "distance" in out
    # The page hears the same, as a 400 with the reason
    page = offline_app.client.post(f"/api/coverage/{coverage_city}/plan",
                                   json={"distance_km": 3, "start": [far.lat, far.lon]})
    assert page.status_code == 400 and "No loop" in page.json()["detail"]


def test_the_router_and_the_tools_plan_and_save_through_the_same_service(offline_app: OfflineApp, coverage_city: str,
                                                                          monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    for name in ("plan", "save"):
        real = getattr(planned_routes, name)

        def spy(*args: Any, _real: Any = real, _name: str = name, **kwargs: Any) -> Any:
            calls.append(_name)
            return _real(*args, **kwargs)
        monkeypatch.setattr(planned_routes, name, spy)

    by_page = offline_app.client.post(f"/api/coverage/{coverage_city}/plan",
                                      json={"distance_km": 3, "start": [START["lat"], START["lon"]], "seed": 1}).json()
    by_coach = plan(offline_app, coverage_city, 3)
    assert calls == ["plan", "plan"]
    # A loop planned by either is saved by the other
    saved = run(offline_app, lambda ctx: coverage_tools.save_route(ctx, coverage_city, by_page["properties"]["plan_id"],
                                                                    "Synthetic loop"))
    page_saved = offline_app.client.post(f"/api/coverage/{coverage_city}/plans", json={
        "name": "From the coach", "plan_id": by_coach["plan_id"], "request": {"distance_km": 3}}).json()
    assert calls == ["plan", "plan", "save", "save"]
    listed = offline_app.client.get(f"/api/coverage/{coverage_city}/plans").json()
    assert [r["id"] for r in listed] == [page_saved["id"], saved["id"]]
    assert page_saved["distance_km"] == pytest.approx(by_coach["km"], abs=0.05)


def test_routes_lists_saved_loops_and_garmin_courses_without_their_lines(offline_app: OfflineApp, coverage_city: str,
                                                                          monkeypatch: pytest.MonkeyPatch):
    loop = plan(offline_app, coverage_city, 3)
    saved = run(offline_app, lambda ctx: coverage_tools.save_route(ctx, coverage_city, loop["plan_id"]))
    assert saved["name"] == f"Loop {loop['km']:.1f} km · {loop['new_km']:.1f} new"

    out = run(offline_app, lambda ctx: coverage_tools.routes(ctx, coverage_city))
    shapeless(out)
    assert out == {"saved": [{**{k: saved[k] for k in ("id", "name", "km", "new_km", "on_garmin")},
                              "date": out["saved"][0]["date"]}], "saved_total": 1, "garmin": "not connected"}

    # With Garmin: its courses here, a saved loop sent there listed once
    monkeypatch.setattr(offline_app.z2, "garmin_client", SimpleNamespace(enabled=True))
    course = {"course_id": 5, "name": "Synthetic course", "distance_km": 8.04, "start": [0.0, 3.0], "sport": "running",
              "created_at": None, "new_km": 2.5, "city_km": 4.0}
    monkeypatch.setattr(coverage, "garmin_courses_in", lambda slug, z2: [course, {**course, "course_id": 6}])
    asyncio.run(_set_course(saved["id"], 6))
    out = run(offline_app, lambda ctx: coverage_tools.routes(ctx, coverage_city))
    shapeless(out)
    assert out["courses"] == [{"course_id": 5, "name": "Synthetic course", "km": 8.0, "new_km": 2.5, "city_km": 4.0}]
    assert out["saved"][0]["on_garmin"] is True


async def _set_course(route_id: int, course_id: int) -> None:
    async with calendar_db.connect_db() as db:
        await db.execute("UPDATE planned_routes SET garmin_course_id = ? WHERE id = ?", (course_id, route_id))
        await db.commit()


# ── Opening the page on a route ──────────────────────────────────────────

def test_open_page_shows_a_held_loop_or_a_saved_route_on_the_coverage_page(offline_app: OfflineApp,
                                                                           coverage_city: str):
    loop = plan(offline_app, coverage_city, 3)
    saved = run(offline_app, lambda ctx: coverage_tools.save_route(ctx, coverage_city, loop["plan_id"]))

    def open_page(**kwargs: Any) -> str:
        return run(offline_app, lambda ctx: tools.open_page(ctx, **kwargs))
    assert open_page(page="coverage") == "/coverage"
    assert open_page(page="coverage", id=coverage_city) == f"/coverage?city={coverage_city}"
    assert open_page(page="coverage", id=coverage_city, plan_id=loop["plan_id"]) == \
        f"/coverage?city={coverage_city}&plan={loop['plan_id']}"
    assert open_page(page="coverage", id=coverage_city, route_id=saved["id"]) == \
        f"/coverage?city={coverage_city}&route={saved['id']}"
    for wrong, why in [(dict(page="coverage", id=coverage_city, plan_id="0123456789abcdef"), "plan it again"),
                       (dict(page="coverage", id=coverage_city, route_id=999), "no saved route"),
                       (dict(page="coverage", plan_id=loop["plan_id"]), "slug"),
                       (dict(page="activity", id="1", route_id=saved["id"]), "coverage page")]:
        with pytest.raises(ModelRetry, match=why):
            open_page(**wrong)


# ── Writes wait for a yes ────────────────────────────────────────────────

class StubGarmin:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def course_devices(self) -> list[dict[str, Any]]:
        return [{"device_id": 2, "name": "Other watch", "primary": False},
                {"device_id": 1, "name": "Synthetic watch", "primary": True}]

    def create_course(self, name: str, gpx: bytes) -> dict[str, Any]:
        assert gpx.startswith(b"<?xml")
        self.calls.append(("create", name))
        return {"courseId": 77}

    def send_course(self, course_id: int, device_id: int) -> None:
        self.calls.append(("send", course_id, device_id))


def scripted_turns(app: OfflineApp, tool: str, args: dict[str, Any],
                   schedule: Schedule | None = None) -> tuple[DeferredToolRequests, Any]:
    """The agent calling `tool` (loading its capability first), then the athlete's yes."""
    async def go() -> tuple[DeferredToolRequests, Any]:
        async with calendar_db.connect_db() as db:
            deps = tools.AgentDeps(z2=app.z2, db=db, schedule=schedule or Schedule())
            agent, model = build_agent(), _scripted(tool, args)
            asked = await agent.run(f"call {tool}", deps=deps, model=model)
            assert isinstance(asked.output, DeferredToolRequests)
            assert chat.pending_calls(asked.all_messages())[0].tool_name == tool
            yes = DeferredToolResults(approvals={c.tool_call_id: True for c in asked.output.approvals})
            done = await agent.run(message_history=asked.all_messages(), deferred_tool_results=yes, deps=deps, model=model)
            return asked.output, done.output
    return asyncio.run(go())


def test_saving_a_loop_and_sending_it_to_the_watch_waits_for_a_yes(offline_app: OfflineApp, coverage_city: str,
                                                                    monkeypatch: pytest.MonkeyPatch):
    garmin = StubGarmin()
    monkeypatch.setattr(offline_app.z2, "garmin_client", garmin)
    loop = plan(offline_app, coverage_city, 3)
    before = offline_app.client.get(f"/api/coverage/{coverage_city}/plans").json()

    asked, done = scripted_turns(offline_app, "save_route", {"city": coverage_city, "plan_id": loop["plan_id"],
                                                            "name": "Synthetic loop", "to_watch": True})
    assert [c.tool_name for c in asked.approvals] == ["save_route"]
    assert before == []
    [route] = offline_app.client.get(f"/api/coverage/{coverage_city}/plans").json()
    assert (route["name"], route["garmin_course_id"]) == ("Synthetic loop", 77)
    # The primary watch first, as the page offers them
    assert garmin.calls == [("create", "Synthetic loop"), ("send", 77, 1)]
    assert json.loads(done)["sent_to"] == "Synthetic watch"

    # Sent again: the course exists, so only the send
    scripted_turns(offline_app, "send_route", {"city": coverage_city, "route_id": route["id"]})
    assert garmin.calls[2:] == [("send", 77, 1)]
    assert {"save_route", "send_route", "add_city"} <= chat.WRITE_TOOLS


def test_the_coverage_tools_load_on_demand_and_only_writes_ask(offline_app: OfflineApp):
    toolset, description = ON_DEMAND["coverage"]
    assert toolset is coverage_tools.coverage_tools and len(description) < 200
    assert {n for n, t in toolset.tools.items() if t.requires_approval} == {"save_route", "send_route", "add_city"}


# ── Adding a city ────────────────────────────────────────────────────────

def test_find_city_answers_with_the_place_its_size_and_whether_it_is_added(offline_app: OfflineApp, coverage_city: str,
                                                                            monkeypatch: pytest.MonkeyPatch):
    place = gpd.GeoDataFrame({"display_name": ["Testville, Region, Nowhere Land"], "osm_id": [1]},
                             geometry=[box(3.0, 0.0, 3.05, 0.05)], crs="EPSG:4326")
    monkeypatch.setattr(coverage, "_geocode_to_gdf", lambda q: place)
    out = run(offline_app, lambda ctx: coverage_tools.find_city(ctx, "Testville"))
    shapeless(out)
    assert out["place"] == "Testville, Region, Nowhere Land" and out["country"] == "Nowhere Land"
    assert out["area_km2"] == pytest.approx(30.9, abs=0.5) and out["added"] is False
    assert out["centre"] == pytest.approx([0.025, 3.025], abs=1e-3)
    assert run(offline_app, lambda ctx: coverage_tools.find_city(ctx, GRID_CITY))["added"] is True

    # A place OSM has only as a point: the area around it is suggested
    def point_only(q: str) -> gpd.GeoDataFrame:
        if q == "Hamlet":
            raise TypeError("a point")
        return place.assign(osm_id=[42])
    answers = {"search": [{"display_name": "Hamlet, Nowhere Land", "lat": "0.01", "lon": "3.01",
                           "boundingbox": ["0.0", "0.02", "3.0", "3.02"]}],
               "reverse": {"osm_type": "relation", "osm_id": 42, "name": "Testville",
                           "address": {"country": "Nowhere Land"}}}
    monkeypatch.setattr(coverage, "_geocode_to_gdf", point_only)
    monkeypatch.setattr(coverage, "_nominatim", lambda endpoint, **params: answers[endpoint])
    monkeypatch.setattr(coverage.time, "sleep", lambda s: None)
    out = run(offline_app, lambda ctx: coverage_tools.find_city(ctx, "Hamlet"))
    assert out["point_only"] is True and out["suggestion"]["name"] == "Testville, Nowhere Land"
    assert "area_km2" not in out


def test_adding_a_city_waits_for_a_yes_starts_one_download_and_reports_progress(
        offline_app: OfflineApp, coverage_city: str, monkeypatch: pytest.MonkeyPatch):
    schedule = Schedule()
    asked, done = scripted_turns(offline_app, "add_city", {"name": "Testville"}, schedule)
    assert [c.tool_name for c in asked.approvals] == ["add_city"]
    assert schedule.calls == [("download_city", ("Testville",))]
    assert "few minutes" in done
    assert run(offline_app, coverage_tools.cities)["adding"] == {"name": "Testville", "stage": "starting", "minutes": 0}

    # One at a time, from the coach or the page
    with pytest.raises(ModelRetry, match="already running"):
        run(offline_app, lambda ctx: coverage_tools.add_city(ctx, "Elsewhere"))
    assert offline_app.client.post("/api/coverage/add", params={"city_name": "Elsewhere"}).status_code == 409
    assert len(schedule.calls) == 1

    stages: list[Any] = []

    class Download:
        """The OSM download, made up: reports a stage, then fails."""
        def __init__(self, city_name: str, workdir: Any, on_progress: Callable[[str], None]) -> None:
            on_progress("downloading the street network of Testville")
            stages.append(run(offline_app, coverage_tools.cities)["adding"]["stage"])
            raise RuntimeError("Overpass is busy")
    monkeypatch.setattr(coverage, "StravaMapMatcher", Download)
    coverage.download_city("Testville")
    assert stages == ["downloading the street network of Testville"]
    assert run(offline_app, coverage_tools.cities)["adding"] == {"name": "Testville",
                                                                  "failed": "RuntimeError: Overpass is busy"}
    # A city added already isn't downloaded again
    with pytest.raises(ModelRetry, match="already added"):
        run(offline_app, lambda ctx: coverage_tools.add_city(ctx, GRID_CITY))
