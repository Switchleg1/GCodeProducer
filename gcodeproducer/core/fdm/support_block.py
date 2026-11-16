"""SupportBlock — fdm subsystem."""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass
class SupportBlock:
    """An axis-aligned support volume in world (bed) coordinates, mm."""
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float

    def __post_init__(self):
        self.normalize()

    def normalize(self) -> "SupportBlock":
        self.x0, self.x1 = sorted((float(self.x0), float(self.x1)))
        self.y0, self.y1 = sorted((float(self.y0), float(self.y1)))
        self.z0, self.z1 = sorted((float(self.z0), float(self.z1)))
        self.z0 = max(0.0, self.z0)
        return self

    # centre / size view used by the GUI
    @property
    def center(self):
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @property
    def size(self):
        return (self.x1 - self.x0, self.y1 - self.y0, self.z1 - self.z0)

    def set_geometry(self, cx, cy, z0, w, d, h) -> None:
        w, d, h = max(0.1, w), max(0.1, d), max(0.1, h)
        self.x0, self.x1 = cx - w / 2, cx + w / 2
        self.y0, self.y1 = cy - d / 2, cy + d / 2
        self.z0, self.z1 = max(0.0, z0), max(0.0, z0) + h

    def translate(self, dx=0.0, dy=0.0, dz=0.0) -> None:
        self.x0 += dx
        self.x1 += dx
        self.y0 += dy
        self.y1 += dy
        self.z0 = max(0.0, self.z0 + dz)
        self.z1 = max(self.z0 + 0.1, self.z1 + dz)

    def to_dict(self) -> dict:
        return {k: round(v, 4) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict) -> "SupportBlock":
        return cls(*(float(d[k]) for k in ("x0", "y0", "z0", "x1", "y1", "z1")))
