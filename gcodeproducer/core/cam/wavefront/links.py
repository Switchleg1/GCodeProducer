"""Stay-down links through cleared space between wavefront cuts."""
import math

from shapely import points, prepare
from shapely.geometry import LineString, Point

from gcodeproducer.core.geometry.polygon_parts import polygons
from .polyline import stretch
from .wavefront_constants import (LINK_TOLERANCE, LINK_HANDLE, LINK_HANDLE_SHARES, LINK_STEP)


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


def smooth_link(route, leaving, arriving, clear, stock, radius):
    """A stay-down route made tangent to the cuts it joins and rounded at its corners.

    leaving and arriving are unit headings at the end of the cut before and
    the start of the cut after. The route becomes a chain of cubic curves
    through its corners, each tangent to the next, with handles as long as
    the legs allow up to LINK_HANDLE. It is kept only where it stays inside
    the cleared region and clear of stock; shorter handles are tried before
    falling back to the route as it was, so smoothing never makes a link unsafe.
    """
    if len(route) < 2 or math.dist(route[0], route[-1]) < 1e-6:
        return route
    room = clear.buffer(LINK_TOLERANCE)
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
        if room.covers(line) and (stock.is_empty or line.distance(stock) >= radius - 5*LINK_TOLERANCE):
            return curve
    return route


def heading(points, at_end):
    """Unit heading of a path at its start or end, over its last or first non-zero step."""
    seq = points[::-1] if at_end else points
    for q in seq[1:]:
        dx, dy = q[0]-seq[0][0], q[1]-seq[0][1]
        size = math.hypot(dx, dy)
        if size > 1e-6:
            return (-dx/size, -dy/size) if at_end else (dx/size, dy/size)
    return (0., 0.)
