"""Detect overlapping closed solids and optionally union them at slice time."""
import numpy as np
from shapely import union_all
from shapely.geometry import box
from shapely.strtree import STRtree

from gcodeproducer.core.geometry.kernel import slice_planes
from gcodeproducer.core.geometry.mesh import Mesh
from gcodeproducer.core.fdm.wall_regions import region_rings, slice_region


def _components(triangles, vertex_count):
    """Group faces by vertex connectivity with batched union-find."""
    parent = np.arange(vertex_count, dtype=np.intp)
    a = np.concatenate((triangles[:, 0], triangles[:, 0]))
    b = np.concatenate((triangles[:, 1], triangles[:, 2]))
    while True:
        ra, rb = parent[a], parent[b]
        different = ra != rb
        if not different.any():
            return parent[triangles[:, 0]]
        ra, rb = ra[different], rb[different]
        np.minimum.at(parent, np.maximum(ra, rb), np.minimum(ra, rb))
        while not np.array_equal(parent, parent[parent]):
            parent = parent[parent]


def _shells(mesh):
    t = mesh.triangles
    if not len(t):
        return []
    labels = _components(t, len(mesh.vertices))
    if np.all(labels == labels[0]):
        return []
    order = labels.argsort(kind="stable")
    parts = np.split(order, np.flatnonzero(np.diff(labels[order])) + 1)
    shells = []
    for faces in parts:
        ids, triangles = np.unique(t[faces], return_inverse=True)
        s = Mesh(mesh.vertices[ids], triangles.reshape(-1, 3))
        # Require exactly two oppositely oriented faces per edge. Any ambiguous
        # shell keeps the original slice; this isn't a hole-closing mesh repair.
        edges = s.triangles[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
        key = np.sort(edges, axis=1)
        order = np.lexsort(key.T)
        if (len(order) % 2 or not np.array_equal(edges[order[::2]], edges[order[1::2], ::-1])
                or np.any(np.all(key[order[1:-1:2]] == key[order[2::2]], axis=1))):
            return []
        t0, t1, t2 = (s.vertices[s.triangles[:, i]] - s.vertices[0] for i in range(3))
        volume = np.einsum("ij,ij->i", t0, np.cross(t1, t2)).sum() / 6.
        if volume == 0:
            return []
        shells.append((s, 1 if volume > 0 else -1))
    return shells


def _candidate_planes(shells, planes):
    """Only planes at which two outward shell bounds overlap in all three axes."""
    bounds = [s.bounds for s, sign in shells if sign > 0]
    if len(bounds) < 2:
        return np.array([], dtype=int)
    boxes = [box(lo[0], lo[1], hi[0], hi[1]) for lo, hi in bounds]
    tree = STRtree(boxes)
    active = np.zeros(len(planes), dtype=bool)
    for i, (lo, hi) in enumerate(bounds):
        for j in tree.query(boxes[i]):
            if j <= i:
                continue
            other_lo, other_hi = bounds[j]
            low, high = np.maximum(lo, other_lo), np.minimum(hi, other_hi)
            if np.all(high > low):
                a, b = np.searchsorted(planes, [low[2], high[2]])
                active[a:b] = True
    return np.flatnonzero(active)


def _solid_region(signed):
    """Add outward shells and subtract inward cavities by signed coverage count.

    An outward shell inside a cavity still contributes solid material. Keep
    separate coverage bands only when cavities are present.
    """
    if all(sign > 0 for _, sign in signed):
        return union_all([r for r, _ in signed])
    bands = []
    for region, sign in signed:
        rem, next_bands = region, []
        for piece, count in bands:
            if not piece.intersects(region):
                next_bands.append((piece, count))
                continue
            inside, outside = piece.intersection(region), piece.difference(region)
            if not outside.is_empty:
                next_bands.append((outside, count))
            if count + sign and inside.area > 0:
                next_bands.append((inside, count + sign))
            rem = rem.difference(piece)
        if not rem.is_empty:
            next_bands.append((rem, sign))
        bands = next_bands
    # Retain stray inward-wound solids, just as the ordinary even-odd slicer does.
    return union_all([r for r, _ in bands])


def slice_with_shell_check(mesh, planes, merge, found):
    """Use the ordinary contours except on planes with confirmed solid overlap."""
    from gcodeproducer.core.fdm.fdm_constants import SHELL_OVERLAP_AREA_EPS
    from gcodeproducer.core.geometry.geometry_constants import SLICE_PLANE_BATCH

    shells = _shells(mesh)
    planes = np.asarray(planes)
    candidates = _candidate_planes(shells, planes)
    for i in range(0, len(planes), SLICE_PLANE_BATCH):
        batch = planes[i:i+SLICE_PLANE_BATCH]
        ids = candidates[np.searchsorted(candidates, i):np.searchsorted(candidates, i+len(batch))]
        altered = {}
        if len(ids):
            selected = planes[ids]
            regions = [[] for _ in ids]
            for s, sign in shells:
                lo, hi = s.bounds
                a, b = np.searchsorted(selected, [lo[2], hi[2]])
                for k, contours in enumerate(slice_planes(s, selected[a:b]), a):
                    region = slice_region(contours)
                    if not region.is_empty:
                        regions[k].append((region, sign))
            for idx, signed in zip(ids, regions):
                positive = [r for r, sign in signed if sign > 0]
                if len(positive) < 2:
                    continue
                joined = union_all(positive)
                if sum(r.area for r in positive) - joined.area <= SHELL_OVERLAP_AREA_EPS:
                    continue
                found.append(int(idx))
                if merge:
                    result = joined if len(positive) == len(signed) else _solid_region(signed)
                    altered[idx] = list(region_rings(result))
        for offset, contours in enumerate(slice_planes(mesh, batch), i):
            yield altered.get(offset, contours)
