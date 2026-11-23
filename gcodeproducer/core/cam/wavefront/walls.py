"""How wavefront cuts meet the pocket wall: glances, hooks, bows and corner creeps."""
import math
import numpy as np

from shapely import clip_by_rect, distance, get_coordinates, get_parts, line_interpolate_point, points, segmentize
from shapely.geometry import LineString, Point, box
from shapely.ops import nearest_points

from .regions import eased, sweep
from .links import heading
from .polyline import stretch
from .wavefront_constants import (WALL_TOLERANCE, CORNER_DEPTH, CORNER_TURN, CORNER_RUN_IN, CORNER_STEPS, GLANCE_TURN, GLANCE_REACH, GLANCE_ANGLE, BOW_WIDTH_FACTOR, BOW_SET_BACKS, BOW_EXCESS, BOW_PARALLEL, HOOK_SHARE, MIN_HOOK_TRIM, HOOK_SEARCH, HOOK_RADIUS_FACTOR, WALL_CORNER, CORNER_WINDOW, WALL_GAP, NEAR_WALL, WALL_REACH, PROBE_MARGIN)


_wall_memo = {'for': (None, None), 'found': {}}


def along_wall(rings, xy, part, own, radius, overlap, *, at_least=0., limit=WALL_REACH):
    """walk_wall, remembered while the cleared area and stock stay the same.

    One front asks about the same wall points several times over: to see
    whether its ends are on the wall, again for each shape of end tried, and
    again for each position of a bow.
    """
    if _wall_memo['for'][0] is not part or _wall_memo['for'][1] is not own:
        _wall_memo['for'], _wall_memo['found'] = (part, own), {}
    key = (round(xy[0], 6), round(xy[1], 6), radius, overlap, at_least, limit, len(rings))
    if key not in _wall_memo['found']:
        _wall_memo['found'][key] = walk_wall(rings, xy, part, own, radius, overlap, at_least=at_least, limit=limit)
    found = _wall_memo['found'][key]
    return None if found is None else list(found)


def grown_box(rect, by):
    """A box grown by ``by`` on every side; a square-cornered stand-in for buffering it."""
    x0, y0, x1, y1 = rect.bounds
    return box(x0 - by, y0 - by, x1 + by, y1 + by)


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
    # Which way along the wall the cleared area lies: measured against the cleared area near here only.
    # The whole of it has tens of thousands of vertices on a large pocket.
    span = limit*probe/steps + PROBE_MARGIN
    local = clip_by_rect(part, foot.x - span, foot.y - span, foot.x + span, foot.y + span)
    if local.area <= 0:
        local = part
    way = walk(min((1, -1), key=lambda sign: local.distance(ring.interpolate((here + sign*limit*probe/steps) % total))))
    # Measure against what lies near this stretch of wall only; the whole pocket is far slower.
    xs, ys = zip(*way)
    around = box(min(xs), min(ys), max(xs), max(ys))
    near_own = own.intersection(grown_box(around, radius + .5)) if not own.is_empty else own
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
    near_part = part.intersection(grown_box(around, WALL_GAP + 3.))
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
    return stretch(a, 0., a.length-trim) + curve + stretch(b, trim, b.length)


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
    steps = math.ceil((back + 4*trim)/.2)
    angles = a2 + bend*span/2 + bend*.2*np.arange(1, steps+1)
    onward = np.vstack(((p2.x, p2.y), (p2.x, p2.y) + np.cumsum(.2*np.column_stack((np.cos(angles), np.sin(angles))), axis=0)))
    run_up = LineString(onward)
    lo, hi = onward.min(axis=0) - 1., onward.max(axis=0) + 1.
    ahead = run_up.intersection(ring.intersection(box(lo[0], lo[1], hi[0], hi[1])))
    if ahead.is_empty:
        return None
    reach = min(run_up.project(g) for g in get_parts(ahead) if g.geom_type == 'Point') if any(
        g.geom_type == 'Point' for g in get_parts(ahead)) else None
    if reach is None or reach < 1e-6:
        return None
    corner = run_up.interpolate(reach)
    tail = along_wall(rings, (corner.x, corner.y), part, own, radius, overlap, at_least=trim+overlap)
    if tail is None:
        return None
    leg = stretch(line, 0., line.length - back) + stretch(run_up, 0., reach)[1:]
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
                # Built only if asked for: the bow is usually taken.
                alternatives.append(lambda: wall_ends(run, part, own, radius, allowed, rings, blend,
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
