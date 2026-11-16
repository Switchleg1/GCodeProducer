"""Path — jobs subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from gcodeproducer.core.jobs.cut_condition import CutCondition

@dataclass
class Path:
    """A generated toolpath: a polyline tagged with a feature type."""
    feature: str
    points: np.ndarray                 # (n, 2) XY, or (n, 3) with Z for CAM
    closed: bool = False
    width: float = 0.0                 # extrusion width (FDM) or 0
    speed: Optional[float] = None      # mm/s (FDM) or mm/min (CAM); None = stage default
    stay_down: bool = False             # CAM: validated cutting-depth link from preceding path in same pass
    stay_down_from: Optional[tuple] = None  # expected preceding XY endpoint; stale metadata forces retract
    cut_conditions: list = field(default_factory=list)  # one per emitted XY segment
    link_condition: Optional[CutCondition] = None
