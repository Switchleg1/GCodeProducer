"""Group parallel fill lines into runs that print back and forth as one block.

Straight fill lines of one direction lie on equally spaced scan lines. Only
dense families (solid fill) form runs; sparse lines are far apart and their
crossing families are better interleaved line by line. Where a
hole or a narrowing splits the area, a scan line holds several segments. A
*run* is a chain of segments on consecutive scan lines that overlap and do not
branch; it prints as a zig-zag with only short hops. Where runs branch (a
fork in the road around a hole) the runs on either side are separate, and the
layer order takes the shorter branch first so the way back to the longer one
is short and nothing is left behind to collect later.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from gcodeproducer.core.fdm.fdm_constants import (FILL_RUN_ANGLE_DECIMALS, FILL_RUN_GAP_FACTOR,
                                                   FILL_RUN_MAX_SPACING, FILL_RUN_OVERLAP)


def _family_key(path):
    a, b = np.asarray(path.points, float)[[0, -1], :2]
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.
    return path.feature, round(angle, FILL_RUN_ANGLE_DECIMALS) % 180.


def build_runs(paths):
    """Runs of straight fill lines.

    Returns ``(runs, singles)``: each run is ``{"paths": [...], "next": set, "prev": set,
    "length": float}`` with ``next`` / ``prev`` the indices of runs touching its last /
    first segment; ``singles`` are paths that are not straight two-point lines.
    """
    families = defaultdict(list)
    singles = []
    for path in paths:
        if path.closed or len(path.points) != 2:
            singles.append(path)
        else:
            families[_family_key(path)].append(path)
    runs = []
    for (_, angle), members in families.items():
        found = _family_runs(members, math.radians(angle))
        if found is None:
            singles.extend(members)        # sparse: crossing families interleave better line by line
        else:
            runs.extend(found)
    owner = {}
    for r, run in enumerate(runs):
        for path in run["paths"]:
            owner[id(path)] = r
    for run in runs:
        run["next"] = {owner[id(p)] for p in run.pop("_next")} - {owner[id(run["paths"][-1])]}
        run["prev"] = {owner[id(p)] for p in run.pop("_prev")} - {owner[id(run["paths"][0])]}
    return runs, singles


def _family_runs(members, angle):
    direction = np.array([math.cos(angle), math.sin(angle)])
    normal = np.array([-direction[1], direction[0]])
    ends = np.array([np.asarray(p.points, float)[[0, -1], :2] for p in members])
    u = ends.mean(axis=1) @ normal
    v = np.sort(ends @ direction, axis=1)
    order = np.argsort(u, kind="stable")
    levels = []                           # (u, [segment indices]) per scan line
    for i in order.tolist():
        if levels and abs(u[i] - levels[-1][0]) < 1e-6:
            levels[-1][1].append(i)
        else:
            levels.append((u[i], [i]))
    gaps = np.diff([lv[0] for lv in levels])
    spacing = float(np.median(gaps)) if len(gaps) else 0.
    if spacing > FILL_RUN_MAX_SPACING:
        return None
    forward = defaultdict(list)
    backward = defaultdict(list)
    for (u0, a), (u1, b) in zip(levels, levels[1:]):
        if u1 - u0 > FILL_RUN_GAP_FACTOR * spacing:
            continue
        for i in a:
            for j in b:
                if min(v[i, 1], v[j, 1]) - max(v[i, 0], v[j, 0]) > -FILL_RUN_OVERLAP * spacing:
                    forward[i].append(j)
                    backward[j].append(i)
    runs, used = [], set()
    for i in order.tolist():
        if i in used:
            continue
        chain = [i]
        used.add(i)
        while len(forward[chain[-1]]) == 1:
            j = forward[chain[-1]][0]
            if j in used or len(backward[j]) != 1:
                break
            chain.append(j)
            used.add(j)
        runs.append({"paths": [members[k] for k in chain],
                     "_next": [members[k] for k in forward[chain[-1]]],
                     "_prev": [members[k] for k in backward[chain[0]]],
                     "length": float(sum(v[k, 1] - v[k, 0] for k in chain))})
    return runs


def run_entries(run):
    """Entry points of a run with the exit and the path order for each: ``[(entry, exit, paths, forward)]``."""
    paths = run["paths"]
    out = []
    for forward in (True, False):
        seq = paths if forward else paths[::-1]
        first = np.asarray(seq[0].points, float)[[0, -1], :2]
        for start in first:
            head = start
            for path in seq:
                a, b = np.asarray(path.points, float)[[0, -1], :2]
                head = b if ((a - head)**2).sum() <= ((b - head)**2).sum() else a
            out.append((start, head, seq, forward))
    return out
