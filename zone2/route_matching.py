"""Route-based HMM map matching (Newson & Krumm style).

Each GPS observation gets up to K candidate positions on nearby segments. A
transition between candidates of two observations is scored by how far the
network route between them deviates from the straight distance between the
observations, so the most plausible candidate sequence follows the segments in
the direction of travel and the matched route (the concatenation of those
routes) is connected by construction. Leaving an observation out costs
OUTLIER_COST, which lets a GPS glitch be skipped instead of dragging the route
onto a wrong street; only when nothing recent can reach an observation does a
new chain start.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import shapely


@dataclass
class Candidate:
    edge: int        # row in the segment arrays
    offset: float    # metres from the segment's u end along its geometry
    dist: float      # snap distance to the observation


# (segment row, from offset, to offset): a stretch of one segment walked in
# travel order; from > to means it was walked against the geometry.
Piece = tuple[int, float, float]


@dataclass
class MatchedRoute:
    pieces: list[Piece] = field(default_factory=list)
    chosen: list[tuple[int, Candidate]] = field(default_factory=list)   # (observation, candidate)
    outliers: list[int] = field(default_factory=list)
    breaks: list[int] = field(default_factory=list)   # observations where a new chain starts

    @property
    def length(self) -> float:
        return sum(abs(b - a) for _, a, b in self.pieces)


class RouteMatcher:
    RADIUS_M = 40.0        # candidate search radius
    K = 8                  # candidates kept per observation
    SIGMA_M = 10.0         # GPS noise (emission)
    BETA_M = 8.0           # scale of the |route - straight| mismatch (transition)
    MAX_SKIP = 4           # observations a transition may skip as outliers
    MAX_DETOUR_M = 200.0   # hard cap on route length beyond the straight distance
    OUTLIER_COST = 3.5     # log cost of leaving one observation out (~ a 26 m snap)

    def __init__(self, u: np.ndarray, v: np.ndarray, geoms: np.ndarray,
                 penalty: np.ndarray | None = None):
        """
        :param u, v: segment end node ids.
        :param geoms: segment LineStrings (projected metres), oriented u -> v.
        :param penalty: extra emission cost per segment (log units), so some
            segments are usable for continuity without being preferred.
        """
        self.u, self.v, self.geoms = u, v, geoms
        self.length = shapely.length(geoms)
        self.penalty = penalty if penalty is not None else np.zeros(len(u))
        self.tree = shapely.STRtree(geoms)
        self.adj: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
        for i, (a, b, ln) in enumerate(zip(u.tolist(), v.tolist(), self.length.tolist())):
            self.adj[a].append((b, ln, i))
            self.adj[b].append((a, ln, i))

    def far_share(self, pts: np.ndarray, dist: float) -> float:
        """Share of observations with no segment within dist."""
        if len(pts) == 0:
            return 0.0
        near, _ = self.tree.query(shapely.points(pts), predicate='dwithin', distance=dist)
        return 1.0 - len(np.unique(near)) / len(pts)

    def candidates(self, pts: np.ndarray) -> list[list[Candidate]]:
        points = shapely.points(pts)
        oi, ei = self.tree.query(points, predicate='dwithin', distance=self.RADIUS_M)
        d = shapely.distance(points[oi], self.geoms[ei])
        off = shapely.line_locate_point(self.geoms[ei], points[oi])
        by_obs: list[list[Candidate]] = [[] for _ in range(len(pts))]
        for o, e, dd, of in zip(oi.tolist(), ei.tolist(), d.tolist(), off.tolist()):
            by_obs[o].append(Candidate(e, of, dd))
        return [sorted(cs, key=lambda c: c.dist)[:self.K] for cs in by_obs]

    def match(self, pts: np.ndarray) -> MatchedRoute:
        """Viterbi over candidates, where a transition may skip up to MAX_SKIP
        observations as outliers."""
        cands = self.candidates(pts)
        emis = [[-0.5 * (c.dist / self.SIGMA_M) ** 2 - self.penalty[c.edge] for c in cs] for cs in cands]
        n = len(pts)
        score: list[list[float] | None] = [None] * n
        back: list[list[tuple | None] | None] = [None] * n   # (prev obs, prev candidate, pieces)
        searches: dict[int, dict] = {}
        route = MatchedRoute()
        chain_start = None
        for t in range(n):
            cs = cands[t]
            if not cs:
                continue
            best_s = [-math.inf] * len(cs)
            best_b: list[tuple | None] = [None] * len(cs)
            for k in range(max(0, t - self.MAX_SKIP - 1), t):
                if score[k] is None or chain_start is None or k < chain_start:
                    continue
                straight = float(np.hypot(*(pts[t] - pts[k])))
                skip_cost = self.OUTLIER_COST * (t - k - 1)
                for i, ca in enumerate(cands[k]):
                    if score[k][i] == -math.inf:
                        continue
                    for j, cb in enumerate(cs):
                        r, how = self._route_length(k, ca, cb, pts, cands, searches)
                        if how is None or r > straight + self.MAX_DETOUR_M:
                            continue
                        sc = score[k][i] - abs(r - straight) / self.BETA_M - skip_cost
                        if sc > best_s[j]:
                            best_s[j], best_b[j] = sc, (k, i, self._pieces(ca, cb, how))
            if all(b is None for b in best_b):
                last_alive = max((k for k in range(t) if score[k] is not None), default=None)
                if last_alive is None or t - last_alive > self.MAX_SKIP + 1 or chain_start is None:
                    # nothing recent reaches this observation: start a new chain
                    if chain_start is not None:
                        route.breaks.append(t)
                    chain_start = t
                    score[t], back[t] = list(emis[t]), [None] * len(cs)
                continue
            score[t] = [s + e if b is not None else -math.inf for s, e, b in zip(best_s, emis[t], best_b)]
            back[t] = best_b
            for k in [k for k in searches if k < t - self.MAX_SKIP - 1]:
                del searches[k]
        self._backtrack(score, back, cands, route)
        return route

    def _dijkstra(self, src: int, limit: float, targets: set[int]):
        dist = {src: 0.0}
        pred: dict[int, tuple[int, int]] = {}
        heap = [(0.0, src)]
        left = set(targets)
        while heap and left:
            d, node = heapq.heappop(heap)
            if d > dist.get(node, math.inf):
                continue
            left.discard(node)
            for nb, ln, e in self.adj[node]:
                nd = d + ln
                if nd <= limit and nd < dist.get(nb, math.inf):
                    dist[nb] = nd
                    pred[nb] = (node, e)
                    heapq.heappush(heap, (nd, nb))
        return dist, pred

    def _route_length(self, k: int, a: Candidate, b: Candidate, pts, cands, searches):
        """Shortest walk from a (observation k) to b and how to rebuild it.
        One search per source node serves every observation within k's skip
        window, run until all their candidates' end nodes are settled."""
        if a.edge == b.edge:
            return abs(b.offset - a.offset), 'same'
        if k not in searches:
            window = range(k + 1, min(len(pts), k + self.MAX_SKIP + 2))
            reach = max((float(np.hypot(*(pts[w] - pts[k]))) for w in window), default=0.0)
            searches[k] = {
                'limit': reach + self.MAX_DETOUR_M + 2 * self.RADIUS_M,
                'targets': {nd for w in window for c in cands[w] for nd in (self.u[c.edge], self.v[c.edge])},
            }
        cache = searches[k]
        la, lb = self.length[a.edge], self.length[b.edge]
        ends_b = {self.u[b.edge]: b.offset, self.v[b.edge]: lb - b.offset}
        best, best_how = math.inf, None
        for na, ca, to_off in ((self.u[a.edge], a.offset, 0.0), (self.v[a.edge], la - a.offset, la)):
            if ca > cache['limit']:
                continue
            if na not in cache:
                cache[na] = self._dijkstra(na, cache['limit'], cache['targets'])
            dist, pred = cache[na]
            for nb, cb in ends_b.items():
                if nb in dist and ca + dist[nb] + cb < best:
                    best, best_how = ca + dist[nb] + cb, (na, to_off, nb, pred)
        return best, best_how

    def _pieces(self, a: Candidate, b: Candidate, how) -> list[Piece]:
        if how == 'same':
            return [(a.edge, a.offset, b.offset)]
        na, to_off, nb, pred = how
        chain, node = [], nb
        while node != na:
            p, e = pred[node]
            chain.append((e, p))
            node = p
        pieces = [(a.edge, a.offset, to_off)]
        for e, p in reversed(chain):
            pieces.append((e, 0.0, self.length[e]) if self.u[e] == p else (e, self.length[e], 0.0))
        pieces.append((b.edge, 0.0 if self.u[b.edge] == nb else self.length[b.edge], b.offset))
        return pieces

    def _backtrack(self, score, back, cands, route: MatchedRoute):
        """Backtrack each chain from its most plausible end, latest chain first
        (trailing observations left out pay OUTLIER_COST each)."""
        chains = []
        t = len(score) - 1
        while t >= 0:
            if score[t] is None:
                t -= 1
                continue
            best, arg = -math.inf, None
            for k in range(t, max(-1, t - self.MAX_SKIP - 1), -1):
                if score[k] is None:
                    continue
                for j, sc in enumerate(score[k]):
                    if sc - self.OUTLIER_COST * (t - k) > best:
                        best, arg = sc - self.OUTLIER_COST * (t - k), (k, j)
            if arg is None:
                t -= 1
                continue
            k, j = arg
            chosen, pieces = [], []
            while True:
                chosen.append((k, cands[k][j]))
                step = back[k][j]
                if step is None:
                    break
                k, j, pc = step
                pieces.append(pc)
            chosen.reverse()
            pieces.reverse()
            chains.append((chosen, [p for pc in pieces for p in pc]))
            t = chosen[0][0] - 1
        used = set()
        for chosen, pieces in reversed(chains):
            route.chosen.extend(chosen)
            route.pieces.extend(pieces)
            used.update(t for t, _ in chosen)
        route.outliers = [t for t in range(len(score)) if t not in used]
