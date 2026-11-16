"""DropSurface — conservative model height raster for flat-cutter drop heights."""
from __future__ import annotations
import math
import numpy as np


class DropSurface:
    """Highest model Z under a flat cutter footprint, never below the true surface.

    Each cell stores an upper bound of the upward-facing triangles touching it
    (plane value at the cell centre plus slope times the half diagonal, capped
    by the triangle's top). Cutter lookups take the maximum over the footprint
    grown by one cell. Cells without model are ``-inf``. Steep faces therefore
    keep up to about one cell times the slope of extra material.
    """

    def __init__(self, mesh, low, high, resolution, max_cells):
        low, high = np.asarray(low, float)[:2], np.asarray(high, float)[:2]
        if not (np.isfinite(np.r_[low, high]).all() and np.all(high > low) and resolution > 0):
            raise ValueError("Surface height grid needs a finite, non-empty XY area")
        size = high-low
        resolution = max(float(resolution), math.sqrt(size[0]*size[1]/max(1, max_cells)))
        self.resolution = resolution
        self.origin = low
        self.shape = tuple(int(v) for v in np.maximum(1, np.ceil(size/resolution)))
        self.top = np.full(self.shape, -np.inf)
        self._lowered = {}
        triangles = np.asarray(mesh.vertices, float)[np.asarray(mesh.triangles)]
        normal = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
        length = np.linalg.norm(normal, axis=1)
        keep = normal[:, 2] > 1e-7*np.maximum(length, 1e-30)
        half = resolution*math.sqrt(.5)
        for triangle, n in zip(triangles[keep], normal[keep]):
            lo = np.floor((triangle[:, :2].min(axis=0)-low)/resolution).astype(int)
            hi = np.floor((triangle[:, :2].max(axis=0)-low)/resolution).astype(int)
            lo, hi = np.maximum(lo, 0), np.minimum(hi, np.asarray(self.shape)-1)
            if np.any(hi < lo):
                continue
            x = low[0]+(np.arange(lo[0], hi[0]+1)+.5)*resolution
            y = low[1]+(np.arange(lo[1], hi[1]+1)+.5)*resolution
            gx, gy = np.meshgrid(x, y, indexing="ij")
            inside = np.ones(gx.shape, bool)
            for a, b in ((0, 1), (1, 2), (2, 0)):
                edge = triangle[b, :2]-triangle[a, :2]
                norm = math.hypot(*edge)
                if norm < 1e-15:
                    continue
                # Upward triangles are counter-clockwise in XY: inside is to the left.
                distance = (edge[0]*(gy-triangle[a, 1])-edge[1]*(gx-triangle[a, 0]))/norm
                inside &= distance >= -half
            if not inside.any():
                continue
            slope = np.array([-n[0]/n[2], -n[1]/n[2]])
            z = triangle[0, 2]+slope[0]*(gx-triangle[0, 0])+slope[1]*(gy-triangle[0, 1])+math.hypot(*slope)*half
            z = np.minimum(z, triangle[:, 2].max())
            z = np.maximum(z, triangle[:, 2].min())
            patch = self.top[lo[0]:hi[0]+1, lo[1]:hi[1]+1]
            np.maximum(patch, np.where(inside, z, -np.inf), out=patch)

    def lowered(self, radius):
        """Grid of maxima over a disc of ``radius`` plus one cell (cached per radius)."""
        key = round(float(radius), 6)
        if key not in self._lowered:
            reach = int(math.ceil(radius/self.resolution))+1
            nx, ny = self.shape
            spans = {}
            for dx in range(-reach, reach+1):
                spans.setdefault(int(math.floor(math.sqrt(reach*reach-dx*dx))), []).append(dx)
            result = np.full(self.shape, -np.inf)
            column = self.top.copy()          # running maximum over |dy| <= span
            for span in range(reach+1):
                if 0 < span < ny:
                    np.maximum(column[:, span:], self.top[:, :ny-span], out=column[:, span:])
                    np.maximum(column[:, :ny-span], self.top[:, span:], out=column[:, :ny-span])
                for dx in spans.get(span, ()):
                    if abs(dx) >= nx:
                        continue
                    target = result[max(0, dx):nx+min(0, dx)]
                    np.maximum(target, column[max(0, -dx):nx+min(0, -dx)], out=target)
            self._lowered[key] = result
        return self._lowered[key]

    def heights(self, points, radius):
        """Lowest safe flat-cutter tip Z at each XY point (-inf where no model is below)."""
        points = np.asarray(points, float)[:, :2]
        index = np.floor((points-self.origin)/self.resolution).astype(int)
        valid = np.all((index >= 0) & (index < np.asarray(self.shape)), axis=1)
        result = np.full(len(points), -np.inf)
        grid = self.lowered(radius)
        result[valid] = grid[index[valid, 0], index[valid, 1]]
        return result
