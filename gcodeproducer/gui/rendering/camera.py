"""Orbit camera (Z up) shared between viewers."""
from __future__ import annotations
from .rendering_constants import CAMERA_ANGLES
import math, numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4), np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


def ortho(l, r, b, t, n, f):
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = 2 / (r - l)
    m[1, 1] = 2 / (t - b)
    m[2, 2] = -2 / (f - n)
    m[0, 3] = -(r + l) / (r - l)
    m[1, 3] = -(t + b) / (t - b)
    m[2, 3] = -(f + n) / (f - n)
    return m


def look_at(eye, target, up):
    f = target - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    if np.linalg.norm(s) < 1e-6:
        s = np.cross(f, np.array([0, 1, 0], np.float64))
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


class Camera(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.target = np.array([100.0, 100.0, 0.0])
        self.distance = 300.0
        self.yaw = -60.0      # degrees around Z
        self.pitch = 35.0     # degrees above XY plane
        self.fov = 40.0
        self.ortho = False

    # ----------------------------------------------------------- geometry
    def eye(self) -> np.ndarray:
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        d = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])
        return self.target + d * self.distance

    def view_dir(self) -> np.ndarray:
        d = self.target - self.eye()
        return d / np.linalg.norm(d)

    def view_matrix(self) -> np.ndarray:
        return look_at(self.eye(), self.target, np.array([0.0, 0.0, 1.0]))

    def proj_matrix(self, aspect: float) -> np.ndarray:
        near = max(self.distance * 0.002, 0.01)
        far = self.distance * 20 + 2000
        if self.ortho:
            h = self.distance * math.tan(math.radians(self.fov) / 2)
            return ortho(-h * aspect, h * aspect, -h, h, -far, far)
        return perspective(self.fov, aspect, near, far)

    # --------------------------------------------------------- operations
    def orbit(self, dx: float, dy: float) -> None:
        self.yaw -= dx * 0.4
        self.pitch = max(-89.9, min(89.9, self.pitch + dy * 0.4))
        self.changed.emit()

    def pan(self, dx: float, dy: float, viewport_h: int) -> None:
        h = 2 * self.distance * math.tan(math.radians(self.fov) / 2)
        scale = h / max(1, viewport_h)
        v = self.view_matrix()
        right = v[0, :3].astype(np.float64)
        up = v[1, :3].astype(np.float64)
        self.target = self.target - right * dx * scale + up * dy * scale
        self.changed.emit()

    def zoom(self, steps: float) -> None:
        self.distance = max(0.5, min(1e5, self.distance * (0.85 ** steps)))
        self.changed.emit()

    def fit(self, lo, hi) -> None:
        lo = np.asarray(lo, float)
        hi = np.asarray(hi, float)
        self.target = (lo + hi) / 2
        radius = max(np.linalg.norm(hi - lo) / 2, 1.0)
        self.distance = radius / math.sin(math.radians(self.fov) / 2) * 1.05
        self.changed.emit()

    def set_view(self, name: str) -> None:
        self.yaw, self.pitch = CAMERA_ANGLES[name]
        self.changed.emit()
