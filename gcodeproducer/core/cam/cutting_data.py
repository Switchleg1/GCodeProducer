"""CuttingData — cam subsystem."""
from __future__ import annotations
from dataclasses import dataclass
from gcodeproducer.core.cam.cam_constants import MATERIALS

@dataclass
class CuttingData:
    rpm: float
    feed: float
    lead_feed: float
    stepdown: float
    material: str
    depth_source: str = ""
    requested_stepdown: float = 0.0

    def summary(self):
        label = next((m[1] for m in MATERIALS if m[0] == self.material), self.material)
        source = f" • {self.depth_source}" if self.depth_source else ""
        cap = f" (capped from {self.requested_stepdown:.3f})" if self.requested_stepdown > self.stepdown+1e-9 else ""
        return (f"{label}{source} • {self.rpm:.0f} rpm • requested cut {self.feed:g} • lead {self.lead_feed:g} mm/min "
                f"• depth/pass {self.stepdown:.3f} mm{cap}")
