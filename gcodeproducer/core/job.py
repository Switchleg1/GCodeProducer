"""The slice job: the mutable object that flows through the stage pipeline.

GCodeTools passes a :class:`GCodeProgram` from module to module.  Here the
pipeline passes a :class:`Job`: stages add layers, toolpaths and finally the
emitted :class:`GCodeProgram`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import workflow as wf
from .profiles import Profile


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


@dataclass
class Layer:
    index: int
    z: float                           # top Z of the layer
    height: float
    contours: list = field(default_factory=list)   # region still to fill (innermost walls after perimeters)
    outline: list = field(default_factory=list)    # original slice polygons (n,2) - never modified
    paths: list = field(default_factory=list)       # list[Path] in print order
    solid_mask: object = None                       # geometry.RegionMask: cells filled solid (top/bottom)


@dataclass
class Job:
    workflow: str
    machine: Profile
    material: Optional[Profile] = None
    nozzle: Optional[Profile] = None
    tools: list = field(default_factory=list)       # CAM: list[Profile]
    mesh: object = None                              # imported geometry
    placement: object = None                         # core.placement.Placement (None = default)
    support_blocks: list = field(default_factory=list)  # core.support.SupportBlock (manual support)
    support: object = None                           # core.support.ModelSupport (None = no support)
    cam_setup: object = None                       # core.cam.CAMSetup (None = legacy CLI profile)
    model_path: Optional[str] = None
    settings: dict = field(default_factory=dict)    # resolved per-job overrides
    layers: list = field(default_factory=list)      # list[Layer]
    warnings: list = field(default_factory=list)   # advisory CAM stock safety findings
    program: object = None                          # GCodeProgram once emitted

    def __post_init__(self):
        self.workflow = wf.normalize(self.workflow)

    # ---- convenience accessors (machine speeds live on the machine profile)
    def m(self, key, default=None):
        return self.machine.get(key, default)

    def mat(self, key, default=None):
        return self.material.get(key, default) if self.material else default

    def noz(self, key, default=None):
        return self.nozzle.get(key, default) if self.nozzle else default

    @property
    def line_width(self) -> float:
        lw = self.noz("line_width", 0.0) or 0.0
        if lw > 0:
            return lw
        d = self.noz("diameter", 0.4) or 0.4
        return round(d * 1.1, 3)

    @property
    def layer_height(self) -> float:
        h = self.settings.get("layer_height")
        if h:
            return float(h)
        d = self.noz("diameter", 0.4) or 0.4
        return round(d * 0.5, 3)
