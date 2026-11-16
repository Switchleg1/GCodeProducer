"""RegionMask — geometry subsystem."""
from __future__ import annotations
import math, numpy as np

class RegionMask:
    """Filled boolean occupancy grid for closed polygons (even-odd rule).

    Exposes the same ``res`` / ``lo`` / ``grid`` / ``blocked`` interface as
    :class:`infill_gen.Raster`, so it can be used with ``split_by_raster``.
    Build every layer's mask on a *shared* grid (same ``lo`` / ``res`` / shape)
    to allow boolean operations between layers (top / bottom shell detection).
    """

    def __init__(self, lo, hi, res: float = 0.3, grid=None, pad: float = 2.0):
        self.res = res
        self.lo = np.asarray(lo, float) - pad
        hi = np.asarray(hi, float) + pad
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
