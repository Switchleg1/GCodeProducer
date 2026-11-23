"""EntryExitPlanner — one entry/exit rule for flat and surface-following (XYZ) paths.

A lead-in replaces a plunge only when the descent at the path start would meet
current material. Already-clear starts are approached through verified air.
Leads follow the validated path itself (contour helix/zigzag, or the XYZ
surface path); exits follow already-cut geometry.
"""
from __future__ import annotations
import numpy as np
from gcodeproducer.core.cam.leads import path_ramp, rising_exit
from gcodeproducer.core.cam.cam_constants import RAMP_ANGLE
from gcodeproducer.core.cam.lead_angle import lead_slope
from .planner_constants import SETTLE_PASSES


class EntryExitPlanner:
    def __init__(self, safe_z, lead_clearance, radius, lead_angle=RAMP_ANGLE, lead_out_angle=0.):
        self.lead_angle = lead_angle
        self.lead_out_angle = max(0., float(lead_out_angle or 0))
        self.ramp_slope = lead_slope(lead_angle)
        self.safe_z = float(safe_z)
        self.lead_clearance = float(lead_clearance)
        self.radius = float(radius)

    def enters_material(self, state, xy, z, top=None):
        """Would a vertical descent at ``xy`` from ``top`` (safe Z) to ``z`` meet current material?

        Without a material state the answer is unknown and conservatively yes.
        """
        if state is None:
            return True
        top = self.safe_z if top is None else float(top)
        return bool(state.contact(np.r_[np.asarray(xy, float)[:2], top],
                                  np.r_[np.asarray(xy, float)[:2], z], self.radius))

    def entry(self, state, points, closed, length, top=None, name=""):
        """Lead for any path - flat (XY at its depth) or surface-following (XYZ): (lead (N,3) or None, kind).

        One rule for every operation: no lead where the descent at the path
        start would not meet material; otherwise a ramp along the path itself
        (helix around a closed path, zigzag along an open one) from just above
        the local material (lead clearance, settled over the ramp start, which
        moves with the ramp length), or from ``top`` when the tool is already
        down there. kind is None, 'linear', 'helix', 'zigzag' or 'degenerate'
        (a lead was needed but the path has no length to ramp along).
        """
        p = np.asarray(points, float)
        start = p[0]
        if state is None or not self.enters_material(state, start[:2], start[2], top):
            return None, None
        if len(p) < 2:
            return None, "degenerate"
        if top is not None:
            lead, kind = path_ramp(p, closed, float(top), length, self.lead_angle)
            return lead, kind or "degenerate"
        surface = state.height_at(start[:2], self.radius)
        lead = kind = None
        for _ in range(SETTLE_PASSES):
            entry_z = min(self.safe_z, max(surface, start[2])+self.lead_clearance)
            lead, kind = path_ramp(p, closed, entry_z, length, self.lead_angle)
            if lead is None:
                return None, "degenerate"
            above = state.height_at(lead[0, :2], self.radius)
            if above <= surface+1e-6:
                break
            surface = above
        if state.contact(np.r_[lead[0, :2], self.safe_z], lead[0], self.radius):
            raise ValueError(f"{name}: lead-in start is not clear; increase safe Z or revise the entry")
        return lead, kind

    def exit(self, points, closed, length):
        """Lead-out for any path: back along as much already-cut path as exists (XYZ), climbing at
        the lead-out angle and never above safe Z, or None."""
        result = rising_exit(np.asarray(points, float), closed, length, self.lead_out_angle)
        if result is None or len(result) < 2:
            return None
        result[:, 2] = np.minimum(result[:, 2], np.maximum(self.safe_z, result[0, 2]))
        return result

    # Former entry points, kept for callers and tests: both are the rule above.
    def planar(self, state, points, closed, z, length, top=None):
        p = np.asarray(points, float)[:, :2]
        return self.entry(state, np.column_stack((p, np.full(len(p), float(z)))), closed, length, top)

    def surface(self, state, points, length, name=""):
        return self.entry(state, points, False, length, name=name)

    def planar_exit(self, points, closed, z, length):
        p = np.asarray(points, float)[:, :2]
        return self.exit(np.column_stack((p, np.full(len(p), float(z)))), closed, length)

    def surface_exit(self, points, length):
        return self.exit(points, False, length)
