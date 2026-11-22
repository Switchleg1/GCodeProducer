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
                                                   LAYER_ORDER_RELOCATE_MIN, LAYER_ORDER_RELOCATE_PASSES,
                                                   WALL_FEATURES)
from gcodeproducer.core.fdm.fill_runs import build_runs, run_entries
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
    first_entry = np.searchsorted(owner, np.arange(len(paths)))
    last_entry = np.r_[first_entry[1:], len(owner)]
    alive = np.ones(len(points), bool)
    out = []
    head = np.asarray(head, float)
    for _ in range(len(paths)):
        d = ((points - head)**2).sum(axis=1)
        d[~alive] = np.inf
        k = int(d.argmin())
        i = int(owner[k])
        alive[first_entry[i]:last_entry[i]] = False
        path = paths[i]
        out.append(path)
        if path.closed:
            head = points[k]
        else:
            ends = np.asarray(path.points, float)[[0, -1], :2]
            head = ends[0] if reverse[k] else ends[1]
    return out, head


def _order_fill(fill, head, seam, target):
    """Fill in runs: zig-zag blocks of parallel lines plus single paths, nearest first.

    At a fork - the run just finished continues into several runs, e.g. on
    both sides of a hole - the shortest of those runs is printed first, so
    the way back to the longer side is short and no stragglers are left.
    """
    runs, singles = build_runs(fill)
    points, exits, owner, choice = [], [], [], []
    for r, run in enumerate(runs):
        for entry, exit_, seq, forward in run_entries(run):
            points.append(entry)
            exits.append(exit_)
            owner.append(r)
            choice.append((seq, forward))
    for n, path in enumerate(singles):
        pts, rev = _entries(path, seam, target)
        ends = np.asarray(path.points, float)[[0, -1], :2]
        for k in range(len(pts)):
            points.append(pts[k])
            exits.append(pts[k] if path.closed else (ends[0] if rev[k] else ends[1]))
            owner.append(len(runs) + n)
            choice.append(([path], True))
    head = np.asarray(head, float)
    if not points:
        return [], head
    points = np.asarray(points, float)
    exits = np.asarray(exits, float)
    owner = np.asarray(owner)
    alive = np.ones(len(points), bool)
    done = np.zeros(len(runs) + len(singles), bool)
    start = head
    order = []
    branches = ()
    while alive.any():
        d = ((points - head)**2).sum(axis=1)
        d[~alive] = np.inf
        options = [r for r in branches if not done[r]]
        if len(options) >= 2:
            shortest = min(options, key=lambda r: runs[r]["length"])
            d = np.where(owner == shortest, d, np.inf)
        k = int(d.argmin())
        item = int(owner[k])
        alive[owner == item] = False
        done[item] = True
        order.append(k)
        head = exits[k]
        branches = ()
        if item < len(runs):
            _, forward = choice[k]
            branches = runs[item]["next"] if forward else runs[item]["prev"]
    order = _relocate(order, points, exits, owner, start)
    out = [path for k in order for path in choice[k][0]]
    return out, exits[order[-1]]


def _relocate(order, points, exits, owner, start):
    """Move stragglers to where they cost least (Or-opt with one item, any entry).

    Greedy nearest-neighbour leaves a few paths behind that it must come back
    for. Each item is tried at every gap of the sequence, entered at each of
    its entries; a move is kept when it shortens the total travel.
    """
    rows = {}
    for k, o in enumerate(owner.tolist()):
        rows.setdefault(o, []).append(k)
    rows = {o: np.asarray(v) for o, v in rows.items()}
    order = list(order)
    for _ in range(LAYER_ORDER_RELOCATE_PASSES):
        moved = False
        seq = np.asarray(order)
        prev_exit = np.vstack((start[None], exits[seq[:-1]]))
        hop = np.hypot(*(points[seq] - prev_exit).T)
        nxt_hop = np.r_[hop[1:], 0.]
        for p in np.argsort(-(hop + nxt_hop)).tolist():
            if len(order) < 3:
                break
            seq = np.asarray(order)
            k = order[p] if p < len(order) else None
            if k is None:
                continue
            prev_e = start if p == 0 else exits[order[p - 1]]
            nxt = points[order[p + 1]] if p + 1 < len(order) else None
            gain = np.hypot(*(points[k] - prev_e))
            if nxt is not None:
                gain += np.hypot(*(nxt - exits[k])) - np.hypot(*(nxt - prev_e))
            rest = np.delete(seq, p)
            slot_prev = np.vstack((start[None], exits[rest]))                 # gap q sits after rest[q-1]
            slot_next = np.vstack((points[rest], np.full((1, 2), np.nan)))
            base = np.hypot(*(slot_next - slot_prev).T)
            base = np.where(np.isnan(base), 0., base)
            cand = rows[int(owner[k])]
            e_in = points[cand]
            e_out = exits[cand]
            cost = (np.hypot(*(slot_prev[:, None, :] - e_in[None]).transpose(2, 0, 1))
                    + np.nan_to_num(np.hypot(*(e_out[None] - slot_next[:, None, :]).transpose(2, 0, 1)))
                    - base[:, None])
            q, r = np.unravel_index(int(np.argmin(cost)), cost.shape)
            if cost[q, r] < gain - LAYER_ORDER_RELOCATE_MIN:
                order = rest.tolist()
                order.insert(int(q), int(cand[r]))
                moved = True
        if not moved:
            break
    return order


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
    """Inner walls nearest first across all wall groups; each group's outer wall right after
    its last inner wall.

    An outer wall waits for all inner walls beside it (inner-first printing),
    but the inner walls are not tied to their group's turn: a large outer
    loop whose inner walls are spread over the part (split at narrow necks)
    picks them up as the head passes, instead of crossing the part for them.
    Outer walls with no inner walls join the same nearest-first walk.
    """
    groups = _wall_groups(walls)
    items, owner = [], []                  # inner walls, and outer walls of groups without any
    for g, group in enumerate(groups):
        inner = [p for p in group if p.feature != "outer_perimeter"]
        for p in inner or [p for p in group if p.feature == "outer_perimeter"]:
            items.append(p)
            owner.append(g if inner else -1)
    remaining = np.bincount(np.asarray([g for g in owner if g >= 0], int), minlength=len(groups))
    out = []
    head = np.asarray(head, float)
    if not items:
        return out, head
    points, rows, reverse = [], [], []
    for i, path in enumerate(items):
        pts, rev = _entries(path, seam, target)
        points.append(pts)
        rows.append(np.full(len(pts), i))
        reverse.append(rev)
    points = np.concatenate(points)
    rows = np.concatenate(rows)
    reverse = np.concatenate(reverse)
    first_row = np.searchsorted(rows, np.arange(len(items)))
    last_row = np.r_[first_row[1:], len(rows)]
    alive = np.ones(len(points), bool)
    for _ in range(len(items)):
        d = ((points - head)**2).sum(axis=1)
        d[~alive] = np.inf
        k = int(d.argmin())
        i = int(rows[k])
        alive[first_row[i]:last_row[i]] = False
        path = items[i]
        out.append(path)
        if path.closed:
            head = points[k]
        else:
            ends = np.asarray(path.points, float)[[0, -1], :2]
            head = ends[0] if reverse[k] else ends[1]
        g = owner[i]
        if g >= 0:
            remaining[g] -= 1
            if remaining[g] == 0:
                ordered, head = _nearest_first([p for p in groups[g] if p.feature == "outer_perimeter"],
                                               head, seam, target)
                out.extend(ordered)
    return out, head


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
        if walls:
            ordered, head = _print_walls(walls, head, seam, target)
            out.extend(ordered)
        # bridges together first: they switch the fan and anchor on the walls just printed
        ordered, head = _nearest_first([p for p in fill if p.feature == "bridge"], head, seam, target)
        out.extend(ordered)
        fill = [p for p in fill if p.feature != "bridge"]
        if mixed_fill:
            ordered, head = _order_fill(fill, head, seam, target)
            out.extend(ordered)
        else:
            for feature in dict.fromkeys(p.feature for p in fill):
                ordered, head = _order_fill([p for p in fill if p.feature == feature], head, seam, target)
                out.extend(ordered)
    return out
