"""Exploration loops on made-up street grids in projected metres: properties of the loop
(closed, of the asked length, through the via points, on the streets wanted), not exact paths."""
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from zone2.route_planner import WAY_CLASSES, ExplorationPlanner, PlannedLoop, UnreachablePoint, WayClass
from tests.synthetic import street_grid

TARGET = 1600.0
START = (300.0, 300.0)  # the middle of a 7×7 grid of 100 m blocks


def planner(u: np.ndarray, v: np.ndarray, geoms: np.ndarray, classes: dict[int, WayClass] | None = None
            ) -> ExplorationPlanner:
    codes = np.zeros(len(u), dtype=np.int8)
    for row, way_class in (classes or {}).items():
        codes[row] = WAY_CLASSES.index(way_class)
    return ExplorationPlanner(u, v, geoms, codes)


@pytest.fixture
def grid() -> ExplorationPlanner:
    return planner(*street_grid(7))


def west_half_run(p: ExplorationPlanner) -> tuple[np.ndarray, np.ndarray]:
    """(missing, covered) metres per row: every street west of x = 300 run, the rest not."""
    west = np.array([g.interpolate(0.5, normalized=True).x < 300 for g in p.geoms])
    return np.where(west, 0.0, p.length), np.where(west, p.length, 0.0)


def assert_closed_loop(p: ExplorationPlanner, loop: PlannedLoop, start: tuple[float, float], target: float) -> None:
    coords = list(loop.line.coords)
    assert coords[0] == coords[-1] == start
    assert abs(loop.length_m - target) <= ExplorationPlanner.LENGTH_TOLERANCE * target
    assert loop.line.length == pytest.approx(loop.length_m)
    assert loop.length_m == pytest.approx(p.length[loop.rows].sum())
    # Each row starts where the one before it ends
    ends = [{int(p.u[r]), int(p.v[r])} for r in loop.rows]
    assert all(a & b for a, b in zip(ends, ends[1:]))


@pytest.mark.parametrize("share", [1.0, 0.5, 0.0])
def test_a_loop_of_the_asked_length_back_to_the_start(grid: ExplorationPlanner, share: float):
    missing, covered = west_half_run(grid)
    loop = grid.plan(START, TARGET, missing, covered, new_share=share, seed=1)
    assert loop is not None
    assert_closed_loop(grid, loop, START, TARGET)
    assert loop.new_m == pytest.approx(missing[np.unique(loop.rows)].sum())


def test_the_new_share_sets_how_much_of_the_loop_is_new(grid: ExplorationPlanner):
    missing, covered = west_half_run(grid)
    new_share = {share: grid.plan(START, TARGET, missing, covered, new_share=share, seed=1)
                 for share in (1.0, 0.5, 0.0)}
    share_of = {share: loop.new_m / loop.length_m for share, loop in new_share.items()}
    assert share_of[1.0] >= 0.9
    assert share_of[0.0] <= 0.1
    assert abs(share_of[0.5] - 0.5) <= 0.2


def test_via_points_are_on_the_loop(grid: ExplorationPlanner):
    missing, covered = west_half_run(grid)
    via = [(0.0, 600.0), (600.0, 600.0)]
    loop = grid.plan(START, 1800.0, missing, covered, via_xy=via, seed=1)
    assert loop is not None
    assert_closed_loop(grid, loop, START, 1800.0)
    assert [Point(xy).distance(loop.line) for xy in via] == [0.0, 0.0]


def test_an_unexplored_grid_has_loops_through_its_corners(grid: ExplorationPlanner):
    loop = grid.plan(START, 2400.0, grid.length.copy(), np.zeros(len(grid.u)),
                     via_xy=[(0.0, 600.0), (600.0, 600.0)], seed=0)
    assert loop is not None
    assert_closed_loop(grid, loop, START, 2400.0)


def coverage(p: ExplorationPlanner, run: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(missing, covered) metres per row with the rows flagged in `run` run and the rest not."""
    return np.where(run, 0.0, p.length), np.where(run, p.length, 0.0)


def doorstep(p: ExplorationPlanner) -> np.ndarray:
    """The streets meeting at the start."""
    return np.array([START in (g.coords[0], g.coords[-1]) for g in p.geoms])


# Wanted streets are cheaper to route through, down to 0.4 of their length: the grid's far
# corners, 600 m away (a quarter of these targets or less), must still be in reach
@pytest.mark.parametrize("network, share", [
    ("unexplored", 1.0), ("fully explored", 0.0), ("fully explored", 0.5),
    ("doorstep run", 1.0), ("all run but the doorstep", 0.0), ("west half run", 0.5),
])
@pytest.mark.parametrize("target", [2400.0, 2800.0])
def test_waypoints_are_reached_in_metres_whatever_the_streets_cost(grid: ExplorationPlanner, network: str,
                                                                   share: float, target: float):
    run = {"unexplored": np.zeros(len(grid.u), dtype=bool), "fully explored": np.ones(len(grid.u), dtype=bool),
           "doorstep run": doorstep(grid), "all run but the doorstep": ~doorstep(grid),
           "west half run": west_half_run(grid)[1] > 0}[network]
    missing, covered = coverage(grid, run)
    for seed in range(3):
        loop = grid.plan(START, target, missing, covered, new_share=share, seed=seed)
        assert loop is not None
        assert_closed_loop(grid, loop, START, target)
        assert loop.new_m == pytest.approx(missing[np.unique(loop.rows)].sum())


# A 15×15 grid run from x = KNOWN_X east, or not at all; the starts on the row y = 700 have
# nothing run within 300 m and 800 m of them
KNOWN_X = 1000.0


@pytest.mark.parametrize("known, share", [(False, 0.5), (True, 0.5), (True, 0.0)])
@pytest.mark.parametrize("start", [(200.0, 700.0), (700.0, 700.0)])
@pytest.mark.parametrize("target", [2400.0, 3200.0])
def test_the_new_share_is_honoured_with_nothing_run_near_the_start(known: bool, share: float,
                                                                    start: tuple[float, float], target: float):
    p = planner(*street_grid(15))
    east = np.array([g.interpolate(0.5, normalized=True).x >= KNOWN_X for g in p.geoms])
    missing, covered = coverage(p, east & known)
    for seed in range(5):
        loop = p.plan(start, target, missing, covered, new_share=share, seed=seed)
        assert loop is not None
        assert_closed_loop(p, loop, start, target)
        if share == 0.5:
            # Out and back over unrun streets is half new, wherever the run ones are
            assert loop.new_m / loop.length_m == pytest.approx(0.5, abs=0.05)
        else:
            # New only on the way to the run streets, once however often it is run
            assert loop.new_m <= 1.1 * (KNOWN_X - start[0])


def district_with_a_bridge() -> tuple[ExplorationPlanner, int]:
    """A 7×7 grid and a 4×4 one across the water east of it, joined by a 200 m main road
    bridge at y = 300; with the bridge's row."""
    ua, va, ga = street_grid(7)
    ub, vb, gb = street_grid(4, x0=800.0, first_id=100)
    bridge = LineString([(600.0, 300.0), (700.0, 300.0), (800.0, 300.0)])
    u, v = np.r_[ua, ub, [27]], np.r_[va, vb, [112]]
    geoms = np.r_[ga, gb, np.array([bridge], dtype=object)]
    return planner(u, v, geoms, {len(u) - 1: WayClass.MAIN_ROAD}), len(u) - 1


def test_an_avoided_way_counts_its_avoid_cost_in_the_waypoint_reach():
    p, bridge = district_with_a_bridge()
    # Unrun: the far district, the bridge, and the near district's north and south edges
    ends = np.array([(g.coords[0], g.coords[-1]) for g in p.geoms])
    far = ends[:, :, 0].min(axis=1) >= 600
    edge = (ends[:, :, 1].max(axis=1) == 0) | (ends[:, :, 1].min(axis=1) == 600)
    unrun, run = coverage(p, ~(far | edge))
    # The far district is 300 + 200 m away, AVOID_COST × 200 m more over an avoided bridge:
    # beyond the reach of a 2.4 km loop, which then fits on the near side
    for seed in range(3):
        taking = p.plan(START, 2400.0, unrun, run, seed=seed)
        avoiding = p.plan(START, 2400.0, unrun, run, avoid=frozenset({WayClass.MAIN_ROAD}), seed=seed)
        assert taking is not None and (taking.rows == bridge).any()
        assert avoiding is not None and not (avoiding.rows == bridge).any()
        assert_closed_loop(p, avoiding, START, 2400.0)


def test_avoided_ways_are_left_out_when_the_grid_goes_around_them():
    u, v, geoms = street_grid(7)
    main_road = {row: WayClass.MAIN_ROAD for row, g in enumerate(geoms) if g.coords[0][1] == g.coords[-1][1] == 300}
    p = planner(u, v, geoms, main_road)
    unrun, run = p.length.copy(), np.zeros(len(u))
    rows = list(main_road)
    taking = p.plan(START, TARGET, unrun, run, seed=3)
    avoiding = p.plan(START, TARGET, unrun, run, avoid=frozenset({WayClass.MAIN_ROAD}), seed=3)
    assert taking is not None and np.isin(taking.rows, rows).any()
    assert avoiding is not None and not np.isin(avoiding.rows, rows).any()
    assert_closed_loop(p, avoiding, START, TARGET)
    # Other classes avoided don't matter here
    paths_avoided = p.plan(START, TARGET, unrun, run, avoid=frozenset({WayClass.PATH, WayClass.STEPS}), seed=3)
    assert np.array_equal(paths_avoided.rows, taking.rows)


def two_districts(bridged: bool) -> ExplorationPlanner:
    """Two 4×4 grids with water between them, and a main road bridge across when `bridged`."""
    ua, va, ga = street_grid(4)
    ub, vb, gb = street_grid(4, x0=450.0, first_id=100)
    u, v, geoms = np.r_[ua, ub], np.r_[va, vb], np.r_[ga, gb]
    if not bridged:
        return planner(u, v, geoms)
    bridge = LineString([(300.0, 100.0), (375.0, 100.0), (450.0, 100.0)])
    return planner(np.r_[u, [7]], np.r_[v, [104]], np.r_[geoms, np.array([bridge], dtype=object)],
                   {len(u): WayClass.MAIN_ROAD})


def test_an_avoided_way_is_taken_where_nothing_else_connects():
    p = two_districts(bridged=True)
    bridge = len(p.u) - 1
    loop = p.plan((0.0, 0.0), 2400.0, p.length.copy(), np.zeros(len(p.u)), via_xy=[(750.0, 300.0)],
                  avoid=frozenset({WayClass.MAIN_ROAD}), seed=0)
    assert loop is not None
    assert_closed_loop(p, loop, (0.0, 0.0), 2400.0)
    # Over the bridge and back
    assert (loop.rows == bridge).sum() == 2


def test_a_via_point_across_the_water_cannot_be_reached():
    p = two_districts(bridged=False)
    with pytest.raises(UnreachablePoint) as raised:
        p.plan((300.0, 150.0), TARGET, p.length.copy(), np.zeros(len(p.u)), via_xy=[(10.0, 10.0), (750.0, 300.0)])
    assert raised.value.index == 1


def test_no_loop_when_none_fits(grid: ExplorationPlanner):
    missing, covered = west_half_run(grid)
    # Far longer than the grid allows, nothing near the start, a lone street, and nothing left to explore
    assert grid.plan(START, 50_000.0, missing, covered) is None
    assert grid.plan((100_000.0, 0.0), TARGET, missing, covered) is None
    lone = planner(np.array([0]), np.array([1]), np.array([LineString([(0, 0), (100, 0)])], dtype=object))
    assert lone.plan((0.0, 0.0), 1000.0, np.array([100.0]), np.zeros(1)) is None
    assert grid.plan(START, TARGET, np.zeros(len(grid.u)), np.zeros(len(grid.u))) is None
    # Junction slivers aren't worth a detour
    assert grid.plan(START, TARGET, np.minimum(missing, ExplorationPlanner.MIN_NEW_M - 1), covered) is None
    with pytest.raises(ValueError, match="At most 3 via points"):
        grid.plan(START, TARGET, missing, covered, via_xy=[(0.0, 0.0)] * 4)


def test_the_same_inputs_plan_the_same_loop(grid: ExplorationPlanner):
    missing, covered = west_half_run(grid)
    first = grid.plan(START, TARGET, missing, covered, new_share=0.7, seed=5)
    again = planner(*street_grid(7)).plan(START, TARGET, missing.copy(), covered.copy(), new_share=0.7, seed=5)
    assert np.array_equal(first.rows, again.rows) and first.line.equals(again.line)
    assert (first.length_m, first.new_m) == (again.length_m, again.new_m)
