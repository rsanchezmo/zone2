"""The route HMM beyond tests/test_coverage.py: GPS glitches skipped rather than followed, parallel
streets told apart by continuity, and a run along a connector matched but never counted as street
coverage. Made-up grids in projected metres, and the Gridtown of test_coverage."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from zone2.map_matching import StravaMapMatcher
from zone2.route_matching import MatchedRoute, RouteMatcher
from tests.synthetic import street_grid
from tests.test_coverage import CITY, CRS, SLUG, X0, Y0, activities, grid_edges, node, segment, track, xy

# Along the bottom street of a 3×3 grid (rows 0 and 1), a fix every 5 m, 2 m off
XS = np.arange(10.0, 191.0, 5.0)
GLITCH = int(np.flatnonzero(XS == 50.0)[0])


def bottom_street_fixes() -> np.ndarray:
    return np.c_[XS, np.full(len(XS), 2.0)]


def streets_of(route: MatchedRoute) -> set[int]:
    return {row for row, a, b in route.pieces if abs(b - a) > 0.5}


@pytest.fixture
def grid() -> RouteMatcher:
    return RouteMatcher(*street_grid(3))


def test_a_glitch_near_another_street_is_skipped(grid: RouteMatcher):
    fixes = bottom_street_fixes()
    # 25 m from the street above: reaching it would mean a 195 m detour for a 73 m jump
    fixes[GLITCH] = (50.0, 75.0)
    route = grid.match(fixes)
    assert (route.outliers, route.breaks) == ([GLITCH], [])
    assert streets_of(route) == {0, 1}
    assert route.length == pytest.approx(180.0)
    assert [t for t, _ in route.chosen] == [t for t in range(len(XS)) if t != GLITCH]


def test_a_few_glitches_in_a_row_are_skipped_without_breaking_the_chain(grid: RouteMatcher):
    fixes = bottom_street_fixes()
    fixes[GLITCH:GLITCH + RouteMatcher.MAX_SKIP] = [(50.0 + 5 * k, 75.0) for k in range(RouteMatcher.MAX_SKIP)]
    route = grid.match(fixes)
    assert route.outliers == list(range(GLITCH, GLITCH + RouteMatcher.MAX_SKIP)) and route.breaks == []
    assert streets_of(route) == {0, 1} and route.length == pytest.approx(180.0)


def test_a_long_gap_starts_a_new_chain(grid: RouteMatcher):
    fixes = bottom_street_fixes()
    gap = RouteMatcher.MAX_SKIP + 3
    # Beyond the search radius of every street: these fixes have no candidate at all
    fixes[GLITCH:GLITCH + gap, 1] = -60.0
    route = grid.match(fixes)
    assert route.outliers == list(range(GLITCH, GLITCH + gap))
    assert route.breaks == [GLITCH + gap]
    assert streets_of(route) == {0, 1}


def ladder() -> RouteMatcher:
    """Two parallel 300 m streets 20 m apart, A along y = 0 (rows 0, 2, 4) and B along y = 20
    (rows 1, 3, 5), joined by rungs every 100 m (rows 6 to 9)."""
    u, v, geoms = [], [], []
    for k in range(3):
        for y, first in ((0, 1), (20, 5)):
            u.append(first + k)
            v.append(first + k + 1)
            geoms.append(LineString([(100 * k, y), (100 * k + 50, y), (100 * k + 100, y)]))
    for k in range(4):
        u.append(1 + k)
        v.append(5 + k)
        geoms.append(LineString([(100 * k, 0), (100 * k, 10), (100 * k, 20)]))
    return RouteMatcher(np.asarray(u), np.asarray(v), np.asarray(geoms, dtype=object))


LADDER_XS = np.arange(20.0, 281.0, 5.0)


def test_parallel_streets_are_told_apart_by_continuity():
    # Fixes drifting closer to B for 60 m in the middle: switching streets twice costs more than the drift
    ys = np.where((LADDER_XS >= 120) & (LADDER_XS <= 180), 12.0, 3.0)
    route = ladder().match(np.c_[LADDER_XS, ys])
    assert {c.edge for _, c in route.chosen} == {0, 2, 4}
    assert streets_of(route) == {0, 2, 4}
    assert (route.outliers, route.breaks) == ([], [])
    assert route.length == pytest.approx(260.0)


def test_a_real_switch_to_the_parallel_street_goes_over_the_rungs():
    ys = np.where((LADDER_XS > 105) & (LADDER_XS < 195), 18.0, 2.0)
    route = ladder().match(np.c_[LADDER_XS, ys])
    assert streets_of(route) == {0, 3, 4, 7, 8}
    assert route.length == pytest.approx(300.0)


# ── A connector in Gridtown ──────────────────────────────────────────────

@pytest.fixture
def workdir_with_a_footway(tmp_path: Path) -> Path:
    """test_coverage's Gridtown, plus a footway cutting the bottom-left block diagonally."""
    osm_dir = tmp_path / "osm_maps"
    osm_dir.mkdir()
    grid_edges().to_parquet(osm_dir / f"{SLUG}_edges.parquet")
    gpd.GeoDataFrame(geometry=[box(X0 - 50, Y0 - 50, X0 + 250, Y0 + 250)], crs=CRS).to_parquet(
        osm_dir / f"{SLUG}_boundary.parquet")
    gpd.GeoDataFrame({"u": [node(0, 0)], "v": [node(1, 1)], "highway": ["footway"], "footway": [None],
                      "length": [100 * np.sqrt(2)]},
                     geometry=[segment(xy(0, 0), xy(1, 1))], crs=CRS).to_parquet(osm_dir / f"{SLUG}_connectors.parquet")
    return tmp_path


def test_a_run_along_a_connector_is_matched_but_never_counted(workdir_with_a_footway: Path):
    matcher = StravaMapMatcher(CITY, workdir=workdir_with_a_footway)
    streets = len(grid_edges())
    result = matcher.match(activities({1: track([xy(0, 0), xy(1, 1)])}))[1]
    quality = result.quality
    assert (quality["num_outliers"], quality["num_breaks"], quality["street_km"]) == (0, 0, 0.0)
    assert quality["pct_on_connectors"] > 95
    on_connector = result.route[~result.route["street"]]
    assert on_connector.length.sum() == pytest.approx(100 * np.sqrt(2), abs=1.0)
    # Its stretch is kept for the map, on the connector's row after the streets'
    assert result.walked.set_index("way").loc[streets, ["lo", "hi"]].tolist() == pytest.approx([0.0, 100 * np.sqrt(2)])

    matcher.save_match_state({1: result})
    stats = matcher.coverage_stats_from_state()
    # Neither the walked metres nor the street network's total count the footway
    assert (stats["total_network_km"], stats["traversed_km"], stats["num_unique_streets"]) == (1.2, 0.0, 0)
    # Per walkable row: the footway walked whole, the streets only at its end's junction
    covered = matcher.coverage.walked_state().covered
    assert covered[streets:].tolist() == pytest.approx([100 * np.sqrt(2)])
    assert covered[:streets].sum() < 2.5
