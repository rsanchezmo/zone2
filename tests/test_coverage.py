"""Street coverage on a made-up city: a 3x3 grid of 100 m streets laid out in
open ocean off the equator, so no real place, route or name is involved."""
import json
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import polyline
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, box

from zone2 import city_coverage
from zone2.city_coverage import CityCoverage, atomic_write
from zone2.map_matching import StravaMapMatcher, city_slug

CITY = "Gridtown, Nowhere"
SLUG = city_slug(CITY)
CRS = "EPSG:32631"
X0, Y0 = 500_000.0, 1_000.0
TO_LATLON = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)


def node(i: int, j: int) -> int:
    return 10 * j + i + 1


def xy(i: int, j: int) -> tuple[float, float]:
    return X0 + 100 * i, Y0 + 100 * j


def segment(a: tuple[float, float], b: tuple[float, float]) -> LineString:
    """A straight segment with a vertex halfway, as mapped streets have."""
    return LineString([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), b])


def grid_edges() -> gpd.GeoDataFrame:
    """Rows first, then columns; the top-right segment is a path, not a street."""
    rows = [(node(i, j), node(i + 1, j), f"Row {j}", segment(xy(i, j), xy(i + 1, j)))
            for j in range(3) for i in range(2)]
    rows += [(node(i, j), node(i, j + 1), f"Column {i}", segment(xy(i, j), xy(i, j + 1)))
             for i in range(3) for j in range(2)]
    edges = gpd.GeoDataFrame({
        "u": [r[0] for r in rows], "v": [r[1] for r in rows], "key": 0,
        "highway": ["residential"] * len(rows), "name": [r[2] for r in rows], "length": 100.0,
    }, geometry=[r[3] for r in rows], crs=CRS)
    edges.loc[5, "highway"] = "path"
    return edges


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    osm_dir = tmp_path / "osm_maps"
    osm_dir.mkdir()
    grid_edges().to_parquet(osm_dir / f"{SLUG}_edges.parquet")
    gpd.GeoDataFrame(geometry=[box(X0 - 50, Y0 - 50, X0 + 250, Y0 + 250)], crs=CRS).to_parquet(
        osm_dir / f"{SLUG}_boundary.parquet")
    return tmp_path


def track(points: list[tuple[float, float]], spacing: float = 5.0) -> LineString:
    """A GPS track (EPSG:4326) through projected points, a fix every `spacing` metres, 2 m off the street."""
    coords: list[tuple[float, float]] = []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        n = max(int(np.hypot(bx - ax, by - ay) / spacing), 1)
        coords += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n + 2.0) for k in range(n)]
    coords.append((points[-1][0], points[-1][1] + 2.0))
    return LineString([TO_LATLON.transform(x, y) for x, y in coords])


def activities(tracks: dict[int, LineString]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"id": list(tracks)}, geometry=list(tracks.values()), crs="EPSG:4326")


def summary_map(line: LineString) -> dict:
    return {"summary_polyline": polyline.encode([(lat, lon) for lon, lat in line.coords])}


# Along the bottom row: way 0 from 10 m, way 1 to 90 m
BOTTOM = track([(X0 + 10, Y0), (X0 + 190, Y0)])
# The same row from x = 50
BOTTOM_LATE = track([(X0 + 50, Y0), (X0 + 190, Y0)])


def test_match_follows_the_street(workdir: Path):
    matcher = StravaMapMatcher(CITY, workdir=workdir)
    result = matcher.match(activities({1: BOTTOM}))[1]
    walked = result.walked.sort_values("way").reset_index(drop=True)
    assert walked["way"].tolist() == [0, 1]
    assert walked["lo"].tolist() == pytest.approx([10.0, 0.0], abs=0.5)
    assert walked["hi"].tolist() == pytest.approx([100.0, 90.0], abs=0.5)
    assert result.quality["num_outliers"] == 0
    assert result.quality["street_km"] == pytest.approx(0.18, abs=0.01)
    assert result.route["street"].all()


def test_walked_stretches_counted_once(workdir: Path):
    matcher = StravaMapMatcher(CITY, workdir=workdir)
    matcher.save_match_state(matcher.match(activities({1: BOTTOM, 2: BOTTOM_LATE})), attempted_ids=[1, 2, 3])
    state = matcher.coverage.walked_state()
    assert state.covered[:2] == pytest.approx([90.0, 90.0], abs=0.5)
    stretches = state.stretches
    assert stretches["times"].tolist() == [1, 2, 2]
    assert stretches["way"].tolist() == [0, 0, 1]
    assert stretches["lo"].tolist()[1] == pytest.approx(50.0, abs=0.5)
    # Attempted but not matched: recorded so it isn't retried
    assert matcher.coverage.matched_ids() == {1, 2, 3}
    assert matcher.coverage.read_route(1)["type"] == "MultiLineString"
    assert matcher.coverage.read_route(3) is None


def test_coverage_totals(workdir: Path):
    matcher = StravaMapMatcher(CITY, workdir=workdir)
    matcher.save_match_state(matcher.match(activities({1: BOTTOM, 2: BOTTOM_LATE})))
    assert matcher.coverage_stats_from_state() == {
        "total_network_km": 1.2, "traversed_km": 0.18, "coverage_pct": 15.0, "num_unique_streets": 2}
    assert matcher.coverage_stats_from_state(streets_only=True)["total_network_km"] == 1.1

    corners = [TO_LATLON.transform(x, y) for x, y in
               ((X0 - 20, Y0 - 20), (X0 + 220, Y0 - 20), (X0 + 220, Y0 + 20), (X0 - 20, Y0 + 20))]
    assert matcher.coverage_in_polygon([(lat, lon) for lon, lat in corners]) == {
        "total_km": 0.2, "covered_km": 0.18, "coverage_pct": 90.0, "num_streets": 2, "num_covered_streets": 2}

    matcher.write_stats_cache()
    stats = matcher.coverage.read_stats()
    assert stats["num_matched_activities"] == 2
    assert stats["all"]["traversed_km"] == 0.18

    # Left to run: the ten unwalked segments whole, and the 10 m left at each end of the walked stretch
    matcher.write_viewport_index()
    lon_min, lat_min = TO_LATLON.transform(X0 - 50, Y0 - 50)
    lon_max, lat_max = TO_LATLON.transform(X0 + 250, Y0 + 250)
    body = matcher.coverage.viewport_missing_geojson((lat_min, lon_min, lat_max, lon_max))
    features = json.loads(body)["features"]
    assert len(features) == 12
    assert sum(f["properties"]["name"] == "Row 0" for f in features) == 2


def test_atomic_write(tmp_path: Path):
    fp = tmp_path / "state.parquet"
    atomic_write(fp, pd.DataFrame({"a": [1, 2]}))
    assert pd.read_parquet(fp)["a"].tolist() == [1, 2]
    atomic_write(fp, pa.table({"a": [3]}).replace_schema_metadata({"stamp": "x"}))
    assert pq.read_metadata(fp).metadata[b"stamp"] == b"x"
    atomic_write(tmp_path / "stats.json", '{"a": 1}')
    atomic_write(tmp_path / "body.gz", b"\x1f\x8b")
    assert (tmp_path / "stats.json").read_text() == '{"a": 1}'
    assert (tmp_path / "body.gz").read_bytes() == b"\x1f\x8b"

    # A failed write leaves the previous file whole and no temp file behind
    with pytest.raises(Exception):
        atomic_write(fp, pd.DataFrame({"a": [object()]}))
    assert pq.read_table(fp).column("a").to_pylist() == [3]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["body.gz", "state.parquet", "stats.json"]


def test_remove_forgets_the_city(workdir: Path):
    osm_dir = workdir / "osm_maps"
    # A city whose slug extends this one keeps its files
    (osm_dir / f"{SLUG}_east_edges.parquet").write_bytes(b"")
    matcher = StravaMapMatcher(CITY, workdir=workdir)
    matcher.save_match_state(matcher.match(activities({1: BOTTOM})))
    matcher.write_viewport_index()
    city = CityCoverage(osm_dir, SLUG)
    city.walked_state()
    assert city.read_route(1) is not None
    assert city.viewport_missing_geojson((-1.0, 2.0, 1.0, 4.0)) is not None
    assert (osm_dir, SLUG) in city_coverage._caches

    assert city.remove() == 7
    assert (osm_dir, SLUG) not in city_coverage._caches
    assert sorted(p.name for p in osm_dir.iterdir()) == [f"{SLUG}_east_edges.parquet"]


def test_delete_city_leaves_nothing_cached(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.config import settings
    from backend.services import coverage

    monkeypatch.setattr(settings, "workdir", workdir)
    matcher = coverage.get_matcher(SLUG)
    matcher.save_match_state(matcher.match(activities({1: BOTTOM})))
    coverage.walked_edges(SLUG, streets_only=False, counts=True)
    assert coverage.try_claim_sync(SLUG)
    coverage._sync_status[SLUG] = {"running": False, "last_error": None}
    del matcher
    assert (coverage.osm_dir(), SLUG) in city_coverage._caches

    coverage.delete_city(SLUG)
    assert SLUG not in coverage._matchers and SLUG not in coverage._matcher_used
    assert SLUG not in coverage._sync_status
    assert not any(key[1] == SLUG for key in coverage._responses)
    assert (coverage.osm_dir(), SLUG) not in city_coverage._caches
    assert coverage.known_cities() == {}


def test_new_street_map_forces_a_rematch(workdir: Path):
    matcher = StravaMapMatcher(CITY, workdir=workdir)
    city = matcher.coverage
    far = LineString([(-20.0, -10.0), (-20.01, -10.01)])
    runs = pd.DataFrame({"id": [1, 4], "map": [summary_map(BOTTOM), summary_map(far)]})
    assert city.pending_activities(runs)["id"].tolist() == [1]
    assert pq.read_table(city.path("far_activities.parquet")).column("activity_id").to_pylist() == [4]
    matcher.match_incremental(activities({1: BOTTOM}))
    assert city.state_is_current() and city.matched_ids() == {1}
    assert city.pending_activities(runs).empty
    walked_rows = pq.read_metadata(city.path("walked.parquet")).num_rows

    # A re-downloaded street map: walked rows no longer index into it
    edges_fp = city.path("edges.parquet")
    mtime = edges_fp.stat().st_mtime_ns
    os.utime(edges_fp, ns=(mtime, mtime + 1_000_000_000))
    assert not city.state_is_current()
    assert city.matched_ids() == set()
    assert city.pending_activities(runs)["id"].tolist() == [1]

    # The next sync matches it again and replaces the state rather than appending to it
    matcher.match_incremental(activities({1: BOTTOM}))
    assert city.state_is_current() and city.matched_ids() == {1}
    assert pq.read_metadata(city.path("walked.parquet")).num_rows == walked_rows
    assert city.walked_state().covered[:2] == pytest.approx([90.0, 90.0], abs=0.5)
