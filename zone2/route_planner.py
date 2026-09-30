"""Exploration loops: a run of a given length from a start point through
streets not run yet, mixed with known ones in a chosen share.

An orienteering heuristic on the walkable network. Streets of the wanted kind
are cheaper to route through (EXPLORE_DISCOUNT): unrun ones in proportion to
the new share, run ones to the rest. Free waypoints are drawn from where those
streets are densest at a fitting distance; loops start -> waypoints and via
points (in angular order, so the route circles rather than zigzags) -> start
are assembled from one batch of shortest-path trees, and the loop within
LENGTH_TOLERANCE of the target length whose new metres (each counted once)
come closest to the share wins.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.ops import substring


class WayClass(StrEnum):
    """What a way of the walkable network is to a runner choosing roads.
    Sidewalks take the class of the street they run beside."""
    STREET = 'street'
    MAIN_ROAD = 'main_road'
    CYCLEWAY = 'cycleway'
    PATH = 'path'
    TRACK = 'track'
    STEPS = 'steps'


WAY_CLASSES = list(WayClass)   # a row's class code indexes this


class UnreachablePoint(ValueError):
    """A via point on a part of the network the start can't reach on foot
    (across water with only a ferry, say)."""

    def __init__(self, index: int):
        super().__init__(f"Point {index + 1} can't be reached on foot from the start (water in between?): move one of them")
        self.index = index


@dataclass
class PlannedLoop:
    line: LineString        # projected metres, in running order
    length_m: float
    new_m: float            # street metres not run before
    rows: np.ndarray        # the network rows run, in order


class ExplorationPlanner:
    # Streets of the wanted kind cost up to this share of their length less to route through
    EXPLORE_DISCOUNT = 0.6
    # Loops count when their length is within this share of the target...
    LENGTH_TOLERANCE = 0.15
    # ...and metres beyond this share of it weigh OFF_TARGET_WEIGHT times a new metre
    LENGTH_SLACK = 0.05
    OFF_TARGET_WEIGHT = 3.0
    # An avoided way costs this many times its length: taken only where
    # nothing else connects (a bridge, the one road out)
    AVOID_COST = 5.0
    # Waypoint candidates: this many, at this share of the target length from the start
    CANDIDATES = 36
    WAYPOINT_REACH = (0.12, 0.42)
    # Missing streets shorter than this (junction slivers) aren't worth a detour
    MIN_NEW_M = 20.0
    # Smaller connected parts of the network are islands a start never snaps to
    MIN_NETWORK_NODES = 500
    # Free waypoints per loop, fewer with via points but always at least one
    MAX_WAYPOINTS = 3
    MAX_VIA = 3
    # Loops scored exactly (new metres counted once) among the best estimates
    SHORTLIST = 64

    def __init__(self, u: np.ndarray, v: np.ndarray, geoms: np.ndarray, way_class: np.ndarray):
        """
        :param u, v: end node ids of the walkable network's rows.
        :param geoms: their LineStrings (projected metres), oriented u -> v.
        :param way_class: their WayClass codes (indexes into WAY_CLASSES).
        """
        self.u, self.v, self.geoms, self.way_class = u, v, geoms, way_class
        self.length = shapely.length(geoms)
        self.tree = shapely.STRtree(geoms)

    def plan(self, start_xy: tuple[float, float], target_m: float, missing_m: np.ndarray, covered_m: np.ndarray,
             via_xy: list[tuple[float, float]] = (), new_share: float = 1.0, avoid: frozenset[WayClass] = frozenset(),
             seed: int = 0) -> PlannedLoop | None:
        """The loop from start_xy through every via point, or None when none
        of the target length is found. Raises UnreachablePoint for a via
        point the start can't reach.

        :param missing_m: per row, the street metres not run yet (0 for
            connectors and fully run streets).
        :param covered_m: per row, the street metres run (0 for connectors).
        :param new_share: the share of the loop wanted on streets not run yet;
            beyond it, more new metres score less.
        :param avoid: classes of way routed through only where nothing else
            connects, and never aimed for.
        """
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import connected_components, dijkstra

        if len(via_xy) > self.MAX_VIA:
            raise ValueError(f"At most {self.MAX_VIA} via points")
        rng = np.random.default_rng(seed)
        # The part of the network a loop of this length can reach
        rows = self.tree.query(shapely.Point(start_xy).buffer(0.5 * target_m))
        if not len(rows):
            return None
        nodes, inverse = np.unique(np.concatenate([self.u[rows], self.v[rows]]), return_inverse=True)
        a, b = inverse[:len(rows)], inverse[len(rows):]
        n = len(nodes)
        length = self.length[rows]
        missing_m = np.minimum(missing_m, self.length)
        avoided = np.isin(self.way_class[rows], [WAY_CLASSES.index(c) for c in avoid])
        missing = np.where((missing_m[rows] >= self.MIN_NEW_M) & ~avoided, missing_m[rows], 0.0)
        known = np.where(avoided, 0.0, np.minimum(covered_m, self.length - missing_m)[rows])
        wanted = new_share * missing + (1.0 - new_share) * known
        cost = length * (1.0 - self.EXPLORE_DISCOUNT * wanted / np.maximum(length, 1e-9))
        cost[avoided] *= self.AVOID_COST
        # One edge per node pair, the cheapest row, usable both ways
        lo_node, hi_node = np.minimum(a, b), np.maximum(a, b)
        order = np.lexsort((cost, hi_node, lo_node))
        first = np.r_[True, (lo_node[order][1:] != lo_node[order][:-1]) | (hi_node[order][1:] != hi_node[order][:-1])]
        keep = order[first]
        keep = keep[a[keep] != b[keep]]
        src, dst = np.r_[a[keep], b[keep]], np.r_[b[keep], a[keep]]
        graph = csr_matrix((np.r_[cost[keep], cost[keep]], (src, dst)), shape=(n, n))
        # (from node, to node) -> network row, looked up by the sorted pair keys
        pair_key = src.astype(np.int64) * n + dst
        pair_order = np.argsort(pair_key)
        pair_key, pair_row = pair_key[pair_order], np.r_[rows[keep], rows[keep]][pair_order]
        node_xy = np.zeros((n, 2))
        node_xy[a] = shapely.get_coordinates(shapely.get_point(self.geoms[rows], 0))
        node_xy[b] = shapely.get_coordinates(shapely.get_point(self.geoms[rows], -1))

        # Points snap to the nearest node off islands (a courtyard path joined to nothing)
        _, component = connected_components(graph, directed=False)
        sizes = np.bincount(component)
        networked = np.flatnonzero(sizes[component] >= min(sizes.max(), self.MIN_NETWORK_NODES))

        def snap(xy: tuple[float, float]) -> int:
            return int(networked[np.argmin(((node_xy[networked] - xy) ** 2).sum(axis=1))])
        start = snap(start_xy)
        via = []
        for i, xy in enumerate(via_xy):
            node = snap(xy)
            if component[node] != component[start]:
                raise UnreachablePoint(i)
            if node != start:
                via.append(node)
        d0 = dijkstra(graph, indices=start)

        def density(per_row: np.ndarray) -> np.ndarray:
            at = np.zeros(n)
            np.add.at(at, a, per_row)
            np.add.at(at, b, per_row)
            return at / at.sum() if at.sum() > 0 else at
        # Free waypoints: ends of the wanted streets at a fitting distance, favouring dense spots
        weight = new_share * density(missing) + (1.0 - new_share) * density(known)
        near, far = (f * target_m for f in self.WAYPOINT_REACH)
        pool = np.setdiff1d(np.flatnonzero(np.isfinite(d0) & (d0 >= near) & (d0 <= far) & (weight > 0)), via)
        if not len(pool):
            return None
        pick = rng.choice(pool, size=min(self.CANDIDATES, len(pool)), replace=False, p=weight[pool] / weight[pool].sum())
        sources = np.unique(np.r_[start, np.asarray(via, dtype=np.int64), pick])
        dist, pred = dijkstra(graph, indices=sources, return_predecessors=True)
        index = {int(s): k for k, s in enumerate(sources.tolist())}
        stops_xy = node_xy[sources] - node_xy[start]
        angle = dict(zip(sources.tolist(), np.arctan2(stops_xy[:, 1], stops_xy[:, 0]).tolist()))

        legs: dict[tuple[int, int], tuple[np.ndarray, float, float] | None] = {}

        def leg(p: int, q: int) -> tuple[np.ndarray, float, float] | None:
            """Rows, length and new metres of the shortest leg p -> q, built once."""
            if (p, q) not in legs:
                chain = self._leg(p, q, pred, index)
                if chain is None:
                    legs[(p, q)] = None
                else:
                    path = pair_row[np.searchsorted(pair_key, chain[:-1] * n + chain[1:])]
                    legs[(p, q)] = (path, float(self.length[path].sum()), float(missing_m[np.unique(path)].sum()))
            return legs[(p, q)]

        tolerance = self.LENGTH_TOLERANCE * target_m
        shortlist: list[tuple[float, tuple[int, ...]]] = []
        free_max = max(1, self.MAX_WAYPOINTS - len(via))
        for k in range(0 if via else 1, free_max + 1):
            for combo in itertools.combinations(pick.tolist(), k):
                for stops in self._orders((*via, *combo), angle):
                    loop = [start, *stops, start]
                    # Costing more than the longest length allowed: too long, or mostly on avoided ways
                    # (a cost is at most its length unless avoided)
                    if sum(dist[index[p], q] for p, q in zip(loop, loop[1:])) > target_m + tolerance:
                        continue
                    parts = [leg(p, q) for p, q in zip(loop, loop[1:])]
                    if any(part is None for part in parts):
                        continue
                    loop_m = sum(part[1] for part in parts)
                    if abs(loop_m - target_m) <= tolerance:
                        # Legs may share streets: their new metres are an upper bound
                        new_bound = sum(part[2] for part in parts)
                        shortlist.append((self._score(loop_m, new_bound, target_m, new_share), tuple(loop)))
        best, best_score = None, -math.inf
        for _, loop in sorted(shortlist, reverse=True)[:self.SHORTLIST]:
            path = np.concatenate([legs[(p, q)][0] for p, q in zip(loop, loop[1:])])
            loop_m = float(self.length[path].sum())
            new = float(missing_m[np.unique(path)].sum())
            score = self._score(loop_m, new, target_m, new_share)
            if score > best_score:
                best_score, best = score, (loop, path, loop_m, new)
        if best is None:
            return None
        loop, path, loop_m, new = best
        return PlannedLoop(line=self._line(loop, pred, index, nodes, pair_key, pair_row), length_m=loop_m, new_m=new,
                           rows=path)

    def _score(self, length_m: float, new_m: float, target_m: float, new_share: float) -> float:
        """New metres up to the wanted share (those beyond it count against),
        less the weighted metres off the target beyond the slack."""
        wanted = new_share * length_m
        off = max(0.0, abs(length_m - target_m) - self.LENGTH_SLACK * target_m)
        return min(new_m, wanted) - max(0.0, new_m - wanted) - self.OFF_TARGET_WEIGHT * off

    @staticmethod
    def _orders(stops: tuple[int, ...], angle: dict[int, float]) -> list[tuple[int, ...]]:
        """The stops clockwise and anticlockwise around the start."""
        cw = tuple(sorted(stops, key=lambda w: angle[w]))
        return [cw] if len(cw) == 1 else [cw, cw[::-1]]

    @staticmethod
    def _leg(src: int, dst: int, pred: np.ndarray, index: dict[int, int]) -> np.ndarray | None:
        """Nodes from src to dst on src's shortest-path tree."""
        tree = pred[index[src]]
        chain = [dst]
        while chain[-1] != src:
            p = tree[chain[-1]]
            if p < 0:
                return None
            chain.append(int(p))
        return np.asarray(chain[::-1], dtype=np.int64)

    def _line(self, loop, pred, index, nodes, pair_key, pair_row) -> LineString:
        coords: list[tuple[float, float]] = []
        n = len(nodes)
        for p, q in zip(loop, loop[1:]):
            chain = self._leg(p, q, pred, index)
            path = pair_row[np.searchsorted(pair_key, chain[:-1] * n + chain[1:])]
            for x, row in zip(chain[:-1].tolist(), path.tolist()):
                g = self.geoms[row]
                if self.u[row] != nodes[x]:
                    g = substring(g, g.length, 0.0)   # run against the geometry
                part = list(g.coords)
                coords.extend(part if not coords else part[1:])
        return LineString(coords)
