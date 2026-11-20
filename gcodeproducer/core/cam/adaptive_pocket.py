"""Offline adaptive pocket driver with explicit residual and completion status."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry.base import BaseGeometry

from gcodeproducer.core.cam.adaptive_branch import BranchChoice
from gcodeproducer.core.cam.adaptive_entry import AdaptiveEntry, seed_entry
from gcodeproducer.core.cam.adaptive_frontier import choose_frontier_peel
from gcodeproducer.core.cam.adaptive_finish import AdaptiveFinish
from gcodeproducer.core.cam.cam_constants import (
    ADAPTIVE_LINK_HISTORY_SAMPLES, ADAPTIVE_LINK_HISTORY_STEPS, ADAPTIVE_POCKET_AREA_EPS, RAMP_ANGLE,
)
from gcodeproducer.core.cam.lead_angle import lead_slope


@dataclass(frozen=True)
class AdaptivePocket:
    steps: tuple[AdaptiveEntry | BranchChoice | AdaptiveFinish, ...]
    remaining: BaseGeometry
    initial_area: float
    residual_area: float
    status: str


def plan_pocket(region, material, *, top, depth, entry_budget, turn_budget=None, point_budget=None,
                lead_angle=RAMP_ANGLE, use_link_history=True, finish=None, **settings):
    """Try peels and, when stalled, try an entry in a fresh residual patch.

    The cutter-centre region must account for protection at every entry Z.
    An entry step does not plan travel at clearance height to its start.
    This experiment neither emits G-code nor fills residuals by slotting.
    """
    if (not isinstance(entry_budget, int) or entry_budget < 1
            or (turn_budget is not None and (not isinstance(turn_budget, int) or turn_budget < 0))
            or (point_budget is not None and (not isinstance(point_budget, int) or point_budget < 1))):
        raise ValueError('Invalid adaptive pocket work budget')
    radius = settings['tool_radius']
    if not all(math.isfinite(v) for v in (radius, top, depth)) or radius <= 0 or top <= depth:
        raise ValueError('Adaptive pocket requires a positive radius and descending Z range')
    lead_slope(lead_angle)
    sense = settings.get('sense', 1)
    footprint = region.buffer(radius)
    initial_area = residual = material.intersection(footprint).area
    steps, position, continuation = [], None, None
    supplied_waypoints = list(settings.pop('waypoints', ()))
    history = []
    entries = turns = samples = 0
    status = 'covered'
    while residual > ADAPTIVE_POCKET_AREA_EPS:
        if position is not None and finish is not None:
            tail = finish(position, material)
            if tail is not None and (point_budget is None or samples + len(tail.points) <= point_budget):
                next_area = tail.remaining.intersection(footprint).area
                if residual - next_area > ADAPTIVE_POCKET_AREA_EPS:
                    steps.append(tail)
                    material, residual, status = tail.remaining, next_area, 'checked_finish'
                    break
        if position is not None and turn_budget is not None and turns >= turn_budget:
            status = 'turn_budget'
            break
        waypoints = supplied_waypoints + [p for sample in history for p in sample]
        choice = (choose_frontier_peel(position, region, material, continuation=continuation,
                                       waypoints=waypoints, **settings)
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
        samples += len(choice.peel.points) + len(choice.link.points) if isinstance(choice, BranchChoice) else len(choice.points)
        if point_budget is not None and samples > point_budget:
            status = 'point_budget'
            break
        next_area = next_stock.intersection(footprint).area
        if residual - next_area <= ADAPTIVE_POCKET_AREA_EPS:
            status = 'stalled'
            break
        steps.append(choice)
        if use_link_history:
            if isinstance(choice, AdaptiveEntry):
                points = choice.points[choice.points[:, 2] == depth, :2]
            else:
                points = choice.peel.points
            indices = np.linspace(0, len(points)-1, min(len(points), ADAPTIVE_LINK_HISTORY_SAMPLES), dtype=int)
            history.append(points[indices])
            history = history[-ADAPTIVE_LINK_HISTORY_STEPS:]
        position, material, residual = next_position, next_stock, next_area
    return AdaptivePocket(tuple(steps), material, initial_area, residual, status)
