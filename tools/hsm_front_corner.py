"""Offline straight-to-corner proposal with a tangent circular fillet."""
import math

from tools.check_cambam_pocket import arc_points
from tools.hsm_straight_front import try_front_cut


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
