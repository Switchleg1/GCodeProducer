"""Offline adaptive pocket driver with explicit residual and completion status."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry.base import BaseGeometry

from gcodeproducer.core.cam.adaptive_branch import BranchChoice
from gcodeproducer.core.cam.adaptive_entry import AdaptiveEntry, seed_entry
from gcodeproducer.core.cam.adaptive_frontier import choose_frontier_peel
from gcodeproducer.core.cam.cam_constants import ADAPTIVE_POCKET_AREA_EPS, RAMP_ANGLE
from gcodeproducer.core.cam.lead_angle import lead_slope


@dataclass(frozen=True)
class AdaptivePocket:
    steps: tuple[AdaptiveEntry | BranchChoice, ...]
    remaining: BaseGeometry
    initial_area: float
    residual_area: float
    status: str


def plan_pocket(region, material, *, top, depth, entry_budget, turn_budget,
                lead_angle=RAMP_ANGLE, **settings):
    """Try peels and, when stalled, try an entry in a fresh residual patch.

    The cutter-centre region must account for protection at every entry Z.
    An entry step does not plan travel at clearance height to its start.
    This experiment neither emits G-code nor fills residuals by slotting.
    """
    if not isinstance(entry_budget, int) or entry_budget < 1 or not isinstance(turn_budget, int) or turn_budget < 0:
        raise ValueError('Adaptive pocket needs a positive entry budget and nonnegative turn budget')
    radius = settings['tool_radius']
    if not all(math.isfinite(v) for v in (radius, top, depth)) or radius <= 0 or top <= depth:
        raise ValueError('Adaptive pocket requires a positive radius and descending Z range')
    lead_slope(lead_angle)
    sense = settings.get('sense', 1)
    footprint = region.buffer(radius)
    initial_area = residual = material.intersection(footprint).area
    steps, position, continuation = [], None, None
    entries = turns = 0
    status = 'covered'
    while residual > ADAPTIVE_POCKET_AREA_EPS:
        if position is not None and turns >= turn_budget:
            status = 'turn_budget'
            break
        choice = (choose_frontier_peel(position, region, material, continuation=continuation, **settings)
                  if position is not None else None)
        if choice is not None:
            peel = choice.peel
            next_stock = peel.remaining
            next_position = peel.points[-1]
            tangent = sense*np.array([-peel.seam[1], peel.seam[0]])
            continuation = peel.centre, peel.seam, tangent
            turns += 1
        else:
            if entries >= entry_budget:
                status = 'entry_budget'
                break
            # Re-seed only where the helix footprint fits entirely in the
            # remaining stock. Don't repeatedly ramp in an already cut patch.
            seed_region = region if position is None else region.intersection(material.buffer(-radius))
            choice = seed_entry(seed_region, material, radius=radius, top=top, depth=depth,
                                lead_angle=lead_angle, sense=sense)
            if choice is None:
                status = 'no_entry' if position is None else 'stalled'
                break
            next_stock = choice.remaining
            next_position = choice.points[-1, :2]
            continuation = None
            entries += 1
        next_area = next_stock.intersection(footprint).area
        if residual - next_area <= ADAPTIVE_POCKET_AREA_EPS:
            status = 'stalled'
            break
        steps.append(choice)
        position, material, residual = next_position, next_stock, next_area
    return AdaptivePocket(tuple(steps), material, initial_area, residual, status)
