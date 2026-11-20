"""Center-out clearing with wall-adapted, rounded fronts."""
from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Point
from shapely.prepared import prep

from gcodeproducer.core.cam.cam_constants import TROCHOID_POINT_BUDGET, TROCHOID_MAX_FRONTS, TROCHOID_SEAM_TRIALS
from gcodeproducer.core.cam.paths import _nearest_seam, boundary_paths, orient_contour
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.jobs.path import Path


def _rounded_front(front, rounding):
    """Only round inside the front; retain a narrow piece if it cannot be rounded."""
    for part in polygons(front):
        opened = part.buffer(-rounding, quad_segs=4).buffer(rounding, quad_segs=4).intersection(part)
        if opened.is_empty:
            # A compact core can start on a circle. Keep the original front
            # for a long narrow core that a small circle would not cover.
            lo_x, lo_y, hi_x, hi_y = part.bounds
            if max(hi_x-lo_x, hi_y-lo_y) <= 2*rounding:
                seed = part.representative_point()
                opened = seed.buffer(seed.distance(part.boundary), quad_segs=4)
        yield part if opened.is_empty else opened


def nearby_seams(points, previous, radius):
    """Try a bounded set of nearby, spatially distinct vertices on a closed front."""
    distances = np.linalg.norm(points-previous, axis=1)
    selected = []
    for i in np.argsort(distances, kind='stable'):
        if distances[i] > 2*radius:
            break
        if i == 0 or any(np.linalg.norm(points[i]-points[j]) < radius*.15 for j in selected):
            continue
        selected.append(i)
        yield i
        if len(selected) == TROCHOID_SEAM_TRIALS:
            break


def trochoidal_paths(region, diameter, allowance, stepover, direction, log=None, *, stay_down=True):
    """Work outward from inset cores, keeping moves close to the preceding cut."""
    centre = region.buffer(-(diameter/2+allowance))
    if centre.is_empty:
        raise ValueError("Trochoidal pocket is too small for this tool and stock allowance")
    spacing = diameter * min(stepover, 50.) / 100
    if log and stepover > 50.:
        log("  Trochoidal stepover capped at 50% for clearing coverage")
    paths, vertices = [], 0
    for component in sorted(polygons(centre), key=lambda p: p.bounds):
        fronts = []
        for i in range(TROCHOID_MAX_FRONTS):
            front = component if i == 0 else component.buffer(-i*spacing)
            if front.is_empty:
                break
            shapes = [front] if i == 0 else _rounded_front(front, spacing*.25)
            rings = [(points, island) for shape in shapes for points, island in boundary_paths(shape, direction)]
            vertices += sum(len(points) for points, _ in rings)
            if vertices > TROCHOID_POINT_BUDGET:
                raise ValueError("Trochoidal clearing has too many points; increase stepover or simplify geometry")
            fronts.append(rings)
        else:
            raise ValueError("Trochoidal clearing needs too many fronts; increase stepover")
        previous = None
        valid = prep(component.buffer(1e-7))
        rings = [ring for front in reversed(fronts) for ring in front]
        while rings:
            index, points, linked = 0, rings[0][0], False
            if previous is not None and stay_down:
                # Prefer continuing outward locally rather than jumping across the
                # pocket to cut every disconnected front at the same inset.
                seams = [(*_nearest_seam(p, previous), i) for i, (p, _) in enumerate(rings[:TROCHOID_SEAM_TRIALS])]
                for d, p, k in sorted(seams, key=lambda s: (s[0], s[2])):
                    if d > diameter**2:
                        break
                    segment = Point(p[0]) if d < 1e-18 else LineString((previous, p[0]))
                    if valid.covers(segment):
                        linked, points, index = True, p, k
                        break
            _, island = rings.pop(index)
            points = orient_contour(points, direction, material_inside=island, index=len(paths))
            if previous is not None:
                _, points = _nearest_seam(points, previous)
            paths.append(Path("cut", points, closed=True, width=diameter, stay_down=linked,
                              stay_down_from=tuple(previous) if linked else None))
            previous = points[0]
    return paths
