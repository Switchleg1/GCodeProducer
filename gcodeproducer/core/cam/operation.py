"""Operation — cam subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.depth import Depth
from gcodeproducer.core.cam.cam_constants import ADAPTIVE_CAM_LIMIT, RAMP_ANGLE, LEAD_MODE_KEYS

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
    strategy: str = "contour"          # Pocket/Waterfall: contour, raster_x/y, adaptive
    cut_direction: str = "machine"     # inherit machine default, climb/conventional/meander
    stay_down: bool = True             # pocket contours: region-validated same-depth feed links
    low_engagement_feed: float = 0.0   # percent of tool feed; 0 = inherit tool defaults
    standard_engagement_feed: float = 0.0
    high_engagement_feed: float = 0.0
    slotting_feed: float = 0.0
    lead_in_feed_modifier: float = 0.0  # percent of tool feed; 0 = the tool's lead-in feed
    plunge_feed_modifier: float = 0.0   # percent of tool feed; 0 = the machine's plunge feed modifier
    auto_stepdown: bool = False         # new GUI operations use per-material axial defaults
    unlock_rpm: bool = False
    rpm: float = 18000.
    unlock_feed: bool = False
    feed: float = 800.
    unlock_lead_feed: bool = False
    lead_feed: float = 300.
    unlock_plunge_feed: bool = False
    plunge_feed: float = 150.
    lead_in: str = "every"              # every entry / first entry of each layer / none (LEAD_MODES)
    lead_out: str = "every"             # every exit / last exit of each layer / none
    lead_length: float = 0.0            # 0 = auto: lengthens as needed to respect lead_angle
    overcut: float = 0.0                # Pocket/Waterfall: grow the removal region into void material
    material_limit: float = 0.0         # cutter edge vs blank edge: 0 touch, <0 leave material, >0 pass beyond
    area_order: str = "area"           # area: each area to full depth; depth: all areas at each depth
    follow_surface: bool = False       # Waterfall: each depth rides up the model to the depth above
    protect_model: bool = False        # legacy input: migrates a surface-limited Pocket to Waterfall
    height_references: list[Reference] = field(default_factory=list)  # picked but excluded from machining

    lead_angle: float = RAMP_ANGLE      # maximum lead-in descent, in degrees
    lead_out_angle: float = RAMP_ANGLE  # lead-out climb along the cleared path, in degrees (0 = level)

    adaptive_engagement: float = ADAPTIVE_CAM_LIMIT * 100  # sampled width, percent of cutter diameter

    @staticmethod
    def lead_mode(value):
        """'every', 'layer' or 'none'; saved booleans (older files) read as every / none."""
        if isinstance(value, str) and value in LEAD_MODE_KEYS:
            return value
        return "every" if value is True or (value and not isinstance(value, str)) else "none"

    def __post_init__(self):
        self.lead_in, self.lead_out = self.lead_mode(self.lead_in), self.lead_mode(self.lead_out)
        if self.kind == "pocket" and self.protect_model:
            self.kind = "waterfall"
            self.protect_model = False
        from .strategy import cutting_strategy
        self.strategy = cutting_strategy(self.kind, self.strategy)
