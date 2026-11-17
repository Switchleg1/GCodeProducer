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
from .cam_constants import SURFACE_SIMPLIFY, SURFACE_MAX_POINTS
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


def simplify3d(points, tolerance=SURFACE_SIMPLIFY):
    """Douglas-Peucker in 3D: the result stays within ``tolerance`` of the sampled polyline."""
    points = np.asarray(points, float)
    if len(points) < 3:
        return points
    keep = np.zeros(len(points), bool)
    keep[[0, -1]] = True
    stack = [(0, len(points)-1)]
    while stack:
        first, last = stack.pop()
        if last-first < 2:
            continue
        a, d = points[first], points[last]-points[first]
        rel = points[first+1:last]-a
        length = float(d @ d)
        if length < 1e-24:
            distance = np.linalg.norm(rel, axis=1)
        else:
            t = np.clip(rel @ d/length, 0, 1)
            distance = np.linalg.norm(rel-t[:, None]*d, axis=1)
        worst = int(distance.argmax())
        if distance[worst] > tolerance:
            middle = first+1+worst
            keep[middle] = True
            stack.extend(((first, middle), (middle, last)))
    return points[keep]


def surface_raster(region, surface, radius, spacing, floor, allowance, log=None, floors=(), ceiling=math.inf,
                   strategy="meander"):
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
        z = np.maximum(surface.heights(xy, radius)+allowance, floor)
        for area, roof in floors:     # retained material (holding tabs): never below its top
            z = np.where(contains_xy(area, xy[:, 0], xy[:, 1]), np.maximum(z, roof), z)
        return np.column_stack((xy, z))

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
    result = [simplify3d(p) for p in paths]
    if log:
        log(f"    {sum(len(p) for p in paths)} surface samples reduced to {sum(len(p) for p in result)} points")
    return [p for p in result if len(p) >= 2]
