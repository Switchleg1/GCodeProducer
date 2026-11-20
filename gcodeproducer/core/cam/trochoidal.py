"""Continuous center-out spiral clearing for Pocket and Waterfall."""
from __future__ import annotations

import math

import numpy as np
from shapely import union_all
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, polylabel, substring
from shapely.prepared import prep

from gcodeproducer.core.cam.cam_constants import (
    TROCHOID_CHORD_ERROR, TROCHOID_CORNER_ARC_DIAMETERS, TROCHOID_HISTORY_PIECES, TROCHOID_MAX_FRONTS,
    TROCHOID_MIN_SEGMENTS, TROCHOID_MINOR_RATIO_LIMITS,
    TROCHOID_POINT_BUDGET, TROCHOID_RETURN_DIAMETERS, TROCHOID_SEAM_TRIALS,
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


def _connector(a, b, valid, walls, history, swept, radius, spacing):
    if np.linalg.norm(b-a) < 1e-9:
        return np.vstack((a, b))
    def permitted(xy):
        line = LineString(xy)
        if not valid.covers(line):
            return False
        # Allow a local roll-on into the next cut. A longer reposition must
        # carry the whole cutter inside material swept by prior cuts until
        # the final stepover. In-bounds alone does not mean cleared.
        if line.length <= spacing:
            return True
        transit = substring(line, 0., line.length-spacing)
        return swept.covers(transit.buffer(radius))

    direct = np.vstack((a, b))
    if permitted(direct):
        return direct
    # Try already traversed points before following a cleared wall section.
    if history:
        points = np.vstack(history)
        lengths = np.linalg.norm(points-a, axis=1) + np.linalg.norm(points-b, axis=1)
        for i in np.argsort(lengths, kind='stable')[:TROCHOID_SEAM_TRIALS]:
            xy = np.vstack((a, points[i], b))
            if permitted(xy):
                return xy
    for wall in walls:
        if wall.distance(Point(a)) > 1e-7 or wall.distance(Point(b)) > 1e-7:
            continue
        route = _wall_route(wall, a, b)
        if permitted(route):
            return route
    return None


def _return_along_cut(trace, target, valid, spacing):
    """Retrace a verified cut to a nearby entry rather than slotting across it."""
    if trace is None or trace.length < 1e-9:
        return None
    target_point = Point(target)
    at = trace.project(target_point)
    near = trace.interpolate(at)
    distance = near.distance(target_point)
    if distance > spacing or (distance > 1e-9 and not valid.covers(LineString((near.coords[0], target)))):
        return None
    back = substring(trace, at, trace.length)
    return np.vstack((np.asarray(back.coords)[::-1], target))


def _stitch(pieces, walls, valid, diameter, spacing, stay_down, budget):
    result, chunks, end, history, used = [], [], None, [], 0
    radius = diameter/2
    swept = Point().buffer(0)
    pieces = list(pieces)
    while pieces:
        index, link = 0, None
        covered = prep(swept.buffer(1e-6)) if stay_down and end is not None else None
        if covered is not None and not pieces[0][1]:
            # Once the spiral is clipped, prefer nearby arcs over crossing the
            # pocket repeatedly to complete all fragments of the same turn.
            candidates = []
            for i, (p, closed) in enumerate(pieces[:TROCHOID_SEAM_TRIALS]):
                if closed:
                    break
                d = np.linalg.norm(p[0]-end)
                candidates.append((d, i))
            for _, i in sorted(candidates):
                link = _connector(end, pieces[i][0][0], valid, walls, history, covered, radius, spacing)
                if link is not None:
                    index = i
                    break
        trace = None
        if link is None and covered is not None and chunks:
            # These chunks are one connected, already cut path. Limit the
            # search to its tail to avoid retracing an entire pocket.
            coords = np.vstack(chunks[-TROCHOID_HISTORY_PIECES:])
            if len(coords) >= 2:
                trace = LineString(coords)
                trace = substring(trace, max(0., trace.length-TROCHOID_RETURN_DIAMETERS*diameter), trace.length)
            if trace is not None and not pieces[0][1]:
                returns = []
                for i, (p, closed) in enumerate(pieces[:TROCHOID_SEAM_TRIALS]):
                    if closed:
                        break
                    route = _return_along_cut(trace, p[0], valid, spacing)
                    if route is not None:
                        returns.append((LineString(route).length, i, route))
                if returns:
                    _, index, link = min(returns, key=lambda item: item[:2])
        xy, closed = pieces.pop(index)
        if closed and end is not None:
            _, xy = _nearest_seam(xy, end)
        if closed:
            xy = np.vstack((xy, xy[0]))
        if link is None and covered is not None and closed:
            link = _connector(end, xy[0], valid, walls, history, covered, radius, spacing)
            if link is None:
                link = _return_along_cut(trace, xy[0], valid, spacing)
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
        if stay_down:
            actual = xy if link is None else np.vstack((link[:-1], xy))
            swept = swept.union(LineString(actual).buffer(radius))
        end = xy[-1]
        history.append(xy[np.linspace(0, len(xy)-1, min(len(xy), TROCHOID_SEAM_TRIALS), dtype=int)])
        history = history[-TROCHOID_HISTORY_PIECES:]
    if chunks:
        result.append(Path('cut', np.vstack(chunks), width=diameter))
    return result, used


def _spiral(component, spacing, sense, budget):
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
    count = max(1, math.ceil((far-first)/spacing))
    if count > TROCHOID_MAX_FRONTS:
        raise ValueError('Trochoidal pocket needs too many turns; increase stepover')
    turns, vertices = [], 0
    for i in range(count):
        bound = first + (i+2)*spacing
        angle_step = 2*math.asin(math.sqrt(min(1., TROCHOID_CHORD_ERROR/(2*bound))))
        n = max(TROCHOID_MIN_SEGMENTS, math.ceil(math.pi/angle_step))
        vertices += n
        if vertices > budget:
            raise ValueError('Trochoidal pocket has too many samples; increase stepover or simplify geometry')
        turn = i + np.arange(n+(i == count-1))/n
        angle = sense*2*math.pi*turn
        major = first + spacing*turn
        turns.append(middle + major[:, None]*(np.column_stack((np.cos(angle), np.sin(angle))) @ axes))
    return LineString(np.vstack(turns)), vertices


def _corner_spirals(component, arcs, walls, radius, spacing, sense, budget):
    """Replace short clipped arcs with local spirals in the uncovered corners."""
    major, small = [], []
    for i, p in enumerate(arcs):
        (major if i == 0 or LineString(p).length >= 2*radius*TROCHOID_CORNER_ARC_DIAMETERS else small).append(p)
    if not small:
        return arcs, 0
    # Account for the final wall pass when deciding which spots need rest cuts.
    # Do not count that pass as cleared stock when routing a move to a corner.
    coverage = union_all([LineString(p).buffer(radius) for p in major] + [w.buffer(radius) for w in walls])
    residual = component.difference(coverage)
    local, used = [], 0
    for rest in sorted(polygons(residual), key=lambda p: (-p.area, p.bounds)):
        if rest.difference(coverage).area <= 1e-8:
            continue
        domain = rest.buffer(spacing).intersection(component)
        for part in polygons(domain):
            spiral, n = _spiral(part, spacing, sense, budget-used)
            used += n
            for p in _pieces(spiral, part, prep(part.buffer(1e-7))):
                sweep = LineString(p).buffer(radius)
                if sweep.intersection(residual).difference(coverage).area > 1e-8:
                    local.append(p)
                    coverage = coverage.union(sweep)
    # Preserve coverage in awkward residual slivers a local spiral couldn't reach.
    for p in small:
        sweep = LineString(p).buffer(radius)
        if sweep.intersection(residual).difference(coverage).area > 1e-8:
            local.append(p)
            coverage = coverage.union(sweep)
    return major + local, used


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
        valid = prep(component.buffer(1e-7))
        sense = -1 if direction == 'conventional' else 1
        spiral, sampled = _spiral(component, spacing, sense, TROCHOID_POINT_BUDGET-vertices)
        vertices += sampled
        walls = [LineString(ring.coords) for ring in (component.exterior, *component.interiors)]
        arcs, sampled = _corner_spirals(component, _pieces(spiral, component, valid), walls,
                                        diameter/2, spacing, sense, TROCHOID_POINT_BUDGET-vertices)
        vertices += sampled
        pieces = [(p, False) for p in arcs]
        pieces.extend((p, True) for p, _ in boundary_paths(component, direction, len(paths)))
        planned, used = _stitch(pieces, walls, valid, diameter, spacing, stay_down, TROCHOID_POINT_BUDGET-vertices)
        vertices += used
        paths.extend(planned)
        if log and len(planned) > 1 and stay_down:
            log(f'  Trochoidal pocket: {len(planned)-1} gap(s) require re-entry; no cleared route to a local approach was found')
    return paths
