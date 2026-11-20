"""Center-out circular clearing for Pocket and Waterfall."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import polylabel
from shapely.prepared import prep

from gcodeproducer.core.cam.cam_constants import (
    TROCHOID_CHORD_ERROR, TROCHOID_MIN_SEGMENTS, TROCHOID_POINT_BUDGET,
)
from gcodeproducer.core.cam.paths import _nearest_seam, boundary_paths
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.jobs.path import Path


def _circle_pieces(points, component, valid, origin, sense):
    ring = LineString(np.vstack((points, points[0])))
    if valid.covers(ring):
        yield points, True
        return
    # Keep the circle's chords, not a polygon intersection boundary (which
    # would insert straight wall chords between separate arcs).
    result = ring.intersection(component)
    if result.geom_type == "MultiLineString":
        from shapely.ops import linemerge
        result = linemerge(result)
    lines = [result] if result.geom_type == "LineString" else getattr(result, "geoms", ())
    pieces = []
    for line in lines:
        if line.geom_type != "LineString" or line.length <= 1e-6:
            continue
        xy = np.asarray(line.coords)
        rel = xy - origin
        turn = (rel[:-1, 0]*rel[1:, 1] - rel[:-1, 1]*rel[1:, 0]).sum()
        pieces.append(xy if turn * sense >= 0 else xy[::-1])
    for xy in sorted(pieces, key=lambda p: tuple(p[0])):
        yield xy, False


def _ordered_paths(component, diameter, spacing, direction, stay_down, budget):
    middle = polylabel(component, tolerance=max(TROCHOID_CHORD_ERROR, spacing*.1))
    if not component.contains(middle):
        middle = component.representative_point()
    origin = np.array([middle.x, middle.y])
    minx, miny, maxx, maxy = component.bounds
    far = math.hypot(max(abs(minx-middle.x), abs(maxx-middle.x)),
                     max(abs(miny-middle.y), abs(maxy-middle.y)))
    first = min(spacing, component.boundary.distance(middle) * .5)
    count = math.floor((far-first)/spacing) + 1
    # polylabel starts inside the deepest available space even for concave
    # pockets or islands; the first ring's cutter sweep covers that centre.
    if count * TROCHOID_MIN_SEGMENTS > budget:
        raise ValueError("Circular clearing needs too many rings; increase stepover or split the area")
    valid = prep(component.buffer(1e-7))
    paths, previous, samples = [], None, 0

    def append(points, closed):
        nonlocal previous
        start = points[0]
        linked = False
        if stay_down and previous is not None:
            distance = float(np.linalg.norm(previous - start))
            if distance <= diameter:
                segment = Point(start) if distance < 1e-9 else LineString((previous, start))
                linked = valid.covers(segment)
        paths.append(Path("cut", points, closed=closed, width=diameter, stay_down=linked,
                          stay_down_from=tuple(previous) if linked else None))
        previous = start if closed else points[-1]

    for i in range(count):
        radius = first + i * spacing
        half_chord = math.sqrt(min(1., TROCHOID_CHORD_ERROR/(2*radius)))
        n = max(TROCHOID_MIN_SEGMENTS, math.ceil(math.pi/(2*math.asin(half_chord))))
        samples += n
        if samples > budget:
            raise ValueError("Circular clearing has too many arc samples; increase stepover or split the area")
        sense = -1 if direction == "conventional" or (direction == "meander" and i % 2) else 1
        phase = math.atan2(previous[1]-origin[1], previous[0]-origin[0]) if previous is not None else 0.
        angle = phase + np.arange(n) * (sense * 2 * math.pi / n)
        ring = origin + radius*np.column_stack((np.cos(angle), np.sin(angle)))
        for points, closed in _circle_pieces(ring, component, valid, origin, sense):
            append(points, closed)
    for wall, _ in boundary_paths(component, direction, len(paths)):
        samples += len(wall)
        if samples > budget:
            raise ValueError("Circular clearing has too many points; increase stepover or simplify geometry")
        if previous is not None:
            _, wall = _nearest_seam(wall, previous)
        append(wall, True)
    return paths, samples


def trochoidal_paths(region, diameter, allowance, stepover, direction, log=None, *, stay_down=True):
    """Small circles first, then expanding circles/arcs and final boundary passes."""
    centre = region.buffer(-(diameter/2+allowance))
    if centre.is_empty:
        raise ValueError("Trochoidal pocket is too small for this tool and stock allowance")
    spacing = diameter * min(stepover, 50.) / 100
    if log and stepover > 50.:
        log("  Trochoidal stepover capped at 50% for clearing coverage")
    paths, budget = [], TROCHOID_POINT_BUDGET
    for component in sorted(polygons(centre), key=lambda p: p.bounds):
        area, used = _ordered_paths(component, diameter, spacing, direction, stay_down, budget)
        paths.extend(area)
        budget -= used
    return paths
