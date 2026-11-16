"""One model-owned, constant-Z reference outline in CAM work coordinates."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import uuid
import numpy as np
from .cam_constants import REFERENCE_CHORD_ERROR, REFERENCE_MIN_SEGMENTS, REFERENCE_MAX_SEGMENTS


@dataclass
class ReferenceShape:
    kind: str = "circle"
    construction: str = "center"
    first: tuple = (0., 0.)
    second: tuple = (1., 1.)
    z: float = 0.
    name: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        try:
            self.first = tuple(float(v) for v in self.first)
            self.second = tuple(float(v) for v in self.second)
            self.z = float(self.z)
            self.dimensions()
        except (TypeError, OverflowError) as exc:
            raise ValueError("Invalid reference geometry coordinates") from exc

    def dimensions(self):
        if self.kind not in ("circle", "rectangle") or self.construction not in ("center", "edge"):
            raise ValueError("Unknown reference shape or construction method")
        a, b = np.asarray(self.first, float), np.asarray(self.second, float)
        if a.shape != (2,) or b.shape != (2,) or not np.isfinite(np.r_[a, b, self.z]).all():
            raise ValueError("Reference geometry needs finite XY points and Z")
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Reference geometry needs a stable ID")
        center = a if self.construction == "center" else (a+b)/2
        if self.kind == "circle":
            radius = float(np.linalg.norm(b-a)) / (1 if self.construction == "center" else 2)
            if not np.isfinite(np.r_[center,radius]).all() or radius <= 1e-6:
                raise ValueError("Circle radius must be positive")
            return center, radius
        half = np.abs(b-a) / (1 if self.construction == "center" else 2)
        if not np.isfinite(np.r_[center,half]).all() or np.any(half <= 1e-6):
            raise ValueError("Rectangle needs positive width and height")
        return center, half

    def segment_count(self):
        _, size = self.dimensions()
        if self.kind != "circle":
            return 4
        angle = math.acos(max(-1., 1.-REFERENCE_CHORD_ERROR/size))
        count = max(REFERENCE_MIN_SEGMENTS, math.ceil(math.pi/max(angle, 1e-15)))
        if count > REFERENCE_MAX_SEGMENTS:
            raise ValueError("Circle too large for reference chord tolerance")
        return count

    def polyline(self):
        center, size = self.dimensions()
        if self.kind == "circle":
            count = self.segment_count()
            theta = np.linspace(0., 2*math.pi, count, endpoint=False)
            xy = center + size*np.column_stack((np.cos(theta), np.sin(theta)))
        else:
            lo, hi = center-size, center+size
            xy = np.array([lo, [hi[0],lo[1]], hi, [lo[0],hi[1]]])
        xy = np.vstack((xy, xy[0]))
        return np.column_stack((xy, np.full(len(xy), self.z)))

    def set_geometry(self, center=None, size=None, z=None):
        """Move/resize in place, keeping the construction method and ID.

        ``size`` is a radius for circles and half (width, height) for rectangles,
        as returned by :meth:`dimensions`. Invalid results raise and leave the
        shape unchanged.
        """
        old_center, old_size = self.dimensions()
        center = np.asarray(old_center if center is None else center, float)
        size = old_size if size is None else size
        a, b = np.asarray(self.first, float), np.asarray(self.second, float)
        if self.kind == "circle":
            radius = float(size)
            direction = (b-a)/max(float(np.linalg.norm(b-a)), 1e-300)
            if self.construction == "center":
                first, second = center, center+radius*direction
            else:
                first, second = center-radius*direction, center+radius*direction
        else:
            half = np.abs(np.asarray(size, float).reshape(2))
            sign = np.where(b-a < 0, -1., 1.)
            if self.construction == "center":
                first, second = center, center+half*sign
            else:
                first, second = center-half*sign, center+half*sign
        previous = (self.first, self.second, self.z)
        self.first, self.second = tuple(float(v) for v in first), tuple(float(v) for v in second)
        if z is not None:
            self.z = float(z)
        try:
            self.dimensions()
            self.segment_count()
        except (ValueError, TypeError, OverflowError):
            self.first, self.second, self.z = previous
            raise ValueError("Reference geometry needs a finite position and positive size") from None

    def contains(self, point):
        center, size = self.dimensions()
        delta = np.asarray(point, float)-center
        return bool(np.linalg.norm(delta) <= size) if self.kind == "circle" else bool(np.all(np.abs(delta) <= size))

    def summary(self):
        center, size = self.dimensions()
        dimensions = f"R{size:g}" if self.kind == "circle" else f"{2*size[0]:g} × {2*size[1]:g}"
        return f"{self.name or self.kind.title()}: {dimensions}, center {center[0]:g}, {center[1]:g}, Z{self.z:g}"
