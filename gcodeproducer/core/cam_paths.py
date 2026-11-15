"""Wall-parallel CAM clearing with topology-aware cutter-centre regions.

Shapely/GEOS offsets split/merge contours where advancing fronts meet walls
or islands. Unlike independent polygon offsets, this cannot knowingly route a
closed clearing loop through an island when a square meets a circle.
Output remains polygonal G1 paths from STL, not fitted controller arcs.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon
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


def contour_pocket(loops, radius, allowance, stepover, direction, log=None):
    """Successive inward offsets of the whole pocket, including island fronts.

    Return closed XY loops. Fronts split into mixed-shape loops as islands meet
    the outside wall. At most 50% diameter spacing avoids a central uncut strip
    when two offset fronts disappear between consecutive sampled distances.
    """
    if not 0 < stepover <= 100:
        raise ValueError("Pocket stepover must be between 0 and 100 percent")
    if radius <= 0 or allowance < 0:
        raise ValueError("Pocket tool radius must be positive and stock allowance nonnegative")
    region = pocket_region(loops)
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
