"""Operation — cam subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.depth import Depth

@dataclass
class Operation:
    name: str = "Profile"
    kind: str = "profile"
    geometry: list[Reference] = field(default_factory=list)
    start: Depth = field(default_factory=Depth)
    end: Depth = field(default_factory=lambda: Depth("bottom"))
    stepdown: float = 1.0
    stepover: float = 40.0
    side: str = "outside"
    stock: float = 0.0
    enabled: bool = True
    strategy: str = "contour"          # pocket: contour-parallel or legacy raster
    cut_direction: str = "machine"     # inherit machine default, climb/conventional/meander
    stay_down: bool = True             # pocket contours: region-validated same-depth feed links
    low_engagement_feed: float = 0.0   # percent of tool feed; 0 = inherit tool defaults
    standard_engagement_feed: float = 0.0
    high_engagement_feed: float = 0.0
    slotting_feed: float = 0.0
    auto_stepdown: bool = False         # new GUI operations use per-material axial defaults
    unlock_rpm: bool = False
    rpm: float = 18000.
    unlock_feed: bool = False
    feed: float = 800.
    unlock_lead_feed: bool = False
    lead_feed: float = 300.
    lead_in: bool = True
    lead_out: bool = True
    lead_length: float = 0.0            # 0 = auto: >= one diameter, with <=10-degree ramp
    overcut: float = 0.0                # pocket: grow the floor region into void material (never the part)
    material_limit: float = 0.0         # cutter edge vs blank edge: 0 touch, <0 leave material, >0 pass beyond
    area_order: str = "area"           # area: each area to full depth; depth: all areas at each depth
