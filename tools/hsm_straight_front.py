"""Offline straight side-cut proposals along a live-stock frontier."""
import math

from shapely.geometry import LineString
from shapely.geometry.polygon import orient

from gcodeproducer.core.geometry.polygon_parts import polygons
from tools.check_cambam_pocket import BUFFER_SEGMENTS, CLEAR_AREA_MM2
from tools.hsm_contact_replay import sampled_contact


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


def try_front_cut(pocket, stock, points, radius, *, contact_limit, sample_step):
    """Return (updated stock, sampled peak) only for a contained, useful cut.

    This trial commits one candidate, not the motion to reach its start. The
    sampled limit is a diagnostic; resolution must be checked separately.
    """
    if (not math.isfinite(radius) or radius <= 0 or not 0 < contact_limit <= 360
            or not math.isfinite(sample_step) or sample_step <= 0):
        raise ValueError('invalid cutter radius, contact limit, or sample spacing')
    axis = LineString(points)
    if not axis.length or not pocket.covers(axis) or axis.distance(pocket.boundary) < radius:
        return None
    sweep = axis.buffer(radius, quad_segs=BUFFER_SEGMENTS)
    if stock.intersection(sweep).area <= CLEAR_AREA_MM2:
        return None
    peak = 0.
    for angle, _ in sampled_contact(points, stock, radius, sample_step, BUFFER_SEGMENTS):
        if angle > contact_limit:
            return None
        peak = max(peak, angle)
    return stock.difference(sweep), peak
