"""Approximate medial axis (centre line + local half width) of polygon regions.

The axis is the subset of the Voronoi diagram of densely sampled boundary
points that lies inside the region. Each axis vertex carries its distance to
the region boundary (the inscribed radius), so ``2 * radius`` is the local
width of the material there.
"""
from __future__ import annotations

import numpy as np
import shapely

from gcodeproducer.core.geometry.geometry_constants import MEDIAL_KEY_DECIMALS


def medial_edges(material, window, step, margin, window_tolerance=0.):
    """Axis edges ``(m, 2, 2)`` and endpoint radii ``(m, 2)`` of ``material`` within
    ``window_tolerance`` of ``window``.

    Voronoi vertices are the circumcentres of the Delaunay triangles of the
    boundary samples (GEOS Delaunay is much faster than its Voronoi builder);
    an axis edge joins the centres of two triangles sharing a side. Only
    boundary within ``margin`` of the window is sampled, so radii are exact
    for axis points whose inscribed circle (radius <= margin) fits that band.
    """
    empty = np.zeros((0, 2, 2)), np.zeros((0, 2))
    if material.is_empty or window.is_empty:
        return empty
    shapely.prepare(window)
    x0, y0, x1, y1 = window.bounds
    boundary = shapely.clip_by_rect(material.boundary, x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    if boundary.is_empty:
        return empty
    pts = shapely.get_coordinates(shapely.segmentize(boundary, step))
    pts = pts[shapely.dwithin(window, shapely.points(pts), margin)]
    pts = np.unique(np.round(pts, MEDIAL_KEY_DECIMALS), axis=0)
    if len(pts) < 3:
        return empty
    tris = shapely.get_coordinates(shapely.get_parts(shapely.delaunay_triangles(shapely.multipoints(pts))))
    if not len(tris):
        return empty
    tris = tris.reshape(-1, 4, 2)[:, :3]
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    d = 2 * (a[:, 0]*(b[:, 1]-c[:, 1]) + b[:, 0]*(c[:, 1]-a[:, 1]) + c[:, 0]*(a[:, 1]-b[:, 1]))
    ok = np.abs(d) > 1e-12
    a2, b2, c2 = (a**2).sum(1), (b**2).sum(1), (c**2).sum(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        centre = np.stack(((a2*(b[:, 1]-c[:, 1]) + b2*(c[:, 1]-a[:, 1]) + c2*(a[:, 1]-b[:, 1])) / d,
                           (a2*(c[:, 0]-b[:, 0]) + b2*(a[:, 0]-c[:, 0]) + c2*(b[:, 0]-a[:, 0])) / d), axis=1)
    radius = np.hypot(*(centre - a).T)
    shapely.prepare(material)
    inside = ok.copy()
    inside[ok] = shapely.contains_xy(material, centre[ok, 0], centre[ok, 1])
    inside[inside] = shapely.dwithin(window, shapely.points(centre[inside]), window_tolerance)
    # triangle sides as sorted vertex-id pairs; a side shared by two inside triangles is an axis edge
    ids = np.searchsorted(_row_keys(pts), _row_keys(np.round(tris.reshape(-1, 2), MEDIAL_KEY_DECIMALS)))
    ids = ids.reshape(-1, 3)
    tri = np.flatnonzero(inside)
    if len(tri) < 2:
        return empty
    sides = np.concatenate([np.sort(ids[tri][:, [i, j]], axis=1) for i, j in ((0, 1), (1, 2), (2, 0))])
    owner = np.tile(tri, 3)
    key = sides[:, 0].astype(np.int64) * len(pts) + sides[:, 1]
    order = np.argsort(key, kind="stable")
    key, owner = key[order], owner[order]
    shared = np.flatnonzero(key[1:] == key[:-1])
    if not len(shared):
        return empty
    t0, t1 = owner[shared], owner[shared + 1]
    edges = np.stack((centre[t0], centre[t1]), axis=1)
    radii = np.stack((radius[t0], radius[t1]), axis=1)
    keep = shapely.covers(material, shapely.linestrings(edges))
    return edges[keep], radii[keep]


def _row_keys(xy):
    """Scalar keys that sort like the rows of ``np.unique(xy, axis=0)`` (x, then y)."""
    xy = np.asarray(xy, dtype=float)
    return xy[:, 0] + 1j * xy[:, 1]


def chain_edges(edges, values, prune, radius_factor=0.):
    """Join axis edges into polylines, dropping leaf spurs shorter than ``prune``.

    With ``radius_factor`` a spur is also dropped while shorter than that many
    times the junction value (the inscribed radius there): the two short
    branches into the corners of a square stroke end are not features.

    Returns a list of ``(points (n, 2), values (n,))``.
    """
    if not len(edges):
        return []
    keys = np.round(edges.reshape(-1, 2), MEDIAL_KEY_DECIMALS)
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    node_value = np.zeros(len(uniq))
    node_value[inverse] = values.reshape(-1)
    adj: dict = {}
    for a, b in inverse.reshape(-1, 2).tolist():
        if a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)

    def walk(start, nxt):
        path = [start, nxt]
        while len(adj.get(path[-1], ())) == 2:
            following = next(iter(adj[path[-1]] - {path[-2]}), None)
            if following is None:
                break
            path.append(following)
            if following == path[0]:          # closed axis loop
                break
        return path

    def length(path):
        p = uniq[path]
        return float(np.hypot(*np.diff(p, axis=0).T).sum())

    for _ in range(4):                    # spurs exposed by pruning are pruned next round
        changed = False
        for leaf in [n for n, nb in adj.items() if len(nb) == 1]:
            if leaf not in adj or len(adj[leaf]) != 1:
                continue
            path = walk(leaf, next(iter(adj[leaf])))
            limit = max(prune, radius_factor * node_value[path[-1]])
            if len(adj.get(path[-1], ())) >= 3 and length(path) < limit:
                for a, b in zip(path, path[1:]):
                    adj[a].discard(b)
                    adj[b].discard(a)
                for n in path[:-1]:
                    if not adj.get(n):
                        adj.pop(n, None)
                changed = True
        if not changed:
            break

    out, used = [], set()
    starts = [n for n, nb in adj.items() if len(nb) != 2] + list(adj)
    for start in starts:
        for nxt in list(adj.get(start, ())):
            if (min(start, nxt), max(start, nxt)) in used:
                continue
            path = walk(start, nxt)
            for a, b in zip(path, path[1:]):
                used.add((min(a, b), max(a, b)))
            out.append((uniq[path], node_value[path]))
    return out
