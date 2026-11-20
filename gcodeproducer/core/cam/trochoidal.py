"""Continuous center-out spiral clearing for Pocket and Waterfall."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, polylabel, substring
from shapely.prepared import prep

from gcodeproducer.core.cam.cam_constants import (
    TROCHOID_CHORD_ERROR, TROCHOID_HISTORY_PIECES, TROCHOID_MAX_FRONTS,
    TROCHOID_MIN_SEGMENTS, TROCHOID_MINOR_RATIO_LIMITS,
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


def _pieces(line, component, valid):
    """Clip without adding artificial wall edges; retain unwrapped spiral order."""
    if valid.covers(line):
        return [np.asarray(line.coords)]
    cut = line.intersection(component)
    lines = [cut] if cut.geom_type == 'LineString' else [p for p in getattr(cut, 'geoms', ())
                                                       if p.geom_type == 'LineString']
    if len(lines) > 1:
        cut = linemerge(lines)
        lines = [cut] if cut.geom_type == 'LineString' else list(cut.geoms)
    positioned = []
    for part in lines:
        if part.length <= 1e-6:
            continue
        xy = np.asarray(part.coords)
        a, b = line.project(Point(xy[0])), line.project(Point(xy[-1]))
        positioned.append((a, xy) if a <= b else (b, xy[::-1]))
    return [xy for _, xy in sorted(positioned, key=lambda item: item[0])]


def _wall_route(ring, a, b):
    pa, pb = ring.project(Point(a)), ring.project(Point(b))
    if pa > pb:
        return _wall_route(ring, b, a)[::-1]
    if pb-pa <= ring.length-(pb-pa):
        coords = np.asarray(substring(ring, pa, pb).coords)
    else:
        coords = np.vstack((substring(ring, 0., pa).coords[::-1],
                            substring(ring, pb, ring.length).coords[-2::-1]))
    return np.vstack((a, coords, b))


def _connector(a, b, valid, walls, history):
    if np.linalg.norm(b-a) < 1e-9:
        return np.vstack((a, b))
    direct = LineString((a, b))
    if valid.covers(direct):
        return np.vstack((a, b))
    # Try already traversed points before following the wall. Validation is in
    # the cutter-centre region; the engagement planner still rates any cutting.
    if history:
        points = np.vstack(history)
        lengths = np.linalg.norm(points-a, axis=1) + np.linalg.norm(points-b, axis=1)
        for i in np.argsort(lengths, kind='stable')[:TROCHOID_SEAM_TRIALS]:
            xy = np.vstack((a, points[i], b))
            if valid.covers(LineString(xy)):
                return xy
    for wall in walls:
        if wall.distance(Point(a)) > 1e-7 or wall.distance(Point(b)) > 1e-7:
            continue
        route = _wall_route(wall, a, b)
        if valid.covers(LineString(route)):
            return route
    return None


def _stitch(pieces, walls, valid, diameter, stay_down, budget):
    result, chunks, end, history, used = [], [], None, [], 0
    pieces = list(pieces)
    while pieces:
        index = 0
        if stay_down and end is not None and not pieces[0][1]:
            # Once the spiral is clipped, prefer nearby arcs over crossing the
            # pocket repeatedly to complete all fragments of the same turn.
            candidates = []
            for i, (p, closed) in enumerate(pieces[:TROCHOID_SEAM_TRIALS]):
                if closed:
                    break
                d = np.linalg.norm(p[0]-end)
                candidates.append((d, i))
            for distance, i in sorted(candidates):
                if distance < 1e-9 or valid.covers(LineString((end, pieces[i][0][0]))):
                    index = i
                    break
        xy, closed = pieces.pop(index)
        if closed and end is not None:
            _, xy = _nearest_seam(xy, end)
        if closed:
            xy = np.vstack((xy, xy[0]))
        link = _connector(end, xy[0], valid, walls, history) if end is not None and stay_down else None
        if link is None and chunks:
            result.append(Path('cut', np.vstack(chunks), width=diameter))
            chunks, history = [], []
        if link is not None and len(link) > 2:
            chunks.append(link[1:-1])
            used += len(link)-2
        chunks.append(xy)
        used += len(xy)
        if used > budget:
            raise ValueError('Trochoidal pocket has too many points after linking; simplify geometry')
        end = xy[-1]
        history.append(xy[np.linspace(0, len(xy)-1, min(len(xy), TROCHOID_SEAM_TRIALS), dtype=int)])
        history = history[-TROCHOID_HISTORY_PIECES:]
    if chunks:
        result.append(Path('cut', np.vstack(chunks), width=diameter))
    return result, used


def trochoidal_paths(region, diameter, allowance, stepover, direction, log=None, *, stay_down=True):
    """Grow the radius continuously at cutting Z, then follow the cleanup boundary."""
    centre = region.buffer(-(diameter/2+allowance))
    if centre.is_empty:
        raise ValueError('Trochoidal pocket is too small for this tool and stock allowance')
    spacing = diameter * min(stepover, 50.) / 100
    if log and stepover > 50.:
        log('  Trochoidal stepover capped at 50% for clearing coverage')
    paths, vertices = [], 0
    for component in sorted(polygons(centre), key=lambda p: p.bounds):
        axes = _axes(component)
        seed = component.centroid
        if not component.contains(seed) or seed.distance(component.boundary) < spacing*.5:
            seed = polylabel(component, tolerance=max(TROCHOID_CHORD_ERROR, spacing*.1))
        if not component.contains(seed):
            seed = component.representative_point()
        middle = np.array([seed.x, seed.y])
        local = (np.asarray(component.exterior.coords)-middle) @ np.linalg.inv(axes)
        far = np.linalg.norm(local, axis=1).max()
        first = min(spacing*.25, seed.distance(component.boundary)*.5)
        valid = prep(component.buffer(1e-7))
        # One uninterrupted parametric curve, not closed laps with a step at the seam.
        count = max(1, math.ceil((far-first)/spacing))
        if count > TROCHOID_MAX_FRONTS:
            raise ValueError('Trochoidal pocket needs too many turns; increase stepover')
        sense = -1 if direction == 'conventional' else 1
        turns = []
        for i in range(count):
            bound = first + (i+2)*spacing
            angle_step = 2*math.asin(math.sqrt(min(1., TROCHOID_CHORD_ERROR/(2*bound))))
            n = max(TROCHOID_MIN_SEGMENTS, math.ceil(math.pi/angle_step))
            vertices += n
            if vertices > TROCHOID_POINT_BUDGET:
                raise ValueError('Trochoidal pocket has too many samples; increase stepover or simplify geometry')
            turn = i + np.arange(n+(i == count-1))/n
            angle = sense*2*math.pi*turn
            major = first + spacing*turn
            turns.append(middle + major[:, None]*(np.column_stack((np.cos(angle), np.sin(angle))) @ axes))
        spiral = LineString(np.vstack(turns))
        pieces = [(p, False) for p in _pieces(spiral, component, valid)]
        pieces.extend((p, True) for p, _ in boundary_paths(component, direction, len(paths)))
        walls = [LineString(ring.coords) for ring in (component.exterior, *component.interiors)]
        planned, used = _stitch(pieces, walls, valid, diameter, stay_down, TROCHOID_POINT_BUDGET-vertices)
        vertices += used
        paths.extend(planned)
        if log and len(planned) > 1 and stay_down:
            log(f'  Trochoidal pocket: {len(planned)-1} gap(s) require re-entry; no in-region link was found')
    return paths
