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


class _Search:
    """Dijkstra from one node that can be resumed: a later call settles more
    targets or reaches further without redoing the work already done, so
    neighbouring observations (which share most of their candidates' nodes)
    reuse each other's searches. Distances of settled nodes are final."""
    __slots__ = ('dist', 'pred', 'heap', 'done')

    def __init__(self, src: int):
        self.dist: dict[int, float] = {src: 0.0}
        self.pred: dict[int, tuple[int, int]] = {}
        self.heap: list[tuple[float, int]] = [(0.0, src)]
        self.done: set[int] = set()

    def settle(self, adj, targets: set[int], limit: float) -> None:
        dist, pred, heap, done = self.dist, self.pred, self.heap, self.done
        left = targets - done
        while heap and left:
            d, node = heap[0]
            if d > limit:
                break
            heapq.heappop(heap)
            if node in done:
                continue
            done.add(node)
            left.discard(node)
            for nb, ln, e in adj[node]:
                nd = d + ln
                if nd < dist.get(nb, math.inf):
                    dist[nb] = nd
                    pred[nb] = (node, e)
                    heapq.heappush(heap, (nd, nb))


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
        u, v, length = self.u, self.v, self.length
        n = len(pts)
        score: list[list[float] | None] = [None] * n
        back: list[list[tuple | None] | None] = [None] * n   # (prev obs, prev candidate, pieces)
        # Searches depend only on their source node, so neighbouring observations
        # sharing candidate segments share them; each is extended only as far as
        # the observation being scored needs.
        searches: dict[int, _Search] = {}                    # source node -> its resumable search
        reached: dict[tuple[int, int], float] = {}           # (source node, target obs) -> limit searched to
        last_used: dict[int, int] = {}                       # source node -> latest target obs
        route = MatchedRoute()
        chain_start = None
        for t in range(n):
            cs = cands[t]
            if not cs:
                continue
            # how each candidate is entered from its segment's ends: (node, metres to the candidate)
            entries = [((u[c.edge], c.offset), (v[c.edge], length[c.edge] - c.offset)) for c in cs]
            targets = {nd for entry in entries for nd, _ in entry}
            best_s = [-math.inf] * len(cs)
            best_b: list[tuple | None] = [None] * len(cs)
            # Most recent predecessor first: a transition only ever loses score,
            # so a candidate whose score minus the skip cost can't beat the best
            # found so far needs no routing (that prunes almost every skip).
            for k in range(t - 1, max(-1, t - self.MAX_SKIP - 2), -1):
                if score[k] is None or chain_start is None or k < chain_start:
                    continue
                skip_cost = self.OUTLIER_COST * (t - k - 1)
                if max(score[k]) - skip_cost <= min(best_s):
                    continue
                straight = float(np.hypot(*(pts[t] - pts[k])))
                max_route = straight + self.MAX_DETOUR_M
                limit = max_route + 2 * self.RADIUS_M
                for i, ca in enumerate(cands[k]):
                    prev = score[k][i]
                    if prev == -math.inf or prev - skip_cost <= min(best_s):
                        continue
                    # the two ways out of a's segment, each with the search from that end
                    exits = []
                    for na, out_cost, to_off in ((u[ca.edge], ca.offset, 0.0),
                                                 (v[ca.edge], length[ca.edge] - ca.offset, length[ca.edge])):
                        if out_cost <= limit:
                            search = searches.get(na)
                            if search is None:
                                search = searches[na] = _Search(na)
                            if reached.get((na, t), -1.0) < limit:
                                search.settle(self.adj, targets, limit)
                                reached[(na, t)] = limit
                                last_used[na] = t
                            exits.append((na, out_cost, to_off, search))
                    for j, cb in enumerate(cs):
                        if prev - skip_cost <= best_s[j]:
                            continue
                        if cb.edge == ca.edge:
                            r, how = abs(cb.offset - ca.offset), 'same'
                        else:
                            r, how = math.inf, None
                            for na, out_cost, to_off, search in exits:
                                dist, done = search.dist, search.done
                                for nb, in_cost in entries[j]:
                                    if nb in done:
                                        total = out_cost + dist[nb] + in_cost
                                        if total < r:
                                            r, how = total, (na, to_off, nb, search.pred)
                            if how is None:
                                continue
                        if r > max_route:
                            continue
                        sc = prev - abs(r - straight) / self.BETA_M - skip_cost
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
            horizon = t - self.MAX_SKIP - 1
            for node in [nd for nd, used in last_used.items() if used < horizon]:
                del searches[node], last_used[node]
        self._backtrack(score, back, cands, route)
        return route

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
