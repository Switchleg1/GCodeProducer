"""DropSurface — conservative model height raster for flat-cutter drop heights."""
from __future__ import annotations
import math
import numpy as np
from .cam_constants import SURFACE_FOLLOW_SPREAD


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

    def smooth(self, radius):
        """The cutter grid with each cell raised to the highest of its 3 x 3 neighbourhood (cached)."""
        key = ('smooth', round(float(radius), 6))
        if key not in self._lowered:
            grid = self.lowered(radius)
            padded = np.pad(grid, 1, constant_values=-np.inf)
            nx, ny = grid.shape
            self._lowered[key] = np.max([padded[1+dx:1+dx+nx, 1+dy:1+dy+ny]
                                         for dx in (-1, 0, 1) for dy in (-1, 0, 1)], axis=0)
        return self._lowered[key]

    def follow(self, points, radius):
        """Safe cutter heights at ``points``, interpolated so a slope reads as a slope, not as stairs.

        ``heights`` gives one safe height per cell, which a path crossing a
        slope follows as a staircase: flat, then a little plunge at every cell.
        Interpolating bilinearly between the four nearest cell centres of the
        ``smooth`` grid is continuous and never below ``heights``: each of those
        four centres is in the 3 x 3 neighbourhood of the point's cell. The raise
        is at most about one cell of slope. Across a step steeper than
        ``SURFACE_FOLLOW_SPREAD`` cells of rise per cell (a wall), or where a
        neighbour has no model below, the plain ``heights`` are kept.
        """
        grid = self.smooth(radius)
        nx, ny = grid.shape
        u = (np.asarray(points, float)[:, :2]-self.origin)/self.resolution - .5
        cell = np.floor(u+.5).astype(int)
        inside = np.all((cell >= 0) & (cell < np.array([nx, ny])), axis=1)   # as heights
        base = np.floor(u).astype(int)
        t = u-base
        total = np.zeros(len(u))
        low = np.full(len(u), np.inf)
        for di, wx in ((0, 1-t[:, 0]), (1, t[:, 0])):
            for dj, wy in ((0, 1-t[:, 1]), (1, t[:, 1])):
                value = grid[np.clip(base[:, 0]+di, 0, nx-1), np.clip(base[:, 1]+dj, 0, ny-1)]
                low = np.minimum(low, value)
                total += np.where(np.isfinite(value), value, 0.)*wx*wy
        high = np.full(len(u), -np.inf)
        for di in (0, 1):
            for dj in (0, 1):
                high = np.maximum(high, grid[np.clip(base[:, 0]+di, 0, nx-1), np.clip(base[:, 1]+dj, 0, ny-1)])
        finite = np.isfinite(low)
        smooth = finite & (np.where(finite, high-np.where(finite, low, 0.), np.inf) <= SURFACE_FOLLOW_SPREAD*self.resolution)
        return np.where(smooth, total, self.heights(points, radius))

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
