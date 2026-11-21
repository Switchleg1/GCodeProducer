"""Offline straight-to-corner proposal with a tangent circular fillet."""
import math
from itertools import chain

from shapely.geometry import Point

from tools.check_cambam_pocket import arc_points
from tools.hsm_center_regions import cleared_start_intervals
from tools.hsm_straight_front import fitted_front_candidates, frontier_edges, try_front_cut


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


def roll_off(path, turn_radius, chord_error):
    """Append a tangent quarter turn to the right, away from a stock-left front."""
    return _quarter_exit(path, turn_radius, chord_error, -1)


def roll_on(path, turn_radius, chord_error):
    """Prepend a tangent quarter turn from the clearance side of a stock-left front."""
    return _quarter_exit(path[::-1], turn_radius, chord_error, 1)[::-1]


def shifted_roll_ons(path, turn_radius, chord_error, distances):
    """Try joining farther along the initial straight without changing the exit."""
    start, end = path[:2]
    length = math.dist(start, end)
    for distance in distances:
        if not math.isfinite(distance) or distance <= 0:
            raise ValueError('join shifts must be positive and finite')
        if distance >= length:
            continue
        join = tuple(a+(b-a)*distance/length for a, b in zip(start, end))
        yield roll_on([join, *path[1:]], turn_radius, chord_error)


def tapered_roll_on(path, offset, run, chord_error):
    """Approach a stock-left cut from a parallel line on the clearance side."""
    if not all(math.isfinite(v) and v > 0 for v in (offset, run, chord_error)):
        raise ValueError('expected positive offset, approach run and chord error')
    start, end = path[:2]
    length = math.dist(start, end)
    if not length:
        raise ValueError('expected a nonzero initial leg')
    ux, uy = ((b-a)/length for a, b in zip(start, end))
    # Cubic easing gives parallel tangents at both ends. Its maximum second
    # derivative is 6*offset, bounding uniform chord interpolation error.
    count = max(2, math.ceil(math.sqrt(6*offset/(8*chord_error))))
    lead = []
    for i in range(count):
        t = i/count
        back = (1-t)*run
        lateral = (1-t)**2*(1+2*t)*offset
        lead.append((start[0]-ux*back+uy*lateral, start[1]-uy*back-ux*lateral))
    return [*lead, *path]


def turned_straight_candidates(pocket, stock, radius, clearance, *, focus=None, longer=False, on_long_variant=None):
    """Place short straight bodies between tangent turns into mapped clearance."""
    if clearance.is_empty:
        return
    seen = set()
    axes = ((axis, (.75, 1.25, 1.75)) for axis in fitted_front_candidates(pocket, stock, radius, focus=focus))
    if longer:
        extended = ((axis, tuple(span for span in (2.25, 2.75, 3.25) if span <= math.dist(*axis)))
                    for axis in fitted_front_candidates(pocket, stock, radius, focus=focus, extensions=(0.,)))
        axes = chain(axes, extended)
    for (start, end), spans in axes:
        length = math.dist(start, end)
        ux, uy = ((b-a)/length for a, b in zip(start, end))
        mx, my = ((a+b)/2 for a, b in zip(start, end))
        for span in spans:
            for advance in (0., .08):
                x, y = mx-uy*advance, my+ux*advance
                body = [(x-ux*span/2, y-uy*span/2), (x+ux*span/2, y+uy*span/2)]
                key = tuple(round(v, 9) for point in body for v in point)
                if key in seen:
                    continue
                seen.add(key)
                for r in (.4, .65):
                    path = roll_off(roll_on(body, r, .0025), r, .0025)
                    mapped = clearance.covers(Point(path[0])) and clearance.covers(Point(path[-1]))
                    if span >= 2.25 and on_long_variant is not None:
                        on_long_variant(mapped)
                    if mapped:
                        yield path


def clearance_tapers(pocket, stock, path, radius, *, offset, run, chord_error):
    """Sample tapered joins whose starts lie in verified live clearance."""
    start, end = path[:2]
    length = math.dist(start, end)
    if length <= radius:
        return
    heading = tuple((b-a)/length for a, b in zip(start, end))
    guide_start = tapered_roll_on(path, offset, run, chord_error)[0]
    guide_end = tuple(x + d*(length-radius) for x, d in zip(guide_start, heading))
    for lo, hi in cleared_start_intervals(pocket, stock, guide_start, guide_end, radius):
        for shift in (lo + .1*(hi-lo), (lo+hi)/2):
            join = tuple(x + d*shift for x, d in zip(start, heading))
            yield tapered_roll_on([join, *path[1:]], offset, run, chord_error)


def _quarter_exit(path, turn_radius, chord_error, sign):
    if not all(math.isfinite(v) and v > 0 for v in (turn_radius, chord_error)):
        raise ValueError('expected positive turn radius and chord error')
    start, end = path[-2:]
    length = math.dist(start, end)
    if not length:
        raise ValueError('expected a nonzero final leg')
    ux, uy = ((b-a)/length for a, b in zip(start, end))
    offset = (-sign*uy*turn_radius, sign*ux*turn_radius)
    exit = (end[0]+offset[0]+ux*turn_radius, end[1]+offset[1]+uy*turn_radius)
    arc, _ = arc_points(end, exit, offset, sign, chord_error)
    return [*path, *arc[1:]]


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
