"""ModelShadow — XY footprint of all model material above a Z level (3-axis reachability)."""
from __future__ import annotations
import math
import numpy as np
from shapely import BufferJoinStyle
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .cam_constants import SURFACE_TOLERANCE, SHADOW_SEAL


def clip_band(triangle, low, high):
    """XY polygon of the part of a 3D triangle with low <= Z <= high, or None."""
    points = [np.asarray(p, float) for p in triangle]
    for sign, limit in ((1., low), (-1., -high)):
        if not math.isfinite(limit):
            continue
        clipped = []
        for a, b in zip(points, points[1:]+points[:1]):
            da, db = sign*a[2]-limit, sign*b[2]-limit
            if da >= 0:
                clipped.append(a)
            if (da > 0 > db) or (da < 0 < db):
                clipped.append(a+(b-a)*(da/(da-db)))
        points = clipped
        if len(points) < 3:
            return None
    polygon = Polygon([p[:2] for p in points])
    return polygon if polygon.is_valid and polygon.area > 1e-12 else None


class ModelShadow:
    """A vertical cutter at level Z cannot enter the projection of material above Z.

    For a closed solid that projection equals the projection of its upward-facing
    surface above Z, so undercuts/overhangs are covered without sampling slices.
    Levels are normally requested top-down; each request only adds the new band.
    """

    def __init__(self, mesh):
        triangles = np.asarray(mesh.vertices, float)[np.asarray(mesh.triangles)]
        normal = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
        length = np.linalg.norm(normal, axis=1)
        self.triangles = triangles[normal[:, 2] > 1e-7*np.maximum(length, 1e-30)]
        self.low = self.triangles[:, :, 2].min(axis=1) if len(self.triangles) else np.empty(0)
        self.high = self.triangles[:, :, 2].max(axis=1) if len(self.triangles) else np.empty(0)
        self._level = math.inf
        self._raw = Polygon()
        self._sealed = Polygon()

    def at(self, z):
        """Footprint of material more than the surface tolerance above ``z``."""
        level = float(z)+SURFACE_TOLERANCE
        if not math.isfinite(level):
            raise ValueError("Model shadow level must be finite")
        if level > self._level+1e-12:
            self._level, self._raw, self._sealed = math.inf, Polygon(), Polygon()
        if level < self._level-1e-12:
            pieces = [] if self._raw.is_empty else [self._raw]
            for triangle in self.triangles[(self.high > level) & (self.low < self._level)]:
                piece = clip_band(triangle, level, self._level)
                if piece is not None:
                    pieces.append(piece)
            self._raw = unary_union(pieces) if pieces else Polygon()
            self._level = level
            self._sealed = (self._raw if self._raw.is_empty else
                            self._raw.buffer(SHADOW_SEAL, join_style=BufferJoinStyle.mitre))
        return self._sealed
