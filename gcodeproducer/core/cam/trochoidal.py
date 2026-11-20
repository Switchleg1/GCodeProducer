"""Center-out elliptical clearing for Pocket and Waterfall."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, polylabel
from shapely.prepared import prep

from gcodeproducer.core.cam.cam_constants import (
    TROCHOID_CHORD_ERROR, TROCHOID_MAX_FRONTS, TROCHOID_MIN_SEGMENTS, TROCHOID_MINOR_RATIO_LIMITS,
    TROCHOID_POINT_BUDGET, TROCHOID_SEAM_TRIALS,
)
from gcodeproducer.core.cam.paths import _nearest_seam, boundary_paths
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.jobs.path import Path


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


def _axes(component):
    corners = np.asarray(component.minimum_rotated_rectangle.exterior.coords)[:3]
    edges = np.diff(corners, axis=0)
    lengths = np.linalg.norm(edges, axis=1)
    major = int(np.argmax(lengths))
    u = edges[major]/lengths[major]
    if u[0] < 0 or (u[0] == 0 and u[1] < 0):
        u = -u
    ratio = float(np.clip(lengths.min()/lengths.max(), *TROCHOID_MINOR_RATIO_LIMITS))
    return np.array([u, ratio*np.array([-u[1], u[0]])])


def _pieces(points, component, valid, middle, sense):
    line = LineString(np.vstack((points, points[0])))
    if valid.covers(line):
        return [(points, True)]
    clipped = line.intersection(component)
    if clipped.geom_type == 'MultiLineString':
        clipped = linemerge(clipped)
    lines = [clipped] if clipped.geom_type == 'LineString' else getattr(clipped, 'geoms', ())
    pieces = []
    for part in lines:
        if part.geom_type != 'LineString' or part.length <= 1e-6:
            continue
        xy = np.asarray(part.coords)
        p = xy - middle
        turn = (p[:-1, 0]*p[1:, 1] - p[:-1, 1]*p[1:, 0]).sum()
        pieces.append((xy if turn*sense > 0 else xy[::-1], False))
    return sorted(pieces, key=lambda p: tuple(p[0][0]))


def _append_band(paths, band, previous, valid, diameter, stay_down):
    """Prefer short validated links without moving a pass ahead of its inner band."""
    while band:
        index = 0
        points, closed = band[0]
        linked = False
        if previous is not None:
            starts = []
            for i, (p, is_closed) in enumerate(band[:TROCHOID_SEAM_TRIALS]):
                if is_closed:
                    d, p = _nearest_seam(p, previous)
                else:
                    d = float(np.sum((p[0]-previous)**2))
                starts.append((d, i, p, is_closed))
            starts.sort(key=lambda item: item[:2])
            _, index, points, closed = starts[0]
            if stay_down:
                for distance, i, p, is_closed in starts:
                    if distance > diameter**2:
                        break
                    sweep = Point(p[0]) if distance < 1e-18 else LineString((previous, p[0]))
                    if valid.covers(sweep):
                        index, points, closed, linked = i, p, is_closed, True
                        break
        band.pop(index)
        paths.append(Path('cut', points, closed=closed, width=diameter, stay_down=linked,
                          stay_down_from=tuple(previous) if linked else None))
        previous = points[0] if closed else points[-1]
    return previous


def trochoidal_paths(region, diameter, allowance, stepover, direction, log=None, *, stay_down=True):
    """Concentric ellipse sweeps, clipped at walls and islands, then boundary cleanup."""
    centre = region.buffer(-(diameter/2+allowance))
    if centre.is_empty:
        raise ValueError('Trochoidal pocket is too small for this tool and stock allowance')
    spacing = diameter * min(stepover, 50.) / 100
    if log and stepover > 50.:
        log('  Trochoidal stepover capped at 50% for clearing coverage')
    paths, vertices = [], 0
    for component in sorted(polygons(centre), key=lambda p: p.bounds):
        axes = _axes(component)
        seed = polylabel(component, tolerance=max(TROCHOID_CHORD_ERROR, spacing*.1))
        if not component.contains(seed):
            seed = component.representative_point()
        middle = np.array([seed.x, seed.y])
        local = (np.asarray(component.exterior.coords)-middle) @ np.linalg.inv(axes)
        far = np.linalg.norm(local, axis=1).max()
        first = min(spacing, seed.distance(component.boundary)*.5)
        valid = prep(component.buffer(1e-7))
        previous = None
        count = math.floor((far-first)/spacing) + 1
        if count > TROCHOID_MAX_FRONTS:
            raise ValueError('Trochoidal pocket needs too many ellipses; increase stepover')
        for i in range(count):
            major = first + i*spacing
            sense = -1 if direction == 'conventional' or (direction == 'meander' and i % 2) else 1
            # The affine map scales the unit-circle chord error by at most the major radius.
            angle_step = 2*math.asin(math.sqrt(min(1., TROCHOID_CHORD_ERROR/(2*major))))
            n = max(TROCHOID_MIN_SEGMENTS, math.ceil(math.pi/angle_step))
            vertices += n
            if vertices > TROCHOID_POINT_BUDGET:
                raise ValueError('Trochoidal pocket has too many samples; increase stepover or simplify geometry')
            angle = np.arange(n) * (sense*2*math.pi/n)
            ring = middle + major*(np.column_stack((np.cos(angle), np.sin(angle))) @ axes)
            band = _pieces(ring, component, valid, middle, sense)
            previous = _append_band(paths, band, previous, valid, diameter, stay_down)
        walls = [(p, True) for p, _ in boundary_paths(component, direction, len(paths))]
        vertices += sum(len(p) for p, _ in walls)
        if vertices > TROCHOID_POINT_BUDGET:
            raise ValueError('Trochoidal pocket has too many boundary points; simplify geometry')
        _append_band(paths, walls, previous, valid, diameter, stay_down)
    return paths
