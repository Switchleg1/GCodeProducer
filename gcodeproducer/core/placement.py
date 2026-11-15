"""Model placement on the bed: position, rotation, scale, lay flat.

Placement belongs to the *model* (plate), not to the process: the same process
can print a part in any orientation.  :meth:`Placement.apply` returns a new,
transformed :class:`~gcodeproducer.core.geometry.Mesh`; slicing always works on
the placed mesh, so what the placement view shows is what gets sliced.

Rotation is stored as Euler angles in degrees applied X, then Y, then Z (about
the model's centre), i.e. ``R = Rz @ Ry @ Rx``.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

from .geometry import Mesh


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def euler_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    return rot_z(math.radians(rz)) @ rot_y(math.radians(ry)) @ rot_x(math.radians(rx))


def matrix_to_euler(R: np.ndarray) -> tuple:
    """Inverse of :func:`euler_matrix` (degrees, each in -180..180)."""
    sy = -R[2, 0]
    sy = max(-1.0, min(1.0, sy))
    ry = math.asin(sy)
    if abs(math.cos(ry)) > 1e-6:
        rx = math.atan2(R[2, 1], R[2, 2])
        rz = math.atan2(R[1, 0], R[0, 0])
    else:                                    # gimbal lock
        rx = math.atan2(-R[1, 2], R[1, 1])
        rz = 0.0
    out = []
    for a in (rx, ry, rz):
        d = math.degrees(a)
        d = round(d, 6) + 0.0
        out.append(0.0 if abs(d) < 1e-9 else d)
    return tuple(out)


def align_matrix(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Rotation taking unit vector ``src`` onto unit vector ``dst``."""
    a = np.asarray(src, float) / np.linalg.norm(src)
    b = np.asarray(dst, float) / np.linalg.norm(dst)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -1 + 1e-9:                        # opposite: 180 deg about any perpendicular axis
        axis = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def face_normals(vertices: np.ndarray, triangles: np.ndarray):
    """Unit normals and areas of every triangle."""
    t = vertices[triangles]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ln = np.linalg.norm(n, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        unit = np.where(ln[:, None] > 0, n / ln[:, None], 0.0)
    return unit, ln * 0.5


@dataclass
class Placement:
    x: Optional[float] = None        # bounding-box centre X on the bed (None = auto)
    y: Optional[float] = None        # bounding-box centre Y on the bed (None = auto)
    rx: float = 0.0                  # rotation about X (deg)
    ry: float = 0.0
    rz: float = 0.0
    scale: float = 100.0             # uniform scale (%)
    drop: bool = True                # put the lowest point at height ``z`` (else keep original Z)
    z: float = 0.0                   # anchor height: FDM bottom / CAM top (mm)

    z_anchor: str = "bottom"         # CAM: top referenced to z (normally surface Z0)

    # ------------------------------------------------------------------
    def rotation(self) -> np.ndarray:
        return euler_matrix(self.rx, self.ry, self.rz)

    def set_rotation(self, R: np.ndarray) -> None:
        self.rx, self.ry, self.rz = matrix_to_euler(R)

    def apply(self, mesh: Mesh, auto_xy=None) -> Mesh:
        """Return a transformed copy of ``mesh``.

        ``auto_xy`` is used when ``x`` / ``y`` are None (e.g. the bed centre);
        if that is None too the model keeps its original XY centre.
        """
        v = np.asarray(mesh.vertices, float)
        lo, hi = v.min(axis=0), v.max(axis=0)
        c = (lo + hi) / 2
        R = self.rotation() * (self.scale / 100.0)
        out = (v - c) @ R.T
        lo2, hi2 = out.min(axis=0), out.max(axis=0)
        mid = (lo2 + hi2) / 2
        tx = self.x if self.x is not None else (auto_xy[0] if auto_xy is not None else c[0])
        ty = self.y if self.y is not None else (auto_xy[1] if auto_xy is not None else c[1])
        anchor = hi2[2] if self.z_anchor == "top" else lo2[2]
        target = float(self.z) if self.z_anchor == "top" else max(0.0, float(self.z))
        tz = (target - anchor) if self.drop else c[2]
        out = out + np.array([tx - mid[0], ty - mid[1], tz])
        return Mesh(out, mesh.triangles)

    # ---------------------------------------------------------- helpers
    def lay_flat(self, mesh: Mesh) -> None:
        """Rotate so the largest flat face (in the current orientation) rests on the bed."""
        R = self.rotation()
        n, area = face_normals(np.asarray(mesh.vertices, float) @ R.T, mesh.triangles)
        keys = np.round(n, 2)
        uniq, inv = np.unique(keys, axis=0, return_inverse=True)
        totals = np.bincount(inv.ravel(), weights=area, minlength=len(uniq))
        best = int(np.argmax(totals))
        normal = n[inv.ravel() == best]
        normal = (normal * area[inv.ravel() == best][:, None]).sum(axis=0)
        self.place_on_face(normal)

    def place_on_face(self, world_normal) -> None:
        """Rotate so a face with (current, world-space) ``world_normal`` points down onto the bed."""
        n = np.asarray(world_normal, float)
        if np.linalg.norm(n) < 1e-12:
            return
        A = align_matrix(n, [0.0, 0.0, -1.0])
        self.set_rotation(A @ self.rotation())

    def rotate_by(self, axis: str, degrees: float) -> None:
        """Rotate by ``degrees`` about a *world* axis ('x', 'y' or 'z')."""
        f = {"x": rot_x, "y": rot_y, "z": rot_z}[axis.lower()]
        self.set_rotation(f(math.radians(degrees)) @ self.rotation())

    def reset_rotation(self) -> None:
        self.rx = self.ry = self.rz = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Placement":
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in (d or {}).items() if k in keys})


def overhang_faces(vertices: np.ndarray, triangles: np.ndarray, angle_deg: float,
                   bed_tol: float = 0.05, bed_z: float = 0.0) -> np.ndarray:
    """Bool per triangle: faces that need support for an overhang ``angle_deg`` (from vertical).

    A face needs support when it points downward more steeply than the angle
    allows; faces lying on the bed (at ``bed_z``) do not - so the underside of a
    model lifted off the bed does.
    """
    n, _a = face_normals(vertices, triangles)
    limit = -math.sin(math.radians(angle_deg))
    on_bed = np.asarray(vertices)[triangles][:, :, 2].max(axis=1) <= bed_z + bed_tol
    return (n[:, 2] < limit) & ~on_bed


def bed_xy(machine, workflow: str):
    """Default model position: the bed / work-area centre (origin aware)."""
    from . import workflow as wf
    if machine is None:
        return None
    if wf.normalize(workflow) == wf.FDM:
        if machine.get("origin_center"):
            return (0.0, 0.0)
        return (machine.get("bed_x", 220) / 2.0, machine.get("bed_y", 220) / 2.0)
    if machine.get("origin") == "center":
        return (0.0, 0.0)
    return (machine.get("work_x", 300) / 2.0, machine.get("work_y", 300) / 2.0)


def bed_rect(machine, workflow: str):
    """(x0, y0, x1, y1, height) of the build plate / work area."""
    from . import workflow as wf
    if wf.normalize(workflow) == wf.FDM:
        bx, by, h = machine.get("bed_x", 220), machine.get("bed_y", 220), machine.get("height", 250)
        if machine.get("origin_center"):
            return (-bx / 2, -by / 2, bx / 2, by / 2, h)
        return (0.0, 0.0, bx, by, h)
    wx, wy, wz = machine.get("work_x", 300), machine.get("work_y", 300), machine.get("work_z", 100)
    if machine.get("origin") == "center":
        return (-wx / 2, -wy / 2, wx / 2, wy / 2, -wz)
    return (0.0, 0.0, wx, wy, -wz)


def fits(mesh: Mesh, rect, tol: float = 1e-3) -> bool:
    lo, hi = mesh.bounds
    x0, y0, x1, y1, h = rect
    return (lo[0] >= x0 - tol and lo[1] >= y0 - tol and hi[0] <= x1 + tol and hi[1] <= y1 + tol
            and lo[2] >= min(0, h) - tol and hi[2] <= max(0, h) + tol)
