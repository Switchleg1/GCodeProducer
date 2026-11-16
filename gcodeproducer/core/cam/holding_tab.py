"""HoldingTab — cam subsystem."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class HoldingTab:
    triangle: int
    barycentric: list
    width: float = 4.0
    height: float = 4.0
    direction: str = "auto"             # auto, +x, -x, +y, -y (machine XY axes)
    enabled: bool = True
