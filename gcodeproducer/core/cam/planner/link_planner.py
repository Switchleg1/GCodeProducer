"""LinkPlanner — how the tool gets from one path to the next entry.

Planned stay-down links, staying at the current depth across cleared material,
short retracts above the current material, and the rapid descent to the entry
height: one rule set for planar and surface paths.
"""
from __future__ import annotations
import numpy as np
from .planner_constants import (CLEARANCE_MARGIN, SWEEP_GRAZE, DESCENT_SIDE_CLEAR, INWARD_ROUTE_CANDIDATES,
                                INWARD_ROUTE_DETOUR_DIAMETERS)


class LinkPlanner:
    def __init__(self, safe_z, travel_clearance, lead_clearance, short_retracts, radius):
        self.safe_z = float(safe_z)
        self.travel_clearance = float(travel_clearance)
        self.lead_clearance = float(lead_clearance)
        self.short_retracts = bool(short_retracts)
        self.radius = float(radius)
        self.reach = self.radius + CLEARANCE_MARGIN   # rapid checks include emitted-coordinate rounding
        # The recorded cutter sweeps are credited a hair under the cutter's radius, so a cutter going
        # back along its own pass would never read as clear at its full radius. The sweep check
        # therefore tests a cutter a graze smaller: it misses only stock touching the outermost rim.
        self.probe = max(self.radius - SWEEP_GRAZE, self.radius/2)

    @staticmethod
    def linked(path, previous_end):
        """A planned, region-validated same-depth cutting link from the previous path end."""
        return bool(path.stay_down and previous_end is not None and path.stay_down_from is not None
                    and np.allclose(previous_end, path.stay_down_from, atol=1e-7, rtol=0))

    def _clear(self, state, a, b):
        if state.contact(a,b,self.reach):
            return False
        detail = getattr(state,'hybrid',None)
        z = a[2]
        return (detail is None or z >= detail.top or
                (z >= detail.bottom and detail.clear_at_depth(a[:2],b[:2],self.probe,z)))

    def stay_at_depth(self, state, position, target_xy, floor):
        """Move at the current Z if it is at/above the entry floor and the sweep is clear."""
        here = float(position[2])
        if state is None or not self.short_retracts or here >= self.safe_z-1e-9 or here < floor-1e-9:
            return False
        target_xy = np.asarray(target_xy, float)[:2]
        return bool(state.height_at(target_xy, self.reach) <= here+1e-6
                    and self._clear(state, position, np.r_[target_xy, here]))

    def inward_waypoint(self, state, position, target_xy, candidates):
        """One short dogleg via a prior cut, if both full cutter sweeps are clear."""
        if state is None or not self.short_retracts or not len(candidates):
            return None
        xy, z = position[:2], position[2]
        if (state.height_at(target_xy, self.reach) > z+1e-6
                or state.height_at(xy, self.reach) > z+1e-6):
            return None
        lengths = np.linalg.norm(candidates-xy, axis=1) + np.linalg.norm(candidates-target_xy, axis=1)
        limit = np.linalg.norm(target_xy-xy) + 2*self.radius*INWARD_ROUTE_DETOUR_DIAMETERS
        for i in np.argsort(lengths, kind='stable')[:INWARD_ROUTE_CANDIDATES]:
            if lengths[i] > limit:
                break
            via = np.r_[candidates[i], z]
            if (self._clear(state, position, via)
                    and self._clear(state, via, np.r_[target_xy, z])):
                return candidates[i]
        return None

    def travel_height(self, state, position, target_xy, entry_z):
        """Retract height for the XY travel: clearance above current material, never above safe Z."""
        if state is None or not self.short_retracts:
            return self.safe_z
        target_xy = np.asarray(target_xy, float)[:2]
        top = max(state.max_height_along(position[:2], target_xy, self.reach),
                  state.height_at(target_xy, self.reach))
        height = max(min(self.safe_z, top+self.travel_clearance), float(entry_z))
        # The height grid cannot see a skin thinner than a cell along a wall. If the recorded sweeps
        # do not show the whole cutter clear along the way at that height, retract fully.
        detail = getattr(state, 'hybrid', None)
        if (detail is not None and detail.bottom <= height < detail.top and height < self.safe_z
                and not detail.clear_at_depth(np.asarray(position, float)[:2], target_xy, self.probe, height)):
            return max(self.safe_z, float(entry_z))
        return height

    def descent_height(self, state, current_z, target_xy, entry_z, lead):
        """Rapid-descent target above the entry: lead clearance over a ramp start, travel clearance otherwise."""
        if state is None or not self.short_retracts:
            return float(current_z)
        clearance = self.lead_clearance if lead else self.travel_clearance
        xy = np.asarray(target_xy, float)[:2]
        local = state.height_at(xy, self.reach)+clearance
        target = max(float(entry_z), min(float(current_z), local))
        # The height grid cannot see stock thinner than a cell (a skin along a wall, the edge of the
        # cut the entry is about to take). The blocks of the recorded cutter sweeps keep an upper
        # bound of the stock's height that only comes down where a cutter covered the whole block:
        # rapid no lower than clear of the highest of them under the cutter, and feed the rest.
        detail = getattr(state, 'hybrid', None)
        if detail is not None and target < detail.top:
            reach = self.reach + DESCENT_SIDE_CLEAR
            rows, columns = detail._span((xy[0]-reach, xy[1]-reach, xy[0]+reach, xy[1]+reach))
            under = detail.high[rows, columns]
            if under.size:
                target = max(target, min(float(current_z), float(under.max())+clearance))
        return target
