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
from .cam_constants import SURFACE_MAX_POINTS, SURFACE_DIP_FILL, SURFACE_DIP_DEPTH
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


def surface_raster(region, surface, radius, spacing, floor, allowance, log=None, floors=(), ceiling=math.inf,
                   strategy="meander", *, simplifier=None):
    """Depth-clamped XYZ rasters, as meander or independent X/Y cutting lines.

    Meander alternates along the longer side and joins neighbouring passes
    along the surface when the joining move stays inside the region. X/Y
    raster lines run in one direction and retract between cutting lines.
    Stretches where the cutter would sit at or above ``ceiling`` (it rests on
    material that is not being machined, e.g. the top face beside a wall) are
    left out instead of being traced in the air.
    """
    if region.is_empty or spacing <= 0:
        return []
    from .strategy import cutting_strategy
    strategy = cutting_strategy("contour3d", strategy)
    if strategy not in ("meander", "raster_x", "raster_y"):
        raise ValueError(f"Unknown 3D Contour cutting strategy '{strategy}'")
    minx, miny, maxx, maxy = region.bounds
    along_x = strategy == "raster_x" or (strategy == "meander" and (maxx-minx) >= (maxy-miny))
    lo, hi = (miny, maxy) if along_x else (minx, maxx)
    count = max(1, int(math.ceil((hi-lo)/spacing-1e-9)))
    step = surface.resolution
    if (count+1)*(max(maxx-minx, maxy-miny)/step+2) > SURFACE_MAX_POINTS:
        raise ValueError("3D contour would need too many surface samples; increase stepover or reduce the area")

    def sample(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        n = max(1, int(math.ceil(np.linalg.norm(b-a)/step)))
        xy = a+(b-a)*np.linspace(0, 1, n+1)[:, None]
        return np.column_stack((xy, np.maximum(follow_heights(surface, xy, radius, allowance, floors), floor)))

    paths, current, reverse = [], None, False
    cover = prep(region.buffer(1e-7))
    for i in range(count+1):
        offset = lo+(hi-lo)*i/count if count else (lo+hi)/2
        # Keep the outermost passes fractionally inside so they intersect the region.
        offset = min(max(offset, lo+1e-6), hi-1e-6)
        line = LineString([(minx-1, offset), (maxx+1, offset)] if along_x else [(offset, miny-1), (offset, maxy+1)])
        hit = region.intersection(line)
        pieces = [g for g in getattr(hit, "geoms", [hit]) if g.geom_type == "LineString" and g.length > 1e-6]
        pieces.sort(key=lambda g: g.coords[0][0 if along_x else 1], reverse=reverse)
        for piece in pieces:
            ends = np.asarray(piece.coords, float)
            ends = ends[[0, -1]]
            if (ends[0][0 if along_x else 1] > ends[1][0 if along_x else 1]) != reverse:
                ends = ends[::-1]
            whole = sample(ends[0], ends[1])
            below = whole[:, 2] < ceiling-1e-6
            edges = np.flatnonzero(np.diff(np.r_[False, below, False].astype(int)))
            for first, last in zip(edges[::2], edges[1::2]):
                run = whole[first:last]
                if len(run) < 2:
                    continue
                if strategy != "meander":
                    paths.append(run)
                    continue
                if current is not None:
                    link = LineString((current[-1][:2], run[0, :2]))
                    if link.length <= 2.5*spacing+1e-9 and cover.covers(link):
                        bridge = sample(current[-1][:2], run[0, :2])
                        if np.all(bridge[:, 2] < ceiling-1e-6):
                            current = np.vstack((current, bridge[1:-1], run))
                            continue
                    paths.append(current)
                current = run
        if pieces and strategy == "meander":
            reverse = not reverse
    if current is not None:
        paths.append(current)
    result = simplifier(paths) if simplifier is not None else [simplify3d(p) for p in paths]
    if log:
        log(f"    {sum(len(p) for p in paths)} surface samples reduced to {sum(len(p) for p in result)} points")
    return [p for p in result if len(p) >= 2]
