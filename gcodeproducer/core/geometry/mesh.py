"""Mesh — geometry subsystem."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

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
