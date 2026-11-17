"""Bounded same-layer travel routing around holes and concave outlines."""
from heapq import heappop, heappush
import math

from shapely import prepare
from shapely.geometry import LineString, Point, Polygon

from .fdm_constants import TRAVEL_VERTEX_LIMIT, TRAVEL_WAYPOINT_INSET


def _polygons(shape):
    if shape.geom_type == "Polygon":
        if not shape.is_empty:
            yield shape
    elif hasattr(shape, "geoms"):
        for child in shape.geoms:
            yield from _polygons(child)


class TravelRouter:
    def __init__(self, outline, decimals):
        self.decimals = decimals
        self.detours = self.fallbacks = 0
        region = Polygon()
        for ring in outline:
            if len(ring) >= 3:
                part = Polygon(ring)
                region = region.symmetric_difference(part if part.is_valid else part.buffer(0))
        self.islands = [(poly, None) for poly in _polygons(region)]
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
        start_inside = end_inside = False
        for i, (poly, vertices) in enumerate(self.islands):
            inside_a, inside_b = poly.covers(pa), poly.covers(pb)
            start_inside |= inside_a
            end_inside |= inside_b
            if not (inside_a and inside_b):
                continue
            if poly.covers(LineString((a, b))):
                return direct
            if vertices is None:
                # Inset waypoints to leave room for rounded machine coordinates.
                inner = poly.buffer(-TRAVEL_WAYPOINT_INSET, join_style=2).simplify(0)
                vertices = set()
                for part in _polygons(inner):
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
            waypoints = self._search(poly, [a, b, *(p for _, p in candidates[:TRAVEL_VERTEX_LIMIT])], limit)
            if waypoints is not None:
                self.detours += 1
                return [*waypoints, end]
            self.fallbacks += 1
            return direct
        self.fallbacks += int(start_inside or end_inside)
        return direct

    @staticmethod
    def _search(poly, points, limit):
        """A* on the visibility graph, with a straight-line lower bound."""
        end = points[1]
        best = [0.] + [math.inf] * (len(points)-1)
        parent = [-1] * len(points)
        queue = [(math.dist(points[0], end), 0., 0)]
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
            for j, q in enumerate(points[1:], 1):
                if i == j:
                    continue
                new_cost = cost + math.dist(points[i], q)
                bound = new_cost + math.dist(q, end)
                if new_cost < best[j] and bound <= limit and poly.covers(LineString((points[i], q))):
                    best[j], parent[j] = new_cost, i
                    heappush(queue, (bound, new_cost, j))
        return None
