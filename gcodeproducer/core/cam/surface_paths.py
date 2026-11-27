"""3-axis paths limited by the model surface: Z-level wall contours and surface-following rasters.

Flat-cutter geometry only. Ball/bull tools are treated as flat cutters of the
same diameter, which never gouges but leaves extra material on slopes.
"""
from __future__ import annotations
import math
import numpy as np
from shapely import BufferJoinStyle, contains_xy
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union
from shapely.prepared import prep
from .cam_constants import (SURFACE_MAX_POINTS, SURFACE_DIP_FILL, SURFACE_DIP_DEPTH, SURFACE_WALL_SLOPE,
                            SPIRAL_ON_WALL)
from .surface_simplifier import simplify3d
from .paths import _polygons, orient_contour, pocket_region


def selection_region(loops, log=None, name=""):
    """Selected closed XY outlines: nested loops alternate (as for pockets), overlapping ones merge."""
    try:
        return pocket_region(loops)
    except ValueError:
        polygons = []
        for loop in loops:
            polygon = Polygon(loop)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if not polygon.is_empty and polygon.area > 1e-9:
                polygons.append(polygon)
        region = unary_union(polygons) if polygons else Polygon()
        if region.is_empty:
            raise ValueError(f"{name}: selection has no closed XY area") from None
        if log:
            log(f"  {name}: overlapping boundaries merged into one machining area; the model surface limits the cut")
        return region


def waterfall_paths(shadow, allowed, radius, allowance, direction):
    """Cutter-centre contours around everything standing above this level.

    Returns ``(points, closed)``. Contours leaving ``allowed`` are clipped to
    open pieces; material stays on the contour's inner side (holes: outer side).
    """
    if shadow.is_empty:
        return []
    offset = shadow.buffer(radius+allowance, join_style=BufferJoinStyle.round)
    result = []
    for polygon in sorted(_polygons(offset), key=lambda p: p.bounds):
        for ring, inside in [(polygon.exterior, True)]+[(r, False) for r in polygon.interiors]:
            points = np.asarray(ring.coords, float)[:-1]
            if len(points) < 3:
                continue
            points = orient_contour(points, direction, material_inside=inside, index=len(result))
            line = LineString(np.vstack((points, points[0])))
            if allowed.covers(line):
                result.append((points, True))
                continue
            pieces = allowed.intersection(line)
            if pieces.is_empty:
                continue
            if pieces.geom_type not in ("LineString", "MultiLineString"):
                pieces = unary_union([g for g in getattr(pieces, "geoms", ()) if "Line" in g.geom_type])
            if pieces.geom_type == "MultiLineString":
                pieces = linemerge(pieces)
            for piece in getattr(pieces, "geoms", [pieces]):
                if piece.geom_type != "LineString" or piece.length < max(.05, radius*.1):
                    continue
                p = np.asarray(piece.coords, float)
                a, b = line.project(Point(p[0])), line.project(Point(p[min(1, len(p)-1)]))
                if (b < a) != (abs(b-a) > line.length/2):     # keep the oriented ring's travel direction
                    p = p[::-1]
                result.append((p, False))
    return result


def follow_heights(surface, xy, radius, allowance, floors=()):
    """Cutter heights along a path sampled every grid cell: the one rule 3D Contour and Waterfall follow.

    Interpolated safe heights (``DropSurface.follow``) plus stock to leave,
    never below a holding tab's top, with dips narrower than
    ``SURFACE_DIP_FILL`` filled by up to ``SURFACE_DIP_DEPTH`` so grid noise
    does not saw the cutter up and down. Never below ``DropSurface.heights``
    + ``allowance``.
    """
    xy = np.asarray(xy, float)[:, :2]
    follow = getattr(surface, 'follow', surface.heights)   # a plain height source has no interpolation
    z = follow(xy, radius)+allowance
    for area, roof in floors:     # retained material (holding tabs): never below its top
        z = np.where(contains_xy(area, xy[:, 0], xy[:, 1]), np.maximum(z, roof), z)
    return fill_dips(z, max(1, round(SURFACE_DIP_FILL/(2*surface.resolution))), SURFACE_DIP_DEPTH)


def fill_dips(height, reach, depth=np.inf):
    """``height`` with every dip narrower than ``2*reach+1`` samples raised by up to ``depth``; never lower.

    A morphological closing (running maximum, then running minimum) along the
    path, limited so a real corner (a floor meeting a wall) is not filled.
    """
    from numpy.lib.stride_tricks import sliding_window_view
    height = np.asarray(height, float)
    if len(height) < 3:
        return height
    width = 2*reach+1
    grown = sliding_window_view(np.pad(height, reach, mode='edge'), width).max(axis=1)
    closed = sliding_window_view(np.pad(grown, reach, mode='edge'), width).min(axis=1)
    return np.maximum(np.minimum(closed, height+depth), height)


def _cutter_track(xy, surface, radius, allowance, floors, floor, top, area):
    """XYZ of the cutter along the points ``xy``: on the model, never below the floor.

    Outside ``area`` (a gap in the selection) it rides at ``top``. Up a wall,
    and where the path leaves the area, it rises vertically at the lower point
    and descends vertically at the lower point after it: never a near-vertical
    slant whose XY, rounded in the program, would move the cutter's height on
    the wall.
    """
    xy = np.asarray(xy, float)
    z = np.maximum(follow_heights(surface, xy, radius, allowance, floors), floor)
    inside = contains_xy(area, xy[:, 0], xy[:, 1])
    if top is not None:
        z = np.where(inside, z, np.maximum(z, top))
    run = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    rise = np.diff(z)
    wall = (np.abs(rise) > SURFACE_WALL_SLOPE*run) | (inside[1:] != inside[:-1])
    if not wall.any():
        return np.column_stack((xy, z))
    points = []
    for k in range(len(xy)):
        if k and wall[k-1] and abs(rise[k-1]) > 1e-9:
            corner = xy[k-1] if rise[k-1] > 0 else xy[k]
            points.append((*corner, max(z[k-1], z[k])))
        points.append((*xy[k], z[k]))
    return np.asarray(points, float)


def _along_the_wall(region, a, b, step):
    """XY points from a to b along the boundary of ``region`` they both lie on (the shorter way), or None."""
    from shapely.ops import substring
    from shapely import segmentize
    pa, pb = Point(a), Point(b)
    for polygon in _polygons(region):
        for ring in (polygon.exterior, *polygon.interiors):
            if ring.distance(pa) > SPIRAL_ON_WALL or ring.distance(pb) > SPIRAL_ON_WALL:
                continue
            line = LineString(ring.coords)
            length, da, db = line.length, line.project(pa), line.project(pb)

            def forward(start, end):
                if end >= start:
                    return list(substring(line, start, end).coords)
                return list(substring(line, start, length).coords) + list(substring(line, 0., end).coords)[1:]
            way = forward(da, db) if (db-da) % length <= (da-db) % length else forward(db, da)[::-1]
            if len(way) < 2:
                return np.array([a, b], float)[:, :2]
            return np.asarray(segmentize(LineString(way), step).coords, float)[:, :2]
    return None


def surface_spiral(region, surface, radius, spacing, floor, allowance, log=None, floors=(), ceiling=math.inf,
                   *, simplifier=None, direction="climb", stay_down=False):
    """One depth band of 3D Contour as a spiral out from the centre of the area.

    The spiral starts at the centre of the area's bounds and grows by
    ``spacing`` a turn until it has passed the area's farthest corner. Like the
    raster lines it follows the model under the cutter, never below ``floor``.
    Only its stretches inside ``region`` (where the cutter's centre may go) are
    cut, in order from the centre outwards. Where it runs into the edge of the
    area: with ``stay_down`` the cutter walks along that edge to where the
    spiral comes back in, without lifting (a new path only where the two points
    are on different edges); without it each stretch is a path of its own, the
    cutter lifting to the start of the next. It ends with one pass round each
    edge of the area: the turn that would clear the strip beside an edge lies
    outside the area, so without that pass strips would be left along the walls.

    Climb turns counter-clockwise (M3: the uncut turns outside are on the
    cutter's right), Conventional clockwise. A spiral cannot alternate, so
    Meander turns as Climb.
    """
    if region.is_empty or spacing <= 0:
        return []
    if direction not in ("climb", "conventional", "meander"):
        raise ValueError(f"Unknown cutting direction '{direction}'")
    minx, miny, maxx, maxy = region.bounds
    centre = np.array([(minx+maxx)/2, (miny+maxy)/2])
    reach = math.hypot(maxx-minx, maxy-miny)/2 + spacing
    step = surface.resolution
    if math.pi*reach*reach/spacing/step > SURFACE_MAX_POINTS:
        raise ValueError("3D contour would need too many surface samples; increase stepover or reduce the area")
    # Equal steps of arc along r = spacing*angle/2pi: angle = sqrt(4pi*length/spacing).
    count = int(math.ceil(math.pi*reach*reach/spacing/step)) + 1
    angle = np.sqrt(4*math.pi*step*np.arange(count+1)/spacing)
    angle = angle[angle <= 2*math.pi*reach/spacing]
    r = spacing*angle/(2*math.pi)
    turn = angle if direction != "conventional" else -angle
    spiral = centre + np.column_stack((r*np.cos(turn), r*np.sin(turn)))
    if len(spiral) < 2:
        return []
    line = LineString(spiral)
    hit = line.intersection(region)
    pieces = [g for g in getattr(hit, "geoms", [hit]) if g.geom_type == "LineString" and g.length > 1e-6]
    if not pieces:
        return []
    # GEOS keeps the spiral's direction within each piece; put them in order from the centre out.
    pieces.sort(key=lambda g: line.project(Point(g.coords[0])))
    top = ceiling if math.isfinite(ceiling) else None
    area = region.buffer(1e-7)

    def track(xy):
        return _cutter_track(xy, surface, radius, allowance, floors, floor, top, area)

    runs = [track(np.asarray(g.coords, float)) for g in pieces]
    if top is not None:
        runs = [run for run in runs if np.any(run[:, 2] < top-1e-6)]   # riding on the top all the way: cuts nothing
    if not runs:
        return []
    paths, walked = [runs[0]], 0
    for run in runs[1:]:
        wall = _along_the_wall(region, paths[-1][-1, :2], run[0, :2], step) if stay_down else None
        if wall is None or len(wall) < 2:
            paths.append(run)
            continue
        walked += 1
        link = track(wall)
        paths[-1] = np.vstack((paths[-1], link[1:-1], run))
    # Where the spiral is cut off at an edge, the turn that would have cleared the strip beside that
    # edge lies outside the area. One pass round each edge of the area takes those strips. The stock
    # left is inside the area: climb keeps it on the right (clockwise round the outside, the other
    # way round a hole).
    from shapely import segmentize
    from shapely.geometry.polygon import orient
    edges = 0
    for polygon in _polygons(region):
        polygon = orient(polygon, sign=-1. if direction != "conventional" else 1.)
        for ring in (polygon.exterior, *polygon.interiors):
            lap = track(np.asarray(segmentize(LineString(ring.coords), step).coords, float)[:, :2])
            if top is None or np.any(lap[:, 2] < top-1e-6):
                paths.append(lap)
                edges += 1
    result = simplifier(paths) if simplifier is not None else [simplify3d(p) for p in paths]
    if log:
        log(f"    spiral of {len(runs)} stretches from the centre out in {len(result)-edges} paths"
            + (f", {walked} joined along the edge of the area" if walked else "")
            + f", then {edges} pass(es) round the edge")
    return [p for p in result if len(p) >= 2]


def surface_raster(region, surface, radius, spacing, floor, allowance, log=None, floors=(), ceiling=math.inf,
                   strategy="raster_x", *, simplifier=None, direction="climb", stay_down=False):
    """One depth band of 3D Contour: XYZ raster lines along X or Y, in order across the area.

    Every line runs the whole width of the selected area, from where it first
    enters the area to where it last leaves it, following the model under the
    cutter and never below ``floor`` (the depth of this pass): it traces the
    whole contour of the model and does not lift or stop where it crosses
    ground an earlier pass already cut. Where a line crosses a gap in the
    selection it rides at ``ceiling`` (the top of the material), so nothing
    outside the selection is cut; it rises and descends vertically there.

    ``direction``: Meander cuts the lines alternately one way and the other,
    each joined to the next by a move along the edge of the area: one path.
    Climb and Conventional cut every line the same way (climb keeps the uncut
    lines on the cutter's right with an M3 spindle). With ``stay_down`` the
    cutter comes back along the line just cut (exactly the same points, over
    cut ground) and steps over to the next: one path. Without it, one path per
    line, the cutter lifting at the end of each and going back to the start
    of the next. The order is never changed and nothing is skipped.
    """
    if region.is_empty or spacing <= 0:
        return []
    from .strategy import cutting_strategy
    strategy = cutting_strategy("contour3d", strategy)
    if strategy not in ("raster_x", "raster_y"):
        raise ValueError(f"Unknown 3D Contour cutting strategy '{strategy}'")
    if direction not in ("climb", "conventional", "meander"):
        raise ValueError(f"Unknown cutting direction '{direction}'")
    minx, miny, maxx, maxy = region.bounds
    along_x = strategy == "raster_x"
    axis = 0 if along_x else 1
    lo, hi = (miny, maxy) if along_x else (minx, maxx)
    count = max(1, int(math.ceil((hi-lo)/spacing-1e-9)))
    step = surface.resolution
    if 2*(count+1)*(max(maxx-minx, maxy-miny)/step+2) > SURFACE_MAX_POINTS:
        raise ValueError("3D contour would need too many surface samples; increase stepover or reduce the area")
    top = ceiling if math.isfinite(ceiling) else None

    def sample(a, b):
        """The cutter along a to b: on the model, never below the floor; at the top outside the area."""
        a, b = np.asarray(a, float), np.asarray(b, float)
        n = max(1, int(math.ceil(np.linalg.norm(b-a)/step)))
        return _cutter_track(a+(b-a)*np.linspace(0, 1, n+1)[:, None], surface, radius, allowance, floors, floor,
                             top, area)

    area = region.buffer(1e-7)
    # Climb keeps the uncut lines (the next ones) on the right: lines along X step to +Y, so climb
    # runs -X; lines along Y step to +X, so climb runs +Y.
    climb_forward = not along_x
    rows = []
    for i in range(count+1):
        offset = lo+(hi-lo)*i/count if count else (lo+hi)/2
        # Keep the outermost passes fractionally inside so they intersect the region.
        offset = min(max(offset, lo+1e-6), hi-1e-6)
        line = LineString([(minx-1, offset), (maxx+1, offset)] if along_x else [(offset, miny-1), (offset, maxy+1)])
        hit = region.intersection(line)
        pieces = [g for g in getattr(hit, "geoms", [hit]) if g.geom_type == "LineString" and g.length > 1e-6]
        if not pieces:
            continue
        ends = np.asarray([q for g in pieces for q in g.coords], float)
        first, last = ends[:, axis].min(), ends[:, axis].max()
        a, b = np.array([first, offset]), np.array([last, offset])
        if not along_x:
            a, b = a[::-1], b[::-1]
        forward = climb_forward if direction != "conventional" else not climb_forward
        if direction == "meander" and len(rows) % 2:
            forward = not forward
        rows.append((a, b) if forward else (b, a))
    if not rows:
        return []
    cuts = [sample(a, b) for a, b in rows]
    if top is not None:
        # Lines at the start or end of the band that ride entirely on the top of the material
        # (the cutter overlapping the selection's wall) cut nothing: leave them out. Lines between
        # are kept, so the step over from one line to the next never grows.
        cutting = [k for k, cut in enumerate(cuts) if np.any(cut[:, 2] < top-1e-6)]
        if not cutting:
            return []
        keep = slice(cutting[0], cutting[-1]+1)
        rows, cuts = rows[keep], cuts[keep]
        if direction == "meander" and cutting[0] % 2:
            rows = [(b, a) for a, b in rows]
            cuts = [cut[::-1] for cut in cuts]
    reduce = simplifier if simplifier is not None else (lambda paths: [simplify3d(p) for p in paths])
    if direction != "meander" and not stay_down:
        lines = [line for line in reduce(cuts) if len(line) >= 2]
        if log:
            log(f"    {len(lines)} raster lines, each cut one way, lifting back to the start of the next")
        return lines
    joins = []
    for k in range(len(rows)-1):
        # Meander joins the end of a line to the start of the next along the edge of the area; one
        # way staying down comes back along the line just cut and joins its start to the next one's.
        joins.append(sample(rows[k][1] if direction == "meander" else rows[k][0], rows[k+1][0]))
    reduced = reduce(cuts + joins)
    cuts, joins = reduced[:len(cuts)], reduced[len(cuts):]
    pieces = []
    for k, cut in enumerate(cuts):
        pieces.append(cut)
        if k < len(joins):
            if direction != "meander":
                pieces.append(cut[::-1][1:])     # back over the line just cut: exactly the same points
            pieces.append(joins[k][1:])
    path = np.vstack(pieces)
    if log:
        log(f"    {len(rows)} raster lines in one path of {len(path)} points"
            + ("" if direction == "meander" else ", each line cut one way and travelled back over"))
    return [path] if len(path) >= 2 else []
