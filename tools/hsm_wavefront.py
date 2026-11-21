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

from shapely import distance, get_parts, points, prepare, segmentize
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, polylabel, substring, unary_union

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gcodeproducer.core.cam.adaptive_entry import seed_entry
from gcodeproducer.core.geometry.polygon_parts import polygons
from tools.hsm_center_regions import CENTER_BUFFER_SEGMENTS, center_regions
from tools.hsm_contact_replay import indexed_contact
from tools.hsm_replay_overlay import write_overlay

STEPOVERS = (1., .8, .65, .5, .4, .3, .2, .12)
SWEEP_SEGMENTS = 16
CUT_SEGMENTS = 32  # keeps a cut's end cap within the link tolerance of a true disc
WALL_TOLERANCE = .02
MIN_GAIN_MM2 = 1e-4
ELONGATED_ASPECT = 2.
PROFILE_CHUNK = 8.  # mm of wall judged at a time
NEAR_WALL = .3  # mm; an arc end this close to the wall is carried onto it
WALL_REACH = 20.  # mm; farthest an arc end follows the wall back looking for clean wall
LINK_TOLERANCE = 1e-3  # mm; buffered arcs make the cleared region slightly approximate


class Stroke(NamedTuple):
    kind: str  # 'spiral', 'front' or wall 'profile' cut, or a stay-down 'link' through cleared area
    points: list
    stepover_mm: float
    peak_deg: float


def find_lobes(allowed, *, min_radius, step=.25, neck_ratio=2.):
    """Split a cutter-centre region at its necks: [(widest xy, distance to wall, bounds)].

    The region is shrunk in steps. A piece counts as a lobe while its widest
    spot is at least neck_ratio times the shrink that separated it, so a
    passage must be clearly narrower than the areas it joins.
    """
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
        if not allowed.covers(Point(q)):
            n = nearest_points(allowed, Point(q))[0]
            q = (n.x, n.y)
        if not out or q != out[-1]:
            out.append(q)
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


def along_wall(rings, xy, part, own, radius, overlap, *, limit=WALL_REACH):
    """Dense points from a wall point back along the wall until it is already clean, plus an overlap.

    The wall counts as clean where the cutter, sitting on it, would find no
    more than a WALL_TOLERANCE skin of this island's stock.
    Returns None for a point that is not on the wall.
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
        pts = [ring.interpolate((here + sign*limit*k/steps) % total) for k in range(1, steps+1)]
        return [(q.x, q.y) for q in pts]

    ways = (walk(1), walk(-1))
    way = min(ways, key=lambda pts: part.distance(Point(pts[min(4, len(pts)-1)])))
    clean = [True]*len(way) if own.is_empty else (distance(own, points(way)) >= radius - WALL_TOLERANCE).tolist()
    keep = len(way)
    if any(clean):
        keep = min(len(way), clean.index(True) + 1 + math.ceil(overlap/(limit/steps)))
    onto = [] if math.dist(xy, (foot.x, foot.y)) < 1e-9 else [(foot.x, foot.y)]
    return [tuple(xy)] + onto + way[:keep]


def fillet(first, second, trim):
    """Join two legs that meet at first[-1] == second[0] with a curve tangent to both."""
    a, b = LineString(first), LineString(second)
    trim = min(trim, a.length/3, b.length/2)
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


def wall_ends(run, part, own, radius, allowed, rings, blend, *, overlap=.75, corner=.5, turn=.75):
    """Carry an arc to the wall, follow the wall back toward cleared ground, then turn into the pocket.

    The same shape in reverse starts the arc. An end that is not on the wall
    rolls on from or off to the old front instead.
    """
    # Reach back to wall the earlier peels already cleaned, so every stretch is passed along at least once.
    lead = along_wall(rings, run[0], part, own, radius, overlap)
    tail = along_wall(rings, run[-1], part, own, radius, overlap)
    path = eased(run, False, part, allowed, blend, ends=(lead is None, tail is None))
    if len(path) < 2:
        return path
    if tail is not None:
        path = fillet(path, tail, corner)
        path += turn_away(tail[-2], tail[-1], allowed, turn)
    if lead is not None:
        path = fillet(lead[::-1], path, corner)
        path = turn_away(lead[-2], lead[-1], allowed, turn)[::-1] + path
    # Snap the two tips into ground this island has already cleared.
    return eased(path, False, part, allowed, 1., ends=(lead is not None, tail is not None))


def sweep(path, stock, radius):
    """Remove the cutter's swept area without measuring contact."""
    return stock.difference(LineString(path).buffer(radius, quad_segs=CUT_SEGMENTS))


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


def cut(path, stock, radius, sample_step, *, where=None):
    """Sampled peak contact and updated stock; chunked so each replay stays local.

    where, if given, receives the distance along the path of the peak sample.
    """
    peak, chunk, length, travelled = 0., [path[0]], 0., 0.
    for i in range(1, len(path)):
        chunk.append(path[i])
        length += math.dist(path[i-1], path[i])
        if length >= 6. or i == len(path)-1:
            xs, ys = zip(*chunk)
            reach = radius + .01
            local = stock.intersection(box(min(xs)-reach, min(ys)-reach, max(xs)+reach, max(ys)+reach))
            for _, angle, step in indexed_contact(chunk, local, radius, sample_step, SWEEP_SEGMENTS):
                travelled += step
                if angle > peak:
                    peak = angle
                    if where is not None:
                        where[:] = [travelled]
            stock = stock.difference(LineString(chunk).buffer(radius, quad_segs=CUT_SEGMENTS))
            chunk, length = [path[i]], 0.
    return peak, stock


def clear_pocket(pocket, radius, *, limit=60., sample_step=.1, stepovers=STEPOVERS, blend=3.,
                 islands=None, placement='lobes', wall_pull_back=True, wall_profile=False, trace=None, top=0., depth=-2., lead_angle=2.5, time_budget=None):
    """Return (strokes, residual, report) for one target plane, starting from intact stock."""
    allowed = unary_union(center_regions(pocket, radius))
    wall = allowed.boundary
    rings = [LineString(r.coords) for g in polygons(allowed) for r in (g.exterior, *g.interiors)]
    reachable = allowed.buffer(radius, quad_segs=SWEEP_SEGMENTS)
    stock = pocket
    strokes, island_reports = [], []
    travel = {'rapids': 0, 'links': 0}
    refused = {}

    def commit(kind, path, stepover, peak):
        """Join the cut to the previous one through cleared space, else count a retract and rapid."""
        if strokes:
            route = stay_down_link(clearance(allowed, stock, radius), stock, radius, strokes[-1].points[-1], path[0],
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

    def wave(index, centre, own, shared):
        """Grow one island as if it were alone, cutting only where real stock remains.

        own is the stock this island would see by itself; it keeps the fronts
        concentric when they reach space another island has opened. A shared
        island leaves arcs that mostly belong to a neighbour for that neighbour.
        """
        nonlocal stock
        start, passes, arcs, blocked = 0, 0, 0, False
        while not out_of_time():
            parts = [g for g in polygons(clearance(allowed, own, radius)) if g.area > 1e-6]
            if not parts:
                break
            part = min(parts, key=lambda g: g.distance(Point(centre)))
            progressed, used, zone, blocked = False, None, None, False
            for level in range(start, len(stepovers)):
                stepover = stepovers[level]
                grown = part.buffer(stepover, quad_segs=SWEEP_SEGMENTS).intersection(allowed)
                runs = fronts(part, grown, wall, zone=zone)
                failed, halt = [], False
                while runs and not halt:
                    at = strokes[-1].points[-1] if strokes else centre
                    run, closed = runs.pop(min(range(len(runs)), key=lambda k: math.dist(at, runs[k][0][0])))
                    # Sweep the wall at the arc ends; only at the smallest stepover fall back to
                    # rolling off before the wall, so a lighter cut gets to try the wall first.
                    if wall_pull_back and not closed:
                        shapes = [wall_ends(run, part, own, radius, allowed, rings, blend)]
                        if level == len(stepovers)-1:
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
                            at = []
                            peak, after = cut(piece, trial, radius, sample_step, where=at)
                            if peak > limit:
                                done = None
                                if trace is not None:
                                    trace.append({'island': index, 'stepover_mm': stepover, 'retry': zone is not None,
                                                  'wall_ended': path is shapes[0] and len(shapes[0]) > 0
                                                  and wall_pull_back and not closed,
                                                  'run_start_xy': run[0], 'run_end_xy': run[-1], 'peak_deg': peak,
                                                  'peak_at_mm': at[0] if at else None,
                                                  'piece_mm': LineString(piece).length,
                                                  'piece_end_xy': piece[-1], 'outcome': 'over_limit'})
                                break
                            if trial.area - after.area >= MIN_GAIN_MM2:
                                done.append((piece, peak))
                            trial = after
                        if done is not None:
                            break
                    if skip:
                        continue
                    if done is None:
                        failed.append(LineString(run))
                        continue
                    if trace is not None:
                        trace.append({'island': index, 'stepover_mm': stepover, 'retry': zone is not None,
                                      'wall_ended': path is shapes[0] and wall_pull_back and not closed,
                                      'run_start_xy': run[0], 'run_end_xy': run[-1], 'pieces': len(done), 'path_mm': LineString(path).length,
                                      'path_end_xy': path[-1], 'outcome': 'cut' if done else 'air'})
                    for piece, peak in done:
                        commit('front', piece, stepover, peak)
                    stock = trial
                    own = sweep(path, own, radius)
                    progressed = True
                    if done:
                        arcs += len(done)
                        used = level if used is None else used
                        halt = zone is None  # Stay with this stretch of front; the others wait their turn.
                blocked = bool(failed)
                if not failed or out_of_time():
                    break
                zone = unary_union(failed).buffer(max(1., 2*stepover))
                parts = [g for g in polygons(clearance(allowed, own, radius)) if g.area > 1e-6]
                part = min(parts, key=lambda g: g.distance(Point(centre)))
            if not progressed:
                break
            passes += used is not None
            start = max(0, (start if used is None else used)-1)
        return passes, arcs, blocked

    front_passes, any_blocked = 0, False
    for index, (centre, room) in enumerate(seeds):
        region = Point(centre).buffer(room)
        entry = seed_entry(region, stock, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
        alone = seed_entry(region, pocket, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
        if entry is None or alone is None:
            continue
        centre = tuple(entry.points[-1, :2])
        stock, own = entry.remaining, alone.remaining
        reach = Point(centre).distance(wall) - 1e-3
        island = {'centre_xy_mm': centre, 'radius_mm': reach}
        chosen = None
        for stepover in stepovers:
            probe = spiral_out(centre, min(reach, 1.8*radius + 3.), stepover, blend=blend)
            if cut(probe, stock, radius, sample_step)[0] <= limit:
                chosen = stepover
                break
        if chosen is not None:
            path = spiral_out(centre, reach, chosen, blend=blend)
            peak, trial = cut(path, stock, radius, sample_step)
            island.update(stepover_mm=chosen, peak_deg=peak, feed_mm=LineString(path).length,
                          accepted=peak <= limit)
            if peak <= limit:
                commit('spiral', path, chosen, peak)
                stock, own = trial, sweep(path, own, radius)
        # Every island but the last leaves shared ground to its neighbour; the last one cleans up.
        passes, arcs, blocked = wave(index, centre, own, shared=index < len(seeds)-1)
        island.update(front_passes=passes, front_arcs=arcs)
        front_passes += passes
        any_blocked = any_blocked or blocked
        island_reports.append(island)

    # Optional wall profile: follow the pocket wall to take whatever the arc ends left on it.
    profile = {'pieces': 0, 'over_limit': 0, 'refused_mm': 0., 'feed_mm': 0.,
               'reachable_stock_before_mm2': stock.intersection(reachable).area}
    for inset in ((.3, 0.) if wall_profile else ()):
        for part in polygons(allowed.buffer(-inset) if inset else allowed):
            if part.area < 1e-6:
                continue
            part = orient(part, sign=-1.)
            for ring in (part.exterior, *part.interiors):
                dense = list(segmentize(LineString(ring.coords), .1).coords)
                for whole in cutting_pieces(dense, stock, radius, run_out=1.5, closed=True):
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
                            piece = eased(piece, False, clearance(allowed, stock, radius), allowed, 1.5,
                                          ends=(True, False))
                            if len(piece) < 2:
                                continue
                        peak, trial = cut(piece, stock, radius, sample_step)
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
                        profile['feed_mm'] += LineString(piece).length

    stop = 'time_budget' if out_of_time() else 'blocked' if any_blocked or profile['over_limit'] else 'front_exhausted'
    passes = front_passes
    residual = stock.intersection(reachable)
    total = pocket.intersection(reachable).area
    cuts = [s for s in strokes if s.kind == 'front']
    feeds = [s for s in strokes if s.kind != 'link']
    report = {'stop': stop, 'placement': placement, 'wall_pull_back': wall_pull_back,
              'lobes': [{'widest_xy_mm': xy, 'room_mm': room, 'bounds_mm': bounds}
                        for xy, room, bounds in find_lobes(allowed, min_radius=radius)],
              'islands': island_reports, 'front_passes': passes, 'front_arcs': len(cuts),
              'wall_profile': profile if wall_profile else None,
              'reachable_stock_before_profile_mm2': profile['reachable_stock_before_mm2'],
              'reachable_mm2': total, 'reachable_residual_mm2': residual.area,
              'cleared_fraction': 1 - residual.area/total if total else None,
              'peak_contact_deg': max((s.peak_deg for s in feeds), default=None),
              'cut_feed_mm': sum(LineString(s.points).length for s in feeds),
              'link_feed_mm': sum(LineString(s.points).length for s in strokes if s.kind == 'link'),
              'spiral_feed_mm': sum(LineString(s.points).length for s in strokes if s.kind == 'spiral'),
              'stay_down_links': travel['links'], 'retract_rapids': travel['rapids'],
              'retract_reasons': dict(refused, first_cut=1),
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
    parser.add_argument('--review-gcode', type=Path, help='save cuts to a new debug-only .nc file and .svg overlay')
    parser.add_argument('--islands', type=int, help='number of helical islands; default is chosen from the shape')
    parser.add_argument('--placement', choices=('lobes', 'thirds', 'widest'), default='lobes',
                        help='one island per lobe, spread along the long axis, or the widest remaining spots')
    parser.add_argument('--no-wall-pull-back', action='store_true',
                        help='roll arcs off before the wall instead of following it back')
    parser.add_argument('--wall-profile', action='store_true', help='finish with a pass along the pocket wall')
    parser.add_argument('--time-budget', type=float, help='stop adding passes after this many seconds')
    parser.add_argument('--sample-step', type=float, default=.1, help='contact sampling distance in mm')
    args = parser.parse_args()
    fixture, _ = neck_fixture()
    result = clear_pocket(fixture, 2., islands=args.islands, placement=args.placement,
                          wall_pull_back=not args.no_wall_pull_back, wall_profile=args.wall_profile, time_budget=args.time_budget,
                          sample_step=args.sample_step)
    if args.review_gcode is not None:
        write_review(args.review_gcode, fixture, *result)
    print(json.dumps(result[2], indent=2))
