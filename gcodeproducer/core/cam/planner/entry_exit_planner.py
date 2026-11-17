"""EntryExitPlanner — one entry/exit rule for planar and surface (XYZ) paths.

A lead-in replaces a plunge only when the descent at the path start would meet
current material. Already-clear starts are approached through verified air.
Leads follow the validated path itself (contour helix/zigzag, or the XYZ
surface path); exits follow already-cut geometry.
"""
from __future__ import annotations
import numpy as np
from gcodeproducer.core.cam.leads import ramp_entry, exit_path
from gcodeproducer.core.cam.surface_leads import surface_entry, surface_exit
from gcodeproducer.core.cam.cam_constants import SURFACE_LEAD_SETTLE
from .planner_constants import SETTLE_PASSES


class EntryExitPlanner:
    def __init__(self, safe_z, lead_clearance, radius):
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

    def planar(self, state, points, closed, z, length, top=None):
        """Lead for an XY path at depth ``z``: (lead (N,3) or None, kind).

        kind is None (no lead needed or possible), 'linear', 'helix', 'zigzag' or
        'degenerate' (a lead was needed but the path has no length to ramp along).
        """
        points = np.asarray(points, float)
        start = points[0, :2]
        if state is None or not self.enters_material(state, start, z, top):
            return None, None
        if len(points) < 2:
            return None, "degenerate"
        if top is not None:
            lead, kind = ramp_entry(points, closed, z, float(top), length)
            return lead, kind or "degenerate"
        surface = state.height_at(start, self.radius)
        lead = kind = None
        for _ in range(SETTLE_PASSES):
            # The ramp starts just above the local material (lead clearance), settled over
            # both the path start and the ramp start, which moves with the ramp length.
            entry_z = min(self.safe_z, max(surface, z)+self.lead_clearance)
            lead, kind = ramp_entry(points, closed, z, entry_z, length)
            if lead is None:
                return None, "degenerate"
            above = state.height_at(lead[0, :2], self.radius)
            if above <= surface+1e-6:
                break
            surface = above
        return lead, kind

    def surface(self, state, points, length, name=""):
        """Lead for an XYZ surface path: (lead (N,3) or None, kind)."""
        points = np.asarray(points, float)
        first = points[0]
        if not self.enters_material(state, first[:2], first[2]):
            return None, None
        surface = state.height_at(first[:2], self.radius)
        lead = kind = None
        for _ in range(SURFACE_LEAD_SETTLE):
            entry_z = min(self.safe_z, max(surface, first[2])+self.lead_clearance)
            lead, kind = surface_entry(points, entry_z, length)
            above = state.height_at(lead[0, :2], self.radius)
            if above <= surface+1e-6:
                break
            surface = above
        if state.contact(np.r_[lead[0, :2], self.safe_z], lead[0], self.radius):
            raise ValueError(f"{name}: 3D Contour lead start is not clear; increase safe Z or revise the entry")
        return lead, kind

    @staticmethod
    def planar_exit(points, closed, z, length):
        xy = exit_path(points, closed, length)
        return None if xy is None else np.column_stack((xy, np.full(len(xy), float(z))))

    @staticmethod
    def surface_exit(points, length):
        return surface_exit(points, length)
