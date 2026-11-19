"""Bounded same-layer travel routing around holes and concave outlines."""
from heapq import heappop, heappush
import math

import numpy as np
from shapely import covers, linestrings, prepare
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points

from .fdm_constants import (TRAVEL_RETRY_VERTEX_LIMIT, TRAVEL_VERTEX_LIMIT,
                            TRAVEL_VISIBILITY_CACHE_ROWS, TRAVEL_WAYPOINT_INSET)

from gcodeproducer.core.geometry.polygon_parts import polygons


def _visible_edges(poly, coords, points, i, ids, cache):
    # Cache only stable waypoint-to-waypoint edges; travel endpoints vary.
    row = None
    if i >= 2:
        row = cache.get(points[i])
        if row is None and len(cache) < TRAVEL_VISIBILITY_CACHE_ROWS:
            row = cache.setdefault(points[i], {})
    visible = np.empty(len(ids), dtype=bool)
    missing = []
    for k, j in enumerate(ids):
        hit = row.get(points[j]) if row is not None and j >= 2 else None
        if hit is None:
            missing.append(k)
        else:
            visible[k] = hit
    if missing:
        dest = ids[missing]
        edges = np.empty((len(dest), 2, 2))
        edges[:, 0] = coords[i]
        edges[:, 1] = coords[dest]
        hits = covers(poly, linestrings(edges))
        visible[missing] = hits
        if row is not None and len(row) < TRAVEL_RETRY_VERTEX_LIMIT:
            for j, hit in zip(dest[:TRAVEL_RETRY_VERTEX_LIMIT-len(row)], hits):
                if j >= 2:
                    row[points[j]] = hit
    return visible


class TravelRouter:
    def __init__(self, outline, decimals, *, simplification=0.):
        self.decimals = decimals
        self.simplification = simplification
        self.detours = self.fallbacks = self.outside = self.bridges = 0
        region = Polygon()
        for ring in outline:
            if len(ring) >= 3:
                part = Polygon(ring)
                region = region.symmetric_difference(part if part.is_valid else part.buffer(0))
        self.region = region
        self.islands = list(polygons(region))
        self._bridge_edges = {}
        self._waypoints = {}
        self._visibility = {}  # per-island, per-layer waypoint visibility
        for poly in self.islands:
            prepare(poly)

    def route(self, start, end, extra):
        """Return travel destinations (not the start). ``extra`` is the XY detour budget in mm."""
        direct = [end]
        a, b = tuple(start), tuple(end)
        if extra <= 0 or a == b:
            return direct
        # Test the rounded XY coordinates that the writer will send.
        a = tuple(round(v, self.decimals) for v in a)
        b = tuple(round(v, self.decimals) for v in b)
        if a == b:
            return direct
        pa, pb = Point(a), Point(b)
        limit = math.dist(a, b) + extra
        start_island = end_island = None
        for i, poly in enumerate(self.islands):
            inside_a, inside_b = poly.covers(pa), poly.covers(pb)
            if inside_a:
                start_island = i
            if inside_b:
                end_island = i
            if not (inside_a and inside_b):
                continue
            if poly.covers(LineString((a, b))):
                return direct
            waypoints = self._route_inside(i, a, b, limit, self.simplification)
            if waypoints is None and self.simplification > 0:
                waypoints = self._route_inside(i, a, b, limit, 0.)
            if waypoints is not None:
                self.detours += 1
                return [*waypoints, end]
            self.fallbacks += 1
            return direct
        if start_island is not None and end_island is not None:
            bridge = self._bridge(a, b, start_island, end_island, limit)
            if bridge is not None:
                self.bridges += 1
                return [*bridge, end]
        self.outside += int(start_island is not None or end_island is not None)
        return direct

    def _route_inside(self, island, a, b, limit, tolerance):
        poly = self.islands[island]
        key = island, tolerance
        if key not in self._waypoints:
            # Simplify only candidate geometry. Every leg is checked against
            # the original polygon, including the edges of its holes.
            inset = max(TRAVEL_WAYPOINT_INSET, tolerance)
            inner = poly.buffer(-inset, join_style=2).simplify(tolerance)
            self._waypoints[key] = sorted({(round(x, self.decimals), round(y, self.decimals))
                                           for part in polygons(inner)
                                           for ring in (part.exterior, *part.interiors)
                                           for x, y in list(ring.coords)[:-1]})
        candidates = []
        for p in self._waypoints[key]:
            if p != a and p != b:
                lower = math.dist(a, p) + math.dist(p, b)
                if lower <= limit:
                    candidates.append((lower, p))
        if not candidates:
            return None  # the direct leg has already been rejected
        candidates.sort()
        options = [a, b, *(p for _, p in candidates[:TRAVEL_RETRY_VERTEX_LIMIT])]
        first = TRAVEL_VERTEX_LIMIT + 2
        visibility = self._visibility.setdefault(island, {})
        route = self._search(poly, options[:first], limit, visibility)
        if route is None and len(options) > first:
            route = self._search(poly, options, limit, visibility)
        return route

    def crosses_open(self, start, route):
        """Classify the chosen travel, not the original straight line."""
        points = [tuple(round(v, self.decimals) for v in p) for p in (start, *route)]
        return any(a != b and not self.region.covers(LineString((a, b)))
                   for a, b in zip(points, points[1:]))

    def _bridge(self, a, b, i, j, limit):
        """Try the closest facing edges to shorten the portion in open air."""
        source, dest = self.islands[i], self.islands[j]
        if (i, j) not in self._bridge_edges:
            p, q = nearest_points(source, dest)
            self._bridge_edges[i, j] = p.coords[0], q.coords[0]
            self._bridge_edges[j, i] = q.coords[0], p.coords[0]
        # Move off the boundary toward each endpoint before rounding to G-code precision.
        def inside_point(edge, endpoint):
            distance = math.dist(edge, endpoint)
            t = min(1., TRAVEL_WAYPOINT_INSET / distance) if distance else 1.
            return tuple(round(x + t*(y-x), self.decimals) for x, y in zip(edge, endpoint))

        # A closest pair on parallel edges can land at a remote corner. Also
        # look for facing points near the middle of the intended travel.
        middle = Point((a[0]+b[0])/2, (a[1]+b[1])/2)
        pm = nearest_points(source.exterior, middle)[0]
        qm = nearest_points(dest.exterior, middle)[0]
        pairs = (self._bridge_edges[i, j],
                 (pm.coords[0], nearest_points(dest.exterior, pm)[0].coords[0]),
                 (nearest_points(source.exterior, qm)[0].coords[0], qm.coords[0]))
        direct_air = LineString((a, b)).difference(self.region).length
        unit = 10**-self.decimals
        choices = []
        for p, q in pairs:
            p, q = inside_point(p, a), inside_point(q, b)
            length = math.dist(a, p) + math.dist(p, q) + math.dist(q, b)
            if length > limit:
                continue
            if ((a != p and not source.covers(LineString((a, p)))) or
                    (q != b and not dest.covers(LineString((q, b))))):
                continue
            air = LineString((p, q)).difference(self.region).length
            if air < direct_air - unit:
                choices.append((round(air, self.decimals), length, p, q))
        if not choices:
            return None
        _, _, p, q = min(choices)
        return [point for point, endpoint in ((p, a), (q, b)) if point != endpoint] or None

    @staticmethod
    def _search(poly, points, limit, visibility):
        """A* on the visibility graph, with a straight-line lower bound."""
        end = points[1]
        coords = np.asarray(points)
        remaining = np.hypot(*(coords - end).T)
        best = np.full(len(points), np.inf)
        best[0] = 0.
        parent = [-1] * len(points)
        queue = [(remaining[0], 0., 0)]
        while queue:
            _, cost, i = heappop(queue)
            if cost != best[i]:
                continue
            if i == 1:
                waypoints = []
                j = parent[i]
                while j > 0:
                    waypoints.append(points[j])
                    j = parent[j]
                return waypoints[::-1]
            new_cost = cost + np.hypot(*(coords - coords[i]).T)
            bound = new_cost + remaining
            ids = np.flatnonzero((new_cost < best) & (bound <= limit))
            if not len(ids):
                continue
            visible = _visible_edges(poly, coords, points, i, ids, visibility)
            for j in ids[visible]:
                best[j], parent[j] = new_cost[j], i
                heappush(queue, (bound[j], new_cost[j], j))
        return None
