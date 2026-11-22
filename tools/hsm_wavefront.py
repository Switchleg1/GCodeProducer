"""Offline wavefront clearing: helical islands, outward spirals, then rounded offset fronts.

Every pass is the cleared cutter-centre region grown by one stepover and
clipped to the pocket. Cuts start and end on the previous front, so they
roll into and out of the material. Moves between cuts are rapids and are
not planned here. Planar geometry only; nothing is qualified for a machine.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import NamedTuple

import numpy as np
from shapely import contains_xy, covers, distance, get_coordinates, get_parts, line_interpolate_point, points, prepare, segmentize
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, polylabel, split, substring, unary_union

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gcodeproducer.core.cam.adaptive_entry import seed_entry
from gcodeproducer.core.geometry.polygon_parts import polygons
from tools.hsm_center_regions import CENTER_BUFFER_SEGMENTS, center_regions
from tools.hsm_contact_replay import indexed_contact
from tools.hsm_replay_overlay import write_overlay

STEPOVERS = (1., .8, .65, .5, .45, .4, .35, .3, .25, .2, .15, .12)
SWEEP_SEGMENTS = 16
CUT_SEGMENTS = 32  # keeps a cut's end cap within the link tolerance of a true disc
WALL_TOLERANCE = .02
CORNER_DEPTH = .3  # mm of stock a corner creep may meet at its deepest point
CORNER_TURN = 30.  # degrees of wall turn that make a corner worth creeping into
CORNER_RUN_IN = 8.  # mm of wall back from a corner where a creep may start
CORNER_STEPS = (2., 1., .4, .3, .2, .15, .1, .06)  # mm a corner creep goes deeper each time, tried in turn
SLIVER = 1e-3  # mm; half the thickness of a film of stock that is only polygon arithmetic
MIN_GAIN_MM2 = 1e-4
ELONGATED_ASPECT = 2.
NECK_RATIO = 2.  # a lobe is at least this much wider than the neck that separates it
HOLED_NECK_RATIO = 1.15  # the same round a boss
PROFILE_CHUNK = 8.  # mm of wall judged at a time
GLANCE_TURN = 40.  # degrees turned over a hook's length; more means the arc is curling onto an old hook
GLANCE_REACH = 6.  # mm of wall an arc may run on along before reaching clean wall
GLANCE_ANGLE = 55.  # degrees; an arc meeting the wall more squarely than this gets a hook
BOW_WIDTH_FACTOR = 2.6  # a channel narrower than this many full hook trims is crossed in one bow
BOW_SET_BACKS = 6  # tries at setting a bow back behind a curved front
BOW_EXCESS = .03  # mm a bow may stand out beyond its front
ROLL_STEPOVER = .35  # mm; at or below this an arc may roll off before the wall instead of sweeping it
SPAN_SLACK = .15  # cutter radii by which a spiral may miss the second wall and still span the channel
STEADY_STEPOVER = .4  # mm; from here up a refused larger stepover is not retried on every pass
RAISE_PATIENCE = 2  # passes at one stepover before a larger one is tried again
RAISE_PATIENCE_MAX = 8  # the wait doubles up to this each time the larger one is refused
BOW_PARALLEL = 8.  # degrees; walls further from parallel than this get separate hooks
HOOK_SHARE = .45  # share of the channel width each end of a bow may round
MIN_HOOK_TRIM = .5  # mm; below this an arc end rolls off to the old front instead
HOOK_SEARCH = 25.  # mm of arc searched back from the wall for a steady heading
HOOK_RADIUS_FACTOR = 2.0  # hook radius at the wall, in cutter radii
WALL_CORNER = 40.  # degrees of wall turning within CORNER_WINDOW that end a wall
CORNER_WINDOW = 2.  # mm
WALL_GAP = .8  # mm between cleared ground and the wall beyond which the wall is not followed
NEAR_WALL = .3  # mm; an arc end this close to the wall is carried onto it
WALL_REACH = 20.  # mm; farthest an arc end follows the wall back looking for clean wall
LINK_TOLERANCE = 1e-3  # mm; buffered arcs make the cleared region slightly approximate


class Stroke(NamedTuple):
    kind: str  # 'spiral', 'front', 'corner' or wall 'profile' cut, or a stay-down 'link' through cleared area
    points: list
    stepover_mm: float
    peak_deg: float


def find_lobes(allowed, *, min_radius, step=.25, neck_ratio=None):
    """Split a cutter-centre region at its necks: [(widest xy, distance to wall, bounds)].

    The region is shrunk in steps. A piece counts as a lobe while its widest
    spot is at least neck_ratio times the shrink that separated it, so a
    passage must be clearly narrower than the areas it joins. Round a boss a
    milder narrowing counts: fronts from one start would have to wrap round
    the boss both ways and fan out at its corners, so each wider spot on the
    way round is worth its own start.
    """
    if neck_ratio is None:
        holed = any(part.interiors for part in polygons(allowed))
        neck_ratio = HOLED_NECK_RATIO if holed else NECK_RATIO
    def widest(part):
        centre = polylabel(part, tolerance=.05)
        return centre, centre.distance(allowed.boundary)

    whole = [(c, room, part.bounds) for part in polygons(allowed) if part.area > 1e-6
             for c, room in [widest(part)] if room >= min_radius]
    best, shrink = whole, step
    limit = max((room for _, room, _ in whole), default=0.)/neck_ratio
    while shrink <= limit:
        lobes = []
        for core in polygons(allowed.buffer(-shrink)):
            if core.area < 1e-6:
                continue
            centre, room = widest(core)
            if room >= max(min_radius, neck_ratio*shrink):
                lobes.append((centre, room, core.buffer(shrink).intersection(allowed).bounds))
        if len(lobes) > len(best):
            best = lobes
        shrink += step
    return [((c.x, c.y), room, bounds) for c, room, bounds in sorted(best, key=lambda lobe: -lobe[1])]


def choose_seeds(allowed, count=None, *, min_radius, placement='lobes'):
    """Place island centres: (xy, distance to wall).

    One island sits at the widest spot. Several are spread along the long
    axis, one third of the way in from each end for two, each snapped to the
    widest spot of its own band.
    """
    if count is not None and count < 1:
        raise ValueError('expected at least one island')
    if placement not in ('lobes', 'thirds', 'widest'):
        raise ValueError('unknown island placement')
    if placement == 'lobes':
        lobes = find_lobes(allowed, min_radius=min_radius)
        if len(lobes) != 1:
            return [(xy, room) for xy, room, _ in (lobes if count is None else lobes[:count])]
        # One lobe: a long shape takes two islands, a squarer one a single island.
        corners = list(allowed.minimum_rotated_rectangle.exterior.coords)[:4]
        sides = sorted((math.dist(corners[0], corners[1]), math.dist(corners[1], corners[2])))
        count = count or (2 if sides[1] >= ELONGATED_ASPECT*sides[0] else 1)
        placement = 'thirds'
    if count is None:
        raise ValueError('this placement needs an island count')
    if placement == 'widest' and count > 1:
        seeds, remaining = [], allowed
        for _ in range(count):
            spots = [(c.distance(allowed.boundary), c) for c in
                     (polylabel(part, tolerance=.05) for part in polygons(remaining) if part.area > 1e-6)]
            spots = [(min(room, c.distance(remaining.boundary)), room, c) for room, c in spots]
            if not spots:
                break
            free, room, c = max(spots, key=lambda spot: spot[0])
            if free < min_radius:
                break
            seeds.append(((c.x, c.y), room))
            remaining = remaining.difference(c.buffer(room))
        return seeds
    if count == 1:
        bands = [allowed]
    else:
        corners = list(allowed.minimum_rotated_rectangle.exterior.coords)[:4]
        a, b, c = corners[0], corners[1], corners[2]
        if math.dist(a, b) < math.dist(b, c):
            a, b, c = b, c, corners[3]
        length, width = math.dist(a, b), math.dist(b, c)
        ux, uy = (b[0]-a[0])/length, (b[1]-a[1])/length
        vx, vy = (c[0]-b[0])/width, (c[1]-b[1])/width
        half = length/(2*(count+1))
        bands, targets = [], []
        for i in range(count):
            mid = length*(i+1)/(count+1)
            lo, hi = mid-half, mid+half
            slab = [(a[0]+ux*lo, a[1]+uy*lo), (a[0]+ux*hi, a[1]+uy*hi),
                    (a[0]+ux*hi+vx*width, a[1]+uy*hi+vy*width), (a[0]+ux*lo+vx*width, a[1]+uy*lo+vy*width)]
            bands.append(allowed.intersection(Polygon(slab)))
            targets.append(Point(a[0]+ux*mid+vx*width/2, a[1]+uy*mid+vy*width/2))
    seeds = []
    for index, band in enumerate(bands):
        best = None
        for part in polygons(band):
            if part.area < 1e-6:
                continue
            centre = polylabel(part, tolerance=.05)
            room = centre.distance(allowed.boundary)
            if best is None or room > best[1]:
                best = (centre.x, centre.y), room
        if best is not None and count > 1 and allowed.covers(targets[index]):
            # Keep the even spacing unless a clearly wider spot exists in the band.
            room = targets[index].distance(allowed.boundary)
            if room >= .95*best[1]:
                best = (targets[index].x, targets[index].y), room
        if best is not None and best[1] >= min_radius:
            seeds.append(best)
    return seeds


def spiral_out(centre, max_radius, stepover, *, chord_error=.0025, blend=3.):
    """Stock-left (clockwise) spiral from the centre, one full circle, then a roll-off inward."""
    if max_radius <= 0 or stepover <= 0:
        raise ValueError('expected a positive spiral radius and stepover')
    points, theta = [], 0.

    def add(radius):
        points.append((centre[0] + radius*math.cos(-theta), centre[1] + radius*math.sin(-theta)))

    def advance(radius):
        return min(.5, 2*math.acos(max(-1., 1 - chord_error/max(radius, 2*chord_error))))

    radius = 0.
    while radius < max_radius:
        add(radius)
        theta += advance(radius)
        radius = stepover*theta/(2*math.pi)
    full = theta + 2*math.pi
    while theta < full:
        add(max_radius)
        theta += advance(max_radius)
    retreat = min(stepover, max_radius/2)
    sweep = blend/max_radius
    end = theta + sweep
    while theta < end:
        t = 1 - (end-theta)/sweep
        add(max_radius - retreat*t*t*(3-2*t))
        theta += advance(max_radius)
    return points


def clearance(allowed, stock, radius):
    """Cutter-centre positions whose whole disk is clear of live stock."""
    if stock.is_empty:
        return allowed
    return allowed.difference(stock.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS))


def grow_clearance(clear, allowed, stock, path, radius):
    """clearance(allowed, stock, radius) after a cut along path, given it from before the cut.

    A cut only opens centre positions within two cutter radii of its path,
    and stock only ever shrinks, so the new positions are worked out stretch
    by stretch near the path and added. Recomputing the whole pocket after
    every cut took over half of the run time.
    """
    reach, stretch, length, added = 2*radius + .1, [path[0]], 0., []
    for i in range(1, len(path)):
        stretch.append(path[i])
        length += math.dist(path[i-1], path[i])
        if length >= 8. or i == len(path)-1:
            xs, ys = zip(*stretch)
            around = box(min(xs)-reach, min(ys)-reach, max(xs)+reach, max(ys)+reach)
            near = stock.intersection(around.buffer(radius + .1, join_style=2))
            opened = allowed.intersection(around)
            if not near.is_empty:
                opened = opened.difference(near.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS))
            added.append(opened)
            stretch, length = [path[i]], 0.
    return unary_union([clear, *added])


def fronts(clear, grown, wall, *, zone=None):
    """Stock-left runs of the grown boundary that are not pocket wall: (points, closed)."""
    runs = []
    for part in polygons(grown):
        if part.area < 1e-6 or not part.intersects(clear):
            continue
        part = orient(part, sign=-1.)
        for ring in (part.exterior, *part.interiors):
            pts = list(ring.coords)[:-1]
            n = len(pts)
            free = [wall.distance(Point((pts[i][0]+pts[(i+1) % n][0])/2,
                                        (pts[i][1]+pts[(i+1) % n][1])/2)) > WALL_TOLERANCE for i in range(n)]
            if all(free):
                runs.append((pts + [pts[0]], True))
                continue
            if not any(free):
                continue
            start = next(i for i in range(n) if free[i] and not free[i-1])
            run = []
            for k in range(n):
                i = (start+k) % n
                if free[i]:
                    run = run or [pts[i]]
                    run.append(pts[(i+1) % n])
                elif run:
                    runs.append((run, False))
                    run = []
            if run:
                runs.append((run, False))
    if zone is not None:
        clipped = []
        for run, _ in runs:
            line = LineString(run)
            for piece in get_parts(line.intersection(zone)):
                if piece.geom_type != 'LineString' or piece.is_empty:
                    continue
                pts = list(piece.coords)
                if line.project(Point(pts[0])) > line.project(Point(pts[-1])):
                    pts.reverse()
                clipped.append((pts, False))
        runs = clipped
    long = [(run, closed) for run, closed in runs if LineString(run).length >= 1.]
    return long or [(run, closed) for run, closed in runs if LineString(run).length >= .3]


def eased(run, closed, clear, allowed, blend, *, ends=(True, True)):
    """Roll on from the old front and roll off back to it; closed rings overlap their start."""
    line = LineString(run)
    reach = min(blend, line.length/3)
    pts = list(run)
    if closed:
        pts += list(substring(line, 0., min(2*reach, line.length)).coords)[1:]
    dense = list(segmentize(LineString(pts), .1).coords)
    total = LineString(dense).length
    out, travelled = [], 0.
    for i, q in enumerate(dense):
        if i:
            travelled += math.dist(dense[i-1], q)
        near = min(travelled if ends[0] else math.inf, total-travelled if ends[1] else math.inf)
        t = near/reach if reach else 1.
        if t < 1.:
            w = max(0., t*t*(3-2*t))
            n = nearest_points(clear, Point(q))[0]
            q = (n.x + (q[0]-n.x)*w, n.y + (q[1]-n.y)*w)
        if not out or q != out[-1]:
            out.append(q)
    inside = covers(allowed, points(out)).tolist() if out else []
    if not all(inside):
        kept = []
        for q, ok in zip(out, inside):
            if not ok:
                n = nearest_points(allowed, Point(q))[0]
                q = (n.x, n.y)
            if not kept or q != kept[-1]:
                kept.append(q)
        out = kept
    return out


def stay_down_link(clear, stock, radius, start, end, *, why=None):
    """Feed route through already cleared space, or None when a retract is needed.

    The route follows the edge of the cleared-centre region and is pulled
    taut where the cutter can see ahead. It is checked against live stock.
    """
    def refuse(reason):
        if why is not None:
            why[reason] = why.get(reason, 0) + 1

    if math.dist(start, end) < 1e-9:
        return [start, end]
    part = next((g for g in polygons(clear) if g.distance(Point(start)) < LINK_TOLERANCE and g.distance(Point(end)) < LINK_TOLERANCE),
                None)
    if part is None:
        return refuse('separate_cleared_areas')
    room = part.buffer(LINK_TOLERANCE)
    prepare(room)

    def visible(a, b):
        return room.covers(LineString([a, b]))

    if visible(start, end):
        route = [start, end]
    else:
        ring = LineString(part.exterior.coords)
        a = ring.interpolate(ring.project(Point(start)))
        b = ring.interpolate(ring.project(Point(end)))
        if not visible(start, (a.x, a.y)) or not visible((b.x, b.y), end):
            return refuse('no_way_to_front_edge')
        da, db = ring.project(a), ring.project(b)
        lo, hi = sorted((da, db))
        inner = list(substring(ring, lo, hi).coords)
        outer = list(substring(ring, hi, ring.length).coords) + list(substring(ring, 0., lo).coords)[1:]
        if LineString(outer).length < LineString(inner).length:
            walk = outer if da > db else outer[::-1]
        else:
            walk = inner if da <= db else inner[::-1]
        walk = [start, *walk, end]
        route, i = [start], 0
        while i < len(walk)-1:
            j, reach = i+1, 1
            while i+reach < len(walk) and visible(walk[i], walk[min(i+2*reach, len(walk)-1)]):
                j = min(i+2*reach, len(walk)-1)
                if j == len(walk)-1:
                    break
                reach *= 2
            route.append(walk[j])
            i = j
    if not stock.is_empty and LineString(route).distance(stock) < radius - 5*LINK_TOLERANCE:
        return refuse('route_touches_stock')
    return route


_WALL_MEMO = {'for': (None, None), 'found': {}}


def along_wall(rings, xy, part, own, radius, overlap, *, at_least=0., limit=WALL_REACH):
    """walk_wall, remembered while the cleared area and stock stay the same.

    One front asks about the same wall points several times over: to see
    whether its ends are on the wall, again for each shape of end tried, and
    again for each position of a bow.
    """
    if _WALL_MEMO['for'][0] is not part or _WALL_MEMO['for'][1] is not own:
        _WALL_MEMO['for'], _WALL_MEMO['found'] = (part, own), {}
    key = (round(xy[0], 6), round(xy[1], 6), radius, overlap, at_least, limit, len(rings))
    if key not in _WALL_MEMO['found']:
        _WALL_MEMO['found'][key] = walk_wall(rings, xy, part, own, radius, overlap, at_least=at_least, limit=limit)
    found = _WALL_MEMO['found'][key]
    return None if found is None else list(found)


def walk_wall(rings, xy, part, own, radius, overlap, *, at_least=0., limit=WALL_REACH):
    """Dense points from a wall point back along the wall until it is already clean, plus an overlap.

    The wall counts as clean where the cutter, sitting on it, would find no
    more than a WALL_TOLERANCE skin of this island's stock. The walk also
    stops where the cleared area falls away from the wall: beyond that the
    stock beside the wall is too thick to take in passing, and following it
    would be a slot. Returns None for a point that is not on the wall.
    """
    at = Point(xy)
    ring = min(rings, key=lambda r: r.distance(at), default=None)
    # A front often ends a few hundredths short of the wall behind a thin skin; that still counts.
    if ring is None or ring.distance(at) > NEAR_WALL:
        return None
    here, total = ring.project(at), ring.length
    foot = ring.interpolate(here)
    steps = max(2, math.ceil(limit/.1))

    def walk(sign):
        at = (here + sign*limit*np.arange(1, steps+1)/steps) % total
        return [tuple(q) for q in get_coordinates(line_interpolate_point(ring, at)).tolist()]

    probe = min(4, steps-1) + 1
    way = walk(min((1, -1), key=lambda sign: part.distance(ring.interpolate((here + sign*limit*probe/steps) % total))))
    # Measure against what lies near this stretch of wall only; the whole pocket is far slower.
    xs, ys = zip(*way)
    around = box(min(xs), min(ys), max(xs), max(ys))
    near_own = own.intersection(around.buffer(radius + .5)) if not own.is_empty else own
    clean = [True]*len(way) if near_own.is_empty else (distance(near_own, points(way)) >= radius - WALL_TOLERANCE).tolist()
    keep, spacing = len(way), limit/steps
    if any(clean):
        keep = min(len(way), max(clean.index(True) + 1 + math.ceil(overlap/spacing), math.ceil(at_least/spacing)))
    # Stay on this wall: a corner leads onto a different wall, often into another arm full of stock.
    headings = [math.atan2(b[1]-a[1], b[0]-a[0]) for a, b in zip(way, way[1:])]
    window = max(1, round(CORNER_WINDOW/spacing))
    for k in range(window, len(headings)):
        if abs((headings[k]-headings[k-window]+math.pi) % (2*math.pi) - math.pi) > math.radians(WALL_CORNER):
            keep = min(keep, k)
            break
    near_part = part.intersection(around.buffer(WALL_GAP + 3.))
    gap = np.full(len(way), WALL_GAP + 3.) if near_part.is_empty else distance(near_part, points(way))
    deep = (gap > max(WALL_GAP, float(gap[0]) + .2)).tolist()
    if any(deep):
        keep = min(keep, deep.index(True))
    if not any(clean[:keep]):
        # Nothing clean within reach: the cleared area only comes close to the wall here. Go as far as
        # its nearest approach; the arc arriving from the other side takes the rest.
        keep = min(keep, int(gap[:keep].argmin()) + 1 + math.ceil(overlap/spacing))
    if keep < 2:
        return None
    onto = [] if math.dist(xy, (foot.x, foot.y)) < 1e-9 else [(foot.x, foot.y)]
    return [tuple(xy)] + onto + way[:keep]


def fillet(first, second, trim, *, shares=(1/3, 1/2)):
    """Join two legs that meet at first[-1] == second[0] with a curve tangent to both.

    shares caps how much of each leg the curve may replace.
    """
    a, b = LineString(first), LineString(second)
    trim = min(trim, a.length*shares[0], b.length*shares[1])
    if trim <= 0:
        return list(first) + list(second)[1:]
    start, end, corner = a.interpolate(a.length-trim), b.interpolate(trim), first[-1]
    curve = [((1-t)**2*start.x + 2*(1-t)*t*corner[0] + t*t*end.x,
              (1-t)**2*start.y + 2*(1-t)*t*corner[1] + t*t*end.y) for t in (k/8 for k in range(1, 8))]
    return list(substring(a, 0., a.length-trim).coords) + curve + list(substring(b, trim, b.length).coords)


def turn_away(before, end, allowed, radius):
    """Quarter turn off the wall into the pocket, leaving end along the travel direction."""
    length = math.dist(before, end)
    if not length:
        return []
    tx, ty = (end[0]-before[0])/length, (end[1]-before[1])/length
    for nx, ny in ((-ty, tx), (ty, -tx)):
        if allowed.buffer(-.05).covers(Point(end[0]+nx*radius/2, end[1]+ny*radius/2)):
            return [(end[0] + radius*(math.sin(a)*tx + (1-math.cos(a))*nx),
                     end[1] + radius*(math.sin(a)*ty + (1-math.cos(a))*ny))
                    for a in (math.pi/2*k/8 for k in range(1, 9))]
    return []


def hook_to_wall(path, rings, part, own, radius, allowed, trim, overlap, turn):
    """Replace the last stretch of an arc with a wide hook onto the wall, or return None.

    The hook rounds the corner between the wall and the arc's own heading a
    little way back, not the arc's actual end: a front grown from an earlier
    hook curls in early at the wall, and hooking from that would land further
    back every pass. Built this way successive hooks nest one stepover apart.
    """
    line = LineString(path)
    # A short arc gets a proportionally tighter hook, which the contact check then answers with a
    # smaller stepover; without any hook the wall side would stall.
    trim = min(trim, line.length/4)
    if trim < MIN_HOOK_TRIM:
        return None

    def heading(back):
        a, b = line.interpolate(line.length-back-.3), line.interpolate(line.length-back)
        return math.atan2(b.y-a.y, b.x-a.x)

    def turned(one, other):
        return abs((heading(one)-heading(other)+math.pi) % (2*math.pi) - math.pi)

    # Step back past the curl to where the arc turns at a steady rate. A round front turns all the
    # way along, so it is the change in turning, not the turning, that marks the curl.
    back, limit = trim, min(line.length/2, HOOK_SEARCH)
    while back + 3. < limit and abs(turned(back, back+1.5) - turned(back+1.5, back+3.)) > math.radians(4):
        back += .5
    ring = min(rings, key=lambda r: r.distance(Point(path[-1])), default=None)
    span = min(2., (line.length-back)/2)
    if ring is None or span < .2:
        return None
    # Carry the arc on with the curvature it has there. A straight run-up would leave a round front
    # on its outside and dig into stock.
    p0, p1, p2 = (line.interpolate(line.length-back-k*span) for k in (2, 1, 0))
    a1, a2 = math.atan2(p1.y-p0.y, p1.x-p0.x), math.atan2(p2.y-p1.y, p2.x-p1.x)
    bend = ((a2-a1+math.pi) % (2*math.pi) - math.pi)/span  # radians per mm, signed
    angle, x, y, onward = a2 + bend*span/2, p2.x, p2.y, [(p2.x, p2.y)]
    for _ in range(math.ceil((back + 4*trim)/.2)):
        angle += bend*.2
        x, y = x + .2*math.cos(angle), y + .2*math.sin(angle)
        onward.append((x, y))
    ahead = LineString(onward).intersection(ring)
    if ahead.is_empty:
        return None
    run_up = LineString(onward)
    reach = min(run_up.project(g) for g in get_parts(ahead) if g.geom_type == 'Point') if any(
        g.geom_type == 'Point' for g in get_parts(ahead)) else None
    if reach is None or reach < 1e-6:
        return None
    corner = run_up.interpolate(reach)
    tail = along_wall(rings, (corner.x, corner.y), part, own, radius, overlap, at_least=trim+overlap)
    if tail is None:
        return None
    leg = list(substring(line, 0., line.length - back).coords) + list(substring(run_up, 0., reach).coords)[1:]
    hooked = fillet(leg, tail, trim, shares=(1., .85))
    return hooked + turn_away(tail[-2], tail[-1], allowed, turn)


def glance_onto_wall(path, rings, part, own, radius, allowed, trim, overlap, turn):
    """Let an arc that meets the wall at a shallow angle run on along it; None if it meets it steeply.

    Where the cleared area nearly touches a wall, the next front arrives
    almost parallel to the wall and the cleared ground along the wall lies
    ahead of it. The arc then only has to bend a little to follow the wall
    until it is clean. A hook is wrong there: its straight run-up leaves a
    tightly curved front and digs into stock.
    """
    tail = along_wall(rings, path[-1], part, own, radius, overlap, at_least=overlap+1.)
    # Running on is only light while the wall ahead is nearly clean; a long dirty stretch would be a slot.
    if tail is None or len(tail) < 3 or LineString(tail).length > GLANCE_REACH:
        return None
    line = LineString(path)

    def heading(back):
        a, b = line.interpolate(max(0., line.length-back-1.)), line.interpolate(max(0., line.length-back))
        return math.atan2(b.y-a.y, b.x-a.x)

    def apart(one, other):
        return abs((one-other+math.pi) % (2*math.pi) - math.pi)

    # Skip the last millimetre, where the front rounds onto the wall. A front that follows an earlier
    # hook also comes in shallow, but it has turned sharply to do so; following that curl would land
    # further back every pass.
    there = math.atan2(tail[-1][1]-tail[1][1], tail[-1][0]-tail[1][0])
    near, far = heading(1.), heading(1. + min(trim, line.length/3))
    if apart(there, near) > math.radians(GLANCE_ANGLE) or apart(near, far) > math.radians(GLANCE_TURN):
        return None
    return fillet(path, tail, 1., shares=(1/3, .6)) + turn_away(tail[-2], tail[-1], allowed, turn)


def bow_across(path, rings, part, own, radius, allowed, full, overlap, turn):
    """In a narrow channel with near-parallel walls, cross it as one bow; None anywhere else.

    The cut comes in along one wall, curves out across the channel through
    the middle of the front at right angles to the walls, curves onto the
    other wall tangentially and runs back along it toward cleared ground.
    Every pass then has the same shape one stepover further on. Two separate
    hooks on so short an arc are tight corners that dig in.
    """
    line = LineString(path)
    if line.length < 1.:
        return None
    half = min(1., line.length/8)
    mid = line.interpolate(line.length/2)
    a, b = line.interpolate(line.length/2-half), line.interpolate(line.length/2+half)
    span = math.dist((a.x, a.y), (b.x, b.y))
    if not span:
        return None
    hx, hy = (b.x-a.x)/span, (b.y-a.y)/span
    reach = line.length + 2*full

    def hit(sign):
        ray = LineString([(mid.x, mid.y), (mid.x + sign*hx*reach, mid.y + sign*hy*reach)])
        best = None
        for ring in rings:
            for piece in get_parts(ray.intersection(ring)):
                if piece.is_empty:
                    continue
                q = nearest_points(piece, mid)[0]
                if q.distance(mid) > 1e-6 and (best is None or q.distance(mid) < best[0]):
                    best = q.distance(mid), (q.x, q.y), ring
        return best

    def wall_heading(ring, xy):
        at, total = ring.project(Point(xy)), ring.length
        p, q = ring.interpolate((at-.5) % total), ring.interpolate((at+.5) % total)
        return math.atan2(q.y-p.y, q.x-p.x)

    ahead, behind = hit(1), hit(-1)
    if ahead is None or behind is None:
        return None
    # Cross at right angles to the two walls the front spans, not along the front: the front only
    # lies square to the walls in a straight channel, and following it round a curved one would turn
    # the crossing a little further from square on every pass.
    one, other = wall_heading(ahead[2], ahead[1]), wall_heading(behind[2], behind[1])
    if math.cos(one - other) < 0:
        other += math.pi
    tx, ty = math.cos(one) + math.cos(other), math.sin(one) + math.sin(other)
    if math.hypot(tx, ty) > 1e-9:
        nx, ny = -ty/math.hypot(tx, ty), tx/math.hypot(tx, ty)
        hx, hy = (nx, ny) if nx*hx + ny*hy >= 0 else (-nx, -ny)
        ahead, behind = hit(1), hit(-1)
        if ahead is None or behind is None:
            return None
    def build():
        width = ahead[0] + behind[0]
        skew = wall_heading(ahead[2], ahead[1]) - wall_heading(behind[2], behind[1])
        if width > BOW_WIDTH_FACTOR*full or abs((skew + math.pi/2) % math.pi - math.pi/2) > math.radians(BOW_PARALLEL):
            return None
        trim = min(full, HOOK_SHARE*width)
        tail = along_wall(rings, ahead[1], part, own, radius, overlap, at_least=trim+overlap)
        lead = along_wall(rings, behind[1], part, own, radius, overlap, at_least=trim+overlap)
        if tail is None or lead is None:
            return None
        body = fillet([behind[1], (mid.x, mid.y), ahead[1]], tail, trim, shares=(.5, .85))
        body = fillet(lead[::-1], body, trim, shares=(.85, .5))
        return (turn_away(lead[-2], lead[-1], allowed, turn)[::-1] + body
                + turn_away(tail[-2], tail[-1], allowed, turn))

    bow = build()
    if bow is None:
        return None
    # The crossing is straight; a front still curved from a spiral is not. Through the middle of such
    # a front the crossing would stand out beyond it beside the walls and cut far deeper there. Set it
    # back until it is nowhere further from cleared ground than the front: it then takes the two
    # flanks, passes through air in the middle, and the front is straight after a few passes.
    step = float(distance(part, points(path)).max())
    ox, oy = -hy, hx
    if part.distance(Point(mid.x + .2*ox, mid.y + .2*oy)) < part.distance(Point(mid.x - .2*ox, mid.y - .2*oy)):
        ox, oy = -ox, -oy
    for _ in range(BOW_SET_BACKS):
        # Judge the crossing only: the legs along the walls and the turns off them lie where they must.
        body = [q for q in segmentize(LineString(bow), .2).coords if allowed.boundary.distance(Point(q)) > 2*turn]
        excess = float(distance(part, points(body)).max()) - step if body else 0.
        if excess <= BOW_EXCESS:
            break
        mid = Point(mid.x - excess*ox, mid.y - excess*oy)
        ahead, behind = hit(1), hit(-1)
        moved = None if ahead is None or behind is None else build()
        if moved is None:
            break
        bow = moved
    return bow


def wall_ends(run, part, own, radius, allowed, rings, blend, *, overlap=.75, turn=.75, note=None, alternatives=None, bows=True):
    """Give an arc hooked ends that keep the wall clean at a steady cut.

    The arc curves round to meet the wall tangentially, heading back toward
    cleared ground, runs a little way along it and turns into the pocket; the
    start is the same shape in reverse. Successive hooks nest one stepover
    apart and each touches the wall, so no skin is left. The hook must be
    wide: a round cutter driven square into the corner between the front and
    the wall is wrapped by stock it left there on the previous pass. An end
    that is not on the wall rolls on from or off to the old front instead.
    """
    # A quadratic corner of trim d has a tightest radius of about 0.7 d.
    trim = HOOK_RADIUS_FACTOR*radius/.7
    at_start = along_wall(rings, run[0], part, own, radius, overlap) is not None
    at_end = along_wall(rings, run[-1], part, own, radius, overlap) is not None
    path = eased(run, False, part, allowed, blend, ends=(not at_start, not at_end))
    if len(path) < 2:
        return path
    hooked = [False, False]
    shapes = ['roll', 'roll']
    if bows and at_start and at_end:
        bow = bow_across(path, rings, part, own, radius, allowed, trim, overlap, turn)
        if bow is not None:
            if note is not None:
                note[:] = ['bow', 'bow']
            if alternatives is not None:
                # Separate hooks stay a fallback where the bow is too heavy, as at the mouth of an arm
                # where the front is still curved from the spiral.
                alternatives.append(wall_ends(run, part, own, radius, allowed, rings, blend,
                                              overlap=overlap, turn=turn, bows=False))
            return eased(bow, False, part, allowed, 1., ends=(True, True))
    for side, wanted in ((1, at_end), (0, at_start)):
        if not wanted:
            continue
        facing = path if side else path[::-1]
        new, shapes[side] = glance_onto_wall(facing, rings, part, own, radius, allowed, trim, overlap, turn), 'glance'
        if new is None:
            new, shapes[side] = hook_to_wall(facing, rings, part, own, radius, allowed, trim, overlap, turn), 'hook'
        if new is None:
            shapes[side] = 'roll'
        else:
            path, hooked[side] = (new if side else new[::-1]), True
    if note is not None:
        note[:] = shapes
    if at_start and not hooked[0] or at_end and not hooked[1]:
        # Too short for a hook: roll on from or off to the old front at that end instead.
        path = eased(path, False, part, allowed, blend, ends=(at_start and not hooked[0], at_end and not hooked[1]))
    # Snap the two tips into ground this island has already cleared.
    return eased(path, False, part, allowed, 1., ends=tuple(hooked))


def round_a_boss(centre, reach, rings, radius):
    """Where a spiral spans the channel between the outer wall and a boss: (half behind it, way ahead).

    The half is everything more than a cutter radius behind the line across
    the channel through the spiral's centre, so that the cutter centre may
    come up to that line. None when the spiral does not touch two walls.
    """
    at = Point(centre)
    near = sorted(rings, key=lambda ring: ring.distance(at))
    if len(near) < 2 or near[1].distance(at) > reach + SPAN_SLACK*radius:
        return None
    wall = nearest_points(near[0], at)[0]
    span = wall.distance(at)
    if span < 1e-9:
        return None
    dx, dy = (wall.x-at.x)/span, (wall.y-at.y)/span
    px, py, far = -dy, dx, 1e4
    line = [(at.x - radius*px - far*dx, at.y - radius*py - far*dy), (at.x - radius*px + far*dx, at.y - radius*py + far*dy)]
    behind = Polygon(line + [(line[1][0] - far*px, line[1][1] - far*py), (line[0][0] - far*px, line[0][1] - far*py)])
    return behind, (at.x + reach*px, at.y + reach*py)


def without_slivers(stock):
    """Drop films thinner than 2*SLIVER that polygon arithmetic leaves along walls and between cuts.

    A cutter disc is a 128-sided polygon here, so two cuts that meet exactly
    leave a film under a micron thick. Every film puts a scallop in the
    cleared region, whose outline then grows by thousands of points and slows
    every later step.
    """
    if stock.is_empty:
        return stock
    return stock.buffer(-SLIVER, join_style=2).buffer(SLIVER, join_style=2)


def convex_corners(ring):
    """[(vertex xy, [(position along ring, direction, wall length)] * 2)] where the wall turns sharply.

    A corner is a stretch of at most CORNER_WINDOW in which the wall turns
    by more than CORNER_TURN in all: a sharp vertex, or a short chamfer or
    small arc that a polygon outline makes of one. Each wall reaches to the
    next corner, so a creep never runs round onto another wall.
    """
    pts = list(ring.coords)[:-1]
    n = len(pts)
    if n < 3:
        return []
    total, at, turn = ring.length, [0.], []
    for i in range(1, n):
        at.append(at[-1] + math.dist(pts[i-1], pts[i]))
    for i in range(n):
        a, here, b = pts[i-1], pts[i], pts[(i+1) % n]
        h1, h2 = math.atan2(here[1]-a[1], here[0]-a[0]), math.atan2(b[1]-here[1], b[0]-here[0])
        turn.append(abs((h2-h1+math.pi) % (2*math.pi) - math.pi) if math.dist(a, here) > 1e-9 and math.dist(here, b) > 1e-9 else 0.)
    bent = [i for i in range(n) if turn[i] > math.radians(1.)]
    clusters, used = [], set()
    for i in sorted(bent, key=lambda k: -turn[k]):
        if i in used:
            continue
        group = [k for k in bent if k not in used and min(abs(at[k]-at[i]), total-abs(at[k]-at[i])) <= CORNER_WINDOW/2]
        if sum(turn[k] for k in group) > math.radians(CORNER_TURN):
            used.update(group)
            clusters.append(at[i])
    clusters.sort()
    found = []
    for j, place in enumerate(clusters):
        before = (place - clusters[j-1]) % total if len(clusters) > 1 else total/2
        after = (clusters[(j+1) % len(clusters)] - place) % total if len(clusters) > 1 else total/2
        corner = ring.interpolate(place)
        found.append(((corner.x, corner.y), [(place, -1, before), (place, 1, after)]))
    return found


def corner_pecks(vertex, along, stock, radius, ring):
    """Yield short cuts along a wall into a corner, each a little deeper; None when stuck.

    Each runs in along the wall from clean wall to a point nearer the corner
    and backs out along its own track. A step is
    judged by depth, not contact angle: at its deepest point the cutter may
    meet at most CORNER_DEPTH of stock. Deep in a corner the stock left is a
    crescent hugging the cutter, so the contact angle reads 90-180 degrees
    however thin the crescent is; its depth is what loads the cutter.
    The caller cuts each one before asking for the next.
    """
    state, total = {'stock': stock}, ring.length
    for place, sign, length in along:
        reach_in = min(CORNER_RUN_IN, .9*length)

        def at(d, place=place, sign=sign):
            q = ring.interpolate((place + sign*d) % total)
            return (q.x, q.y)

        def touches(d, live):
            return distance(live, Point(at(d))) < radius - WALL_TOLERANCE

        # Clean wall to start from: the nearest point back from the corner where the cutter is clear,
        # beyond any skin still on this wall.
        dirty = [d for d in np.arange(0., reach_in, .05) if touches(d, state['stock'])]
        if not dirty:
            continue
        start = next((d for d in np.arange(max(dirty), reach_in + 1e-9, .05) if not touches(d, state['stock'])), None)
        if start is None:
            continue
        reached = start
        while reached > 1e-6:
            done = False
            for step in CORNER_STEPS:
                target = max(0., reached - step)
                run = [at(d) for d in np.linspace(min(reach_in, reached + 1.), target, 16)]
                # Back out along the same track: the cleared space beside a corner creep is only as
                # wide as the track itself, too narrow for a link to find its way.
                path = run + run[-2::-1]
                if radius - float(distance(state['stock'], points(run)).min()) <= CORNER_DEPTH:
                    state['stock'] = (yield path) or sweep(path, state['stock'], radius)
                    reached, done = target, True
                    break
            if not done:
                yield None
                break


def channel_stretches(allowed, seeds, radius):
    """For starts along one channel round a boss: [(stretch, point ahead, own piece, rank)] per start, else None.

    rank is the start's place going forward round the channel.

    The centre region is cut across the channel at every start. A start's
    stretch runs forward from its cut to the next start's cut, plus the next
    start's spiral disc, so its front can run on into that spiral. Forward is
    the direction of the outer wall's outline.
    """
    parts = list(polygons(allowed))
    if len(parts) != 1 or len(parts[0].interiors) != 1 or len(seeds) < 2:
        return None
    outer, inner = LineString(parts[0].exterior.coords), LineString(parts[0].interiors[0].coords)

    def first_hit(at, dx, dy):
        hits = [g for g in get_parts(LineString([(at.x, at.y), (at.x + 1e3*dx, at.y + 1e3*dy)]).intersection(outer))
                if g.geom_type == 'Point']
        return min(hits, key=at.distance) if hits else None

    feet, places = [], []
    for centre, room in seeds:
        at = Point(centre)
        if outer.distance(at) > room + SPAN_SLACK*radius or inner.distance(at) > room + SPAN_SLACK*radius:
            return None  # This start's spiral does not span the channel.
        into = nearest_points(inner, at)[0]
        span = math.dist((at.x, at.y), (into.x, into.y))
        if span < 1e-9:
            return None
        out = first_hit(at, (at.x-into.x)/span, (at.y-into.y)/span)
        if out is None:
            return None
        feet.append(into)
        places.append(outer.project(out))
    ranked = sorted(range(len(seeds)), key=lambda k: places[k])
    cuts, forward = [None]*len(seeds), [None]*len(seeds)
    for rank, k in enumerate(ranked):
        (cx, cy), _ = seeds[k]
        (nx, ny), _ = seeds[ranked[(rank+1) % len(ranked)]]
        span = math.hypot(nx-cx, ny-cy)
        if span < 1e-9:
            return None
        fx, fy = (nx-cx)/span, (ny-cy)/span
        into = feet[k]
        # Cut across the channel: from the boss to the start, then on to the outer wall square to the
        # way forward. A corner outside the start then falls to the stretch that arrives there,
        # whose front runs straight on into it, instead of being split down its bisector.
        ox, oy = -fy, fx
        if ox*(cx-into.x) + oy*(cy-into.y) < 0:
            ox, oy = -ox, -oy
        out = first_hit(Point(cx, cy), ox, oy)
        if out is None:
            return None
        bx, by = cx-into.x, cy-into.y
        size = math.hypot(bx, by)
        cuts[k] = LineString([(into.x - bx/size, into.y - by/size), (cx, cy), (out.x + ox, out.y + oy)])
        forward[k] = (fx, fy)
    pieces = list(polygons(split(parts[0], unary_union(cuts))))
    if len(pieces) != len(seeds):
        return None
    stretches = [None]*len(seeds)
    for rank, k in enumerate(ranked):
        following = ranked[(rank+1) % len(ranked)]
        (cx, cy), room = seeds[k]
        tx, ty = forward[k]
        probe = Point(cx + .5*tx, cy + .5*ty)
        piece = next((g for g in pieces if g.buffer(1e-6).covers(probe)), None)
        if piece is None:
            return None
        (nx, ny), next_room = seeds[following]
        stretch = unary_union([piece, Point(nx, ny).buffer(next_room)]).intersection(allowed)
        stretches[k] = (stretch, (cx + room*tx, cy + room*ty), piece, rank)
    return stretches


def sweep(path, stock, radius):
    """Remove the cutter's swept area without measuring contact."""
    return without_slivers(stock.difference(LineString(path).buffer(radius, quad_segs=CUT_SEGMENTS)))


def cutting_pieces(path, stock, radius, *, run_out=1., closed=False):
    """Keep the stretches of a dense path that touch stock, with a short run in and out through air."""
    if stock.is_empty or len(path) < 2:
        return []
    touching = (distance(stock, points([tuple(q) for q in path])) < radius - 1e-6).tolist()
    if not any(touching):
        return []
    if closed and not all(touching):
        # Start in the middle of the longest stretch of air so no piece straddles the seam.
        n, best, i = len(path)-1, (0, 0), 0
        while i < n:
            if touching[i]:
                i += 1
                continue
            j = i
            while j-i < n and not touching[(j+1) % n]:
                j += 1
            best = max(best, (j-i+1, i))
            i = j+1
        first = (best[1] + best[0]//2) % n
        path, touching = path[first:] + path[1:first+1], touching[first:] + touching[1:first+1]
    along = [0.]
    for a, b in zip(path, path[1:]):
        along.append(along[-1] + math.dist(a, b))
    spans, i = [], 0
    while i < len(path):
        if touching[i]:
            j = i
            while j+1 < len(path) and touching[j+1]:
                j += 1
            lo, hi = along[i]-run_out, along[j]+run_out
            if spans and lo <= spans[-1][1]:
                spans[-1][1] = hi
            else:
                spans.append([lo, hi])
            i = j
        i += 1
    pieces = []
    for lo, hi in spans:
        piece = [q for q, d in zip(path, along) if lo <= d <= hi]
        if len(piece) > 1 and LineString(piece).length >= .3:
            pieces.append(piece)
    return pieces


def chunk_contact(chunk, stock, radius, step):
    """Contact angle in degrees at each sample along a short stretch of path: (angles, distances).

    stock is the material before this stretch. The cutter has swept
    everything behind it, so only the half of its edge facing forward can
    touch material; that half is measured against stock, and the path's own
    sweep never has to be subtracted sample by sample. The window reaches a
    little past the half, by the angle the previous sample's disc leaves
    uncovered, which is what a replay that subtracts each step would see. This
    holds where the path turns no tighter than the cutter radius; a tighter
    turn reads high, never low. hsm_contact_replay.indexed_contact is the
    reference this is checked against.
    """
    poses, headings, lengths = [], [], []
    for start, end in zip(chunk, chunk[1:]):
        span = math.dist(start, end)
        if not span:
            continue
        count = math.ceil(span/step)
        heading = math.atan2(end[1]-start[1], end[0]-start[0])
        for k in range(1, count+1):
            t = k/count
            poses.append((start[0] + (end[0]-start[0])*t, start[1] + (end[1]-start[1])*t))
            headings.append(heading)
            lengths.append(span/count)
    angles = np.zeros(len(poses))
    if stock.is_empty or not poses:
        return angles.tolist(), lengths
    a, b = [], []
    for part in polygons(stock):
        for ring in (part.exterior, *part.interiors):
            coords = np.asarray(ring.coords)[:, :2]
            a.append(coords[:-1])
            b.append(coords[1:])
    if not a:
        return angles.tolist(), lengths
    a, b = np.concatenate(a), np.concatenate(b)
    delta = (b - a)/radius
    norm2 = (delta*delta).sum(axis=1)
    a, delta, norm2 = a[norm2 > 0], delta[norm2 > 0], norm2[norm2 > 0]
    centres, heading = np.asarray(poses), np.asarray(headings)
    half = math.pi/2 + np.arcsin(np.minimum(1., np.asarray(lengths)/(2*radius)))
    # Every sample against every edge at once: where the cutter circle crosses the stock outline.
    p = (a[None, :, :] - centres[:, None, :])/radius
    t = -(p*delta[None, :, :]).sum(axis=2)/norm2[None, :]
    closest = p + t[:, :, None]*delta[None, :, :]
    h2 = 1. - (closest*closest).sum(axis=2)
    reach = np.sqrt(np.maximum(0., h2)/norm2[None, :])
    sample, angle = [np.arange(len(poses)), np.arange(len(poses))], [-half, half]
    for sense in (-1, 1):
        at = t + sense*reach
        on = (h2 >= -1e-12) & (at >= -1e-12) & (at <= 1.+1e-12)
        rows, cols = np.nonzero(on)
        q = p[rows, cols] + np.clip(at[rows, cols], 0., 1.)[:, None]*delta[cols]
        phi = (np.arctan2(q[:, 1], q[:, 0]) - heading[rows] + math.pi) % math.tau - math.pi
        inside = np.abs(phi) < half[rows]
        sample.append(rows[inside])
        angle.append(phi[inside])
    sample, angle = np.concatenate(sample), np.concatenate(angle)
    order = np.lexsort((angle, sample))
    sample, angle = sample[order], angle[order]
    # Between neighbouring crossings the edge is either all in stock or all out: test the middle.
    pair = (sample[1:] == sample[:-1]) & (angle[1:] - angle[:-1] > 1e-12)
    owner, lo, hi = sample[:-1][pair], angle[:-1][pair], angle[1:][pair]
    middle = heading[owner] + (lo+hi)/2
    inside = contains_xy(stock, centres[owner, 0] + radius*np.cos(middle), centres[owner, 1] + radius*np.sin(middle))
    np.add.at(angles, owner[inside], np.degrees((hi-lo)[inside]))
    return angles.tolist(), lengths


def cut(path, stock, radius, sample_step, *, where=None, tally=None, stop_above=None):
    """Sampled peak contact and updated stock; chunked so each replay stays local.

    where, if given, receives the distance along the path of the peak sample.
    tally, if given, is [angle x distance, distance, distance in contact] and is added to.
    stop_above, if given, ends the replay at the first sample over it: the cut is refused
    anyway, and the returned stock is then not the stock after the cut.
    """
    peak, chunk, length, travelled = 0., [path[0]], 0., 0.
    for i in range(1, len(path)):
        chunk.append(path[i])
        length += math.dist(path[i-1], path[i])
        if length >= 6. or i == len(path)-1:
            xs, ys = zip(*chunk)
            reach = radius + .01
            local = stock.intersection(box(min(xs)-reach, min(ys)-reach, max(xs)+reach, max(ys)+reach))
            for angle, step in zip(*chunk_contact(chunk, local, radius, sample_step)):
                travelled += step
                if tally is not None:
                    tally[0] += angle*step
                    tally[1] += step
                    tally[2] += step if angle > 0 else 0.
                if angle > peak:
                    peak = angle
                    if where is not None:
                        where[:] = [travelled]
                    if stop_above is not None and peak > stop_above:
                        return peak, stock
            stock = stock.difference(LineString(chunk).buffer(radius, quad_segs=CUT_SEGMENTS))
            chunk, length = [path[i]], 0.
    return peak, stock


def clear_pocket(pocket, radius, *, limit=60., sample_step=.1, stepovers=STEPOVERS, blend=3.,
                 islands=None, placement='lobes', wall_pull_back=True, wall_profile=True, trace=None, top=0., depth=-2., lead_angle=2.5, time_budget=None):
    """Return (strokes, residual, report) for one target plane, starting from intact stock."""
    allowed = unary_union(center_regions(pocket, radius))
    wall = allowed.boundary
    rings = [LineString(r.coords) for g in polygons(allowed) for r in (g.exterior, *g.interiors)]
    reachable = allowed.buffer(radius, quad_segs=SWEEP_SEGMENTS)
    stock = pocket
    strokes, island_reports = [], []
    travel = {'rapids': 0, 'links': 0}
    contact = [0., 0., 0.]  # committed cuts only: angle x distance, distance, distance in contact

    def count(tally):
        for k in range(3):
            contact[k] += tally[k]

    refused = {}
    cleared = [None]  # clearance for the live stock; None until asked for after a wholesale change

    def stock_clear():
        if cleared[0] is None:
            cleared[0] = clearance(allowed, stock, radius)
        return cleared[0]

    def commit(kind, path, stepover, peak):
        """Join the cut to the previous one through cleared space, else count a retract and rapid."""
        if strokes:
            route = stay_down_link(stock_clear(), stock, radius, strokes[-1].points[-1], path[0],
                                  why=refused)
            if route is None:
                travel['rapids'] += 1
            else:
                travel['links'] += 1
                strokes.append(Stroke('link', route, 0., 0.))
        else:
            travel['rapids'] += 1
        strokes.append(Stroke(kind, path, stepover, peak))

    started = time.time()

    def out_of_time():
        return time_budget is not None and time.time()-started > time_budget

    seeds = choose_seeds(allowed, islands, min_radius=radius, placement=placement)

    def owner(xy):
        """Island whose spiral disc is nearest; decides who finishes shared ground."""
        return min(range(len(seeds)), key=lambda k: math.dist(xy, seeds[k][0]) - seeds[k][1])

    def wave(index, centre, own, shared, focus=None, region=None):
        """Grow one island as if it were alone, cutting only where real stock remains.

        own is the stock this island would see by itself; it keeps the fronts
        concentric when they reach space another island has opened. A shared
        island leaves arcs that mostly belong to a neighbour for that neighbour.
        region, if given, is the stretch of the centre region this island works; its edges that are
        not pocket wall are not fronts.
        """
        nonlocal stock
        here = allowed if region is None else region
        edge = wall if region is None else region.boundary
        start, passes, arcs, blocked = 0, 0, 0, False
        own_clear = clearance(here, own, radius)
        steady, since, patience = 0, 0, RAISE_PATIENCE  # stepover level in use; passes at it; passes to wait
        # focus is the middle of the front last cut. Where it is given, that front is followed until it
        # is finished; elsewhere the front nearest the cutter goes next, which keeps links short and
        # measured better on the L-shape, cross and square with a boss.
        follow = focus is not None
        while not out_of_time():
            parts = [g for g in polygons(own_clear) if g.area > 1e-6]
            if not parts:
                break
            part = min(parts, key=lambda g: g.distance(Point(centre)))
            progressed, used, zone, blocked = False, None, None, False
            for level in range(start, len(stepovers)):
                stepover = stepovers[level]
                grown = part.buffer(stepover, quad_segs=SWEEP_SEGMENTS).intersection(here)
                runs = fronts(part, grown, edge, zone=zone)
                failed, halt = [], False
                while runs and not halt:
                    # Stay with one front. Round a boss two fronts set off opposite ways; taking whichever
                    # is nearer advances both, and they meet head-on on the far side in a narrowing pinch.
                    # One front followed all the way round breaks through into the space the spiral opened.
                    if focus is None:
                        at = strokes[-1].points[-1] if strokes else centre
                        pick = min(range(len(runs)), key=lambda k: math.dist(at, runs[k][0][0]))
                    else:
                        pick = min(range(len(runs)), key=lambda k: LineString(runs[k][0]).distance(Point(focus)))
                    run, closed = runs.pop(pick)
                    # Sweep the wall at the arc ends; only at ROLL_STEPOVER or below fall back to
                    # rolling off before the wall, so a lighter cut gets to try the wall first.
                    if wall_pull_back and not closed:
                        ends, others = [], []
                        shapes = [wall_ends(run, part, own, radius, allowed, rings, blend, note=ends, alternatives=others),
                                  *others]
                        if stepover <= ROLL_STEPOVER or level == len(stepovers)-1:
                            shapes.append(eased(run, closed, part, allowed, blend))
                    else:
                        shapes = [eased(run, closed, part, allowed, blend)]
                    done, skip = None, False
                    for path in shapes:
                        if len(path) < 2:
                            continue
                        pieces = cutting_pieces(path, stock, radius)
                        if shared and pieces:
                            points = [q for piece in pieces for q in piece]
                            if sum(owner(q) == index for q in points) < len(points)/2:
                                skip = True  # A neighbour finishes this stretch; do not advance through it.
                                break
                        trial, done = stock, []
                        for piece in pieces:
                            at, tally = [], [0., 0., 0.]
                            peak, after = cut(piece, trial, radius, sample_step, where=at, tally=tally, stop_above=limit)
                            if peak > limit:
                                done = None
                                if trace is not None:
                                    trace.append({'island': index, 'stepover_mm': stepover, 'retry': zone is not None,
                                                  'wall_ended': path is shapes[0] and len(shapes[0]) > 0
                                                  and wall_pull_back and not closed,
                                                  'ends': list(ends) if path is shapes[0] and wall_pull_back and not closed else None,
                                                  'run_start_xy': run[0], 'run_end_xy': run[-1], 'peak_deg': peak,
                                                  'peak_at_mm': at[0] if at else None,
                                                  'piece_mm': LineString(piece).length,
                                                  'piece_end_xy': piece[-1], 'outcome': 'over_limit'})
                                break
                            if trial.area - after.area >= MIN_GAIN_MM2:
                                done.append((piece, peak, tally))
                            trial = after
                        if done is not None:
                            break
                    if skip:
                        continue
                    if done is None:
                        failed.append(LineString(run))
                        # Retry this front lighter before turning to another; only when it cannot be
                        # cut at all do the others get their turn. Trying the others at the same heavier
                        # stepover first refuses them too, and the lighter retry then cuts one front in
                        # each arm in turn, crossing the pocket between arms on every pass.
                        halt = zone is None and level < len(stepovers)-1
                        continue
                    if trace is not None:
                        trace.append({'island': index, 'stepover_mm': stepover, 'retry': zone is not None,
                                      'wall_ended': path is shapes[0] and wall_pull_back and not closed,
                                      'run_start_xy': run[0], 'run_end_xy': run[-1], 'pieces': len(done), 'path_mm': LineString(path).length,
                                      'path_end_xy': path[-1], 'outcome': 'cut' if done else 'air'})
                    for piece, peak, tally in done:
                        commit('front', piece, stepover, peak)
                        count(tally)
                    if done:
                        trial = without_slivers(trial)
                        cleared[0] = grow_clearance(stock_clear(), allowed, trial, path, radius)
                    stock = trial
                    before = own.area
                    own = sweep(path, own, radius)
                    own_clear = grow_clearance(own_clear, here, own, path, radius)
                    # A pass through air counts only if it moved the front on; otherwise it would repeat for ever.
                    moved = bool(done) or before - own.area > MIN_GAIN_MM2
                    progressed = progressed or moved
                    followed = focus is not None and moved
                    if follow and (done or followed):
                        middle = LineString(run).interpolate(.5, normalized=True)
                        focus = (middle.x, middle.y)
                    if done:
                        arcs += len(done)
                        used = level if used is None else used
                    # Stay with this stretch of front, also while it passes through space already
                    # open; the others wait their turn.
                    halt = zone is None and (bool(done) or followed)
                blocked = bool(failed)
                if not failed or out_of_time():
                    break
                zone = unary_union(failed).buffer(max(1., 2*stepover))
                parts = [g for g in polygons(own_clear) if g.area > 1e-6]
                part = min(parts, key=lambda g: g.distance(Point(centre)))
            if not progressed:
                if focus is None:
                    break
                focus = None  # The front being followed cannot be cut at all: give every front a turn.
                continue
            passes += used is not None
            # Try a larger stepover again only now and then. A front that takes 0.5 mm but not 0.65 mm
            # would otherwise have every pass replayed twice, once to be refused.
            if used is not None:
                if used < steady:
                    steady, since, patience = used, RAISE_PATIENCE, RAISE_PATIENCE  # It took more: try more again at once.
                elif used > steady:
                    steady, since, patience = used, RAISE_PATIENCE, RAISE_PATIENCE  # Dropped: climb back without waiting.
                elif start < steady and stepovers[steady] < STEADY_STEPOVER:
                    since = patience  # A thin peel: keep trying for a thicker one every pass.
                elif start < steady:
                    since, patience = 0, min(2*patience, RAISE_PATIENCE_MAX)  # The larger one was refused: wait longer.
                else:
                    since += 1
            start = max(0, steady-1) if since >= patience else steady
        return passes, arcs, blocked

    front_passes, any_blocked = 0, False

    def open_island(centre, room):
        """Helix and spiral for one start: (centre, spiral reach, island report, own stock, spiral kept)."""
        nonlocal stock
        region = Point(centre).buffer(room)
        entry = seed_entry(region, stock, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
        alone = seed_entry(region, pocket, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
        if entry is None or alone is None:
            return None
        centre = tuple(entry.points[-1, :2])
        stock, own = entry.remaining, alone.remaining
        cleared[0] = None
        reach = Point(centre).distance(wall) - 1e-3
        island = {'centre_xy_mm': centre, 'radius_mm': reach}
        chosen, kept = None, False
        for stepover in stepovers:
            probe = spiral_out(centre, min(reach, 1.8*radius + 3.), stepover, blend=blend)
            if cut(probe, stock, radius, sample_step, stop_above=limit)[0] <= limit:
                chosen = stepover
                break
        if chosen is not None:
            path = spiral_out(centre, reach, chosen, blend=blend)
            tally = [0., 0., 0.]
            peak, trial = cut(path, stock, radius, sample_step, tally=tally)
            island.update(stepover_mm=chosen, peak_deg=peak, feed_mm=LineString(path).length,
                          accepted=peak <= limit)
            if peak <= limit:
                commit('spiral', path, chosen, peak)
                count(tally)
                stock, own = trial, sweep(path, own, radius)
                cleared[0] = None
                kept = True
        return centre, reach, island, own, kept

    stretches = channel_stretches(allowed, seeds, radius) if len(seeds) > 1 else None
    if stretches is not None:
        # Several starts in one channel round a boss: open every start first, then send one front
        # forward from each, across its own stretch of channel and into the next start's spiral.
        # Fronts never meet head-on between starts.
        # Open them in order round the channel; the last one opened works first. Each front ends in the
        # next start's spiral, where the next front begins, so the fronts follow on without a lift.
        order = sorted(range(len(seeds)), key=lambda k: stretches[k][3])
        opened = {k: open_island(*seeds[k]) for k in order}
        for index in order[-1:] + order[:-1]:
            found = opened[index]
            if found is None:
                continue
            centre, reach, island, own, kept = found
            region, ahead, piece, _ = stretches[index]
            # As in a ring with one start: the front runs straight on through the next start's spiral
            # up to its cut, instead of closing on it from both walls in a pinch of small arcs.
            through = pocket.difference(stock).intersection(piece.buffer(radius, quad_segs=SWEEP_SEGMENTS))
            passes, arcs, blocked = wave(index, centre, stock.union(through.difference(
                Point(centre).buffer(reach + radius))), shared=False, focus=ahead, region=region)
            island.update(front_passes=passes, front_arcs=arcs, one_way=True)
            front_passes += passes
            any_blocked = any_blocked or blocked
            island_reports.append(island)
    for index, (centre, room) in enumerate(seeds if stretches is None else ()):
        found = open_island(centre, room)
        if found is None:
            continue
        centre, reach, island, own, kept = found
        focus = None
        if len(seeds) == 1 and kept:
            one_way = round_a_boss(centre, reach, rings, radius)
            if one_way is not None:
                # The spiral fills a channel that runs round a boss. Its two sides would each send a
                # front round, to meet head-on on the far side. Treat the half behind as still uncut:
                # one front then goes all the way round and passes straight through the spiral.
                behind, focus = one_way
                own = own.union(pocket.difference(stock).intersection(behind))
        # Every island but the last leaves shared ground to its neighbour; the last one cleans up.
        passes, arcs, blocked = wave(index, centre, own, shared=index < len(seeds)-1, focus=focus)
        island.update(front_passes=passes, front_arcs=arcs)
        front_passes += passes
        any_blocked = any_blocked or blocked
        island_reports.append(island)

    # Corners: the fronts swallow a corner once it is within a stepover, so the cutter centre never
    # reaches it. Creep into each corner along one wall in steps no deeper than CORNER_DEPTH.
    corners = {'visits': 0, 'refused': 0, 'no_link': 0, 'feed_mm': 0., 'peak_deg': 0.}
    for ring in rings:
        for vertex, along in convex_corners(ring):
            if distance(stock, Point(vertex)) >= radius - WALL_TOLERANCE:
                continue
            for path in corner_pecks(vertex, along, stock, radius, ring):
                if path is None:
                    corners['refused'] += 1
                    continue
                if strokes and stay_down_link(stock_clear(), stock, radius, strokes[-1].points[-1], path[0]) is None:
                    corners['no_link'] += 1  # Not worth a lift for a corner.
                    break
                peak, trial = cut(path, stock, radius, sample_step)
                commit('corner', path, 0., peak)
                corners['peak_deg'] = max(corners['peak_deg'], peak)
                stock, cleared[0] = without_slivers(trial), None
                corners['visits'] += 1
                corners['feed_mm'] += LineString(path).length

    # Finish: follow the pocket wall only where stock is still on it, such as the skin the last front
    # of a channel leaves because no later front sweeps back over it. Clean wall is not passed again.
    profile = {'pieces': 0, 'over_limit': 0, 'refused_mm': 0., 'feed_mm': 0.,
               'reachable_stock_before_mm2': stock.intersection(reachable).area}
    for inset in ((.3, 0.) if wall_profile else ()):
        # Only stock thicker than the wall tolerance sends the cutter back to a wall.
        thick = stock.buffer(-WALL_TOLERANCE/2, join_style=2).buffer(WALL_TOLERANCE/2, join_style=2)
        for part in polygons(allowed.buffer(-inset) if inset else allowed):
            if part.area < 1e-6:
                continue
            part = orient(part, sign=-1.)
            for ring in (part.exterior, *part.interiors):
                dense = list(segmentize(LineString(ring.coords), .1).coords)
                for whole in cutting_pieces(dense, thick, radius, run_out=1.5, closed=True):
                    # Judge the wall in short stretches so one tight spot does not refuse the rest.
                    chunks, chunk, length = [], [whole[0]], 0.
                    for q in whole[1:]:
                        length += math.dist(chunk[-1], q)
                        chunk.append(q)
                        if length >= PROFILE_CHUNK:
                            chunks.append(chunk)
                            chunk, length = [q], 0.
                    if len(chunk) > 1:
                        chunks.append(chunk)
                    restart = False
                    for piece in chunks:
                        if restart:
                            # The stretch before was refused, so roll on from cleared space again.
                            piece = eased(piece, False, stock_clear(), allowed, 1.5,
                                          ends=(True, False))
                            if len(piece) < 2:
                                continue
                        tally = [0., 0., 0.]
                        peak, trial = cut(piece, stock, radius, sample_step, tally=tally)
                        if stock.area - trial.area < MIN_GAIN_MM2:
                            continue
                        if peak > limit:
                            profile['over_limit'] += 1
                            profile['refused_mm'] += LineString(piece).length
                            restart = True
                            continue
                        restart = False
                        last = strokes[-1] if strokes else None
                        if last is not None and last.kind == 'profile' and last.points[-1] == piece[0]                                 and last.stepover_mm == inset:
                            strokes[-1] = Stroke('profile', last.points + piece[1:], inset, max(last.peak_deg, peak))
                        else:
                            commit('profile', piece, inset, peak)
                            profile['pieces'] += 1
                        stock = trial
                        cleared[0] = None
                        count(tally)
                        profile['feed_mm'] += LineString(piece).length

    stop = 'time_budget' if out_of_time() else 'blocked' if any_blocked or profile['over_limit'] else 'front_exhausted'
    passes = front_passes
    residual = stock.intersection(reachable)
    total = pocket.intersection(reachable).area
    cuts = [s for s in strokes if s.kind == 'front']
    feeds = [s for s in strokes if s.kind not in ('link', 'corner')]  # Corners are judged by depth.
    report = {'stop': stop, 'placement': placement, 'wall_pull_back': wall_pull_back,
              'lobes': [{'widest_xy_mm': xy, 'room_mm': room, 'bounds_mm': bounds}
                        for xy, room, bounds in find_lobes(allowed, min_radius=radius)],
              'islands': island_reports, 'front_passes': passes, 'front_arcs': len(cuts),
              'wall_profile': profile if wall_profile else None, 'corners': corners,
              'reachable_stock_before_profile_mm2': profile['reachable_stock_before_mm2'],
              'reachable_mm2': total, 'reachable_residual_mm2': residual.area,
              'cleared_fraction': 1 - residual.area/total if total else None,
              'peak_contact_deg': max((s.peak_deg for s in feeds), default=None),
              'mean_contact_deg': contact[0]/contact[1] if contact[1] else None,
              'mean_contact_while_cutting_deg': contact[0]/contact[2] if contact[2] else None,
              'share_of_cut_feed_in_contact': contact[2]/contact[1] if contact[1] else None,
              'cut_feed_mm': sum(LineString(s.points).length for s in feeds),
              'link_feed_mm': sum(LineString(s.points).length for s in strokes if s.kind == 'link'),
              'spiral_feed_mm': sum(LineString(s.points).length for s in strokes if s.kind == 'spiral'),
              'stay_down_links': travel['links'], 'retract_rapids': travel['rapids'],
              'retract_reasons': dict(refused, first_cut=1),
              'arcs_at_0.2_mm_or_less': sum(s.stepover_mm <= .2 for s in cuts),
              'front_stepover_histogram': {str(v): sum(s.stepover_mm == v for s in cuts) for v in stepovers},
              'seconds': time.time()-started}
    return strokes, residual, report


def write_review(path, pocket, strokes, residual, report):
    """Save XY geometry for a viewer. G0 marks a retract and rapid; helix entries are not included."""
    path = Path(path)
    overlay = path.with_suffix('.svg')
    cuts = sum(stroke.kind != 'link' for stroke in strokes)
    with path.open('x', encoding='ascii', newline='\n') as out:
        out.write('(DEBUG ONLY - XY GEOMETRY REVIEW - DO NOT RUN ON A MACHINE)\n'
                  f'(Wavefront trial: {report["stop"]}, {cuts} cuts, {report["retract_rapids"]} retracts; '
                  'helix entries omitted)\n'
                  '(Each G0 stands for a retract, rapid and re-entry that are not planned here)\n'
                  '(No Z, entry, spindle, tool or feed schedule; rounded XY not replayed)\nG21\nG90\n')
        number, joined = 0, False
        for stroke in strokes:
            points = list(LineString(stroke.points).simplify(.002).coords)
            if stroke.kind == 'link':
                out.write('(Stay-down link through cleared area)\n')
                joined = True
            else:
                number += 1
                out.write(f'(Cut {number}: {stroke.kind}, stepover {stroke.stepover_mm:g} mm, '
                          f'sampled peak {stroke.peak_deg:.1f} deg)\n')
                if not joined:
                    out.write(f'G0 X{points[0][0]:.4f} Y{points[0][1]:.4f}\n')
                joined = False
            for x, y in points[1:]:
                out.write(f'G1 X{x:.4f} Y{y:.4f}\n')
        out.write('M2\n')
    with overlay.open('x', encoding='ascii', newline='\n') as out:
        write_overlay(out, pocket, residual,
                      [(n, list(LineString(s.points).simplify(.01).coords), s.kind == 'link')
                       for n, s in enumerate(strokes, 1)],
                      legend='Wavefront trial | blue: cuts | gray: stay-down links in cleared area | '
                             'orange: reachable stock left | retracts not drawn')


if __name__ == '__main__':
    from tools.check_hsm_neck import neck_fixture

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pocket-wkt', type=Path, help='pocket outline as a WKT polygon; default is the two-lobe fixture')
    parser.add_argument('--review-gcode', type=Path, help='save cuts to a new debug-only .nc file and .svg overlay')
    parser.add_argument('--islands', type=int, help='number of helical islands; default is chosen from the shape')
    parser.add_argument('--placement', choices=('lobes', 'thirds', 'widest'), default='lobes',
                        help='one island per lobe, spread along the long axis, or the widest remaining spots')
    parser.add_argument('--no-wall-pull-back', action='store_true',
                        help='roll arcs off before the wall instead of following it back')
    parser.add_argument('--no-wall-finish', action='store_true', help='skip the finish along wall that still has stock on it')
    parser.add_argument('--time-budget', type=float, help='stop adding passes after this many seconds')
    parser.add_argument('--sample-step', type=float, default=.1, help='contact sampling distance in mm')
    args = parser.parse_args()
    if args.pocket_wkt is not None:
        from shapely import from_wkt
        fixture = from_wkt(args.pocket_wkt.read_text(encoding='utf-8'))
    else:
        fixture, _ = neck_fixture()
    result = clear_pocket(fixture, 2., islands=args.islands, placement=args.placement,
                          wall_pull_back=not args.no_wall_pull_back, wall_profile=not args.no_wall_finish, time_budget=args.time_budget,
                          sample_step=args.sample_step)
    if args.review_gcode is not None:
        write_review(args.review_gcode, fixture, *result)
    print(json.dumps(result[2], indent=2))
