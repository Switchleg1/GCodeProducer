"""Layer — jobs subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Layer:
    index: int
    z: float                           # top Z of the layer
    height: float
    contours: list = field(default_factory=list)   # region still to fill (innermost walls after perimeters)
    outline: list = field(default_factory=list)    # original slice polygons (n,2) - never modified
    paths: list = field(default_factory=list)       # list[Path] in print order
    solid_mask: object = None                       # geometry.RegionMask: cells filled solid (top/bottom)
    bridge_region: object = None                    # FDM: area occupied by bridge beads
