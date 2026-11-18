"""Infill pattern generation (pure numpy, no polygon library needed).

Regions are given as closed polylines (even-odd fill rule).  Each pattern is
a set of *line families*; a family is a set of parallel lines described by
the angle of its normal ``phi``, a ``period`` (distance between lines) and an
``offset`` along the normal.  Lines are clipped against the region with a
scan-line algorithm and trimmed so they stay ``inset`` away from the
boundary.  An optional :class:`Raster` mask removes parts that would overlap
other extrusions (solid infill, bridges...).
"""
from __future__ import annotations

from gcodeproducer.core.geometry.geometry_constants import PATTERNS
import math, numpy as np


def pattern_families(pattern: str, layer_index: int, z: float, spacing: float, angle_deg: float) -> list:
    """Return [(phi, period, offset)] for the given pattern.

    ``spacing`` is the equivalent rectilinear line distance (= width / density),
    so every pattern deposits roughly the same amount of material.
    """
    a = math.radians(angle_deg)
    if pattern == "rectilinear":
        return [(a + (math.pi / 2 if layer_index % 2 else 0.0), spacing, 0.0)]
    if pattern == "lines":
        return [(a, spacing, 0.0)]
    if pattern == "grid":
        return [(a, 2 * spacing, 0.0), (a + math.pi / 2, 2 * spacing, 0.0)]
    if pattern == "triangles":
        return [(a + k * math.pi / 3, 3 * spacing, 0.0) for k in range(3)]
    if pattern == "cubic":
        # cube lattice standing on a corner: three plane families whose
        # intersection lines move by z/sqrt(2) per unit of height
        return [(a + k * 2 * math.pi / 3, 3 * spacing, -z / math.sqrt(2)) for k in range(3)]
    raise ValueError(f"unknown infill pattern '{pattern}'")


def _edges(polys: list):
    a, b = [], []
    for p in polys:
        p = np.asarray(p, float)
        if len(p) < 3:
            continue
        a.append(p)
        b.append(np.roll(p, -1, axis=0))
    if not a:
        return np.zeros((0, 2)), np.zeros((0, 2))
    return np.concatenate(a), np.concatenate(b)


def scan_fill(polys: list, phi: float, period: float, offset: float, inset: float,
              min_length: float = 0.0) -> np.ndarray:
    """Clip a family of parallel lines to ``polys`` (even-odd). Returns (n,2,2)."""
    ea, eb = _edges(polys)
    if len(ea) == 0 or period <= 0:
        return np.zeros((0, 2, 2))
    n = np.array([math.cos(phi), math.sin(phi)])
    t = np.array([-math.sin(phi), math.cos(phi)])
    ua, ub = ea @ n, eb @ n
    va, vb = ea @ t, eb @ t
    du, dv = ub - ua, vb - va
    elen = np.hypot(du, dv)
    keep = elen > 1e-9
    ua, ub, va, vb, du, dv, elen = ua[keep], ub[keep], va[keep], vb[keep], du[keep], dv[keep], elen[keep]
    sin = np.abs(du) / elen
    trim = np.minimum(inset / np.maximum(sin, 1e-6), 4 * inset) if inset > 0 else np.zeros_like(sin)
    umin, umax = min(ua.min(), ub.min()), max(ua.max(), ub.max())
    k0 = math.ceil((umin - offset) / period)
    k1 = math.floor((umax - offset) / period)
    out = []
    for k in range(k0, k1 + 1):
        u = offset + k * period
        cross = ((ua <= u) & (ub > u)) | ((ub <= u) & (ua > u))
        if cross.sum() < 2:
            continue
        idx = np.nonzero(cross)[0]
        tt = (u - ua[idx]) / du[idx]
        v = va[idx] + tt * dv[idx]
        order = np.argsort(v)
        v = v[order]
        tr = trim[idx][order]
        for j in range(0, len(v) - 1, 2):
            v0 = v[j] + tr[j]
            v1 = v[j + 1] - tr[j + 1]
            if v1 - v0 > max(min_length, 1e-6):
                out.append((u, v0, v1))
    if not out:
        return np.zeros((0, 2, 2))
    arr = np.array(out)
    p0 = arr[:, 0:1] * n + arr[:, 1:2] * t
    p1 = arr[:, 0:1] * n + arr[:, 2:3] * t
    return np.stack([p0, p1], axis=1)


def split_by_raster(segs: np.ndarray, raster, min_length: float) -> np.ndarray:
    """Remove the parts of each segment that fall on blocked cells of one or more rasters."""
    rasters = [r for r in (raster if isinstance(raster, (list, tuple)) else [raster])
               if r is not None and r.grid.any()]
    if not rasters or len(segs) == 0:
        return segs
    step = min(r.res for r in rasters) * 0.5
    out = []
    for batch in _raster_sample_batches(segs, step):
        points = np.concatenate([row[4] for row in batch])
        free = np.ones(len(points), bool)
        for r in rasters:
            free &= ~r.blocked(points)
        offset = 0
        for p0, p1, d, t, pts in batch:
            keep = free[offset:offset+len(t)]
            offset += len(t)
            if keep.all():
                out.append((p0, p1))
            elif keep.any():
                edges = np.diff(keep.astype(np.int8), prepend=0, append=0)
                starts = np.flatnonzero(edges == 1)
                ends = np.flatnonzero(edges == -1) - 1
                for s, e in zip(starts, ends):
                    if (t[e] - t[s]) * d > min_length:
                        out.append((pts[s], pts[e]))
    if not out:
        return np.zeros((0, 2, 2))
    return np.array(out, float)


def _raster_sample_batches(segs, step):
    """Keep the original sample spacing and segment order; batch grid lookups."""
    from .geometry_constants import RASTER_SAMPLE_BATCH

    batch, size = [], 0
    for p0, p1 in segs:
        delta = p1 - p0
        d = float(np.linalg.norm(delta))
        n = max(2, int(math.ceil(d / step)) + 1)
        if batch and size + n > RASTER_SAMPLE_BATCH:
            yield batch
            batch, size = [], 0
        t = np.linspace(0, 1, n)
        batch.append((p0, p1, d, t, p0 + delta*t[:, None]))
        size += n
    if batch:
        yield batch


def order_segments(segs: np.ndarray, start=(0.0, 0.0)) -> np.ndarray:
    """Greedy nearest-neighbour ordering (segments may be reversed)."""
    n = len(segs)
    if n <= 1:
        return segs
    a = segs[:, 0].copy()
    b = segs[:, 1].copy()
    used = np.zeros(n, bool)
    cur = np.asarray(start, float)
    out = np.empty_like(segs)
    for k in range(n):
        da = ((a - cur) ** 2).sum(axis=1)
        db = ((b - cur) ** 2).sum(axis=1)
        da[used] = np.inf
        db[used] = np.inf
        ia, ib = int(np.argmin(da)), int(np.argmin(db))
        if da[ia] <= db[ib]:
            i, rev = ia, False
        else:
            i, rev = ib, True
        used[i] = True
        if rev:
            out[k, 0], out[k, 1] = b[i], a[i]
        else:
            out[k, 0], out[k, 1] = a[i], b[i]
        cur = out[k, 1]
    return out
