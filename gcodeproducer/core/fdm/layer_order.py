"""Print order within one FDM layer that keeps travel short.

Stages append paths feature by feature across the whole layer (every inner
wall, then every outer wall, then fill...). Printed in that order the head
crosses the plate several times per layer and hops between unrelated loops.
Here the layer is reorganised:

1. paths outside any part island (skirt, brim, support) keep their order and
   print first, as before;
2. part islands are visited nearest-first;
3. inside an island the walls print as *wall groups* - each outer loop with
   the inner walls nearest to it (inner first, then the outer, as before) -
   visited nearest-first, so a feature such as one fan is completed before
   moving on;
4. then the island's bridges (one fan change), then all its other fill
   (sparse, solid, gap fill) nearest first, entering each line at its nearer
   end and each loop where it will start.

Closed loops are entered where the emitter will start them: at the point
closest to the seam target (``xy``), at their first point (``origin``), or
at the point closest to the head (``nearest``).
"""
from __future__ import annotations

import numpy as np
import shapely

from gcodeproducer.core.fdm.fdm_constants import (LAYER_ORDER_FILL_FEATURES, LAYER_ORDER_LOOP_SAMPLES,
                                                   WALL_FEATURES)
from gcodeproducer.core.fdm.path_order import closed_loop


def _entries(path, seam, target):
    """Candidate start points of a path: ``(points (k, 2), reverse flags (k,))``."""
    pts = np.asarray(path.points, float)[:, :2]
    if not path.closed:
        return pts[[0, -1]], np.array([False, True])
    if path.feature in WALL_FEATURES and seam == "xy":
        return closed_loop(pts, target)[:1], np.array([False])
    if path.feature in WALL_FEATURES and seam == "origin":
        return pts[:1], np.array([False])
    step = max(1, len(pts) // LAYER_ORDER_LOOP_SAMPLES)
    sample = pts[::step]
    return sample, np.zeros(len(sample), bool)


def _nearest_first(paths, head, seam, target):
    """Greedy nearest-neighbour order; returns ``(ordered paths, head after them)``."""
    if len(paths) <= 1:
        if paths:
            pts, _ = _entries(paths[0], seam, target)
            head = _exit(paths[0], int(np.argmin(((pts - head)**2).sum(1))), pts, head)
        return list(paths), head
    points, owner, reverse = [], [], []
    for i, path in enumerate(paths):
        pts, rev = _entries(path, seam, target)
        points.append(pts)
        owner.append(np.full(len(pts), i))
        reverse.append(rev)
    points = np.concatenate(points)
    owner = np.concatenate(owner)
    reverse = np.concatenate(reverse)
    alive = np.ones(len(points), bool)
    out = []
    head = np.asarray(head, float)
    for _ in range(len(paths)):
        d = ((points - head)**2).sum(axis=1)
        d[~alive] = np.inf
        k = int(d.argmin())
        i = int(owner[k])
        alive[owner == i] = False
        path = paths[i]
        out.append(path)
        if path.closed:
            head = points[k]
        else:
            ends = np.asarray(path.points, float)[[0, -1], :2]
            head = ends[0] if reverse[k] else ends[1]
    return out, head


def _exit(path, k, pts, head):
    if path.closed:
        return pts[k]
    ends = np.asarray(path.points, float)[[0, -1], :2]
    return ends[1] if k == 0 else ends[0]


def _wall_groups(walls):
    """Each closed outer loop with the other wall paths nearest to it."""
    outers = [i for i, p in enumerate(walls) if p.feature == "outer_perimeter" and p.closed]
    if not outers:
        return [walls]
    rings = [shapely.linearrings(np.asarray(walls[i].points, float)[:, :2]) for i in outers]
    tree = shapely.STRtree(rings)
    groups = {i: [] for i in range(len(outers))}
    others = [i for i in range(len(walls)) if i not in set(outers)]
    if others:
        # a wall's start point is a line width or so from the outer wall it belongs to
        reps = shapely.points([np.asarray(walls[i].points, float)[0, :2] for i in others])
        (src, dst) = tree.query_nearest(reps, all_matches=False)
        for s, d in zip(src.tolist(), dst.tolist()):
            groups[d].append(others[s])
    return [[walls[i] for i in members] + [walls[outers[g]]] for g, members in groups.items()]


def _print_walls(walls, head, seam, target):
    groups = _wall_groups(walls)
    if len(groups) == 1:
        return _group_order(groups[0], head, seam, target)
    # visit groups nearest-first by their entry points
    out = []
    pending = list(range(len(groups)))
    entries = []
    for g in groups:
        pts = np.concatenate([_entries(p, seam, target)[0] for p in g])
        entries.append(pts)
    head = np.asarray(head, float)
    while pending:
        best = min(pending, key=lambda g: float(((entries[g] - head)**2).sum(1).min()))
        pending.remove(best)
        ordered, head = _group_order(groups[best], head, seam, target)
        out.extend(ordered)
    return out, head


def _group_order(group, head, seam, target):
    inner = [p for p in group if p.feature != "outer_perimeter"]
    outer = [p for p in group if p.feature == "outer_perimeter"]
    first, head = _nearest_first(inner, head, seam, target)
    second, head = _nearest_first(outer, head, seam, target)
    return first + second, head


def _island_of(paths, islands):
    """Island index per path (-1 = outside every island)."""
    owner = np.full(len(paths), -1)
    if not islands or not paths:
        return owner
    reps = shapely.points([np.asarray(p.points, float)[0, :2] for p in paths])
    tree = shapely.STRtree(islands)
    src, dst = tree.query(reps, predicate="intersects")
    owner[src] = dst
    missing = np.flatnonzero(owner < 0)
    if len(missing):
        # paths starting just outside an island (rounding) still belong to the nearest one
        src, dst = tree.query_nearest(reps[missing], all_matches=False, max_distance=1.)
        owner[missing[src]] = dst
    return owner


def order_layer(paths, head, islands, seam="nearest", target=(0., 0.), mixed_fill=True):
    """Paths of one layer in travel-saving order (see module docstring).

    ``islands`` are the layer's part polygons; ``mixed_fill`` False keeps the
    fill features in their original sequence (each still ordered nearest first).
    """
    target = np.asarray(target, float)
    part = [p.feature in WALL_FEATURES or p.feature in LAYER_ORDER_FILL_FEATURES for p in paths]
    owner = _island_of([p for p, inside in zip(paths, part) if inside], islands)
    out = [p for p, inside in zip(paths, part) if not inside]       # skirt, brim, support...
    if out:
        last = out[-1]
        pts = np.asarray(last.points, float)
        head = pts[0, :2] if last.closed else pts[-1, :2]
    members = {}
    for path, isl in zip([p for p, inside in zip(paths, part) if inside], owner.tolist()):
        members.setdefault(isl, []).append(path)
    pending = list(members)
    head = np.asarray(head, float)
    while pending:
        def distance(isl):
            pts = np.concatenate([_entries(p, seam, target)[0] for p in members[isl]])
            return float(((pts - head)**2).sum(1).min())
        isl = min(pending, key=distance)
        pending.remove(isl)
        group = members[isl]
        walls = [p for p in group if p.feature in WALL_FEATURES]
        fill = [p for p in group if p.feature not in WALL_FEATURES]
        ordered, head = _print_walls(walls, head, seam, target) if walls else ([], head)
        out.extend(ordered)
        # bridges together first: they switch the fan and anchor on the walls just printed
        ordered, head = _nearest_first([p for p in fill if p.feature == "bridge"], head, seam, target)
        out.extend(ordered)
        fill = [p for p in fill if p.feature != "bridge"]
        if mixed_fill:
            ordered, head = _nearest_first(fill, head, seam, target)
            out.extend(ordered)
        else:
            for feature in dict.fromkeys(p.feature for p in fill):
                ordered, head = _nearest_first([p for p in fill if p.feature == feature], head, seam, target)
                out.extend(ordered)
    return out
