"""One planned move of a wavefront pocket."""
from typing import NamedTuple

from shapely import points




class Stroke(NamedTuple):
    kind: str  # 'spiral', 'front', 'corner' or wall 'profile' cut, or a stay-down 'link' through cleared area
    points: list
    stepover_mm: float
    peak_deg: float
