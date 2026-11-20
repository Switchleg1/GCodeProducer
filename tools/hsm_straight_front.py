"""Offline straight side-cut proposals along a live-stock frontier."""
import math

from shapely.geometry import LineString
from shapely.geometry.polygon import orient

from gcodeproducer.core.geometry.polygon_parts import polygons


def frontier_edges(pocket, stock):
    """Yield straight frontier edges with stock on the left; omit pocket walls."""
    walls = pocket.boundary
    for part in polygons(stock.intersection(pocket)):
        oriented = orient(part, sign=1.)
        for ring in (oriented.exterior, *oriented.interiors):
            vertices = list(ring.coords)
            for start, end in zip(vertices, vertices[1:]):
                if start == end:
                    continue
                edge = LineString((start, end))
                exposed = edge.difference(walls)
                pieces = exposed.geoms if exposed.geom_type == 'MultiLineString' else (exposed,)
                for piece in pieces:
                    if piece.is_empty or piece.geom_type != 'LineString':
                        continue
                    a, b = piece.coords[0], piece.coords[-1]
                    aligned = sum((q-p)*(v-u) for p, q, u, v in zip(a, b, start, end)) > 0
                    yield (a, b) if aligned else (b, a)


def straight_advance(pocket, edge, radius, immersion, *, lead=0.):
    """Propose a parallel cut, offset into clearance by radius minus immersion.

    The optional straight lead extends from the edge's start. Only the pocket
    boundary is checked here; replay must verify stock contact and any entry.
    """
    if (not all(map(math.isfinite, (radius, immersion, lead)))
            or not 0 < immersion < radius or lead < 0):
        raise ValueError('expected 0 < immersion < radius and a nonnegative lead')
    (ax, ay), (bx, by) = edge
    length = math.hypot(bx-ax, by-ay)
    if not length:
        raise ValueError('expected a nonzero frontier edge')
    tx, ty = (bx-ax)/length, (by-ay)/length
    offset = radius - immersion
    points = [(ax + ty*offset - tx*lead, ay - tx*offset - ty*lead),
              (bx + ty*offset, by - tx*offset)]
    axis = LineString(points)
    return points if pocket.covers(axis) and axis.distance(pocket.boundary) >= radius else None
