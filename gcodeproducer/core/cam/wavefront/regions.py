"""Cutter-centre regions of a wavefront pocket: starts, spirals, fronts and the cleared area."""
import math

from shapely import covers, get_parts, points, segmentize
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, polylabel, split, substring, unary_union

from gcodeproducer.core.geometry.polygon_parts import polygons
from .wavefront_constants import (CENTER_BUFFER_SEGMENTS, CUT_SEGMENTS, WALL_TOLERANCE, SLIVER, ELONGATED_ASPECT, NECK_RATIO, HOLED_NECK_RATIO, SPAN_SLACK)


def center_regions(pocket, radius, *, margin=0.):
    """Return positive-area center components in reproducible spatial order.

    The model deliberately excludes zero-width connections. These components
    describe geometric access only, not a cleared route through live stock.
    """
    if not math.isfinite(radius) or radius <= 0 or not math.isfinite(margin) or margin < 0:
        raise ValueError('expected a positive radius and nonnegative margin')
    if pocket.geom_type not in {'Polygon', 'MultiPolygon'} or not pocket.is_valid:
        raise ValueError('expected valid planar pocket polygons')
    centers = pocket.buffer(-(radius + margin), quad_segs=CENTER_BUFFER_SEGMENTS)
    return tuple(sorted((p for p in polygons(centers) if p.area > 0), key=lambda p: p.bounds))


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


def sweep(path, stock, radius):
    """Remove the cutter's swept area without measuring contact."""
    return without_slivers(stock.difference(LineString(path).buffer(radius, quad_segs=CUT_SEGMENTS)))


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
