"""Bounded same-layer travel routing around holes and concave outlines."""
from heapq import heappop, heappush
import math

import numpy as np
from shapely import covers, linestrings, prepare
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points

from .fdm_constants import TRAVEL_RETRY_VERTEX_LIMIT, TRAVEL_VERTEX_LIMIT, TRAVEL_WAYPOINT_INSET

from gcodeproducer.core.geometry.polygon_parts import polygons


class TravelRouter:
    def __init__(self, outline, decimals):
        self.decimals = decimals
        self.detours = self.fallbacks = self.outside = self.bridges = 0
        region = Polygon()
        for ring in outline:
            if len(ring) >= 3:
                part = Polygon(ring)
                region = region.symmetric_difference(part if part.is_valid else part.buffer(0))
        self.region = region
        self.islands = [(poly, None) for poly in polygons(region)]
        self._bridge_edges = {}
        for poly, _ in self.islands:
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
        for i, (poly, vertices) in enumerate(self.islands):
            inside_a, inside_b = poly.covers(pa), poly.covers(pb)
            if inside_a:
                start_island = i
            if inside_b:
                end_island = i
            if not (inside_a and inside_b):
                continue
            if poly.covers(LineString((a, b))):
                return direct
            if vertices is None:
                # Inset waypoints to leave room for rounded machine coordinates.
                inner = poly.buffer(-TRAVEL_WAYPOINT_INSET, join_style=2).simplify(0)
                vertices = set()
                for part in polygons(inner):
                    for ring in (part.exterior, *part.interiors):
                        vertices.update((round(x, self.decimals), round(y, self.decimals))
                                        for x, y in list(ring.coords)[:-1])
                vertices = sorted(vertices)
                self.islands[i] = poly, vertices
            candidates = []
            for p in vertices:
                if p != a and p != b:
                    lower = math.dist(a, p) + math.dist(p, b)
                    if lower <= limit:
                        candidates.append((lower, p))
            # Keep the best lower bounds; raising the budget can only append
            # less promising candidates, not disable a previously valid route.
            candidates.sort()
            options = [a, b, *(p for _, p in candidates[:TRAVEL_RETRY_VERTEX_LIMIT])]
            first = TRAVEL_VERTEX_LIMIT + 2
            waypoints = self._search(poly, options[:first], limit)
            if waypoints is None and len(options) > first:
                waypoints = self._search(poly, options, limit)
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

    def crosses_open(self, start, route):
        """Classify the chosen travel, not the original straight line."""
        points = [tuple(round(v, self.decimals) for v in p) for p in (start, *route)]
        return any(a != b and not self.region.covers(LineString((a, b)))
                   for a, b in zip(points, points[1:]))

    def _bridge(self, a, b, i, j, limit):
        """Try the closest facing edges to shorten the portion in open air."""
        source, dest = self.islands[i][0], self.islands[j][0]
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
    def _search(poly, points, limit):
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
            edges = np.empty((len(ids), 2, 2))
            edges[:, 0] = coords[i]
            edges[:, 1] = coords[ids]
            for j in ids[covers(poly, linestrings(edges))]:
                best[j], parent[j] = new_cost[j], i
                heappush(queue, (bound[j], new_cost[j], j))
        return None
