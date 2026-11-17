"""Local FDM print ordering without changing feature geometry or stage dependencies."""
from itertools import groupby

import numpy as np

from .fdm_constants import FILL_FEATURES, FILL_LOOKAHEAD


def _fill(path):
    return path.feature in FILL_FEATURES and not path.closed and len(path.points) >= 2


def _ends(points, position):
    return ((points - position)**2).sum(axis=-1)


def _order(block, start):
    ends = np.asarray([(p.points[0], p.points[-1]) for p in block], float)
    groups = {}
    for i, path in enumerate(block):
        groups.setdefault(path.feature, []).append(i)
    pending = list(groups.values())
    heads = [0] * len(pending)
    chosen = []
    current = start
    distance = 0.
    for _ in block:
        candidates = [(i, g, k) for g, group in enumerate(pending)
                      for k, i in enumerate(group[heads[g]:heads[g]+FILL_LOOKAHEAD], heads[g])]
        ds = _ends(ends[[i for i, _, _ in candidates]], current)
        best, end = divmod(int(ds.argmin()), 2)
        i, g, k = candidates[best]
        # Swap out the winner without shifting the rest of a long path list.
        pending[g][k] = pending[g][heads[g]]
        heads[g] += 1
        chosen.append(block[i])
        distance += float(np.sqrt(ds[best, end]))
        current = ends[i, 1-end]

    # Keep the existing ordering if the heuristic doesn't improve XY travel.
    original = 0.
    current = start
    for pair in ends:
        ds = _ends(pair, current)
        end = int(ds.argmin())
        original += float(np.sqrt(ds[end]))
        current = pair[1-end]
    return chosen if distance < original - 1e-9 else block


def ordered_paths(paths, head):
    """Interleave only adjacent mixed fill features; read the head at each block start."""
    for fill, run in groupby(paths, key=_fill):
        block = list(run)
        if fill and len({p.feature for p in block}) > 1:
            block = _order(block, head())
        yield from block


def closed_loop(points, target):
    """Start a closed path at the closest position on its edges, retaining winding."""
    nxt = np.roll(points, -1, axis=0)
    edges = nxt - points
    squared = (edges**2).sum(axis=1)
    t = np.clip(((target - points)*edges).sum(axis=1)/np.maximum(squared, 1e-30), 0, 1)
    closest = points + t[:, None]*edges
    i = int(_ends(closest, target).argmin())
    if t[i] <= 1e-9:
        return np.roll(points, -i, axis=0)
    if t[i] >= 1-1e-9:
        return np.roll(points, -(i+1), axis=0)
    return np.vstack((closest[i], np.roll(points, -(i+1), axis=0)))
