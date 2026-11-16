"""SimResult — gcode subsystem."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from gcodeproducer.core.gcode.gcode_constants import EPS_E

@dataclass
class SimResult:
    """Per-line machine state (arrays have one entry per program line).

    ``x/y/z/e`` are the *logical* coordinates after the line executed
    (E is the value the firmware believes, i.e. affected by G92).
    ``px/py/pz/pe`` are the values before the line.
    """
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    e: np.ndarray
    px: np.ndarray
    py: np.ndarray
    pz: np.ndarray
    pe: np.ndarray
    feed: np.ndarray          # modal feed (mm/min) in effect for the line (nan = unknown)
    de: np.ndarray            # extrusion delta caused by the line
    motion: np.ndarray        # bool: G0/G1/G2/G3 (or modal motion)
    moved: np.ndarray         # bool: XYZ position changed
    dist: np.ndarray          # XYZ distance (straight line; arcs approximated by chord)
    dist_xy: np.ndarray
    e_relative: np.ndarray    # bool: E in relative mode at this line
    xyz_relative: np.ndarray  # bool
    motion_cmd: list          # effective motion command per line (or None)
    scale: np.ndarray = None  # units -> mm factor in effect (25.4 after G20)
    tool: np.ndarray = None   # active tool number (-1 = none selected)

    @property
    def extruding(self) -> np.ndarray:
        return self.motion & self.moved & (self.de > EPS_E)


    @property
    def retracting(self) -> np.ndarray:
        return self.de < -EPS_E

    def __len__(self) -> int:
        return len(self.x)
