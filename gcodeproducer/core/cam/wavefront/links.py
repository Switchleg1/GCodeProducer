"""Stay-down links through cleared space between wavefront cuts."""
import math

from shapely import points, prepare
from shapely.geometry import LineString, Point

from gcodeproducer.core.geometry.polygon_parts import polygons
from .polyline import stretch
from .wavefront_constants import (LINK_TOLERANCE, LINK_HANDLE, LINK_HANDLE_SHARES, LINK_STEP, LINK_TURN_RADII,
                                  LINK_TURN_STRETCH, LINK_TURN_REACH, LINK_TURN_BENDS, LINK_HEADING_SPAN, LINK_TANGENT, LINK_INSETS)


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
        # Walk round the cleared area a little way in from its edge where it can: a route along the
        # very edge runs at a cutter radius from the stock, and no curve leaving or joining a cut
        # there can bend without touching it, so the link would have to reverse.
        ring = None
        for share in LINK_INSETS:
            inner = part.buffer(-share*radius) if share else part
            pieces = [g for g in polygons(inner) if g.area > 1e-6]
            if not pieces:
                continue
            core = max(pieces, key=lambda g: g.area)
            candidate = LineString(core.exterior.coords)
            a = candidate.interpolate(candidate.project(Point(start)))
            b = candidate.interpolate(candidate.project(Point(end)))
            if visible(start, (a.x, a.y)) and visible((b.x, b.y), end):
                ring = candidate
                break
        if ring is None:
            return refuse('no_way_to_front_edge')
        da, db = ring.project(a), ring.project(b)
        lo, hi = sorted((da, db))
        inner = stretch(ring, lo, hi)
        outer = stretch(ring, hi, ring.length) + stretch(ring, 0., lo)[1:]
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


def smooth_link(route, leaving, arriving, room, stock, radius):
    """A stay-down route made tangent to the cuts it joins and rounded at its corners.

    room is where the cutter centre may go (the pocket's centre region); a curve
    is kept only inside it and clear of live stock. The cleared region itself is
    too tight a test: a cut ends against the stock it has just left, so the
    first and last tenths of a millimetre of any link lie outside it, and every
    curve leaving tangentially was refused there.

    leaving and arriving are unit headings at the end of the cut before and
    the start of the cut after. The route becomes a chain of cubic curves
    through its corners, each tangent to the next, with handles as long as
    the legs allow up to LINK_HANDLE. It is kept only where it stays inside
    the cleared region and clear of stock; shorter handles are tried before
    falling back to the route as it was, so smoothing never makes a link unsafe.
    """
    if len(route) < 2 or math.dist(route[0], route[-1]) < 1e-6:
        return route
    room = room.buffer(LINK_TOLERANCE)
    prepare(room)
    n = len(route)
    heads = []
    for i, q in enumerate(route):
        if i == 0:
            heads.append(leaving)
        elif i == n-1:
            heads.append(arriving)
        else:
            a, b = route[i-1], route[i+1]
            la, lb = math.dist(a, q), math.dist(q, b)
            ux, uy = (q[0]-a[0])/la + (b[0]-q[0])/lb, (q[1]-a[1])/la + (b[1]-q[1])/lb
            size = math.hypot(ux, uy)
            heads.append((ux/size, uy/size) if size > 1e-9 else ((b[0]-q[0])/lb, (b[1]-q[1])/lb))
    for share in LINK_HANDLE_SHARES:
        curve = [route[0]]
        for i in range(n-1):
            a, b = route[i], route[i+1]
            h = min(LINK_HANDLE, share*math.dist(a, b))
            c1 = (a[0] + h*heads[i][0], a[1] + h*heads[i][1])
            c2 = (b[0] - h*heads[i+1][0], b[1] - h*heads[i+1][1])
            steps = max(4, math.ceil(math.dist(a, b)/LINK_STEP))
            for k in range(1, steps+1):
                t = k/steps
                u = 1-t
                curve.append((u*u*u*a[0] + 3*u*u*t*c1[0] + 3*u*t*t*c2[0] + t*t*t*b[0],
                              u*u*u*a[1] + 3*u*u*t*c1[1] + 3*u*t*t*c2[1] + t*t*t*b[1]))
        line = LineString(curve)
        if (room.covers(line) and (stock.is_empty or line.distance(stock) >= radius - 5*LINK_TOLERANCE)
                and follows(curve, leaving, arriving, LINK_TANGENT)):
            return curve
    # No curve through the route's corners fits, typically because the cut before ends, or the next
    # one starts, right against stock or a wall. Turn round on the widest circles that fit instead
    # (arc, straight, arc): the cutter leaves and joins the cuts along their own headings rather
    # than stopping and reversing.
    near = None if stock.is_empty else stock
    limit = LINK_TURN_STRETCH*LineString(route).length + 4*radius
    wide = room

    def fits(curve, bend=180.):
        line = LineString(curve)
        return (line.length <= limit and wide.covers(line)
                and (near is None or line.distance(near) >= radius - 5*LINK_TOLERANCE)
                and follows(curve, leaving, arriving, bend + LINK_TANGENT))

    def rotated(h, angle):
        c, s_ = math.cos(angle), math.sin(angle)
        return (h[0]*c - h[1]*s_, h[0]*s_ + h[1]*c)

    def unit(a, b):
        size = math.dist(a, b)
        return ((b[0]-a[0])/size, (b[1]-a[1])/size) if size > 1e-9 else None

    # Leave and join along the cuts' own headings if that fits; a cut that starts or ends square to a
    # wall cannot be joined tangentially without crossing the wall, so then turn by as little as
    # will fit: a rounded corner of up to 90 degrees instead of a reversal.
    for bend in LINK_TURN_BENDS:
        tries = [(math.radians(a), math.radians(b)) for a in sorted({0., bend, -bend}, key=abs)
                 for b in sorted({0., bend, -bend}, key=abs) if max(abs(a), abs(b)) == bend]
        for turn in LINK_TURN_RADII:
            for a, b in tries:
                out, into = rotated(leaving, a), rotated(arriving, b)
                for curve in turn_round(route[0], out, route[-1], into, turn*radius):
                    if fits(curve, bend):
                        return curve
                if len(route) < 3:
                    continue
                # The route bends round stock on its way: keep its corners in the middle and turn
                # round only near its ends, onto a leg far enough along to turn round before.
                reach = LINK_TURN_REACH*turn*radius
                k = next((k for k in range(1, len(route)-1) if math.dist(route[0], route[k]) >= reach), None)
                m = next((m for m in range(len(route)-2, 0, -1) if math.dist(route[-1], route[m]) >= reach), None)
                if k is None or m is None or m < k:
                    continue
                first = unit(route[k], route[k+1])
                last = unit(route[m-1], route[m]) if m > k else first
                if first is None or last is None:
                    continue
                head = next((c for c in turn_round(route[0], out, route[k], first, turn*radius) if fits(c)), None)
                tail = next((c for c in turn_round(route[m], last, route[-1], into, turn*radius) if fits(c)), None)
                if head is not None and tail is not None:
                    curve = head + list(route[k+1:m]) + tail
                    if fits(curve, bend):
                        return curve
    return route


def follows(curve, leaving, arriving, degrees):
    """Does the curve really leave and join along these headings (within ``degrees``)?

    A curve with a very short handle can meet the tolerance and still hook
    round at its very end: judged over LINK_HEADING_SPAN, not its last step.
    """
    least = math.cos(math.radians(degrees))
    out, into = heading(curve, False), heading(curve, True)
    return (out[0]*leaving[0] + out[1]*leaving[1] >= least and into[0]*arriving[0] + into[1]*arriving[1] >= least)


def turn_round(start, leaving, end, arriving, turn):
    """Shortest first: paths of a circle of radius ``turn``, a straight and another circle.

    Each leaves ``start`` along the unit heading ``leaving`` and arrives at
    ``end`` along ``arriving``; all four combinations of left and right turns.
    """
    if turn <= 0 or math.hypot(*leaving) < .5 or math.hypot(*arriving) < .5:
        return []

    def centre(p, h, side):          # side 1 turns left (counter-clockwise), -1 right
        return (p[0] - side*turn*h[1], p[1] + side*turn*h[0])

    found = []
    for s0 in (1, -1):
        for s1 in (1, -1):
            c0, c1 = centre(start, leaving, s0), centre(end, arriving, s1)
            dx, dy = c1[0]-c0[0], c1[1]-c0[1]
            gap = math.hypot(dx, dy)
            if s0 == s1:
                if gap < 1e-9:
                    continue
                ux, uy = dx/gap, dy/gap                      # outer tangent, along the line of centres
            else:
                if gap < 2*turn + 1e-9:
                    continue
                straight = math.sqrt(gap*gap - 4*turn*turn)   # inner tangent, crossing between them
                angle = math.atan2(dy, dx) + math.atan2(2*s0*turn, straight)
                ux, uy = math.cos(angle), math.sin(angle)
            t0 = (c0[0] + s0*turn*uy, c0[1] - s0*turn*ux)      # centre less side x turn x left(u)
            t1 = (c1[0] + s1*turn*uy, c1[1] - s1*turn*ux)
            if (t1[0]-t0[0])*ux + (t1[1]-t0[1])*uy < -1e-9:
                continue
            path = _arc(c0, start, t0, s0, turn) + _segment(t0, t1)[1:] + _arc(c1, t1, end, s1, turn)[1:]
            found.append((LineString(path).length, path))
    return [path for _, path in sorted(found, key=lambda item: item[0])]


def _arc(centre, a, b, side, turn):
    """Points from a to b round centre, turning left (side 1) or right (side -1)."""
    a0 = math.atan2(a[1]-centre[1], a[0]-centre[0])
    a1 = math.atan2(b[1]-centre[1], b[0]-centre[0])
    sweep = (a1 - a0) % (2*math.pi) if side == 1 else -((a0 - a1) % (2*math.pi))
    if abs(sweep) > 2*math.pi - 1e-6:
        sweep = 0.
    steps = max(1, math.ceil(abs(sweep)*turn/LINK_STEP), math.ceil(abs(sweep)/(math.pi/12)))
    points = [(centre[0] + turn*math.cos(a0 + sweep*k/steps), centre[1] + turn*math.sin(a0 + sweep*k/steps))
              for k in range(steps+1)]
    points[0], points[-1] = tuple(a), tuple(b)
    return points


def _segment(a, b):
    steps = max(1, math.ceil(math.dist(a, b)/LINK_STEP))
    return [(a[0] + (b[0]-a[0])*k/steps, a[1] + (b[1]-a[1])*k/steps) for k in range(steps+1)]


def heading(points, at_end):
    """Unit heading of a path at its start or end: toward the first point LINK_HEADING_SPAN away.

    A cut's ends can carry a few points closer than a micron to each other,
    whose direction is noise; the first one far enough away gives the way the
    cutter actually goes. A path shorter than that uses its far end.
    """
    seq = points[::-1] if at_end else points
    far = None
    for q in seq[1:]:
        dx, dy = q[0]-seq[0][0], q[1]-seq[0][1]
        size = math.hypot(dx, dy)
        if size > 1e-6:
            far = (dx/size, dy/size)
            if size >= LINK_HEADING_SPAN:
                break
    if far is None:
        return (0., 0.)
    return (-far[0], -far[1]) if at_end else far
