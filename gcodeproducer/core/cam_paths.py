"""Wall-parallel CAM clearing with topology-aware cutter-centre regions.

Shapely/GEOS offsets split/merge contours where advancing fronts meet walls
or islands. Unlike independent polygon offsets, this cannot knowingly route a
closed clearing loop through an island when a square meets a circle.
Output remains polygonal G1 paths from STL, not fitted controller arcs.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon, LineString, Point
from shapely.prepared import prep
from shapely import BufferJoinStyle

from .geometry import signed_orient

DIRECTIONS = ("climb", "conventional", "meander")


def direction_for(job, operation=None):
    value = getattr(operation, "cut_direction", "machine")
    if value == "machine":
        value = job.m("cut_direction", "climb")
    if value not in DIRECTIONS:
        raise ValueError(f"Unknown cutting direction '{value}'")
    return value


def orient_contour(points, direction, *, material_inside, index=0):
    """M3 spindle: climb CW around retained islands, CCW inside pocket walls.

    material_inside identifies the retained/uncut side of this boundary, not
    input winding. Meander alternates absolute CCW/CW winding between loops.
    This specifies contour handedness, not constant tool engagement.
    """
    ccw = not material_inside
    if direction == "conventional":
        ccw = not ccw
    elif direction == "meander":
        ccw = index % 2 == 0
    return signed_orient(np.asarray(points, float), ccw=ccw)


def pocket_region(loops):
    region = Polygon()
    polygons = []
    for loop in loops:
        p = Polygon(loop)
        if not p.is_valid or p.area <= 1e-9:
            raise ValueError("Pocket boundary is invalid or self-intersecting; repair/reselect geometry")
        if not any(p.equals(q) for q in polygons):
            polygons.append(p)
    # Match the nesting/even-odd convention used by the other CAM stages.
    for i, p in enumerate(polygons):
        for q in polygons[:i]:
            if p.overlaps(q):
                raise ValueError("Pocket boundaries overlap without nesting; select separate closed regions")
        region = region.symmetric_difference(p)
    if region.is_empty or not region.is_valid:
        raise ValueError("Pocket has no valid closed removal region")
    return region


def part_section(mesh, depths, clearance=0.0):
    """Union of valid part cross-sections sampled just above each depth (even-odd nesting).

    Conservative: protects part material anywhere in the sampled depth range.
    Polygons that fail to form valid rings are dilated point sets, never dropped.
    """
    from .geometry import slice_z
    from shapely.geometry import MultiPoint
    from shapely.ops import unary_union
    sections = []
    for z in sorted(set(float(d) for d in depths)):
        region = Polygon()
        for loop in slice_z(mesh, z+1e-4):
            loop = np.asarray(loop, float)
            if len(loop) < 3:
                continue
            p = Polygon(loop)
            if not p.is_valid:
                p = p.buffer(0)
                if p.is_empty:
                    p = MultiPoint(loop).convex_hull
            region = region.symmetric_difference(p)
        if not region.is_empty:
            sections.append(region.buffer(0))
    union = unary_union(sections) if sections else Polygon()
    return union.buffer(clearance, join_style=BufferJoinStyle.round) if clearance > 0 and not union.is_empty else union


def overcut_region(region, overcut, protected, limit=None):
    """Grow a pocket region into void material only: never into the part section."""
    if overcut <= 0:
        return region
    grown = region.buffer(overcut, join_style=BufferJoinStyle.round)
    if limit is not None:
        grown = grown.intersection(limit)
    if protected is not None and not protected.is_empty:
        grown = grown.difference(protected)
    result = region.union(grown).buffer(0)
    if result.is_empty or not result.is_valid:
        raise ValueError("Overcut produced no valid removal region")
    return result


def _polygons(region):
    if region.geom_type == "Polygon":
        return [region]
    return [p for p in getattr(region, "geoms", ()) if p.geom_type == "Polygon"]


def boundary_paths(region, direction, start_index=0):
    """(points, is_island) contours, in deterministic area order."""
    result = []
    for poly in sorted(_polygons(region), key=lambda p: (-p.area, p.bounds)):
        # Outer region boundary: retained material outside. Holes: retained inside.
        rings = [(poly.exterior, False)] + [(r, True) for r in poly.interiors]
        for ring, island in rings:
            points = np.asarray(ring.coords, float)[:-1]
            if len(points) < 3:
                continue
            points = orient_contour(points, direction, material_inside=island,
                                    index=start_index+len(result))
            result.append((points, island))
    return result


def _nearest_seam(points, position):
    """Rotate/insert a seam at the nearest point on a closed loop, preserving winding."""
    p = np.asarray(points, float)
    delta = np.roll(p, -1, axis=0)-p
    length2 = (delta*delta).sum(axis=1)
    u = np.clip(((position-p)*delta).sum(axis=1)/np.maximum(length2, 1e-20), 0, 1)
    nearest = p+u[:, None]*delta
    distance2 = ((nearest-position)**2).sum(axis=1)
    i = int(np.argmin(distance2))
    if u[i] < 1e-9:
        phased = np.roll(p, -i, axis=0)
    elif u[i] > 1-1e-9:
        phased = np.roll(p, -(i+1), axis=0)
    else:
        phased = np.vstack((nearest[i], p[i+1:], p[:i+1]))
    return float(distance2[i]), phased


def link_contours(contours, loops, radius, allowance, direction, enabled=True, region=None):
    """Nearby loops with short, region-checked same-Z cutting links.

    The caller must reset links at every depth/operation/tool boundary. A link
    stays in the complete cutter-centre region (including radial allowance),
    not merely the XY box. If no direct visible link exists, retract instead
    of crossing an island, wall or disconnected gap. This is not cleared-stock
    routing: a feed link may intentionally cut remaining material.
    """
    if not contours:
        return []
    region = pocket_region(loops) if region is None else region
    centre = region.buffer(-(radius+allowance), join_style=BufferJoinStyle.round)
    # Only a sub-micron tolerance for GEOS boundary roundoff, not extra clearance.
    valid = prep(centre.buffer(1e-7))
    remaining = [np.asarray(p, float) for p in contours]
    first = remaining.pop(0)
    result = [(first, False)]
    position = first[0]     # completed closed loop returns to its seam
    while remaining:
        candidates = []
        for i, p in enumerate(remaining):
            distance, phased = _nearest_seam(p, position)
            candidates.append((distance, i, phased))
        candidates.sort(key=lambda c: (c[0], c[1]))
        chosen = candidates[0]
        permitted = False
        if enabled:
            for candidate in candidates:
                endpoint = candidate[2][0]
                segment = (Point(endpoint) if candidate[0] < 1e-18
                           else LineString((position, endpoint)))
                if valid.covers(segment):
                    chosen, permitted = candidate, True
                    break
        _, index, phased = chosen
        remaining.pop(index)
        if direction == "meander":
            phased = signed_orient(phased, ccw=len(result) % 2 == 0)
            _, phased = _nearest_seam(phased, position)
        result.append((phased, permitted))
        position = phased[0]
    return result


def contour_pocket(loops, radius, allowance, stepover, direction, log=None, region=None):
    """Successive inward offsets of the whole pocket, including island fronts.

    Return closed XY loops. Fronts split into mixed-shape loops as islands meet
    the outside wall. At most 50% diameter spacing avoids a central uncut strip
    when two offset fronts disappear between consecutive sampled distances.
    """
    if not 0 < stepover <= 100:
        raise ValueError("Pocket stepover must be between 0 and 100 percent")
    if radius <= 0 or allowance < 0:
        raise ValueError("Pocket tool radius must be positive and stock allowance nonnegative")
    region = pocket_region(loops) if region is None else region
    inset = radius+allowance
    centre = region.buffer(-inset, join_style=BufferJoinStyle.round)
    if centre.is_empty:
        raise ValueError("Pocket is too small for this tool and stock allowance")
    requested = 2*radius*stepover/100
    spacing = min(requested, radius)
    if requested > spacing+1e-9 and log:
        log("  contour pocket stepover capped at 50% to cover meeting offset fronts")
    result = []
    vertices = 0
    for k in range(10000):
        front = centre if k == 0 else centre.buffer(-k*spacing, join_style=BufferJoinStyle.round)
        if front.is_empty or front.area < 1e-9:
            break
        contours = boundary_paths(front, direction, len(result))
        if not contours:
            break
        for points, _ in contours:
            vertices += len(points)
            if vertices > 2_000_000:
                raise ValueError("Contour pocket has too many vertices; increase stepover or simplify geometry")
            result.append(points)
    else:
        raise ValueError("Contour pocket needs too many offset passes; increase stepover")
    if not result:
        raise ValueError("No wall-parallel pocket paths could be generated")
    return result
