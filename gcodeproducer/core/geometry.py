"""Minimal geometry kernel: triangle mesh, planar slicing and polygon offset.

Pure numpy, no external CAD/CGAL/clipper dependency.  This is an *early* kernel:
it slices watertight meshes into closed contours and offsets them with a
miter / vertex-normal method that is robust for simple prismatic parts
(cubes, cylinders, convex-ish shapes).  Heavily concave parts and thin walls
may need a proper polygon-clipping library (pyclipper) later.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

import numpy as np


# --------------------------------------------------------------------------
@dataclass
class Mesh:
    vertices: np.ndarray            # (n, 3) float
    triangles: np.ndarray           # (m, 3) int indices

    @property
    def bounds(self):
        lo = self.vertices.min(axis=0)
        hi = self.vertices.max(axis=0)
        return lo, hi

    def translate(self, v) -> None:
        self.vertices = self.vertices + np.asarray(v, float)

    def center_xy_on(self, cx: float, cy: float) -> None:
        lo, hi = self.bounds
        mid = (lo + hi) / 2
        self.translate([cx - mid[0], cy - mid[1], -lo[2]])   # also drop to bed


# ------------------------------------------------------------------ STL I/O
def load_stl(path: str) -> Mesh:
    with open(path, "rb") as fh:
        head = fh.read(5)
        fh.seek(0)
        data = fh.read()
    if head[:5].lower() == b"solid" and b"facet" in data[:2048].lower():
        return _load_ascii_stl(data.decode("ascii", "replace"))
    return _load_binary_stl(data)


def _load_binary_stl(data: bytes) -> Mesh:
    n = struct.unpack_from("<I", data, 80)[0]
    verts = np.zeros((n * 3, 3), np.float64)
    off = 84
    for i in range(n):
        vals = struct.unpack_from("<12f", data, off)
        verts[i * 3 + 0] = vals[3:6]
        verts[i * 3 + 1] = vals[6:9]
        verts[i * 3 + 2] = vals[9:12]
        off += 50
    tris = np.arange(n * 3).reshape(n, 3)
    return _weld(verts, tris)


def _load_ascii_stl(text: str) -> Mesh:
    verts = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("vertex"):
            parts = s.split()
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
    verts = np.asarray(verts, np.float64)
    tris = np.arange(len(verts)).reshape(-1, 3)
    return _weld(verts, tris)


def _weld(verts: np.ndarray, tris: np.ndarray, tol: float = 1e-6) -> Mesh:
    keys = np.round(verts / tol).astype(np.int64)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    out_v = np.zeros((len(uniq), 3))
    out_v[inv] = verts
    return Mesh(out_v, inv[tris].astype(np.int64))


# --------------------------------------------------------------- slicing
def slice_z(mesh: Mesh, z: float) -> list:
    """Intersect the mesh with the plane Z=z; return a list of closed polygons (n,2)."""
    v = mesh.vertices
    t = mesh.triangles
    zt = v[t][:, :, 2]                     # (m,3) triangle vertex Z
    above = zt > z
    cnt = above.sum(axis=1)
    cross = t[(cnt == 1) | (cnt == 2)]
    if len(cross) == 0:
        return []
    segs = []
    for tri in cross:
        p = v[tri]
        pz = p[:, 2]
        hi = pz > z
        # the lone vertex on one side
        if hi.sum() == 1:
            lone = np.where(hi)[0][0]
        else:
            lone = np.where(~hi)[0][0]
        others = [i for i in range(3) if i != lone]
        a = _interp(p[lone], p[others[0]], z)
        b = _interp(p[lone], p[others[1]], z)
        segs.append((a, b))
    return _chain(segs)


def _interp(p0, p1, z):
    t = (z - p0[2]) / (p1[2] - p0[2]) if p1[2] != p0[2] else 0.0
    return (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))


def _chain(segs, tol: float = 1e-4) -> list:
    """Join undirected edge segments into closed polygons."""
    def key(p):
        return (round(p[0] / tol), round(p[1] / tol))

    coord: dict = {}
    adj: dict = {}
    seen_edges = set()
    for a, b in segs:
        ka, kb = key(a), key(b)
        if ka == kb:
            continue
        e = (ka, kb) if ka <= kb else (kb, ka)
        if e in seen_edges:
            continue
        seen_edges.add(e)
        coord[ka] = a
        coord[kb] = b
        adj.setdefault(ka, []).append(kb)
        adj.setdefault(kb, []).append(ka)

    polys = []
    for start in list(adj):
        while adj.get(start):
            cur = start
            poly = [coord[cur]]
            prev = None
            guard = 0
            while guard < 1000000:
                guard += 1
                nbrs = adj.get(cur, [])
                nxt = None
                for cand in nbrs:
                    if cand != prev or len(nbrs) == 1:
                        nxt = cand
                        break
                if nxt is None:
                    break
                # consume the undirected edge
                adj[cur].remove(nxt)
                adj[nxt].remove(cur)
                prev = cur
                cur = nxt
                if cur == start:
                    break
                poly.append(coord[cur])
            if len(poly) >= 3:
                polys.append(np.asarray(poly, float))
    return polys


# ------------------------------------------------------------- polygons
def area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def signed_orient(poly: np.ndarray, ccw: bool = True) -> np.ndarray:
    a = area(poly)
    if (a < 0 and ccw) or (a > 0 and not ccw):
        return poly[::-1].copy()
    return poly


def offset(poly: np.ndarray, delta: float) -> list:
    """Offset a closed polygon by ``delta`` (negative = inward for CCW outer).

    Miter offset by edge normals.  Returns [] if the loop collapses.
    """
    p = np.asarray(poly, float)
    if len(p) < 3:
        return []
    # ensure CCW so that negative delta moves inward
    if area(p) < 0:
        p = p[::-1]
        delta = delta
    n = len(p)
    out = np.zeros_like(p)
    for i in range(n):
        prev = p[i - 1]
        cur = p[i]
        nxt = p[(i + 1) % n]
        e1 = cur - prev
        e2 = nxt - cur
        n1 = _norm_left(e1)
        n2 = _norm_left(e2)
        bis = n1 + n2
        bl = np.linalg.norm(bis)
        if bl < 1e-9:
            out[i] = cur + n1 * delta
            continue
        bis = bis / bl
        cos_half = float(np.dot(bis, n1))
        cos_half = max(cos_half, 0.1)       # clamp sharp corners
        # n1/n2 are inward normals of a CCW loop, so negative delta = inward
        out[i] = cur - bis * (delta / cos_half)
    # drop collapse: if the offset reversed the loop area sign, it vanished
    if np.sign(area(out)) != np.sign(area(p)) or abs(area(out)) < 1e-6:
        return []
    return [out]


def point_in_polygon(pt, poly: np.ndarray) -> bool:
    x, y = float(pt[0]), float(pt[1])
    p = np.asarray(poly, float)
    x0, y0 = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    cross = (y0 > y) != (y1 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
    return bool(np.count_nonzero(cross & (x < xi)) % 2)


def outer_contours(polys: list) -> list:
    """Contours that are not holes (contained by an even number of other contours)."""
    out = []
    for i, p in enumerate(polys):
        depth = sum(1 for j, q in enumerate(polys) if j != i and point_in_polygon(p[0], q))
        if depth % 2 == 0:
            out.append(p)
    return out


def convex_hull(points: np.ndarray) -> np.ndarray:
    """Monotone-chain convex hull, CCW, (n,2)."""
    pts = np.unique(np.round(np.asarray(points, float), 6), axis=0)
    if len(pts) < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        h = []
        for q in seq:
            while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (q[1] - h[-2][1])
                                   - (h[-1][1] - h[-2][1]) * (q[0] - h[-2][0])) <= 0:
                h.pop()
            h.append(q)
        return h
    lower = half(pts)
    upper = half(pts[::-1])
    return np.asarray(lower[:-1] + upper[:-1], float)


class RegionMask:
    """Filled boolean occupancy grid for closed polygons (even-odd rule).

    Exposes the same ``res`` / ``lo`` / ``grid`` / ``blocked`` interface as
    :class:`infill_gen.Raster`, so it can be used with ``split_by_raster``.
    Build every layer's mask on a *shared* grid (same ``lo`` / ``res`` / shape)
    to allow boolean operations between layers (top / bottom shell detection).
    """

    def __init__(self, lo, hi, res: float = 0.3, grid=None):
        self.res = res
        self.lo = np.asarray(lo, float) - 2.0
        hi = np.asarray(hi, float) + 2.0
        self.nx = max(1, int(math.ceil((hi[0] - self.lo[0]) / res)))
        self.ny = max(1, int(math.ceil((hi[1] - self.lo[1]) / res)))
        self.grid = np.zeros((self.ny, self.nx), bool) if grid is None else grid

    def like(self, grid=None) -> "RegionMask":
        rm = RegionMask.__new__(RegionMask)
        rm.res, rm.lo, rm.nx, rm.ny = self.res, self.lo, self.nx, self.ny
        rm.grid = np.zeros((self.ny, self.nx), bool) if grid is None else grid
        return rm

    def fill(self, polys: list) -> "RegionMask":
        e0, e1 = [], []
        for p in polys:
            p = np.asarray(p, float)
            if len(p) >= 3:
                e0.append(p)
                e1.append(np.roll(p, -1, axis=0))
        if not e0:
            return self
        a = np.concatenate(e0)
        b = np.concatenate(e1)
        y0, y1, x0, x1 = a[:, 1], b[:, 1], a[:, 0], b[:, 0]
        ymin = np.minimum(y0, y1)
        ymax = np.maximum(y0, y1)
        dy = y1 - y0
        for j in range(self.ny):
            y = self.lo[1] + (j + 0.5) * self.res
            m = (ymin <= y) & (ymax > y)
            if not m.any():
                continue
            t = (y - y0[m]) / np.where(dy[m] == 0, 1, dy[m])
            xs = np.sort(x0[m] + t * (x1[m] - x0[m]))
            for k in range(0, len(xs) - 1, 2):
                i0 = int(math.ceil((xs[k] - self.lo[0]) / self.res - 0.5))
                i1 = int(math.floor((xs[k + 1] - self.lo[0]) / self.res - 0.5))
                if i1 >= i0:
                    self.grid[j, max(i0, 0):min(i1 + 1, self.nx)] = True
        return self

    def blocked(self, pts: np.ndarray) -> np.ndarray:
        ij = np.floor((np.asarray(pts, float) - self.lo) / self.res).astype(int)
        ok = (ij[:, 0] >= 0) & (ij[:, 0] < self.nx) & (ij[:, 1] >= 0) & (ij[:, 1] < self.ny)
        res = np.zeros(len(ij), bool)
        res[ok] = self.grid[ij[ok, 1], ij[ok, 0]]
        return res


def _norm_left(edge):
    """Unit left-hand normal of an edge (inward normal for a CCW polygon)."""
    e = np.asarray(edge, float)
    L = math.hypot(e[0], e[1])
    if L < 1e-12:
        return np.zeros(2)
    return np.array([-e[1], e[0]]) / L


def perimeter_loops(contours: list, line_width: float, count: int) -> list:
    """Return ``count`` nested perimeter loops (outer first) for each contour.

    Result: list of (index, loops) where loops[0] is the outer wall.
    """
    result = []
    for c in contours:
        loops = []
        for k in range(count):
            d = -line_width * (0.5 + k)
            got = offset(c, d)
            if not got:
                break
            loops.append(got[0])
        if loops:
            result.append(loops)
    return result
