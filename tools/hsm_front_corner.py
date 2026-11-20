"""Offline straight-to-corner proposal with a tangent circular fillet."""
import math

from tools.check_cambam_pocket import arc_points
from tools.hsm_straight_front import frontier_edges, try_front_cut


def frontier_corner_poses(pocket, stock, radius, immersion, *, lead=0., runoff=0.):
    """Yield offset waypoints at adjacent exposed edges, before cut validation."""
    if (not all(map(math.isfinite, (radius, immersion, lead, runoff)))
            or not 0 < immersion < radius or min(lead, runoff) < 0):
        raise ValueError('expected 0 < immersion < radius and nonnegative lead/runoff')
    edges = list(frontier_edges(pocket, stock))
    successors = {}
    for start, end in edges:
        successors.setdefault(start, []).append(end)
    offset = radius - immersion
    for start, join in edges:
        for end in successors.get(join, ()):
            a, b = math.dist(start, join), math.dist(join, end)
            ux, uy = ((q-p)/a for p, q in zip(start, join))
            vx, vy = ((q-p)/b for p, q in zip(join, end))
            cross = ux*vy-uy*vx
            if abs(cross) < 1e-6:
                continue
            dx, dy = offset*(vy-uy), offset*(ux-vx)
            shift = (dx*vy-dy*vx)/cross
            if a+shift <= 0 or b+shift <= 0:
                continue
            entry = (start[0]+offset*uy-lead*ux, start[1]-offset*ux-lead*uy)
            vertex = (join[0]+offset*uy+shift*ux, join[1]-offset*ux+shift*uy)
            exit = (end[0]+offset*vy+runoff*vx, end[1]-offset*vx+runoff*vy)
            yield entry, vertex, exit


def filleted_corner(start, vertex, end, turn_radius, chord_error):
    """Return a tangent chord chain, or None when the fillet cannot fit."""
    if not all(math.isfinite(v) and v > 0 for v in (turn_radius, chord_error)):
        raise ValueError('expected positive turn radius and chord error')
    lengths = math.dist(start, vertex), math.dist(vertex, end)
    if not all(lengths):
        return None
    ux, uy = ((b-a)/lengths[0] for a, b in zip(start, vertex))
    vx, vy = ((b-a)/lengths[1] for a, b in zip(vertex, end))
    turn = math.atan2(ux*vy-uy*vx, ux*vx+uy*vy)
    if abs(turn) < 1e-9 or math.pi-abs(turn) < 1e-9:
        return None
    trim = turn_radius*math.tan(abs(turn)/2)
    if trim >= min(lengths):
        return None
    ax, ay = vertex
    entry = (ax-trim*ux, ay-trim*uy)
    exit = (ax+trim*vx, ay+trim*vy)
    sign = 1 if turn > 0 else -1
    arc, _ = arc_points(entry, exit, (-sign*uy*turn_radius, sign*ux*turn_radius), sign, chord_error)
    return [start, *arc, end]


def try_corner_advance(pocket, stock, start, vertex, end, radius, *, turn_radius,
                       chord_error, contact_limit, sample_step):
    """Check both straights and their transition as one progressive cut."""
    points = filleted_corner(start, vertex, end, turn_radius, chord_error)
    if points is None:
        return None
    result = try_front_cut(pocket, stock, points, radius, contact_limit=contact_limit, sample_step=sample_step)
    if result is None:
        return None
    remaining, peak = result
    return points, remaining, peak
