"""LinkPlanner — how the tool gets from one path to the next entry.

Planned stay-down links, staying at the current depth across cleared material,
short retracts above the current material, and the rapid descent to the entry
height: one rule set for planar and surface paths.
"""
from __future__ import annotations
import numpy as np
from .planner_constants import CLEARANCE_MARGIN


class LinkPlanner:
    def __init__(self, safe_z, travel_clearance, lead_clearance, short_retracts, radius):
        self.safe_z = float(safe_z)
        self.travel_clearance = float(travel_clearance)
        self.lead_clearance = float(lead_clearance)
        self.short_retracts = bool(short_retracts)
        self.radius = float(radius)
        self.reach = self.radius + CLEARANCE_MARGIN   # rapid checks include emitted-coordinate rounding

    @staticmethod
    def linked(path, previous_end):
        """A planned, region-validated same-depth cutting link from the previous path end."""
        return bool(path.stay_down and previous_end is not None and path.stay_down_from is not None
                    and np.allclose(previous_end, path.stay_down_from, atol=1e-7, rtol=0))

    def stay_at_depth(self, state, position, target_xy, floor):
        """Move across at the current Z (already below safe Z, above ``floor``) if verified clear."""
        here = float(position[2])
        if state is None or not self.short_retracts or here >= self.safe_z-1e-9 or here <= floor+1e-9:
            return False
        target_xy = np.asarray(target_xy, float)[:2]
        return bool(state.height_at(target_xy, self.reach) <= here+1e-6
                    and not state.contact(position, np.r_[target_xy, here], self.reach))

    def travel_height(self, state, position, target_xy, entry_z):
        """Retract height for the XY travel: clearance above current material, never above safe Z."""
        if state is None or not self.short_retracts:
            return self.safe_z
        target_xy = np.asarray(target_xy, float)[:2]
        top = max(state.max_height_along(position[:2], target_xy, self.reach),
                  state.height_at(target_xy, self.reach))
        return max(min(self.safe_z, top+self.travel_clearance), float(entry_z))

    def descent_height(self, state, current_z, target_xy, entry_z, lead):
        """Rapid-descent target above the entry: lead clearance over a ramp start, travel clearance otherwise."""
        if state is None or not self.short_retracts:
            return float(current_z)
        clearance = self.lead_clearance if lead else self.travel_clearance
        local = state.height_at(np.asarray(target_xy, float)[:2], self.reach)+clearance
        return max(float(entry_z), min(float(current_z), local))
