"""Discover experimental peel starts adjacent to already cleared stock."""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point
from shapely.ops import nearest_points, polylabel

from gcodeproducer.core.cam.adaptive_branch import choose_branch
from gcodeproducer.core.cam.cam_constants import (
    ADAPTIVE_BRANCH_LIMIT, ADAPTIVE_FRONTIER_SAMPLES, ADAPTIVE_PEEL_CHORD_ERROR,
)
from gcodeproducer.core.cam.planner.planner_constants import CLEARANCE_MARGIN
from gcodeproducer.core.geometry.polygon_parts import polygons


def discover_starts(position, region, material, *, pitch, tool_radius,
                    min_loop_radius, max_loop_radius, sense=1):
    """Nominate local turns from cleared components, not from virgin stock.

    Each candidate starts tangent to its heading, which points toward the
    nearest remaining material. The peel selector still checks the entire
    moving turn, and the link selector verifies the actual transfer.
    """
    if (not all(math.isfinite(v) and v > 0 for v in (pitch, tool_radius, min_loop_radius, max_loop_radius))
            or min_loop_radius > max_loop_radius or sense not in (-1, 1)):
        raise ValueError('Invalid adaptive frontier geometry')
    xy = np.asarray(position, float)
    if xy.shape != (2,) or not np.isfinite(xy).all():
        raise ValueError('Adaptive frontier needs a finite XY position')
    if material.is_empty:
        return []
    # Inset the cleared tool-centre area by the initial orbit radius. Give
    # round segments additional margin before testing the real transfer.
    reach = tool_radius + CLEARANCE_MARGIN + ADAPTIVE_PEEL_CHORD_ERROR
    clear = region.difference(material.buffer(reach))
    radii = tuple(dict.fromkeys((max_loop_radius, (min_loop_radius+max_loop_radius)/2, min_loop_radius)))
    queues = []
    for patch in sorted(polygons(clear), key=lambda p: (p.distance(Point(xy)), p.bounds))[:ADAPTIVE_BRANCH_LIMIT]:
        candidates = []
        seen = set()

        def offer(point, radius):
            target = nearest_points(point, material)[1]
            centre = np.array(point.coords[0])
            axis = np.array(target.coords[0])-centre
            distance = float(np.linalg.norm(axis))
            if distance <= 1e-9 or distance > reach+radius+pitch:
                return
            axis /= distance
            seam = sense*radius*np.array([axis[1], -axis[0]])
            if not patch.covers(Point(centre+seam)):
                return
            key = tuple(np.round(np.r_[centre, seam], 7))
            if key in seen:
                return
            seen.add(key)
            # Prefer starts close to the remaining frontier, then nearby travel.
            candidates.append((abs(distance-reach-radius), float(np.linalg.norm(centre+seam-xy)),
                               (centre, seam, axis)))

        for radius in radii:
            for core in polygons(patch.buffer(-radius)):
                rings = (core.exterior, *core.interiors)
                for ring in rings:
                    for i in range(ADAPTIVE_FRONTIER_SAMPLES):
                        offer(ring.interpolate(i/ADAPTIVE_FRONTIER_SAMPLES, normalized=True), radius)
        # Exact or near-exact fits can collapse an inward offset to nothing.
        seed = polylabel(patch, tolerance=ADAPTIVE_PEEL_CHORD_ERROR)
        clearance = patch.boundary.distance(seed)
        if patch.contains(seed) and clearance >= min_loop_radius:
            offer(seed, min(clearance, max_loop_radius))
        if candidates:
            queues.append(iter(sorted(candidates, key=lambda c: c[:2])))
    # Round-robin so one nearby lobe cannot use every branch trial.
    starts = []
    while queues and len(starts) < ADAPTIVE_BRANCH_LIMIT:
        active = []
        for queue in queues:
            item = next(queue, None)
            if item is not None:
                starts.append(item[2])
                active.append(queue)
                if len(starts) == ADAPTIVE_BRANCH_LIMIT:
                    break
        queues = active
    return starts


def choose_frontier_peel(position, region, material, *, pitch, tool_radius, limit,
                         min_loop_radius, max_loop_radius, cut_feed, travel_feed, z_feed,
                         lift, waypoints=(), sense=1, continuation=None):
    """Discover and rank one next cut; no new Z entry or coverage guarantee."""
    starts = discover_starts(position, region, material, pitch=pitch, tool_radius=tool_radius,
                             min_loop_radius=min_loop_radius, max_loop_radius=max_loop_radius, sense=sense)
    if continuation is not None:
        starts = [continuation, *starts[:ADAPTIVE_BRANCH_LIMIT-1]]
    return choose_branch(position, starts, region, material, pitch=pitch, tool_radius=tool_radius,
                         limit=limit, min_loop_radius=min_loop_radius, max_loop_radius=max_loop_radius,
                         cut_feed=cut_feed, travel_feed=travel_feed, z_feed=z_feed, lift=lift,
                         waypoints=waypoints, sense=sense)


def trace_frontier(position, region, material, *, turns, **settings):
    """Bounded local run starting in known cleared stock; stop on no useful cut."""
    if not isinstance(turns, int) or turns < 1:
        raise ValueError('Adaptive frontier needs a positive turn budget')
    result, continuation = [], None
    for _ in range(turns):
        choice = choose_frontier_peel(position, region, material, continuation=continuation, **settings)
        if choice is None:
            break
        result.append(choice)
        peel = choice.peel
        position, material = peel.points[-1], peel.remaining
        # The seam's forward tangent supplies a stable heading for the next
        # continuous candidate. Other branches still compete on total time.
        tangent = settings.get('sense', 1)*np.array([-peel.seam[1], peel.seam[0]])
        continuation = peel.centre, peel.seam, tangent
    return result
